#!/usr/bin/env python3
"""
MySQL database setup script for Hostinger
Run this script to initialize your MySQL database with the required tables
"""

import os
import sys
from dotenv import load_dotenv

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from config import config

def setup_mysql_database():
    """Set up MySQL database with required tables"""
    with app.app_context():
        try:
            # Create all tables in the MySQL database
            db.create_all()
            print("✅ MySQL database tables created successfully!")
            
            # Create default super admin if it doesn't exist
            from app import SuperAdmin
            from werkzeug.security import generate_password_hash
            
            # Check if super admin already exists
            existing_super_admin = SuperAdmin.query.filter_by(username='superadmin').first()
            if not existing_super_admin:
                # Create default super admin
                default_super_admin = SuperAdmin(
                    name='Super Admin',
                    username='superadmin',
                    password_hash=generate_password_hash('admin123')
                )
                db.session.add(default_super_admin)
                db.session.commit()
                print("✅ Default super admin created!")
                print("   Username: superadmin")
                print("   Password: admin123")
            else:
                print("ℹ️  Super admin already exists")
            
            print("\n🎉 MySQL database setup completed successfully!")
            print("📝 You can now deploy your application to Render")
            
        except Exception as e:
            print(f"❌ Error setting up MySQL database: {e}")
            return False
    
    return True

if __name__ == "__main__":
    # Load environment variables
    load_dotenv()
    
    # Set environment to production for MySQL setup
    os.environ['FLASK_ENV'] = 'production'
    
    print("🚀 Starting MySQL database setup...")
    print(f"📊 Database URL: {os.environ.get('DATABASE_URL', 'Not set')}")
    
    if setup_mysql_database():
        print("\n🎯 Next steps:")
        print("1. Test your application locally with MySQL")
        print("2. Deploy to Render")
        print("3. Run this script on Render if needed")
    else:
        print("💥 MySQL setup failed!")
        sys.exit(1)
