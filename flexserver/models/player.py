from google.appengine.ext import ndb
from google.appengine.api import memcache
import re
import random
import logging
import datetime
from collections import defaultdict

class GameCreationException(Exception): pass

class Player(ndb.Model):
    username = ndb.StringProperty(required=True)
    first_name = ndb.StringProperty()
    last_name = ndb.StringProperty()
    email = ndb.StringProperty()
    password = ndb.StringProperty()

    score = ndb.IntegerProperty(default=0)
    last_login = ndb.DateTimeProperty(auto_now=True)

    def to_json(self):
        """
        A dictionary of user parameters
        """
        return {'username': self.username,
                'key': self.key.urlsafe()}


class QuestionTemplate(ndb.Model):
    """
    A question is a string along with a series of parameters that
    specify concept types
    """
    ARG_RE = re.compile("\[(.*?)\]")

    question = ndb.StringProperty(required=True)
    predicate_name = ndb.StringProperty(required=True)
    argument_types  = ndb.StringProperty(repeated=True)
    answer_type = ndb.StringProperty()

    created_at = ndb.DateTimeProperty(auto_now_add=True)

    def extract_arguments(self):
        """
        Extracts the concept types from the arguments
        """
        arguments = []
        for match in QuestionTemplate.ARG_RE.finditer(self.question):
            arguments.append(match.groups()[0])

        return arguments

    def arity(self):
        """
        Returns the arity of the predicate 
        """
        return len(self.argument_types)

    def validate(self):
        """
        Ensures that there are enough arguments for the string
        """
        problems = []
        if "0" in self.predicate_name:
            problems.append("Indexing starts at 1 not 0 for predicate arguments!")


        for i, arg in enumerate(self.arguments):
            arg_string = "[%s]" % (arg)
            if arg_string not in self.question:
                problems.append("%s not in question" % (arg_string))

        return problems


    def ground(self):
        """ Populates the question template with concepts of the types and returns the grounded question string along with a list of the concept objects
        """
        grounded_string = self.question[:]
        concepts_list = []

        for match in QuestionTemplate.ARG_RE.finditer(self.question):
            argument_type = match.groups()[0]
            pattern = match.string[match.start():match.end()]
            argument = Concept.get_random(argument_type)
            concepts_list.append(argument.key)
            argument_value = "<b>%s</b>" % (argument.name,)
            grounded_string = grounded_string.replace(pattern, argument_value, 1) 
        
        question_key = Question.get_or_create(question=grounded_string,
                     question_template=self,
                     arguments=concepts_list,
                     answer_type=self.answer_type)
        return question_key

    @classmethod
    def get_random(cls):
        """
        Returns a random question template
        """
        templates = cls.query().fetch()
        return templates[random.randint(0, len(templates)-1)]

class Question(ndb.Model):
    """
    An instance of a grounded question
    """
    question_template = ndb.KeyProperty(QuestionTemplate)
    question = ndb.StringProperty(required=True)
    arguments = ndb.KeyProperty(repeated=True)
    answer_type = ndb.StringProperty()

    @classmethod
    def get_or_create(cls, question_template, question, arguments, answer_type):
        q = ndb.gql(""" SELECT __key__ FROM Question 
                        WHERE question_template = :1
                        AND arguments IN :2""", question_template.key, arguments).get()
                        
        if not q:
            q = cls(question_template=question_template.key,
                    question=question,
                    arguments=arguments,
                    answer_type=answer_type)
            return q.put()
        return q

    def __str__(self):
        return self.question



class QuestionBlacklist(ndb.Model):
    """
    The questions that users have rejected
    """
    pass


class Concept(ndb.Model):
    """
    A word/phrase representative of a concept
    """
    name = ndb.StringProperty()
    concept_types = ndb.StringProperty(repeated=True)
    created_at = ndb.DateTimeProperty(auto_now_add=True)

    @classmethod
    def get_concept_types(cls):
        """
        Returns all of the concept tags
        """
        concept_types = set()
        for concept in ndb.gql("SELECT concept_types FROM Concept").fetch():
            for ct in concept.concept_types:
                concept_types.add(ct)
        return concept_types

    @classmethod
    def get_random(cls, concept_type):
        """
        Returns a random concept of a particular type
        """
        concepts = cls.query(cls.concept_types==concept_type).fetch()
        if len(concepts) == 0:
            msg = "ConceptType %s has no members" % (concept_type)
            logging.error(msg)
            raise GameCreationException(msg)
        return concepts[random.randint(0, len(concepts)-1)]


    def add_concept_type(self, concept_type):
        """
        Adds a concept type
        """
        cleaned = concept_type.strip().lower()
        if cleaned not in self.concept_types:
            self.concept_types.append(cleaned)

