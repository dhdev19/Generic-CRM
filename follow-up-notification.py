import os
from datetime import datetime, date
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import pymysql


firebase_admin = None
try:
    import firebase_admin as _fb
    from firebase_admin import credentials as _fb_credentials, messaging as _fb_messaging
    firebase_admin = _fb
except Exception:
    pass

# Load environment variables
load_dotenv()

# Configure PyMySQL to work with SQLAlchemy
pymysql.install_as_MySQLdb()

class FollowUpNotification:
    def __init__(self):
        self.db_engine = None
        self.db_session = None
        self.firebase_initialized = False
        self._setup_firebase()
        self._setup_database()
    
    def _setup_firebase(self):
        """Initialize Firebase Admin SDK with credentials from environment"""
        global firebase_admin
        if firebase_admin is not None:
            fcm_json = os.environ.get('FIREBASE_CREDENTIALS_JSON')
            if fcm_json and not firebase_admin._apps:
                try:
                    cred = _fb_credentials.Certificate(fcm_json)
                    firebase_admin.initialize_app(cred)
                    self.firebase_initialized = True
                    print("Firebase Admin SDK initialized successfully")
                except Exception as e:
                    print(f"Firebase initialization failed: {e}")
                    firebase_admin = None
                    self.firebase_initialized = False
            else:
                print("Firebase credentials not found or already initialized")
        else:
            print("Firebase Admin SDK not available")
    
    def _setup_database(self):
        """Setup database connection using URL from environment"""
        database_url = os.environ.get('DATABASE_URL')
        if not database_url:
            print("DATABASE_URL not found in environment variables")
            return False
        
        try:
            # Handle MySQL connection string format
            if database_url.startswith('mysql://'):
                # Convert mysql:// to mysql+pymysql:// for SQLAlchemy
                database_url = database_url.replace('mysql://', 'mysql+pymysql://', 1)
            
            self.db_engine = create_engine(database_url)
            Session = sessionmaker(bind=self.db_engine)
            self.db_session = Session()
            print("Database connection established successfully")
            return True
        except Exception as e:
            print(f"Database connection failed: {e}")
            return False
    
    def check_followups_for_today(self):
        """Check followups table for entries where date_of_contact is current date"""
        if not self.db_session:
            print("Database session not available")
            return []
        
        try:
            # Get current date
            today = date.today()
            
            # Query followups for today
            query = text("""
                SELECT fu.id, fu.admin_id, fu.sales_id, fu.query_id, 
                       fu.date_of_contact, fu.remark,
                       q.name as query_name, q.phone_number,
                       s.name as sales_name
                FROM follow_up fu
                JOIN query q ON fu.query_id = q.id
                JOIN sales s ON fu.sales_id = s.id
                WHERE DATE(fu.date_of_contact) = :today
                ORDER BY fu.date_of_contact ASC
            """)
            
            result = self.db_session.execute(query, {"today": today})
            followups = result.fetchall()
            
            print(f"Found {len(followups)} followups for today ({today})")
            return followups
            
        except Exception as e:
            print(f"Error checking followups: {e}")
            return []
    
    def send_notification_to_sales_device(self, sales_id: int, title: str, body: str, data: dict = None) -> int:
        """
        Send notification to a single device for the given sales_id.
        Returns 1 if sent successfully, 0 otherwise.
        """
        if not self.firebase_initialized:
            print("Firebase not initialized")
            return 0
        
        if not self.db_session:
            print("Database session not available")
            return 0
        
        try:
            # Fetch the latest active device token for the sales_id
            query = text("""
                SELECT device_token 
                FROM device_token 
                WHERE sales_id = :sales_id AND is_active = 1 
                ORDER BY updated_at DESC 
                LIMIT 1
            """)
            
            result = self.db_session.execute(query, {"sales_id": sales_id})
            token_row = result.fetchone()
            
            if not token_row:
                print(f"No active device token found for sales_id: {sales_id}")
                return 0
            
            device_token = token_row[0]
            
            message = _fb_messaging.Message(
                notification=_fb_messaging.Notification(title=title, body=body),
                token=device_token,
                data={k: str(v) for k, v in (data or {}).items()}
            )
            
            _fb_messaging.send(message)
            print(f"Notification sent successfully to sales_id: {sales_id}")
            return 1
            
        except Exception as e:
            print(f"FCM send error for sales_id {sales_id}: {e}")
            return 0
    
    def send_followup_reminder_notification(self, followup_data):
        """Send followup reminder notification to sales person"""
        sales_id = followup_data.sales_id
        query_name = followup_data.query_name
        phone_number = followup_data.phone_number
        
        title = "Follow-up Reminder"
        body = f"Follow-up due for {query_name} ({phone_number})"
        data = {
            "query_id": str(followup_data.query_id),
            "followup_id": str(followup_data.id),
            "type": "followup_reminder"
        }
        
        return self.send_notification_to_sales_device(sales_id, title, body, data)
    
    def process_todays_followups(self):
        """Main function to process all followups for today and send notifications"""
        print(f"Processing followups for {date.today()}")
        
        followups = self.check_followups_for_today()
        
        if followups:
            # Print table header
            print(f"{'ID':<5} {'Sales ID':<8} {'Query Name':<20} {'Phone':<15} {'Date':<25} {'Remark':<30}")
            print("-" * 110)
            
            for followup in followups:
                # Format the date properly
                date_str = followup.date_of_contact.strftime('%Y-%m-%d %H:%M:%S') if followup.date_of_contact else 'N/A'
                print(f"{followup.id:<5} {followup.sales_id:<8} {followup.query_name:<20} {followup.phone_number:<15} {date_str:<25} {followup.remark[:30]:<30}")
        
        
        
        if not followups:
            print("No followups found for today")
            return
        
        sent_count = 0
        for followup in followups:
            try:
                result = self.send_followup_reminder_notification(followup)
                if result:
                    sent_count += 1
                    print(f"Sent reminder for followup ID: {followup.id}")
                else:
                    print(f"Failed to send reminder for followup ID: {followup.id}")
            except Exception as e:
                print(f"Error processing followup {followup.id}: {e}")
        
        print(f"Successfully sent {sent_count} out of {len(followups)} followup reminders")
    
    def close_connections(self):
        """Close database connections"""
        if self.db_session:
            self.db_session.close()
        if self.db_engine:
            self.db_engine.dispose()

def main():
    """Main function to run the followup notification system"""
    print("Starting Follow-up Notification System")
    
    notification_system = FollowUpNotification()
    
    try:
        # Process today's followups
        notification_system.process_todays_followups()
        
    except Exception as e:
        print(f"Error in main process: {e}")
    finally:
        # Clean up connections
        notification_system.close_connections()
        print("Follow-up Notification System completed")

if __name__ == "__main__":
    main()
