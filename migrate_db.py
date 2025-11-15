#!/usr/bin/env python3
"""
Database migration script to help migrate from SQLite to MySQL
Run this script after setting up your Hostinger MySQL database
"""

import os
import sys
from dotenv import load_dotenv

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from config import config

def migrate_database():
    """Migrate database schema to the new database"""
    with app.app_context():
        try:
            # Create all tables in the new database
            db.create_all()
            print("✅ Database tables created successfully!")
            
            # You can add data migration logic here if needed
            print("📝 Note: You may need to manually migrate your data from SQLite to PostgreSQL")
            print("💡 Consider using tools like pgloader or writing custom migration scripts")
            
        except Exception as e:
            print(f"❌ Error creating database tables: {e}")
            return False
    
    return True

if __name__ == "__main__":
    # Load environment variables
    load_dotenv()
    
    # Set environment to production for migration
    os.environ['FLASK_ENV'] = 'production'
    
    print("🚀 Starting database migration...")
    print(f"📊 Database URL: {os.environ.get('DATABASE_URL', 'Not set')}")
    
    if migrate_database():
        print("🎉 Migration completed successfully!")
    else:
        print("💥 Migration failed!")
        sys.exit(1)
