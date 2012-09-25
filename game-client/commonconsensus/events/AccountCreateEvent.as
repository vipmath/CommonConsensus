package commonconsensus.events {
    import flash.events.Event;
	//import com.adobe.serialization.json.JSON;
	
    public class AccountCreateEvent extends Event {
        public static const ACCOUNT_CREATE:String =
            "accountCreate";

        public var user:Object;
		public var game:Object;
		
        public function AccountCreateEvent(result:String) {
            super(ACCOUNT_CREATE, true);
			var o:Object = JSON.parse(result);
			this.user = o.user;// JSON.decode(o.user) as Object;
			this.game = o.game;
          
        }
    }
}