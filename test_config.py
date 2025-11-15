import os
import tempfile

class TestConfig:
    """Configuration for testing environment"""
    
    # Testing configuration
    TESTING = True
    DEBUG = False
    
    # Use temporary database for testing
    @staticmethod
    def get_database_uri():
        """Get temporary database URI for testing"""
        db_fd, db_path = tempfile.mkstemp()
        return f'sqlite:///{db_path}', db_fd, db_path
    
    # Disable CSRF protection for testing
    WTF_CSRF_ENABLED = False
    
    # Use a simple secret key for testing
    SECRET_KEY = 'test-secret-key'
    
    # Disable SQLAlchemy track modifications
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Disable Flask-Login's remember me functionality for testing
    REMEMBER_COOKIE_DURATION = 0
    
    # Test user credentials
    TEST_USERS = {
        'super_admin': {
            'username': 'testsuperadmin',
            'password': 'password123',
            'name': 'Test Super Admin'
        },
        'admin': {
            'username': 'testadmin',
            'password': 'password123',
            'name': 'Test Admin'
        },
        'sales': {
            'username': 'testsales',
            'password': 'password123',
            'name': 'Test Sales'
        }
    }
    
    # Test data
    TEST_DATA = {
        'customer': {
            'name': 'Test Customer',
            'phone_number': '1234567890',
            'service_query': 'Test service query',
            'mail_id': 'test@example.com'
        },
        'followup': {
            'remark': 'Test follow up remark'
        }
    }