class Answer(ndb.Model):
    """
    """
    answer = ndb.StringProperty(indexed=True)
    player_name = ndb.StringProperty()
    player_key = ndb.KeyProperty(Player, indexed=True)

class Predicate(ndb.Model):
    """
    Contains all of the predicates
    """
    predicate = ndb.StringProperty(required=True)
    arguments = ndb.StringProperty(repeated=True)
    argument_types = ndb.StringProperty(repeated=True)
    frequency = ndb.IntegerProperty(default=0)

    @classmethod
    def update_or_create(cls, predicate, arguments, argument_types, frequency=1):
        """
        Gets the predicate or adds to the existing one
        """
        logging.error("PREDICATE\n\n\n"+str(predicate))
        logging.error("ARGUMENTS\n\n\n"+str(arguments))
        p = ndb.gql("""SELECT * FROM Predicate
                         WHERE predicate = :1
                         AND argument_types IN :2
                         AND arguments IN :3""", predicate, argument_types, arguments).get()
        if not p:
            p = cls(predicate=predicate,
                    arguments=arguments,
                    argument_types=argument_types)

        p.frequency += frequency
        return p
        

    def fancy_form(self):
        """
        Typed predicate string format
        """
        arg_types = ["%s:%s" % (p[0],p[1]) \
                for p in zip(self.arguments, self.argument_types)]
        return "%s(%s)" % (self.predicate, ', '.join(arg_types))

