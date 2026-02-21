# Deployment Guide: Flask CRM on Render with Hostinger MySQL Database

## Prerequisites
- Hostinger account with PostgreSQL database
- Render account
- Git repository for your code

## Step 1: Set up Hostinger MySQL Database

1. **Login to Hostinger Control Panel**
2. **Navigate to Databases → MySQL**
3. **Create a new MySQL database:**
   - Database name: `crm_db` (or your preferred name)
   - Username: `crm_user` (or your preferred username)
   - Password: Generate a strong password
   - Host: Note down the host address (usually `localhost` or specific IP)

4. **Note down your database credentials:**
   ```
   Host: your_hostinger_host
   Port: 3306 (default MySQL port)
   Database: crm_db
   Username: crm_user
   Password: your_password
   ```

## Step 2: Prepare Your Local Environment

1. **Install required packages:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Create a .env file locally (not committed to git):**
   ```bash
   FLASK_ENV=development
   SECRET_KEY=your-secret-key-here
   DATABASE_URL=sqlite:///crm.db
   # Optional: base URL for Integrations page copy buttons (e.g. https://xyz.crm.com). No trailing slash.
   # BASE_URL=https://your-domain.com
   ```

## Optional: Add integration_slug column (existing databases)

If you already have an `admin` table and are upgrading, add the integration key column so integration endpoints can use non-guessable URLs:

- **MySQL:** `ALTER TABLE admin ADD COLUMN integration_slug VARCHAR(24) UNIQUE NULL DEFAULT NULL;`
- **SQLite:** `ALTER TABLE admin ADD COLUMN integration_slug VARCHAR(24);` (then create a unique index if desired)

Existing admins get a slug automatically the first time they open **Admin → Integrations**. New admins get a slug when they are created.

## Step 3: Test Database Connection Locally

1. **Temporarily update your .env file with Hostinger credentials:**
   ```bash
   FLASK_ENV=production
   SECRET_KEY=your-secret-key-here
   DATABASE_URL=mysql://crm_user:your_password@your_hostinger_host:3306/crm_db
   ```

2. **Test the migration script:**
   ```bash
   python migrate_db.py
   ```

3. **Revert .env file back to development:**
   ```bash
   FLASK_ENV=development
   DATABASE_URL=sqlite:///crm.db
   ```

## Step 4: Deploy to Render

1. **Push your code to Git repository**

2. **Login to Render Dashboard**

3. **Create New Web Service:**
   - Connect your Git repository
   - Choose the repository with your Flask app
   - Set the following:
     - **Name:** `crm-app` (or your preferred name)
     - **Environment:** `Python 3`
     - **Build Command:** `pip install -r requirements.txt`
     - **Start Command:** `gunicorn wsgi:app`

4. **Set Environment Variables in Render:**
   - `FLASK_ENV`: `production`
   - `SECRET_KEY`: Generate a secure random string
   - `DATABASE_URL`: `mysql://crm_user:your_password@your_hostinger_host:3306/crm_db`

5. **Deploy the service**

## Step 5: Final Database Setup

1. **After successful deployment, run the migration script on Render:**
   - Go to your Render service
   - Open the Shell
   - Run: `python migrate_db.py`

2. **Verify your tables are created:**
   - Check your Hostinger database to ensure all tables exist

## Step 6: Test Your Application

1. **Visit your Render URL**
2. **Test login functionality**
3. **Verify database operations work correctly**

## Troubleshooting

### Common Issues:

1. **Database Connection Errors:**
   - Verify Hostinger database credentials
   - Check if your Hostinger IP allows external connections
   - Ensure database is active and running

2. **Import Errors:**
   - Make sure all packages in requirements.txt are compatible
   - Check if PyMySQL is properly installed

3. **Environment Variable Issues:**
   - Verify all environment variables are set in Render
   - Check if FLASK_ENV is set to 'production'

### Security Notes:

- Never commit .env files to Git
- Use strong, unique passwords for database
- Consider using Render's built-in PostgreSQL service for better security
- Regularly rotate your SECRET_KEY

## Alternative: Use Render's Built-in MySQL

If you prefer to use Render's managed MySQL service:

1. **Create a MySQL service in Render**
2. **Update your DATABASE_URL to use Render's internal connection string**
3. **This provides better security and easier management**

## Support

- **Render Documentation:** https://render.com/docs
- **Hostinger Support:** Available through your Hostinger control panel
- **Flask Documentation:** https://flask.palletsprojects.com/
