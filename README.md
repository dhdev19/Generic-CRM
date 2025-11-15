# CRM System

A comprehensive Customer Relationship Management system built with Flask, featuring role-based access control for Super Admins, Admins, and Sales personnel.

## Features

### 🔐 Authentication System
- **Super Admin**: Full system control, manage admins and super admins
- **Admin**: Team management, manage sales persons and queries
- **Sales**: Customer interaction, manage queries and follow-ups

### 📊 Database Tables
- **Super Admin Table**: name, username, password_hash
- **Admin Table**: name, username, password_hash  
- **Sales Table**: admin_id, name, username, password_hash
- **Queries Table**: sales_id, admin_id, date_of_enquiry, name, phone_number, service_query, mail_id, closure
- **Follow Up Table**: admin_id, sales_id, date_of_contact, remark

### 🚀 Functionalities

#### Super Admin
- Add/Remove super admin users
- Add/Remove admin users
- View all super admins and admins
- System overview dashboard

#### Admin
- Add/Remove sales personnel
- Add/View/Edit/Remove queries
- Assign queries to sales persons
- Manage query closure status

#### Sales
- Add new queries
- Edit existing queries
- Add follow-up notes
- View personal dashboard

## 🛠️ Installation & Setup

### Prerequisites
- Python 3.8 or higher
- pip (Python package installer)

### 1. Clone or Download
```bash
# If using git
git clone <repository-url>
cd crm

# Or download and extract to a folder
cd crm
```

### 2. Create Virtual Environment
```bash
# Windows
python -m venv env
env\Scripts\activate

# macOS/Linux
python3 -m venv env
source env/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the Application
```bash
python app.py
```

The application will start on `http://localhost:5000`

## 🔑 Default Login

**Super Admin Account:**
- Username: `superadmin`
- Password: `admin123`

## 🚀 Deployment

### Render + Hostinger Database
This application is configured for deployment on Render with a Hostinger MySQL database.

**Quick Deploy:**
1. Fork/clone this repository
2. Set up PostgreSQL database on Hostinger
3. Deploy to Render using the provided `render.yaml`
4. Set environment variables in Render dashboard

**Detailed deployment guide:** See [DEPLOYMENT.md](DEPLOYMENT.md)

### Alternative: Local Development
For local development, the app uses SQLite by default.

## 📱 Usage Guide

### First Time Setup
1. Run the application
2. Login with default super admin credentials
3. Create additional super admins, admins, and sales personnel as needed

### Workflow
1. **Super Admin** creates **Admin** users
2. **Admin** users create **Sales** personnel
3. **Admin** or **Sales** users create **Queries**
4. **Sales** users manage queries and add **Follow-ups**
5. **Admin** users can edit and close queries

### Security Features
- Password hashing using Werkzeug
- Session-based authentication
- Role-based access control
- Protected routes with login requirements

## 🗄️ Database

The application uses SQLite by default with the following schema:

```sql
-- Super Admin Table
CREATE TABLE super_admin (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    username VARCHAR(80) UNIQUE NOT NULL,
    password_hash VARCHAR(120) NOT NULL
);

-- Admin Table  
CREATE TABLE admin (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    username VARCHAR(80) UNIQUE NOT NULL,
    password_hash VARCHAR(120) NOT NULL
);

-- Sales Table
CREATE TABLE sales (
    id INTEGER PRIMARY KEY,
    admin_id INTEGER NOT NULL,
    name VARCHAR(100) NOT NULL,
    username VARCHAR(80) UNIQUE NOT NULL,
    password_hash VARCHAR(120) NOT NULL,
    FOREIGN KEY (admin_id) REFERENCES admin (id)
);

-- Queries Table
CREATE TABLE query (
    id INTEGER PRIMARY KEY,
    sales_id INTEGER NOT NULL,
    admin_id INTEGER NOT NULL,
    date_of_enquiry DATETIME DEFAULT CURRENT_TIMESTAMP,
    name VARCHAR(100) NOT NULL,
    phone_number VARCHAR(20) NOT NULL,
    service_query TEXT NOT NULL,
    mail_id VARCHAR(120) NOT NULL,
    closure VARCHAR(20) DEFAULT 'not relevant',
    FOREIGN KEY (sales_id) REFERENCES sales (id),
    FOREIGN KEY (admin_id) REFERENCES admin (id)
);

-- Follow Up Table
CREATE TABLE follow_up (
    id INTEGER PRIMARY KEY,
    admin_id INTEGER NOT NULL,
    sales_id INTEGER NOT NULL,
    date_of_contact DATETIME DEFAULT CURRENT_TIMESTAMP,
    remark TEXT NOT NULL,
    FOREIGN KEY (admin_id) REFERENCES admin (id),
    FOREIGN KEY (sales_id) REFERENCES sales (id)
);
```

## 🎨 UI Features

- **Responsive Design**: Works on desktop, tablet, and mobile
- **Modern Interface**: Clean, professional design with Bootstrap 5
- **Interactive Elements**: Hover effects, smooth transitions
- **Icon Integration**: Font Awesome icons for better UX
- **Color-coded Status**: Visual indicators for query status

## 🔧 Customization

### Changing Database
To use a different database (MySQL, PostgreSQL), update the `SQLALCHEMY_DATABASE_URI` in `app.py`:

```python
# MySQL (default for production)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://username:password@localhost/crm_db'

# PostgreSQL  
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://username:password@localhost/crm_db'
```

### Adding New Features
The modular structure makes it easy to add new features:
- Add new models in the database section
- Create new routes in the routes section
- Add new templates in the templates folder

## 🚨 Troubleshooting

### Common Issues

1. **Port already in use**
   ```bash
   # Change port in app.py
   app.run(debug=True, port=5001)
   ```

2. **Database errors**
   ```bash
   # Delete the existing database file
   rm crm.db
   # Restart the application
   ```

3. **Import errors**
   ```bash
   # Ensure virtual environment is activated
   # Reinstall requirements
   pip install -r requirements.txt
   ```

## 📝 License

This project is open source and available under the MIT License.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📞 Support

For support, please open an issue in the repository or contact the development team.

---

**Note**: This is a development version. For production use, ensure proper security measures, environment variables for secrets, and HTTPS configuration.
