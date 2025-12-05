from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
from config import config
import pymysql
from sqlalchemy import desc 
# Firebase Admin SDK (optional; initialized if creds provided)
firebase_admin = None
try:
    import firebase_admin as _fb
    from firebase_admin import credentials as _fb_credentials, messaging as _fb_messaging
    firebase_admin = _fb
except Exception:
    pass
# Configure PyMySQL to work with SQLAlchemy
pymysql.install_as_MySQLdb()
#git check
app = Flask(__name__)

# Load configuration based on environment
config_name = os.environ.get('FLASK_ENV', 'development')
app.config.from_object(config[config_name])

# Initialize Firebase Admin if JSON path provided
if firebase_admin is not None:
    fcm_json = os.environ.get('FIREBASE_CREDENTIALS_JSON')
    if fcm_json and not firebase_admin._apps:
        try:
            cred = _fb_credentials.Certificate(fcm_json)
            firebase_admin.initialize_app(cred)
        except Exception:
            # FCM disabled if init fails
            firebase_admin = None

# Production-specific configurations for Render
if config_name == 'production':
    # Handle proxy headers for Render
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    
    # Ensure HTTPS redirects work properly
    app.config['PREFERRED_URL_SCHEME'] = 'https'

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Database Models
class SuperAdmin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    password_plain_text = db.Column(db.String(255), nullable=False)

class Sales(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

class Query(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sales_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=False)
    date_of_enquiry = db.Column(db.DateTime, default=datetime.utcnow)
    name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    service_query = db.Column(db.Text, nullable=False)
    mail_id = db.Column(db.String(120), nullable=False)
    # New source column and updated closure domain
    source = db.Column(db.String(50), default='reference')  # Gmb, justdial, facebook, website, reference, cold approach, youtube
    # Closures: Closed, Prospect, Positive, pending, call again, bad mei bataenge,
    # not intrested, wrong enquiry, invalid, switch off, not picked
    closure = db.Column(db.String(30), default='pending')

class FollowUp(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=False)
    sales_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    query_id = db.Column(db.Integer, db.ForeignKey('query.id'), nullable=False)
    date_of_contact = db.Column(db.DateTime, default=datetime.utcnow)
    remark = db.Column(db.Text, nullable=False)

# Device token model for mobile push notifications
class DeviceToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sales_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False, index=True)
    device_token = db.Column(db.String(512), nullable=False, index=True)
    platform = db.Column(db.String(50))
    app_version = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime)

@login_manager.user_loader
def load_user(user_id):
    # Prefer the model based on the recorded session user_type to avoid id collisions
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    user_type = session.get('user_type')
    if user_type == 'super_admin':
        return db.session.get(SuperAdmin, uid)
    if user_type == 'admin':
        return db.session.get(Admin, uid)
    if user_type == 'sales':
        return db.session.get(Sales, uid)
    # Fallback (very unlikely needed, but keeps backward compatibility)
    user = db.session.get(SuperAdmin, uid) or db.session.get(Admin, uid) or db.session.get(Sales, uid)
    return user

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/debug-session')
def debug_session():
    """Debug route to check session status"""
    if app.config.get('FLASK_ENV') == 'production':
        return jsonify({
            'session_data': dict(session),
            'user_authenticated': current_user.is_authenticated if current_user else False,
            'user_type': session.get('user_type'),
            'user_id': session.get('user_id')
        })
    return "Debug route only available in development"

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user_type = request.form['user_type']
        
        user = None
        if user_type == 'super_admin':
            user = SuperAdmin.query.filter_by(username=username).first()
        elif user_type == 'admin':
            user = Admin.query.filter_by(username=username).first()
        elif user_type == 'sales':
            user = Sales.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            session['user_type'] = user_type
            session['user_id'] = user.id
            
            # Force session to be saved
            session.modified = True
            
            # Debug logging in production
            if app.config.get('FLASK_ENV') == 'production':
                print(f"Login successful: {user_type} - {username}")
                print(f"Session data: {dict(session)}")
            
            if user_type == 'super_admin':
                return redirect(url_for('super_admin_dashboard'))
            elif user_type == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user_type == 'sales':
                return redirect(url_for('sales_dashboard'))
        
        flash('Invalid username or password')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('index'))

# Super Admin Routes
@app.route('/super-admin/dashboard')
@login_required
def super_admin_dashboard():
    if session.get('user_type') != 'super_admin':
        flash('Access denied')
        return redirect(url_for('index'))
    
    super_admins = SuperAdmin.query.all()
    admins = Admin.query.all()
    return render_template('super_admin_dashboard.html', super_admins=super_admins, admins=admins)

@app.route('/super-admin/add-super-admin', methods=['GET', 'POST'])
@login_required
def add_super_admin():
    if session.get('user_type') != 'super_admin':
        flash('Access denied')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        name = request.form['name']
        username = request.form['username']
        password = request.form['password']
        
        if SuperAdmin.query.filter_by(username=username).first():
            flash('Username already exists')
        else:
            new_super_admin = SuperAdmin(
                name=name,
                username=username,
                password_hash=generate_password_hash(password)
            )
            db.session.add(new_super_admin)
            db.session.commit()
            flash('Super Admin added successfully')
            return redirect(url_for('super_admin_dashboard'))
    
    return render_template('add_super_admin.html')

@app.route('/super-admin/add-admin', methods=['GET', 'POST'])
@login_required
def add_admin():
    if session.get('user_type') != 'super_admin':
        flash('Access denied')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        name = request.form['name']
        username = request.form['username']
        password = request.form['password']
        
        if Admin.query.filter_by(username=username).first():
            flash('Username already exists')
        else:
            new_admin = Admin(
                name=name,
                username=username,
                password_hash=generate_password_hash(password),
                password_plain_text=password
            )
            db.session.add(new_admin)
            db.session.commit()
            flash('Admin added successfully')
            return redirect(url_for('super_admin_dashboard'))
    
    return render_template('add_admin.html')