class Game(ndb.Model):
    """
    Represents an instance of a game.   These can be reused, as long
    as they are reset first
    """

    # class variables
    GAME_DURATION = 35
    ANSWER_DURATION = 11
    GAME_COLORS =[0x3B5959, 0x7F8CF1, 0xF2F2E9, 0xD9C4B8, 0xBF6363, 0x044E7F, 0x75B809, 0x117820, 0xFFE240]

    # model components
    started_at = ndb.DateTimeProperty()
    created_at = ndb.DateTimeProperty(auto_now_add=True)
    question = ndb.KeyProperty(Question)
    question_string = ndb.StringProperty()
    players = ndb.StringProperty(repeated=True)
    answers = ndb.StructuredProperty(Answer, repeated=True)
    background_color = ndb.IntegerProperty()
    times_played = ndb.IntegerProperty(default=0)

    cached_status = ndb.PickleProperty()
    is_dirty = ndb.BooleanProperty(default=False)
    
    

    @classmethod
    def generate(cls):
        """
        Generates a new game
        """
        # pick a random question-template
        question_template = QuestionTemplate.get_random()

        # ground it (attempt 5 times)
        question_key = None
        for _ in range(5): 
            try:
                question_key = question_template.ground()
                break
            except GameCreationException:
                logging.info("Trying to ground another question")

        # find it if it exists
        game = Game.query(Game.question==question_key).get()
        if not game:
            question_string = question_key.get().question
            game = Game(question=question_key,
                        question_string=question_string)
            game.put()

        return game

    @classmethod
    def start_new_game(cls):
        """
        Starts a new game
        """
        new_game = cls.generate()
        # reset the game 
        new_game.started_at = datetime.datetime.now()
        new_game.answers = []
        new_game.background_color = random.choice(Game.GAME_COLORS) 
        new_game.cached_status = None
        new_game.is_dirty = False
        new_game.players = []
        new_game.times_played += 1
        new_game.put()
        memcache.set('current_game', new_game)
        return new_game

    def _get_cached_status(self):
        """
        This function computes the score or returns the cache in two ways, depending
        on whether the game is still going on, or if the answers need to be computed
        """
        is_answer_round = Game.GAME_DURATION - self.duration() <= Game.ANSWER_DURATION
        has_updated = False
        if is_answer_round:
            # compute if:  non-answer-round cache, or no cache
            if not (self.cached_status and self.cached_status.has_key('player_scores')):
                """
                Here is where all the results are computed, new concepts are added,
                and new predicates are created
                """
                logging.error("COMPUTING FINAL ANSWERS")
                has_updated = True
                unsaved = []   # new records to create 
                counts = defaultdict(int)
                answers_by_players = defaultdict(list)
                # type of answer
                question = self.question.get()
                qt = question.question_template.get()
                arguments = [a.name for a in ndb.get_multi(question.arguments)]
                argument_types = qt.argument_types
                predicate = qt.predicate_name
                answer_type = question.answer_type

                # counts answers
                for answer in self.answers:
                    # TODO: filter bad concepts (e.g. bad words, single letters)
                    counts[answer.answer] += 1
                    answers_by_players[answer.player_name].append(answer.answer)

                # computes scores for each answer
                scores = {}
                for answer, count in counts.items():
                    scores[answer] = (count-1) * 2
                    # create concept for scores with more than 1 count
                    if count > 1:
                        c = Concept(name=answer)
                        c.add_concept_type(answer_type)
                        unsaved.append(c)
                    p = Predicate.update_or_create(predicate,
                            arguments + [answer],
                            argument_types + [answer_type],
                            count)
                    unsaved.append(p)

                # computes scores for each player    
                player_scores = defaultdict(int)
                for answer in self.answers:
                    player_scores[answer.player_name] += scores[answer.answer]

                # update the players' scores
                for player in player_scores:
                    # find player and add score
                    p = Player.query(Player.username==player).get()
                    p.score += player_scores[player]
                    unsaved.append(p)
          
                # save all of these
                ndb.put_multi(unsaved)
                
                # store in cached_status
                self.cached_status = {'player_scores': dict(player_scores),
                                      'counts': dict(counts),
                                      'scores':  scores,
                                      'answers_by_players': dict(answers_by_players)}

        elif self.is_dirty or not self.cached_status:
            # compute game-in-progress status
            has_updated = True
            counts = defaultdict(int)
            answers_by_players = defaultdict(list)
            for answer in self.answers:
                counts[answer.answer] += 1
                answers_by_players[answer.player_name].append(answer.answer)
        
            # store in cached_status
            self.cached_status = {'counts': dict(counts),
                                  'answers_by_players': dict(answers_by_players)}

        if has_updated:
            # reset dirty flag and save it
            self.is_dirty = False
            self.put()
            memcache.set('current_game', self)

        # ultimately, return status 
        return self.cached_status

    def add_player(self, player_name):
        """
        Ensures that the player is in the game
        """
        if not player_name in self.players:
            self.players.append(player_name)
            self.put()
            memcache.set('current_game', self)

    def status(self, player_name, force_final=False):
        """  
        Personalizes the status for the particular player
        """
        self.add_player(player_name)
        status = self._get_cached_status()
        # personalize 
        if 'scores' in status:
            # this is the answer round
            user_counts = {}
            user_scores = {}
            round_score = 0
            for answer in status['answers_by_players'].get(player_name, []):
                user_counts[answer] = status['counts'][answer]
                user_scores[answer] = status['scores'][answer]
                round_score += status['scores'][answer]

            p = Player.query(Player.username==player_name).get()
            total_score = p.score 
            status['counts'] = user_counts
            status['user_scores'] = user_scores
            status['round_score'] = round_score
            status['total_score'] = total_score 
        else:
            # this is just the regular round
            user_counts = {}
            for answer in status['answers_by_players'].get(player_name, []):
                user_counts[answer] = status['counts'][answer]
            status['counts'] = user_counts

        del status['answers_by_players']
        return status

    def duration(self):
        """
        How long the game has elapsed in seconds
        """
        if self.started_at:
            return (datetime.datetime.now() - self.started_at).seconds
        else:
            return 1000000000000
       
    def add_answer(self, player_name, player_key, answer):
        """
        Adds an answer as a child to the game instance
        """
        """
        if not self.is_dirty and self.cached_status:
            if answer in self.cached_status['answers_by_players']:
                return
        else:
        """
        for a in self.answers:
            if a.player_key == player_key and a.answer == answer:
                return

        if not player_name in self.players:
            self.players.append(player_name)
        new_answer = Answer(parent=self.key,
                        player_name=player_name,
                        answer=answer,
                        player_key=player_key)
        self.answers.append(new_answer)
        self.is_dirty = True
        self.put()
        memcache.set('current_game', self)


