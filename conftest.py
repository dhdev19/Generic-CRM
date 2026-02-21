# Ensure tests use SQLite (development config)
import os
os.environ.setdefault('FLASK_ENV', 'development')