@app.route('/super-admin/remove-super-admin/<int:id>')
@login_required
def remove_super_admin(id):
    if session.get('user_type') != 'super_admin':
        flash('Access denied')
        return redirect(url_for('index'))
    
    super_admin = SuperAdmin.query.get_or_404(id)
    if super_admin.id == current_user.id:
        flash('Cannot remove yourself')
    else:
        db.session.delete(super_admin)
        db.session.commit()
        flash('Super Admin removed successfully')
    
    return redirect(url_for('super_admin_dashboard'))

@app.route('/super-admin/remove-admin/<int:id>')
@login_required
def remove_admin(id):
    if session.get('user_type') != 'super_admin':
        flash('Access denied')
        return redirect(url_for('index'))
    
    admin = Admin.query.get_or_404(id)
    db.session.delete(admin)
    db.session.commit()
    flash('Admin removed successfully')
    return redirect(url_for('super_admin_dashboard'))

# Admin Routes
@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if session.get('user_type') != 'admin':
        flash('Access denied')
        return redirect(url_for('index'))
    
    sales_persons = Sales.query.filter_by(admin_id=current_user.id).all()

    # Pagination setup
    per_page = 25
    page = request.args.get('page', 1, type=int)

    # Base query joining Query with Sales to get sales person name
    base_query = db.session.query(Query, Sales.name.label('sales_name')).join(
        Sales, Query.sales_id == Sales.id
    ).filter(
        Query.admin_id == current_user.id
    )

    # Total count for pagination
    total_queries = base_query.count()
    total_pages = (total_queries + per_page - 1) // per_page if total_queries > 0 else 1

    # Paginated queries for current page, newest first
    queries = base_query.order_by(Query.id.desc()).limit(per_page).offset((page - 1) * per_page).all()

    # All queries for overview statistics (not paginated)
    queries_list = Query.query.filter_by(admin_id=current_user.id).all()

    # Follow-ups for visible queries only
    visible_query_ids = [q[0].id for q in queries]
    followups_by_query = {}
    if visible_query_ids:
        followups = FollowUp.query.filter(FollowUp.query_id.in_(visible_query_ids)).order_by(FollowUp.date_of_contact.desc()).all()
        for fu in followups:
            followups_by_query.setdefault(fu.query_id, []).append(fu)
    
    return render_template(
        'admin_dashboard.html',
        sales_persons=sales_persons,
        queries=queries,
        queries_list=queries_list,
        followups_by_query=followups_by_query,
        page=page,
        total_pages=total_pages,
    )

@app.route('/admin/add-sales', methods=['GET', 'POST'])
@login_required
def add_sales():
    if session.get('user_type') != 'admin':
        flash('Access denied')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        name = request.form['name']
        username = request.form['username']
        password = request.form['password']
        
        if Sales.query.filter_by(username=username).first():
            flash('Username already exists')
        else:
            new_sales = Sales(
                admin_id=current_user.id,
                name=name,
                username=username,
                password_hash=generate_password_hash(password)
            )
            db.session.add(new_sales)
            db.session.commit()
            flash('Sales person added successfully')
            return redirect(url_for('admin_dashboard'))
    
    return render_template('add_sales.html')

@app.route('/admin/remove-sales/<int:id>')
@login_required
def remove_sales(id):
    if session.get('user_type') != 'admin':
        flash('Access denied')
        return redirect(url_for('index'))
    
    sales = Sales.query.get_or_404(id)
    if sales.admin_id != current_user.id:
        flash('Access denied')
        return redirect(url_for('admin_dashboard'))
    
    try:
        # Delete all related records before deleting the sales person
        # 1. Delete DeviceToken records
        DeviceToken.query.filter_by(sales_id=id).delete()
        
        # 2. Delete FollowUp records (FollowUp has sales_id foreign key)
        FollowUp.query.filter_by(sales_id=id).delete()
        
        # 3. Delete Query records
        Query.query.filter_by(sales_id=id).delete()
        
        # 4. Finally, delete the Sales person
        db.session.delete(sales)
        db.session.commit()
        flash('Sales person removed successfully')
    except Exception as e:
        db.session.rollback()
        flash(f'Error removing sales person: {str(e)}')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/add-query', methods=['GET', 'POST'])
@login_required
def add_query():
    if session.get('user_type') != 'admin':
        flash('Access denied')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        sales_id = request.form['sales_id']
        name = request.form['name']
        phone_number = request.form['phone_number']
        service_query = request.form['service_query']
        mail_id = request.form['mail_id']
        source = request.form.get('source') or 'reference'
        closure = request.form.get('closure') or 'not picked'
        
        new_query = Query(
            sales_id=sales_id,
            admin_id=current_user.id,
            name=name,
            phone_number=phone_number,
            service_query=service_query,
            mail_id=mail_id,
            source=source,
            closure=closure
        )
        db.session.add(new_query)
        db.session.commit()
        # After commit, trigger notification to the sales person
        try:
            send_new_query_notification_to_sales(new_query.sales_id, new_query)
        except Exception:
            pass
        flash('Query added successfully')
        return redirect(url_for('admin_dashboard'))
    
    sales_persons = Sales.query.filter_by(admin_id=current_user.id).all()
    return render_template('add_query.html', sales_persons=sales_persons)

@app.route('/admin/edit-query/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_query(id):
    if session.get('user_type') != 'admin':
        flash('Access denied')
        return redirect(url_for('index'))
    
    query = Query.query.get_or_404(id)
    if query.admin_id != current_user.id:
        flash('Access denied')
        return redirect(url_for('admin_dashboard'))
    
    sales_persons = Sales.query.filter_by(admin_id=current_user.id).all()
    
    if request.method == 'POST':
        query.name = request.form['name']
        query.phone_number = request.form['phone_number']
        query.service_query = request.form['service_query']
        query.mail_id = request.form['mail_id']
        if 'source' in request.form:
            query.source = request.form['source']
        query.closure = request.form['closure']
        
        # Update sales person if changed
        if 'sales_id' in request.form:
            new_sales_id = int(request.form['sales_id'])
            # Verify the sales person belongs to this admin
            sales_person = Sales.query.filter_by(id=new_sales_id, admin_id=current_user.id).first()
            if sales_person and query.sales_id != new_sales_id:
                query.sales_id = new_sales_id
                
                # Update all follow-ups for this query to the new sales person
                follow_ups = FollowUp.query.filter_by(query_id=query.id).all()
                for follow_up in follow_ups:
                    follow_up.sales_id = new_sales_id
        
        db.session.commit()
        
        # Send notification to sales person about query update
        # If sales person changed, notify the new sales person
        try:
            send_new_query_notification_to_sales(query.sales_id, query)
        except Exception:
            pass
        flash('Query updated successfully')
        return redirect(url_for('admin_dashboard'))
    
    return render_template('edit_query.html', query=query, sales_persons=sales_persons)

@app.route('/admin/remove-query/<int:id>')
@login_required
def remove_query(id):
    if session.get('user_type') != 'admin':
        flash('Access denied')
        return redirect(url_for('index'))
    
    query = Query.query.get_or_404(id)
    if query.admin_id != current_user.id:
        flash('Access denied')
        return redirect(url_for('admin_dashboard'))
    
    try:
        # Delete all follow-ups associated with this query first
        FollowUp.query.filter_by(query_id=id).delete()
        
        # Now delete the query
        db.session.delete(query)
        db.session.commit()
        flash('Query removed successfully')
    except Exception as e:
        db.session.rollback()
        flash(f'Error removing query: {str(e)}')
    
    return redirect(url_for('admin_dashboard'))

# Admin analytics
@app.route('/admin/analytics')
@login_required
def admin_analytics():
    if session.get('user_type') != 'admin' or not isinstance(current_user, Admin):
        flash('Access denied')
        return redirect(url_for('index'))

    # Filters
    selected_year = request.args.get('year')
    selected_month = request.args.get('month')
    selected_source = request.args.get('source')
    selected_closure = request.args.get('closure')
    selected_sales_id = request.args.get('sales_id')

    # Sales under this admin
    sales_people = Sales.query.filter_by(admin_id=current_user.id).all()
    sales_ids = [s.id for s in sales_people]

    q = Query.query.filter(Query.admin_id == current_user.id)
    if selected_sales_id and selected_sales_id.isdigit():
        sid = int(selected_sales_id)
        if sid in sales_ids:
            q = q.filter(Query.sales_id == sid)

    # Available values
    all_q = q.all()
    available_years = sorted({row.date_of_enquiry.year for row in all_q})
    available_sources = sorted({(row.source or '').strip() for row in all_q if (row.source or '').strip()})
    closure_options = [
        'Closed',
        'Prospect',
        'Positive',
        'pending',
        'call again',
        'bad mei bataenge',
        'not intrested',
        'wrong enquiry',
        'invalid',
        'switch off',
        'not picked',
    ]

    # Apply filters
    try:
        if selected_year and selected_year.isdigit():
            year = int(selected_year)
            from datetime import datetime as _dt
            start = _dt(year, 1, 1)
            end = _dt(year + 1, 1, 1)
            q = q.filter(Query.date_of_enquiry >= start, Query.date_of_enquiry < end)
        if selected_month and selected_month.isdigit():
            month = int(selected_month)
            if selected_year and selected_year.isdigit():
                year = int(selected_year)
            else:
                year = datetime.utcnow().year
            from calendar import monthrange
            start = datetime(year, month, 1)
            last_day = monthrange(year, month)[1]
            end = datetime(year, month, last_day, 23, 59, 59)
            q = q.filter(Query.date_of_enquiry >= start, Query.date_of_enquiry <= end)
        if selected_source:
            q = q.filter(Query.source == selected_source)
        if selected_closure:
            q = q.filter(Query.closure == selected_closure)
    except Exception:
        pass

    results = q.order_by(Query.date_of_enquiry.desc()).all()

    from collections import Counter
    by_closure = Counter([(r.closure or 'pending') for r in results])
    by_source = Counter([(r.source or 'reference') for r in results])

    return render_template(
        'admin_analytics.html',
        results=results,
        sales_people=sales_people,
        by_closure=by_closure,
        by_source=by_source,
        filters={
            'year': selected_year or '',
            'month': selected_month or '',
            'source': selected_source or '',
            'closure': selected_closure or '',
            'sales_id': selected_sales_id or ''
        },
        available_years=available_years,
        available_sources=available_sources,
        closure_options=closure_options,
    )

# Sales Routes
@app.route('/sales/dashboard')
@login_required
def sales_dashboard():
    if session.get('user_type') != 'sales' or not isinstance(current_user, Sales):
        flash('Access denied')
        return redirect(url_for('index'))
    
    # Base datasets
    base_query = Query.query.filter_by(sales_id=current_user.id)
    follow_ups = FollowUp.query.filter_by(sales_id=current_user.id).all()

    # Filters
    selected_year = request.args.get('year')
    selected_month = request.args.get('month')  # 1-12
    selected_source = request.args.get('source')

    # Distinct years and sources for filter controls
    all_queries = base_query.all()
    available_years = sorted({q.date_of_enquiry.year for q in all_queries})
    available_sources = sorted({(q.source or '').strip() for q in all_queries if (q.source or '').strip()})

    # Apply filters
    filtered = base_query
    try:
        if selected_year and selected_year.isdigit():
            year = int(selected_year)
            from datetime import datetime as _dt
            start = _dt(year, 1, 1)
            end = _dt(year + 1, 1, 1)
            filtered = filtered.filter(Query.date_of_enquiry >= start, Query.date_of_enquiry < end)
        if selected_month and selected_month.isdigit():
            month = int(selected_month)
            if selected_year and selected_year.isdigit():
                year = int(selected_year)
            else:
                # default to current year if month provided without year
                year = datetime.utcnow().year
            from calendar import monthrange
            start = datetime(year, month, 1)
            last_day = monthrange(year, month)[1]
            end = datetime(year, month, last_day, 23, 59, 59)
            filtered = filtered.filter(Query.date_of_enquiry >= start, Query.date_of_enquiry <= end)
        if selected_source:
            filtered = filtered.filter(Query.source == selected_source)
    except Exception:
        pass

    # Pagination setup
    per_page = 25
    page = request.args.get('page', 1, type=int)

    # Total count for pagination (after filters applied)
    total_queries = filtered.count()
    total_pages = (total_queries + per_page - 1) // per_page if total_queries > 0 else 1

    # Paginated queries for current page, newest first
    queries = filtered.order_by(Query.id.desc()).limit(per_page).offset((page - 1) * per_page).all()

    # All queries for overview statistics (not paginated, but still filtered)
    queries_list = filtered.all()


    # Build combined activity (queries + follow-ups) sorted by date desc
    combined_activity = []
    for q in queries:
        combined_activity.append({
            'type': 'Query',
            'date': q.date_of_enquiry,
            'query': q,
            'followup': None
        })
    # include follow-ups for this sales regardless of filters except source/closure/year/month?
    # We'll include follow-ups for queries currently visible (matching filters) for consistency
    visible_query_ids = {q.id for q in queries}
    for f in follow_ups:
        if f.query_id in visible_query_ids:
            combined_activity.append({
                'type': 'Follow Up',
                'date': f.date_of_contact,
                'query': next((q for q in queries if q.id == f.query_id), None),
                'followup': f
            })
    combined_activity.sort(key=lambda x: x['date'], reverse=True)

    # Map follow-ups by query id for collapsible UI
    followups_by_query = {}
    for f in follow_ups:
        if f.query_id in visible_query_ids:
            followups_by_query.setdefault(f.query_id, []).append(f)
    # sort followups newest first
    for lst in followups_by_query.values():
        lst.sort(key=lambda x: x.date_of_contact, reverse=True)

    # Analytics summary (using all filtered queries, not just paginated ones)
    def count_by_closure(value: str) -> int:
        return sum(1 for q in queries_list if (q.closure or '').strip() == value)

    analytics = {
        'total': len(queries_list),
        'closed': count_by_closure('Closed'),
        'prospect': count_by_closure('Prospect'),
        'pending': count_by_closure('pending'),
        'positive': count_by_closure('Positive'),
        'call_again': count_by_closure('call again'),
        'bad_mei_bataenge': count_by_closure('bad mei bataenge'),
        'not_intrested': count_by_closure('not intrested'),
        'wrong_enquiry': count_by_closure('wrong enquiry'),
        'invalid': count_by_closure('invalid'),
        'switch_off': count_by_closure('switch off'),
        'not_picked': count_by_closure('not picked'),
    }

    # Source distribution (using all filtered queries)
    from collections import Counter
    source_counts = Counter([(q.source or 'reference') for q in queries_list])

    return render_template(
        'sales_dashboard.html',
        queries=queries,
        follow_ups=follow_ups,
        combined_activity=combined_activity,
        followups_by_query=followups_by_query,
        analytics=analytics,
        source_counts=source_counts,
        filters={
            'year': selected_year or '',
            'month': selected_month or '',
            'source': selected_source or ''
        },
        available_years=available_years,
        available_sources=available_sources,
        page=page,
        total_pages=total_pages,
    )

@app.route('/sales/add-query', methods=['GET', 'POST'])
@login_required
def sales_add_query():
    if session.get('user_type') != 'sales' or not isinstance(current_user, Sales):
        flash('Access denied')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        name = request.form['name']
        phone_number = request.form['phone_number']
        service_query = request.form['service_query']
        mail_id = request.form['mail_id']
        source = request.form.get('source') or 'reference'
        closure = request.form.get('closure') or 'not picked'
        
        # Derive admin_id from the sales record to avoid attribute errors on mismatched sessions
        sales_record = db.session.get(Sales, current_user.id)
        if sales_record is None:
            flash('Access denied')
            return redirect(url_for('index'))
        new_query = Query(
            sales_id=current_user.id,
            admin_id=sales_record.admin_id,
            name=name,
            phone_number=phone_number,
            service_query=service_query,
            mail_id=mail_id,
            source=source,
            closure=closure
        )
        db.session.add(new_query)
        db.session.commit()
        try:
            send_new_query_notification_to_sales(new_query.sales_id, new_query)
        except Exception:
            pass
        flash('Query added successfully')
        return redirect(url_for('sales_dashboard'))
    
    return render_template('sales_add_query.html')

@app.route('/sales/analytics')
@login_required
def sales_analytics():
    if session.get('user_type') != 'sales' or not isinstance(current_user, Sales):
        flash('Access denied')
        return redirect(url_for('index'))

    # Filters
    selected_year = request.args.get('year')
    selected_month = request.args.get('month')
    selected_source = request.args.get('source')
    selected_closure = request.args.get('closure')

    q = Query.query.filter_by(sales_id=current_user.id)

    # Available filter values
    all_for_user = q.all()
    available_years = sorted({item.date_of_enquiry.year for item in all_for_user})
    available_sources = sorted({(item.source or '').strip() for item in all_for_user if (item.source or '').strip()})
    closure_options = [
        'Closed',
        'Prospect',
        'Positive',
        'pending',
        'call again',
        'bad mei bataenge',
        'not intrested',
        'wrong enquiry',
        'invalid',
        'switch off',
        'not picked',
    ]

    # Apply filters
    filtered = Query.query.filter_by(sales_id=current_user.id)
    try:
        if selected_year and selected_year.isdigit():
            year = int(selected_year)
            from datetime import datetime as _dt
            start = _dt(year, 1, 1)
            end = _dt(year + 1, 1, 1)
            filtered = filtered.filter(Query.date_of_enquiry >= start, Query.date_of_enquiry < end)
        if selected_month and selected_month.isdigit():
            month = int(selected_month)
            if selected_year and selected_year.isdigit():
                year = int(selected_year)
            else:
                year = datetime.utcnow().year
            from calendar import monthrange
            start = datetime(year, month, 1)
            last_day = monthrange(year, month)[1]
            end = datetime(year, month, last_day, 23, 59, 59)
            filtered = filtered.filter(Query.date_of_enquiry >= start, Query.date_of_enquiry <= end)
        if selected_source:
            filtered = filtered.filter(Query.source == selected_source)
        if selected_closure:
            filtered = filtered.filter(Query.closure == selected_closure)
    except Exception:
        pass

    results = filtered.order_by(Query.date_of_enquiry.desc()).all()

    # Simple counts
    from collections import Counter
    by_closure = Counter([(r.closure or 'pending') for r in results])
    by_source = Counter([(r.source or 'reference') for r in results])

    return render_template(
        'sales_analytics.html',
        results=results,
        by_closure=by_closure,
        by_source=by_source,
        filters={
            'year': selected_year or '',
            'month': selected_month or '',
            'source': selected_source or '',
            'closure': selected_closure or ''
        },
        available_years=available_years,
        available_sources=available_sources,
        closure_options=closure_options,
    )

@app.route('/sales/add-followup', methods=['GET', 'POST'])
@login_required
def add_followup():
    if session.get('user_type') != 'sales' or not isinstance(current_user, Sales):
        flash('Access denied')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        remark = request.form['remark']
        query_id = request.form.get('query_id')
        date_of_contact_str = request.form.get('date_of_contact')
        
        if not query_id:
            flash('Please select a query')
            return redirect(url_for('add_followup'))
        
        if not date_of_contact_str:
            flash('Please select a date of contact')
            return redirect(url_for('add_followup'))
        
        # Parse the datetime-local input
        try:
            date_of_contact = datetime.fromisoformat(date_of_contact_str.replace('Z', '+00:00'))
        except ValueError:
            flash('Invalid date format')
            return redirect(url_for('add_followup'))
        
        sales_record = db.session.get(Sales, current_user.id)
        if sales_record is None:
            flash('Access denied')
            return redirect(url_for('index'))
        new_followup = FollowUp(
            admin_id=sales_record.admin_id,
            sales_id=current_user.id,
            query_id=query_id,
            remark=remark,
            date_of_contact=date_of_contact
        )
        db.session.add(new_followup)
        db.session.commit()
        flash('Follow up added successfully')
        return redirect(url_for('sales_dashboard'))
    
    # Provide current sales user's queries for selection
    selected_query = None
    arg_qid = request.args.get('query_id')
    if arg_qid and arg_qid.isdigit():
        selected_query = db.session.get(Query, int(arg_qid))
        if not selected_query or selected_query.sales_id != current_user.id:
            selected_query = None
    queries = Query.query.filter_by(sales_id=current_user.id).all()
    return render_template('add_followup.html', queries=queries, selected_query=selected_query)

@app.route('/sales/edit-query/<int:id>', methods=['GET', 'POST'])
@login_required
def sales_edit_query(id):
    if session.get('user_type') != 'sales' or not isinstance(current_user, Sales):
        flash('Access denied')
        return redirect(url_for('index'))
    
    query = Query.query.get_or_404(id)
    if query.sales_id != current_user.id:
        flash('Access denied')
        return redirect(url_for('sales_dashboard'))
    
    if request.method == 'POST':
        # Sales can only update closure
        if 'closure' in request.form:
            query.closure = request.form['closure']
        
        db.session.commit()
        flash('Query updated successfully')
        return redirect(url_for('sales_dashboard'))
    
    return render_template('sales_edit_query.html', query=query)

# API endpoint for remote Excel sheet data
@app.route("/api/add_query", methods=["POST"])
def api_add_query():
    try:
        # Check if request has JSON content
        if not request.is_json:
            return jsonify({"status": "error", "message": "Content-Type must be application/json"}), 400
        
        data = request.json
        
        # Validate required fields including admin credentials
        required_fields = ["admin_username", "admin_password", "sales_id", "admin_id", "name", "phone_number", "service_query", "mail_id"]
        for field in required_fields:
            if not data.get(field):
                return jsonify({"status": "error", "message": f"Missing required field: {field}"}), 400
        
        # Validate data types
        try:
            sales_id = int(data["sales_id"])
            admin_id = int(data["admin_id"])
        except (ValueError, TypeError):
            return jsonify({"status": "error", "message": "sales_id and admin_id must be integers"}), 400
        
        # Verify admin credentials first
        admin_username = data["admin_username"].strip()
        admin_password = data["admin_password"]
        
        # Find admin by username
        admin_user = Admin.query.filter_by(username=admin_username).first()
        if not admin_user:
            return jsonify({"status": "error", "message": "Invalid admin credentials"}), 401
        
        # Verify admin password
        if not check_password_hash(admin_user.password_hash, admin_password):
            return jsonify({"status": "error", "message": "Invalid admin credentials"}), 401
        
        # Verify admin_id matches the authenticated admin
        if admin_user.id != admin_id:
            return jsonify({"status": "error", "message": "Admin ID mismatch - you can only add queries for your own admin account"}), 403
        
        # Verify that sales exists and belongs to this admin
        sales_user = db.session.get(Sales, sales_id)
        if not sales_user:
            return jsonify({"status": "error", "message": "Sales user not found"}), 404
        
        if sales_user.admin_id != admin_id:
            return jsonify({"status": "error", "message": "Sales user does not belong to specified admin"}), 400
        
        # Create and save query
        query = Query(
            sales_id=sales_id,
            admin_id=admin_id,
            name=data["name"].strip(),
            phone_number=data["phone_number"].strip(),
            service_query=data["service_query"].strip(),
            mail_id=data["mail_id"].strip(),
            source=(data.get("source", "reference").strip()),
            closure=data.get("closure", "pending").strip()
        )
        
        db.session.add(query)
        db.session.commit()
        # Notify sales devices
        try:
            send_new_query_notification_to_sales(query.sales_id, query)
        except Exception:
            pass
        
        return jsonify({
            "status": "success", 
            "message": "Query added successfully",
            "query_id": query.id
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

# API endpoint for website lead form
@app.route("/api/website/lead", methods=["POST"])
def api_website_lead():
    """
    Endpoint for website lead form submissions.
    Accepts JSON with lead information and creates a query.
    Uses hardcoded values: admin_id=3, sales_id=0, source='website'
    """
    try:
        # Check if request has JSON content
        if not request.is_json:
            return jsonify({"status": "error", "message": "Content-Type must be application/json"}), 400
        
        data = request.json
        
        # Validate required fields
        required_fields = ["name", "phone_number", "service_query", "mail_id"]
        for field in required_fields:
            if not data.get(field):
                return jsonify({"status": "error", "message": f"Missing required field: {field}"}), 400
        
        # Hardcoded values as specified
        admin_id = 3
        sales_id = 0
        source = "website"
        date_of_enquiry = datetime.utcnow()
        
        # Verify admin exists
        admin_user = Admin.query.get(admin_id)
        if not admin_user:
            return jsonify({"status": "error", "message": "Admin not found"}), 404
        
        # Verify sales exists (if sales_id = 0 is not a valid sales person, this will fail)
        # But implementing as requested
        sales_user = Sales.query.get(sales_id)
        if not sales_user:
            return jsonify({"status": "error", "message": "Sales user not found"}), 404
        
        # Create and save query
        query = Query(
            sales_id=sales_id,
            admin_id=admin_id,
            name=data["name"].strip(),
            phone_number=data["phone_number"].strip(),
            service_query=data["service_query"].strip(),
            mail_id=data["mail_id"].strip(),
            source=source,
            closure=data.get("closure", "pending").strip(),
            date_of_enquiry=date_of_enquiry
        )
        
        db.session.add(query)
        db.session.commit()
        
        # Notify sales devices
        try:
            send_new_query_notification_to_sales(query.sales_id, query)
        except Exception:
            pass
        
        return jsonify({
            "status": "success", 
            "message": "Lead submitted successfully",
            "query_id": query.id
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

# API endpoint for Google Forms submissions
@app.route("/api/formAdd", methods=["POST"])
def api_form_add():
    """
    Endpoint for Google Forms submissions via Apps Script.
    Accepts JSON with form data and creates a query.
    Uses hardcoded values: admin_id=3, sales_id=0, source='cold approach' (or from payload)
    """
    try:
        # Check if request has JSON content
        if not request.is_json:
            return jsonify({"status": "error", "message": "Content-Type must be application/json"}), 400
        
        data = request.json
        
        # Validate required fields (mail_id is optional, will default if empty)
        required_fields = ["name", "phone_number", "service_query"]
        for field in required_fields:
            if not data.get(field):
                return jsonify({"status": "error", "message": f"Missing required field: {field}"}), 400
        
        # Handle email - default to johndoe@example.com if empty (matching Apps Script behavior)
        mail_id = data.get("mail_id", "").strip() if data.get("mail_id") else ""
        if not mail_id:
            mail_id = "johndoe@example.com"
        
        # Hardcoded values - same as website endpoint
        admin_id = 3
        sales_id = 0
        
        # Normalize source to match exact values used in the system
        # Google Form dropdown values: GMB, Justdial, Facebook, Website, Reference, Cold Approach, Youtube, Other
        # System values: Gmb, justdial, facebook, website, reference, cold approach, youtube
        def normalize_source(source_str):
            if not source_str:
                return "cold approach"
            source_str = source_str.strip()
            source_lower = source_str.lower()
            # Map Google Form values to system values (case-sensitive matching)
            source_map = {
                # Google Form exact values
                "GMB": "Gmb",
                "Justdial": "justdial",
                "Facebook": "facebook",
                "Website": "website",
                "Reference": "reference",
                "Cold Approach": "cold approach",
                "Youtube": "youtube",
                "Other": "cold approach",  # Other defaults to cold approach
                # Common variations (case-insensitive)
                "gmb": "Gmb",
                "justdial": "justdial",
                "just dial": "justdial",
                "facebook": "facebook",
                "fb": "facebook",
                "website": "website",
                "web": "website",
                "reference": "reference",
                "ref": "reference",
                "cold approach": "cold approach",
                "cold": "cold approach",
                "youtube": "youtube",
                "yt": "youtube",
                "other": "cold approach",
            }
            # First try exact match, then try lowercase match
            return source_map.get(source_str, source_map.get(source_lower, "cold approach"))
        
        # Use source from payload if provided, otherwise default to 'cold approach'
        source_input = data.get("source", "").strip() if data.get("source") else ""
        source = normalize_source(source_input)
        date_of_enquiry = datetime.utcnow()
        
        # Verify admin exists
        admin_user = Admin.query.get(admin_id)
        if not admin_user:
            return jsonify({"status": "error", "message": "Admin not found"}), 404
        
        # Verify sales exists
        sales_user = Sales.query.get(sales_id)
        if not sales_user:
            return jsonify({"status": "error", "message": "Sales user not found"}), 404
        
        # Create and save query
        query = Query(
            sales_id=sales_id,
            admin_id=admin_id,
            name=data["name"].strip(),
            phone_number=data["phone_number"].strip(),
            service_query=data["service_query"].strip(),
            mail_id=mail_id,
            source=source,
            closure=data.get("closure", "pending").strip(),
            date_of_enquiry=date_of_enquiry
        )
        
        db.session.add(query)
        db.session.commit()
        
        # Send FCM notification to sales person
        try:
            send_new_query_notification_to_sales(query.sales_id, query)
        except Exception:
            pass
        
        return jsonify({
            "status": "success", 
            "message": "Query added successfully",
            "query_id": query.id
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

# ------------------------
# Mobile App JSON Endpoints
# ------------------------

def _generate_mobile_token(user: Sales) -> str:
    import secrets
    return f"s_{user.id}_" + secrets.token_hex(24)

def _require_json_fields(data, fields):
    missing = [f for f in fields if not data.get(f)]
    if missing:
        return f"Missing required field(s): {', '.join(missing)}"
    return None

# @app.route('/api/mobile/login', methods=['POST'])
# def api_mobile_login():
#     if not request.is_json:
#         return jsonify({"status":"error","message":"Content-Type must be application/json"}), 400
#     data = request.get_json() or {}
#     err = _require_json_fields(data, ["username", "password", "device_token", "platform", "app_version"])
#     if err:
#         return jsonify({"status":"error","message":err}), 400
#     user = Sales.query.filter_by(username=data["username"]).first()
#     if not user or not check_password_hash(user.password_hash, data["password"]):
#         return jsonify({"status":"error","message":"Invalid credentials"}), 401
#     # Issue a simple bearer token (DB-less). In production, use JWT.
#     token = _generate_mobile_token(user)
#     # Upsert device token
#     existing = DeviceToken.query.filter_by(device_token=data["device_token"]).first()
#     if existing:
#         existing.sales_id = user.id
#         existing.platform = data.get("platform")
#         existing.app_version = data.get("app_version")
#         existing.is_active = True
#         existing.last_seen_at = datetime.utcnow()
#     else:
#         rec = DeviceToken(
#             sales_id=user.id,
#             device_token=data["device_token"],
#             platform=data.get("platform"),
#             app_version=data.get("app_version"),
#             is_active=True,
#             last_seen_at=datetime.utcnow(),
#         )
#         db.session.add(rec)
#     db.session.commit()
#     return jsonify({"status":"success","token":token, "sales_id": user.id, "name": user.name})


@app.route('/api/mobile/login', methods=['POST'])
def api_mobile_login():
    if not request.is_json:
        return jsonify({"status":"error","message":"Content-Type must be application/json"}), 400

    data = request.get_json() or {}
    err = _require_json_fields(data, ["username", "password", "device_token", "platform", "app_version"])
    if err:
        return jsonify({"status":"error","message":err}), 400

    user = Sales.query.filter_by(username=data["username"]).first()
    if not user or not check_password_hash(user.password_hash, data["password"]):
        return jsonify({"status":"error","message":"Invalid credentials"}), 401

    # Issue a simple bearer token (DB-less). In production, use JWT.
    token = _generate_mobile_token(user)

    # Check if a device token already exists for this sales_id
    existing = DeviceToken.query.filter_by(sales_id=user.id).first()
    if existing:
        # Update the existing row
        existing.device_token = data["device_token"]
        existing.platform = data.get("platform")
        existing.app_version = data.get("app_version")
        existing.is_active = True
        existing.last_seen_at = datetime.utcnow()
    else:
        # Insert new row
        rec = DeviceToken(
            sales_id=user.id,
            device_token=data["device_token"],
            platform=data.get("platform"),
            app_version=data.get("app_version"),
            is_active=True,
            last_seen_at=datetime.utcnow(),
        )
        db.session.add(rec)

    db.session.commit()

    return jsonify({"status":"success","token":token, "sales_id": user.id, "name": user.name})

def _auth_sales_from_header():
    auth = request.headers.get('Authorization','')
    if not auth.startswith('Bearer '):
        return None
    # For this simple implementation, extract the embedded sales id
    token = auth[7:]
    try:
        # token format: s_<id>_<random>
        parts = token.split('_')
        if len(parts) >= 3 and parts[0] == 's' and parts[1].isdigit():
            sid = int(parts[1])
            return db.session.get(Sales, sid)
    except Exception:
        return None
    return None

@app.route('/api/mobile/queries', methods=['GET'])
def api_mobile_queries():
    sales_user = _auth_sales_from_header()
    if not sales_user:
        return jsonify({"status":"error","message":"Unauthorized"}), 401
    rows = Query.query.filter_by(sales_id=sales_user.id).order_by(Query.id.desc()).all()
    def to_row(q: Query):
        return {
            "id": q.id,
            "name": q.name,
            "phone_number": q.phone_number,
            "service": q.service_query,
            "source": q.source,
            "closure": q.closure,
            "date": q.date_of_enquiry.strftime('%Y-%m-%d %H:%M:%S')
        }
    return jsonify({"status":"success","results":[to_row(q) for q in rows]})

@app.route('/api/mobile/query/<int:query_id>/closure', methods=['PUT'])
def api_mobile_update_closure(query_id: int):
    sales_user = _auth_sales_from_header()
    if not sales_user:
        return jsonify({"status":"error","message":"Unauthorized"}), 401
    q = Query.query.get_or_404(query_id)
    if q.sales_id != sales_user.id:
        return jsonify({"status":"error","message":"Forbidden"}), 403
    if not request.is_json:
        return jsonify({"status":"error","message":"Content-Type must be application/json"}), 400
    closure = (request.json or {}).get('closure')
    if not closure:
        return jsonify({"status":"error","message":"Missing closure"}), 400
    q.closure = closure
    db.session.commit()
    return jsonify({"status":"success"})

@app.route('/api/mobile/followups', methods=['POST'])
def api_mobile_add_followup():
    sales_user = _auth_sales_from_header()
    if not sales_user:
        return jsonify({"status":"error","message":"Unauthorized"}), 401
    if not request.is_json:
        return jsonify({"status":"error","message":"Content-Type must be application/json"}), 400
    data = request.json or {}
    err = _require_json_fields(data, ["query_id", "remark", "date_of_contact"])
    if err:
        return jsonify({"status":"error","message":err}), 400
    q = Query.query.get_or_404(int(data["query_id"]))
    if q.sales_id != sales_user.id:
        return jsonify({"status":"error","message":"Forbidden"}), 403
    
    # Parse the date_of_contact
    date_of_contact_str = data["date_of_contact"]
    try:
        date_of_contact = datetime.fromisoformat(date_of_contact_str.replace('Z', '+00:00'))
    except ValueError:
        return jsonify({"status":"error","message":"Invalid date format"}), 400
    
    fu = FollowUp(
        admin_id=q.admin_id,
        sales_id=sales_user.id,
        query_id=q.id,
        remark=data["remark"].strip(),
        date_of_contact=date_of_contact
    )
    db.session.add(fu)
    db.session.commit()
    return jsonify({"status":"success","followup_id": fu.id})

# Endpoint to send notification by sales id
@app.route('/api/notify/sales/<int:sales_id>', methods=['POST'])
def api_notify_sales(sales_id: int):
    payload = request.get_json() or {}
    title = payload.get('title') or 'New Query Assigned'
    body = payload.get('body') or 'You have a new query.'
    data = payload.get('data') or {}
    count = send_notification_to_sales_device(sales_id, title, body, data)
    return jsonify({"status":"success","sent": count})

# def send_notification_to_sales_devices(sales_id: int, title: str, body: str, data: dict) -> int:
#     if firebase_admin is None:
#         return 0
#     tokens = [d.device_token for d in DeviceToken.query.filter_by(sales_id=sales_id, is_active=True).all()]
#     if not tokens:
#         return 0
#     message = _fb_messaging.MulticastMessage(
#         notification=_fb_messaging.Notification(title=title, body=body),
#         tokens=tokens,
#         data={k: str(v) for (k, v) in (data or {}).items()}
#     )
#     resp = _fb_messaging.send_multicast(message)
#     return resp.success_count


def send_notification_to_sales_device(sales_id: int, title: str, body: str, data: dict) -> int:
    """
    Send notification to a single device for the given sales_id.
    Returns 1 if sent successfully, 0 otherwise.
    """
    if firebase_admin is None:
        return 0

    # Fetch the latest active device token for the sales_id
    token_obj = DeviceToken.query.filter_by(sales_id=sales_id, is_active=True).order_by(DeviceToken.updated_at.desc()).first()
    if not token_obj:
        return 0

    try:
        message = _fb_messaging.Message(
            notification=_fb_messaging.Notification(title=title, body=body),
            token=token_obj.device_token,
            data={k: str(v) for k, v in (data or {}).items()}
        )
        _fb_messaging.send(message)
        return 1
    except Exception as e:
        print(f"FCM send error: {e}")
        return 0




def send_new_query_notification_to_sales(sales_id: int, q: Query):
    title = 'New Query Assigned'
    body = f"{q.name} - {q.service_query[:30]}"
    data = {"query_id": str(q.id), "name": q.name, "phone": q.phone_number}
    return send_notification_to_sales_device(sales_id, title, body, data)


# Add this new route to your app.py
@app.route('/api/debug/sales_tokens/<int:sales_id>', methods=['GET'])
def debug_sales_tokens(sales_id):
    tokens = [d.device_token for d in DeviceToken.query.filter_by(sales_id=sales_id, is_active=True).all()]
    return jsonify({"sales_id": sales_id, "tokens": tokens})

@app.route('/api/mobile/query/<int:query_id>/followups', methods=['GET'])
def api_mobile_get_followups(query_id: int):
    sales_user = _auth_sales_from_header()
    if not sales_user:
        return jsonify({"status":"error","message":"Unauthorized"}), 401

    query = Query.query.get_or_404(query_id)
    if query.sales_id != sales_user.id:
        return jsonify({"status":"error", "message":"Forbidden"}), 403

    followups = FollowUp.query.filter_by(query_id=query_id).order_by(FollowUp.date_of_contact.desc()).all()

    def to_row(fu: FollowUp):
        return {
            "id": fu.id,
            "remark": fu.remark,
            "date_of_contact": fu.date_of_contact.strftime('%Y-%m-%d %H:%M:%S')
        }

    return jsonify({"status": "success", "results": [to_row(fu) for fu in followups]})

@app.route('/test-firebase')
def test_firebase():
    try:
        import firebase_admin
        from firebase_admin import credentials, messaging
        firebase_imported = True
    except Exception as e:
        firebase_imported = False
        import_error = str(e)
    response = {}

    # Check if firebase_admin imported
    if not firebase_imported:
        response['firebase_imported'] = False
        response['import_error'] = import_error
        return jsonify(response)

    response['firebase_imported'] = True

    # Check if Firebase is initialized
    if not firebase_admin._apps:
        response['firebase_initialized'] = False
        response['init_error'] = "Firebase not initialized. Did you set service account credentials?"
        return jsonify(response)

    response['firebase_initialized'] = True

    # Try sending a test multicast message (empty tokens)
    try:
        message = messaging.MulticastMessage(
            tokens=[],  # no real tokens, just testing
            notification=messaging.Notification(
                title="Test Notification",
                body="This is a test message"
            ),
            data={"foo": "bar"}
        )
        result = messaging.send_multicast(message)
        response['test_message'] = f"Success: {result.success_count} messages sent, {result.failure_count} failed"
    except Exception as e:
        response['test_message'] = f"Failed: {str(e)}"

    return jsonify(response)

@app.route('/api/notify/test_token', methods=['POST'])
def api_notify_test_token():
    payload = request.get_json() or {}
    token = payload.get('token')
    if not token:
        return jsonify({"status": "error", "message": "Token is required"}), 400

    title = payload.get('title', 'Test Notification')
    body = payload.get('body', 'This is a test message')
    data = payload.get('data', {})

    if firebase_admin is None:
        return jsonify({"status": "error", "message": "Firebase not initialized"}), 500

    message = _fb_messaging.Message(
        notification=_fb_messaging.Notification(title=title, body=body),
        token=token,
        data={k: str(v) for k, v in data.items()}
    )

    try:
        resp = _fb_messaging.send(message)
        return jsonify({"status": "success", "response": resp})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500



if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        # Create default super admin if none exists
        if not SuperAdmin.query.first():
            default_super_admin = SuperAdmin(
                name='Default Super Admin',
                username='superadmin',
                password_hash=generate_password_hash('admin123')
            )
            db.session.add(default_super_admin)
            db.session.commit()
            print("Default super admin created: username='superadmin', password='admin123'")
    
    app.run(host='0.0.0.0', port=5000, debug=os.getenv('FLASK_ENV', False))
