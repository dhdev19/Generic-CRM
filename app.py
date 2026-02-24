from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone, timedelta
import os
import json
import re
import secrets
import string
from config import config
import pymysql
from sqlalchemy import desc, or_
from sqlalchemy.exc import IntegrityError

# IST timezone (GMT+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

def get_ist_now():
    """Get current time in IST (Indian Standard Time, GMT+5:30)"""
    return datetime.now(IST)


def _db_datetime_aware(dt):
    """Return datetime comparable with get_ist_now(). DB often returns naive; treat as IST."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt 
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

# Auto-assignment configuration
# Set AUTO_ASSIGN=True in environment variable or config to enable automatic sales rep assignment
# When False, queries are assigned to admin's bucket sales (admin_sales_id from DB, or 0 if not set)
AUTO_ASSIGN = os.environ.get('AUTO_ASSIGN', 'false').lower() == 'true'


def get_admin_sales_id(admin_id: int) -> int:
    """Return the Sales id used as the admin's unassigned-query bucket. Falls back to 0 if not set."""
    admin = Admin.query.get(admin_id)
    if not admin or admin.admin_sales_id is None:
        return 0
    return admin.admin_sales_id


def _generate_integration_slug() -> str:
    """Return a new unique 12-char alphanumeric slug for integration URLs. Always checks DB for uniqueness."""
    alphabet = string.ascii_letters + string.digits
    for _ in range(20):
        slug = ''.join(secrets.choice(alphabet) for _ in range(12))
        if not Admin.query.filter_by(integration_slug=slug).first():
            return slug
    # Fallback: ensure even this path returns a slug that was verified unique
    for _ in range(20):
        raw = secrets.token_urlsafe(9)
        slug = (raw.replace('-', 'x').replace('_', 'y') + 'Ab1')[::2][:12]  # 12 chars
        if not Admin.query.filter_by(integration_slug=slug).first():
            return slug
    raise RuntimeError('Could not generate unique integration_slug')


def ensure_admin_integration_slug(admin: 'Admin') -> str:
    """Ensure admin has integration_slug; generate and save if None. Regenerates on unique constraint violation."""
    if admin.integration_slug:
        return admin.integration_slug
    for _ in range(5):
        admin.integration_slug = _generate_integration_slug()
        try:
            db.session.commit()
            return admin.integration_slug
        except IntegrityError:
            db.session.rollback()
            admin.integration_slug = None
    raise RuntimeError('Could not assign unique integration_slug to admin')


def validate_registration_password(password: str) -> tuple:
    """Validate password: min 8 len, 1 upper, 1 lower, 1 special, 1 digit. Returns (True, None) or (False, error_msg)."""
    if len(password) < 8:
        return False, 'Password must be at least 8 characters'
    if not re.search(r'[A-Z]', password):
        return False, 'Password must contain at least one uppercase letter'
    if not re.search(r'[a-z]', password):
        return False, 'Password must contain at least one lowercase letter'
    if not re.search(r'[0-9]', password):
        return False, 'Password must contain at least one number'
    if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\;/\'`~]', password):
        return False, 'Password must contain at least one special character'
    return True, None


def send_verification_email(to_email: str, otp: str) -> tuple:
    """Send OTP email using SMTP credentials from .env. Returns (True, None) on success or (False, error_message)."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    server = os.environ.get('MAIL_SERVER')
    port = int(os.environ.get('MAIL_PORT', '587'))
    username = os.environ.get('MAIL_USERNAME')
    password = os.environ.get('MAIL_PASSWORD')
    use_tls = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    from_addr = os.environ.get('MAIL_FROM') or username
    if not server or not username or not password:
        return False, 'Mail not configured (set MAIL_SERVER, MAIL_USERNAME, MAIL_PASSWORD in .env)'
    try:
        msg = MIMEMultipart()
        msg['From'] = from_addr
        msg['To'] = to_email
        msg['Subject'] = 'Your email verification OTP'
        body = f'Your verification code is: {otp}. It is valid for 5 minutes.'
        msg.attach(MIMEText(body, 'plain'))
        # Port 465 uses implicit SSL (SMTPS); 587 uses STARTTLS
        if port == 465:
            with smtplib.SMTP_SSL(server, port) as s:
                s.login(username, password)
                s.sendmail(from_addr, to_email, msg.as_string())
        else:
            with smtplib.SMTP(server, port) as s:
                if use_tls:
                    s.starttls()
                s.login(username, password)
                s.sendmail(from_addr, to_email, msg.as_string())
        return True, None
    except Exception as e:
        err = str(e)
        print(f'[send_verification_email] failed: {err}')
        return False, err or 'Failed to send email'


def get_admin_by_integration_identifier(identifier) -> 'Admin':
    """Resolve Admin by numeric id or integration_slug. Returns None if not found."""
    try:
        aid = int(identifier)
        return Admin.query.get(aid)
    except (ValueError, TypeError):
        pass
    return Admin.query.filter_by(integration_slug=identifier).first()

# Standard lead sources used across forms and analytics.
SOURCE_OPTIONS = [
    'Gmb',
    'justdial',
    'facebook',
    'website',
    'reference',
    'cold approach',
    'youtube',
    'meta_ads',
    '99acres',
    'magic bricks',
    'housing',
]

def build_available_sources(items):
    dynamic_sources = {(item.source or '').strip() for item in items if (item.source or '').strip()}
    return sorted(set(SOURCE_OPTIONS).union(dynamic_sources))

def is_mobile_request() -> bool:
    ua = (request.headers.get('User-Agent') or '').lower()
    mobile_markers = ('android', 'iphone', 'ipad', 'ipod', 'mobile', 'opera mini', 'iemobile', 'wv')
    return any(marker in ua for marker in mobile_markers)

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
    # Sales record used as "admin queue" bucket for unassigned leads (created when admin is added).
    admin_sales_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=True)
    # Unique slug for integration URLs (auto-generated; not guessable from id).
    integration_slug = db.Column(db.String(24), unique=True, nullable=True, index=True)

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
    date_of_enquiry = db.Column(db.DateTime, default=get_ist_now)
    name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    service_query = db.Column(db.Text, nullable=False)
    mail_id = db.Column(db.String(120), nullable=False)
    # New source column and updated closure domain
    source = db.Column(db.String(50), default='reference')  # Gmb, justdial, facebook, website, reference, cold approach, youtube, meta_ads, 99acres, magic bricks, housing
    # Closures: Closed, Prospect, Positive, pending, call again, bad mei bataenge,
    # not intrested, wrong enquiry, invalid, switch off, not picked
    closure = db.Column(db.String(30), default='pending')
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)

class FollowUp(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=False)
    sales_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    query_id = db.Column(db.Integer, db.ForeignKey('query.id'), nullable=False)
    date_of_contact = db.Column(db.DateTime, default=get_ist_now)
    remark = db.Column(db.Text, nullable=False)

# Device token model for mobile push notifications
class DeviceToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sales_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False, index=True)
    device_token = db.Column(db.String(512), nullable=False, index=True)
    platform = db.Column(db.String(50))
    app_version = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=get_ist_now)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    last_seen_at = db.Column(db.DateTime)

# Device token model for admin WebView push notifications
class AdminDeviceToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=False, index=True)
    device_token = db.Column(db.String(512), nullable=False, index=True)
    platform = db.Column(db.String(50))
    app_version = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=get_ist_now)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    last_seen_at = db.Column(db.DateTime)

# Daily Report model
class DailyReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sales_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False, index=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=False, index=True)
    report_date = db.Column(db.Date, nullable=False, index=True)
    report_text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=get_ist_now)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    __table_args__ = (db.UniqueConstraint('sales_id', 'report_date', name='unique_sales_date'),)

# Payment plans for registration
class PaymentPlan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)  # in INR
    max_users = db.Column(db.Integer, nullable=False)
    validity = db.Column(db.Integer, nullable=False)  # number of days

# Organization details (one per admin)
class OrganizationDetails(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=False, unique=True)
    phone_number = db.Column(db.String(20), nullable=False)
    organization_name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(255), nullable=True)

# Admin's current plan and renewal
class AdminPlan(db.Model):
    admin_id = db.Column(db.Integer, db.ForeignKey('admin.id'), primary_key=True)
    payment_plan_id = db.Column(db.Integer, db.ForeignKey('payment_plan.id'), nullable=False)
    renewal_date = db.Column(db.Date, nullable=False)

# Temp OTP for email verification (validity 5 minutes)
class TempOtp(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    otp = db.Column(db.String(6), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)

# Temp user during registration (before payment and admin creation)
class TempUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    organization_name = db.Column(db.String(200), nullable=False)
    payment_plan_id = db.Column(db.Integer, db.ForeignKey('payment_plan.id'), nullable=False)
    status = db.Column(db.String(50), nullable=False)  # payment_initiated, transaction_completed, user_added_in_db
    razorpay_order_id = db.Column(db.String(100), unique=True, nullable=True, index=True)
    razorpay_payment_id = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=get_ist_now)

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

@app.before_request
def restore_session_user_type_for_authenticated_user():
    """
    When opening deep links (e.g. from push notifications), requests may not
    pass through index/login first. Ensure session user_type is present so role
    checks don't redirect away from the intended page.
    """
    if not current_user.is_authenticated:
        return
    if session.get('user_type'):
        return

    if isinstance(current_user, SuperAdmin):
        session['user_type'] = 'super_admin'
    elif isinstance(current_user, Admin):
        session['user_type'] = 'admin'
    elif isinstance(current_user, Sales):
        session['user_type'] = 'sales'
    session['user_id'] = current_user.id
    session.modified = True

# Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        user_type = session.get('user_type')
        if not user_type:
            if isinstance(current_user, SuperAdmin):
                user_type = 'super_admin'
            elif isinstance(current_user, Admin):
                user_type = 'admin'
            elif isinstance(current_user, Sales):
                user_type = 'sales'
            if user_type:
                session['user_type'] = user_type
                session['user_id'] = current_user.id
                session.modified = True

        if user_type == 'super_admin':
            return redirect(url_for('super_admin_dashboard'))
        if user_type == 'admin':
            return redirect(url_for('admin_dashboard'))
        if user_type == 'sales':
            return redirect(url_for('sales_dashboard'))
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
    if request.method == 'GET' and current_user.is_authenticated:
        user_type = session.get('user_type')
        if not user_type:
            if isinstance(current_user, SuperAdmin):
                user_type = 'super_admin'
            elif isinstance(current_user, Admin):
                user_type = 'admin'
            elif isinstance(current_user, Sales):
                user_type = 'sales'
            if user_type:
                session['user_type'] = user_type
                session['user_id'] = current_user.id
                session.modified = True

        if user_type == 'super_admin':
            return redirect(url_for('super_admin_dashboard'))
        if user_type == 'admin':
            return redirect(url_for('admin_dashboard'))
        if user_type == 'sales':
            return redirect(url_for('sales_dashboard'))

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
            login_user(user, remember=True)
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


# Razorpay (optional; used for registration)
_razorpay_client = None
def get_razorpay_client():
    global _razorpay_client
    if _razorpay_client is None:
        key_id = os.environ.get('RAZORPAY_KEY_ID')
        key_secret = os.environ.get('RAZORPAY_KEY_SECRET')
        if key_id and key_secret:
            try:
                import razorpay
                _razorpay_client = razorpay.Client(auth=(key_id, key_secret))
            except Exception:
                pass
    return _razorpay_client


@app.route('/api/register/check-username')
def api_register_check_username():
    """Return { available: true/false, error?: str } for real-time username check.

    Frontend only needs to know if a username is already taken by a real Admin.
    Any in-progress TempUser registrations are handled on final form submit.
    """
    username = (request.args.get('username') or '').strip()
    if not username:
        return jsonify({'available': False})
    try:
        if Admin.query.filter_by(username=username).first():
            return jsonify({'available': False})
        return jsonify({'available': True})
    except Exception:
        return jsonify({'available': False, 'error': 'Unable to verify username. Please try again.'})


@app.route('/api/register/send-otp', methods=['POST'])
def api_register_send_otp():
    """Send 6-digit OTP to email. Store in TempOtp with 5 min validity. Resend only after 5 mins."""
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    if not email or '@' not in email:
        return jsonify({'success': False, 'message': 'Valid email is required'}), 400
    # Check last OTP for this email: allow resend only if last one is older than 5 mins
    last = TempOtp.query.filter_by(email=email).order_by(TempOtp.expires_at.desc()).first()
    now = get_ist_now()
    if last:
        expires_at = _db_datetime_aware(last.expires_at)
        if expires_at > now:
            delta = expires_at - now
            seconds_left = max(0, int(delta.total_seconds()))
            print(f'[send-otp] 400: resend not yet allowed for {email!r}, wait {seconds_left}s')
            return jsonify({
                'success': False,
                'message': 'Please wait until the current OTP expires (5 minutes) before resending.',
                'resend_after_seconds': seconds_left
            }), 400
    otp = ''.join(secrets.choice(string.digits) for _ in range(6))
    expires_at = now + timedelta(minutes=5)
    TempOtp.query.filter_by(email=email).delete()
    db.session.add(TempOtp(email=email, otp=otp, expires_at=expires_at))
    db.session.commit()
    ok, err_msg = send_verification_email(email, otp)
    if not ok:
        db.session.rollback()
        return jsonify({'success': False, 'message': err_msg or 'Failed to send email. Check mail configuration.'}), 500
    return jsonify({'success': True, 'expires_in_seconds': 300})


@app.route('/api/register/verify-otp', methods=['POST'])
def api_register_verify_otp():
    """Verify OTP for email. On success set session['register_email_verified'] = email."""
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    otp = (data.get('otp') or '').strip()
    if not email or not otp:
        return jsonify({'success': False, 'message': 'Email and OTP required'}), 400
    row = TempOtp.query.filter_by(email=email).order_by(TempOtp.expires_at.desc()).first()
    if not row or row.otp != otp:
        return jsonify({'success': False, 'message': 'Invalid or expired OTP'}), 400
    if _db_datetime_aware(row.expires_at) < get_ist_now():
        return jsonify({'success': False, 'message': 'OTP has expired'}), 400
    session['register_email_verified'] = email
    return jsonify({'success': True})


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Registration: form with plan; on submit save TempUser and initiate Razorpay payment."""
    if request.method == 'GET':
        plans = PaymentPlan.query.order_by(PaymentPlan.amount).all()
        return render_template('register.html', plans=plans)
    # POST
    full_name = (request.form.get('full_name') or '').strip()
    username = (request.form.get('username') or '').strip()
    password = request.form.get('password') or ''
    email = (request.form.get('email') or '').strip().lower()
    phone_number = (request.form.get('phone_number') or '').strip()
    organization_name = (request.form.get('organization_name') or '').strip()
    plan_id = request.form.get('plan_id')
    errors = []
    if not full_name:
        errors.append('Full name is required')
    if not username:
        errors.append('Username is required')
    if not password:
        errors.append('Password is required')
    else:
        ok, msg = validate_registration_password(password)
        if not ok:
            errors.append(msg)
    if not email or '@' not in email:
        errors.append('Valid email is required')
    if session.get('register_email_verified') != email:
        errors.append('Email must be verified')
    if not phone_number:
        errors.append('Phone number is required')
    if not organization_name:
        errors.append('Organization name is required')
    plan = None
    if plan_id:
        try:
            plan = PaymentPlan.query.get(int(plan_id))
        except (ValueError, TypeError):
            pass
    if not plan:
        errors.append('Please select a plan')
    if Admin.query.filter_by(username=username).first():
        errors.append('Username already registered')
    if TempUser.query.filter_by(username=username).filter(TempUser.status.in_(['payment_initiated', 'transaction_completed'])).first():
        errors.append('Username already has a registration in progress')
    if errors:
        plans = PaymentPlan.query.order_by(PaymentPlan.amount).all()
        return render_template('register.html', plans=plans, errors=errors,
                               full_name=full_name, username=username, email=email, phone_number=phone_number,
                               organization_name=organization_name, plan_id=plan_id)
    temp_user = TempUser(
        name=full_name,
        username=username,
        password_hash=generate_password_hash(password),
        email=email,
        phone_number=phone_number,
        organization_name=organization_name,
        payment_plan_id=plan.id,
        status='payment_initiated',
    )
    db.session.add(temp_user)
    db.session.commit()
    razorpay_key_id = os.environ.get('RAZORPAY_KEY_ID', '')
    order_id = None
    amount_paise = int(float(plan.amount) * 100)
    client = get_razorpay_client()
    if client:
        try:
            order = client.order.create({
                'amount': amount_paise,
                'currency': 'INR',
                'receipt': f'temp_{temp_user.id}',
                'notes': {'temp_user_id': str(temp_user.id)},
            })
            order_id = order.get('id')
            if order_id:
                temp_user.razorpay_order_id = order_id
                db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f'Payment setup failed: {str(e)}')
            return redirect(url_for('register'))
    else:
        flash('Payment is not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.')
        return redirect(url_for('register'))
    session.pop('register_email_verified', None)
    return render_template('register_pay.html',
                           order_id=order_id, amount=amount_paise, currency='INR',
                           razorpay_key_id=razorpay_key_id,
                           plan_name=f'Plan (₹{plan.amount}, {plan.validity} days)')


def _complete_registration_after_payment(temp_user: 'TempUser', payment_id: str) -> bool:
    """Create Admin, OrganizationDetails, AdminPlan from TempUser in a transaction. Retries on failure. Returns True if done."""
    plan = PaymentPlan.query.get(temp_user.payment_plan_id)
    if not plan:
        return False
    renewal_date = (get_ist_now().date() + timedelta(days=plan.validity)) if plan.validity else get_ist_now().date()
    max_retries = 3
    for attempt in range(max_retries):
        try:
            new_admin = Admin(
                name=temp_user.name,
                username=temp_user.username,
                password_hash=temp_user.password_hash,
                password_plain_text='',  # not stored after registration
            )
            new_admin.integration_slug = _generate_integration_slug()
            db.session.add(new_admin)
            db.session.flush()
            bucket_sales = Sales(
                admin_id=new_admin.id,
                name='Admin Queue',
                username=f'admin_queue_{new_admin.id}',
                password_hash=generate_password_hash(f'admin_queue_{new_admin.id}'),
            )
            db.session.add(bucket_sales)
            db.session.flush()
            new_admin.admin_sales_id = bucket_sales.id
            org = OrganizationDetails(
                admin_id=new_admin.id,
                phone_number=temp_user.phone_number,
                organization_name=temp_user.organization_name,
                email=getattr(temp_user, 'email', None) or None,
            )
            db.session.add(org)
            admin_plan = AdminPlan(
                admin_id=new_admin.id,
                payment_plan_id=plan.id,
                renewal_date=renewal_date,
            )
            db.session.add(admin_plan)
            temp_user.status = 'user_added_in_db'
            temp_user.razorpay_payment_id = payment_id
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            if attempt == max_retries - 1:
                print(f"Registration completion failed after {max_retries} attempts: {e}")
                return False
    return False


@app.route('/api/webhook/razorpay', methods=['POST'])
def razorpay_webhook():
    """Razorpay webhook: on payment.captured, complete registration (Admin + OrganizationDetails + AdminPlan)."""
    webhook_secret = os.environ.get('RAZORPAY_WEBHOOK_SECRET')
    if not webhook_secret:
        return jsonify({'status': 'error', 'message': 'Webhook not configured'}), 500
    raw_body = request.get_data()
    body_str = raw_body.decode('utf-8') if isinstance(raw_body, bytes) else raw_body
    signature = request.headers.get('X-Razorpay-Signature', '')
    client = get_razorpay_client()
    if not client:
        return jsonify({'status': 'error', 'message': 'Razorpay not configured'}), 500
    try:
        client.utility.verify_webhook_signature(body_str, signature, webhook_secret)
    except Exception as e:
        return jsonify({'status': 'error', 'message': 'Invalid signature'}), 400
    try:
        data = json.loads(body_str)
    except Exception:
        return jsonify({'status': 'error', 'message': 'Invalid JSON'}), 400
    event = data.get('event')
    if event != 'payment.captured':
        return jsonify({'status': 'ok'}), 200
    payload = data.get('payload', {})
    payment_entity = payload.get('payment', {}).get('entity', payload.get('entity', {}))
    order_id = payment_entity.get('order_id')
    payment_id = payment_entity.get('id', '')
    if not order_id:
        return jsonify({'status': 'error', 'message': 'No order_id'}), 400
    temp_user = TempUser.query.filter_by(razorpay_order_id=order_id).first()
    if not temp_user:
        return jsonify({'status': 'error', 'message': 'TempUser not found'}), 404
    if temp_user.status == 'user_added_in_db':
        return jsonify({'status': 'ok', 'message': 'Already processed'}), 200
    temp_user.status = 'transaction_completed'
    db.session.commit()
    if not _complete_registration_after_payment(temp_user, payment_id):
        return jsonify({'status': 'error', 'message': 'Failed to create admin'}), 500
    return jsonify({'status': 'ok'}), 200


@app.route('/logout')
@login_required
def logout():
    logout_user()
    # Do not call session.clear() after logout_user().
    # logout_user() sets internal remember-cookie clear markers in session;
    # clearing the whole session here can remove those markers and cause re-login.
    session.pop('user_type', None)
    session.pop('user_id', None)
    session.modified = True
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
            for _ in range(5):
                new_admin.integration_slug = _generate_integration_slug()
                db.session.add(new_admin)
                try:
                    db.session.commit()
                    break
                except IntegrityError:
                    db.session.rollback()
                    new_admin.integration_slug = None
            else:
                flash('Could not create admin (please try again)')
                return redirect(url_for('add_admin'))
            # Create admin bucket Sales record (for unassigned leads) and link it
            bucket_username = f"admin_queue_{new_admin.id}"
            bucket_sales = Sales(
                admin_id=new_admin.id,
                name="Admin Queue",
                username=bucket_username,
                password_hash=generate_password_hash(bucket_username),  # placeholder, not used for login
            )
            db.session.add(bucket_sales)
            db.session.commit()
            new_admin.admin_sales_id = bucket_sales.id
            db.session.commit()
            flash('Admin added successfully')
            return redirect(url_for('super_admin_dashboard'))
    
    return render_template('add_admin.html')


@app.route('/super-admin/payment-plans', methods=['GET', 'POST'])
@login_required
def payment_plans():
    if session.get('user_type') != 'super_admin':
        flash('Access denied')
        return redirect(url_for('index'))
    if request.method == 'POST':
        try:
            amount = float(request.form.get('amount', 0))
            max_users = int(request.form.get('max_users', 0))
            validity = int(request.form.get('validity', 0))
        except (ValueError, TypeError):
            flash('Invalid amount, max users or validity')
            return redirect(url_for('payment_plans'))
        if amount <= 0 or max_users <= 0 or validity <= 0:
            flash('Amount, max users and validity must be positive')
            return redirect(url_for('payment_plans'))
        db.session.add(PaymentPlan(amount=amount, max_users=max_users, validity=validity))
        db.session.commit()
        flash('Payment plan added successfully')
        return redirect(url_for('payment_plans'))
    plans = PaymentPlan.query.order_by(PaymentPlan.amount).all()
    return render_template('payment_plans.html', plans=plans)


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
    try:
        admin.admin_sales_id = None
        db.session.commit()
        sales_ids = [s.id for s in Sales.query.filter_by(admin_id=id).all()]
        for sid in sales_ids:
            DeviceToken.query.filter_by(sales_id=sid).delete()
            FollowUp.query.filter_by(sales_id=sid).delete()
            Query.query.filter_by(sales_id=sid).delete()
        FollowUp.query.filter_by(admin_id=id).delete()
        Query.query.filter_by(admin_id=id).delete()
        Sales.query.filter_by(admin_id=id).delete()
        db.session.delete(admin)
        db.session.commit()
        flash('Admin removed successfully')
    except Exception as e:
        db.session.rollback()
        flash(f'Error removing admin: {str(e)}')
    return redirect(url_for('super_admin_dashboard'))

# Admin Routes
@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if session.get('user_type') != 'admin':
        flash('Access denied')
        return redirect(url_for('index'))
    
    sales_persons = Sales.query.filter_by(admin_id=current_user.id).all()
    
    # Search parameter
    search_query = request.args.get('search', '').strip()

    # Base query joining Query with Sales to get sales person name
    base_query = db.session.query(Query, Sales.name.label('sales_name')).join(
        Sales, Query.sales_id == Sales.id
    ).filter(
        Query.admin_id == current_user.id
    )
    
    # Apply search filter if provided
    if search_query:
        search_filter = or_(
            Query.name.ilike(f'%{search_query}%'),
            Query.phone_number.ilike(f'%{search_query}%')
        )
        base_query = base_query.filter(search_filter)

    # Get all queries (no pagination when grouping by month)
    all_queries = base_query.order_by(Query.date_of_enquiry.desc(), Query.id.desc()).all()

    # Group queries by month and year
    from collections import defaultdict
    queries_by_month = defaultdict(list)
    current_month_year = None
    
    for query_tuple in all_queries:
        query = query_tuple[0]
        month_year = (query.date_of_enquiry.year, query.date_of_enquiry.month)
        queries_by_month[month_year].append(query_tuple)
        
        # Track current month/year
        if current_month_year is None:
            current_month_year = month_year
    
    # Get current month/year in IST
    ist_now = get_ist_now()
    current_month_year = (ist_now.year, ist_now.month)
    
    # Sort month keys: current month first, then descending
    month_keys = sorted(queries_by_month.keys(), key=lambda x: (x != current_month_year, -x[0], -x[1]))
    
    # All queries for overview statistics (not paginated, without search filter)
    queries_list = Query.query.filter_by(admin_id=current_user.id).all()

    # Get all query IDs for follow-ups
    all_query_ids = [q[0].id for q in all_queries]
    followups_by_query = {}
    if all_query_ids:
        followups = FollowUp.query.filter(FollowUp.query_id.in_(all_query_ids)).order_by(FollowUp.date_of_contact.desc()).all()
        for fu in followups:
            followups_by_query.setdefault(fu.query_id, []).append(fu)
    
    admin_sales_id = get_admin_sales_id(current_user.id)
    return render_template(
        'admin_dashboard.html',
        sales_persons=sales_persons,
        admin_sales_id=admin_sales_id,
        queries_by_month=queries_by_month,
        month_keys=month_keys,
        current_month_year=current_month_year,
        queries_list=queries_list,
        followups_by_query=followups_by_query,
        search_query=search_query,
    )

@app.route('/admin/integrations')
@login_required
def admin_integrations():
    """Integration endpoints page for admin: copy-ready URLs with integration_slug, sample request/response."""
    if session.get('user_type') != 'admin' or not isinstance(current_user, Admin):
        flash('Access denied')
        return redirect(url_for('index'))
    integration_slug = ensure_admin_integration_slug(current_user)
    base_url = (app.config.get('BASE_URL') or request.url_root or '').rstrip('/')
    admin_id = current_user.id
    endpoints = [
        {
            'name': 'Website Lead',
            'method': 'POST',
            'path': f'/api/website/lead/{integration_slug}',
            'description': 'Website lead form. Creates query in your Admin Queue. Optional auto-assign if enabled.',
            'sample_request': {
                'name': 'Lead Name',
                'phone_number': '9999888877',
                'service_query': 'Website enquiry text',
                'mail_id': 'lead@example.com',
                'source': 'website',
                'closure': 'pending'
            },
            'sample_response': {'status': 'success', 'message': 'Lead submitted successfully', 'query_id': 43}
        },
        {
            'name': 'Form / Google Forms',
            'method': 'POST',
            'path': f'/api/formAdd/{integration_slug}',
            'description': 'Google Forms / Apps Script. Source normalized from payload or default "cold approach".',
            'sample_request': {
                'name': 'Form Lead',
                'phone_number': '8888777766',
                'service_query': 'Form enquiry',
                'mail_id': 'form@example.com',
                'source': 'Website',
                'closure': 'pending'
            },
            'sample_response': {'status': 'success', 'message': 'Lead submitted successfully', 'query_id': 44}
        },
        {
            'name': 'Webhook: Magic Bricks',
            'method': 'POST',
            'path': f'/api/webhook/magic-bricks/{integration_slug}',
            'description': 'Webhook for Magic Bricks. Any JSON body; lead created with source "magic bricks".',
            'sample_request': {'foo': 'bar'},
            'sample_response': {'status': 'success', 'message': 'Lead submitted successfully', 'query_id': 45}
        },
        {
            'name': 'Webhook: 99acres',
            'method': 'POST',
            'path': f'/api/webhook/99acres/{integration_slug}',
            'description': 'Webhook for 99acres. Any JSON body; lead created with source "99acres".',
            'sample_request': {},
            'sample_response': {'status': 'success', 'message': 'Lead submitted successfully', 'query_id': 46}
        },
        {
            'name': 'Webhook: Housing',
            'method': 'POST',
            'path': f'/api/webhook/housing/{integration_slug}',
            'description': 'Webhook for Housing. Any JSON body; lead created with source "housing".',
            'sample_request': {},
            'sample_response': {'status': 'success', 'message': 'Lead submitted successfully', 'query_id': 47}
        },
    ]
    for ep in endpoints:
        ep['full_url'] = base_url + ep['path'] if base_url else ep['path']
        ep['sample_request_json'] = json.dumps(ep['sample_request'], indent=2)
        ep['sample_response_json'] = json.dumps(ep['sample_response'], indent=2)
    return render_template(
        'admin_integrations.html',
        base_url=base_url,
        admin_id=admin_id,
        integration_slug=integration_slug,
        endpoints=endpoints,
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
    
    # Do not allow deleting the admin bucket sales (used for unassigned leads)
    if Admin.query.filter_by(admin_sales_id=id).first():
        flash('Cannot remove Admin Queue. It is used for unassigned leads.')
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

@app.route('/admin/change-sales-password', methods=['POST'])
@login_required
def change_sales_password():
    if session.get('user_type') != 'admin':
        flash('Access denied')
        return redirect(url_for('index'))
    
    sales_id = request.form.get('sales_id')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    if not sales_id or not new_password or not confirm_password:
        flash('All fields are required')
        return redirect(url_for('admin_dashboard'))
    
    if new_password != confirm_password:
        flash('Passwords do not match')
        return redirect(url_for('admin_dashboard'))
    
    if len(new_password) < 6:
        flash('Password must be at least 6 characters long')
        return redirect(url_for('admin_dashboard'))
    
    # Get the sales person and verify they belong to this admin
    sales = Sales.query.filter_by(id=sales_id, admin_id=current_user.id).first()
    if not sales:
        flash('Sales person not found or access denied')
        return redirect(url_for('admin_dashboard'))
    
    # Do not allow changing password for Admin Queue (admin bucket sales)
    if get_admin_sales_id(current_user.id) == sales.id:
        flash('Cannot change password for Admin Queue')
        return redirect(url_for('admin_dashboard'))
    
    try:
        # Update the password
        sales.password_hash = generate_password_hash(new_password)
        db.session.commit()
        flash(f'Password changed successfully for {sales.name}')
    except Exception as e:
        db.session.rollback()
        flash(f'Error changing password: {str(e)}')
    
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
    return render_template('add_query.html', sales_persons=sales_persons, source_options=SOURCE_OPTIONS)

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
        old_sales_id = query.sales_id
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
                query.updated_at = get_ist_now()  # Update timestamp when reassigned
                
                # Update all follow-ups for this query to the new sales person
                follow_ups = FollowUp.query.filter_by(query_id=query.id).all()
                for follow_up in follow_ups:
                    follow_up.sales_id = new_sales_id
        
        db.session.commit()
        
        # Notify assignment/reassignment after update.
        try:
            notify_query_assignment(query, previous_sales_id=old_sales_id)
        except Exception:
            pass
        flash('Query updated successfully')
        return redirect(url_for('admin_dashboard'))
    
    return render_template('edit_query.html', query=query, sales_persons=sales_persons, source_options=SOURCE_OPTIONS)

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

@app.route('/admin/update-query-sales', methods=['POST'])
@login_required
def update_query_sales():
    if session.get('user_type') != 'admin':
        return jsonify({"status": "error", "message": "Access denied"}), 403
    
    try:
        data = request.json
        if not data or 'query_id' not in data or 'sales_id' not in data:
            return jsonify({"status": "error", "message": "Missing required fields: query_id and sales_id"}), 400
        
        query_id = int(data['query_id'])
        new_sales_id = int(data['sales_id'])
        
        # Get the query
        query = Query.query.get_or_404(query_id)
        
        # Verify the query belongs to the current admin
        if query.admin_id != current_user.id:
            return jsonify({"status": "error", "message": "Access denied"}), 403
        
        # Verify the sales person belongs to this admin
        sales_person = Sales.query.filter_by(id=new_sales_id, admin_id=current_user.id).first()
        if not sales_person:
            return jsonify({"status": "error", "message": "Sales person not found or access denied"}), 404
        
        # Update sales person if changed
        if query.sales_id != new_sales_id:
            old_sales_id = query.sales_id
            query.sales_id = new_sales_id
            query.updated_at = get_ist_now()  # Update timestamp when reassigned
            
            # Update all follow-ups for this query to the new sales person
            follow_ups = FollowUp.query.filter_by(query_id=query.id).all()
            for follow_up in follow_ups:
                follow_up.sales_id = new_sales_id
            
            db.session.commit()
            
            # Send notification(s) for reassignment
            try:
                notify_query_assignment(query, previous_sales_id=old_sales_id)
            except Exception:
                pass
            
            # Get the updated sales person name
            updated_sales = Sales.query.get(new_sales_id)
            return jsonify({
                "status": "success",
                "message": "Sales person updated successfully",
                "sales_name": updated_sales.name
            })
        else:
            # No change needed
            current_sales = Sales.query.get(query.sales_id)
            return jsonify({
                "status": "success",
                "message": "No change needed",
                "sales_name": current_sales.name
            })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/admin/add-followup', methods=['GET', 'POST'])
@login_required
def admin_add_followup():
    if session.get('user_type') != 'admin':
        flash('Access denied')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        remark = request.form['remark']
        query_id = request.form.get('query_id')
        date_of_contact_str = request.form.get('date_of_contact')
        
        if not query_id:
            flash('Please select a query')
            return redirect(url_for('admin_add_followup'))
        
        if not date_of_contact_str:
            flash('Please select a date of contact')
            return redirect(url_for('admin_add_followup'))
        
        # Parse the datetime-local input
        try:
            date_of_contact = datetime.fromisoformat(date_of_contact_str.replace('Z', '+00:00'))
        except ValueError:
            flash('Invalid date format')
            return redirect(url_for('admin_add_followup'))
        
        # Get the query and verify it belongs to this admin
        query = Query.query.get_or_404(int(query_id))
        if query.admin_id != current_user.id:
            flash('Access denied')
            return redirect(url_for('admin_dashboard'))
        
        # Create follow-up with the query's sales_id (not admin's id)
        new_followup = FollowUp(
            admin_id=current_user.id,
            sales_id=query.sales_id,  # Use the query's sales_id
            query_id=query.id,
            remark=remark,
            date_of_contact=date_of_contact
        )
        db.session.add(new_followup)
        db.session.commit()
        flash('Follow up added successfully')
        return redirect(url_for('admin_dashboard'))
    
    # Provide admin's queries for selection
    selected_query = None
    arg_qid = request.args.get('query_id')
    if arg_qid and arg_qid.isdigit():
        selected_query = Query.query.get(int(arg_qid))
        if not selected_query or selected_query.admin_id != current_user.id:
            selected_query = None
    queries = Query.query.filter_by(admin_id=current_user.id).order_by(Query.id.desc()).all()
    return render_template('admin_add_followup.html', queries=queries, selected_query=selected_query)

@app.route('/admin/bulk-delete-queries', methods=['POST'])
@login_required
def bulk_delete_queries():
    if session.get('user_type') != 'admin':
        return jsonify({"status": "error", "message": "Access denied"}), 403
    
    try:
        data = request.json
        if not data or 'query_ids' not in data:
            return jsonify({"status": "error", "message": "No query IDs provided"}), 400
        
        query_ids = data.get('query_ids', [])
        if not isinstance(query_ids, list) or len(query_ids) == 0:
            return jsonify({"status": "error", "message": "Invalid query IDs"}), 400
        
        # Verify all queries belong to the current admin
        queries = Query.query.filter(
            Query.id.in_(query_ids),
            Query.admin_id == current_user.id
        ).all()
        
        if len(queries) != len(query_ids):
            return jsonify({"status": "error", "message": "Some queries not found or access denied"}), 403
        
        deleted_count = 0
        for query in queries:
            try:
                # Delete all follow-ups associated with this query first
                FollowUp.query.filter_by(query_id=query.id).delete()
                
                # Delete the query
                db.session.delete(query)
                deleted_count += 1
            except Exception as e:
                db.session.rollback()
                return jsonify({"status": "error", "message": f"Error deleting query {query.id}: {str(e)}"}), 500
        
        db.session.commit()
        return jsonify({
            "status": "success",
            "message": f"Successfully deleted {deleted_count} query/queries",
            "deleted_count": deleted_count
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

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
    available_sources = build_available_sources(all_q)
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
                year = get_ist_now().year
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

    results_all = q.order_by(Query.date_of_enquiry.desc()).all()
    total_count = len(results_all)
    per_page = 25
    page = request.args.get('page', 1, type=int)
    total_pages = (total_count + per_page - 1) // per_page if total_count else 1
    page = max(1, min(page, total_pages))
    results = results_all[(page - 1) * per_page:page * per_page]
    result_ids = [r.id for r in results]
    followups_by_query = {}
    if result_ids:
        followups = FollowUp.query.filter(FollowUp.query_id.in_(result_ids)).order_by(FollowUp.date_of_contact.desc()).all()
        for fu in followups:
            followups_by_query.setdefault(fu.query_id, []).append(fu)

    from collections import Counter
    by_closure = Counter([(r.closure or 'pending') for r in results_all])
    by_source = Counter([(r.source or 'reference') for r in results_all])

    return render_template(
        'admin_analytics.html',
        results=results,
        sales_people=sales_people,
        followups_by_query=followups_by_query,
        by_closure=by_closure,
        by_source=by_source,
        total_count=total_count,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
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
    selected_closure = request.args.get('closure')

    # Distinct years and sources for filter controls
    all_queries = base_query.all()
    available_years = sorted({q.date_of_enquiry.year for q in all_queries})
    available_sources = build_available_sources(all_queries)
    
    # Closure options
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
                year = get_ist_now().year
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

    # Pagination setup
    per_page = 25
    page = request.args.get('page', 1, type=int)

    # Total count for pagination (after filters applied)
    total_queries = filtered.count()
    total_pages = (total_queries + per_page - 1) // per_page if total_queries > 0 else 1

    # Paginated queries for current page, newest first (by updated_at, then id)
    queries = filtered.order_by(Query.updated_at.desc(), Query.id.desc()).limit(per_page).offset((page - 1) * per_page).all()

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
            'source': selected_source or '',
            'closure': selected_closure or ''
        },
        available_years=available_years,
        available_sources=available_sources,
        closure_options=closure_options,
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
    
    return render_template('sales_add_query.html', source_options=SOURCE_OPTIONS)

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
    available_sources = build_available_sources(all_for_user)
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
                year = get_ist_now().year
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

    results_all = filtered.order_by(Query.date_of_enquiry.desc()).all()
    total_count = len(results_all)
    per_page = 25
    page = request.args.get('page', 1, type=int)
    total_pages = (total_count + per_page - 1) // per_page if total_count else 1
    page = max(1, min(page, total_pages))
    results = results_all[(page - 1) * per_page:page * per_page]
    result_ids = [r.id for r in results]
    followups_by_query = {}
    if result_ids:
        followups = FollowUp.query.filter(FollowUp.query_id.in_(result_ids)).order_by(FollowUp.date_of_contact.desc()).all()
        for fu in followups:
            followups_by_query.setdefault(fu.query_id, []).append(fu)

    # Simple counts (from all filtered results)
    from collections import Counter
    by_closure = Counter([(r.closure or 'pending') for r in results_all])
    by_source = Counter([(r.source or 'reference') for r in results_all])

    return render_template(
        'sales_analytics.html',
        results=results,
        followups_by_query=followups_by_query,
        by_closure=by_closure,
        by_source=by_source,
        total_count=total_count,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
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
    user_type = session.get('user_type')
    query = Query.query.get_or_404(id)

    # Mobile-only quick-view modal for notification click flows.
    if request.method == 'GET' and is_mobile_request():
        if user_type == 'admin' and isinstance(current_user, Admin):
            if query.admin_id != current_user.id:
                flash('Access denied')
                return redirect(url_for('admin_dashboard'))
            sales_persons = Sales.query.filter_by(admin_id=current_user.id).all()
            return render_template('mobile_query_modal.html', query=query, user_type='admin', sales_persons=sales_persons)
        if user_type == 'sales' and isinstance(current_user, Sales):
            if query.sales_id != current_user.id:
                flash('Access denied')
                return redirect(url_for('sales_dashboard'))
            return render_template('mobile_query_modal.html', query=query, user_type='sales', sales_persons=[])

    # Desktop/admin fallback: route admin users to admin edit page.
    if user_type == 'admin' and isinstance(current_user, Admin):
        if query.admin_id != current_user.id:
            flash('Access denied')
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('edit_query', id=id))

    if user_type != 'sales' or not isinstance(current_user, Sales):
        flash('Access denied')
        return redirect(url_for('index'))

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
        
        # Validate required fields
        required_fields = ["admin_id", "sales_id"]
        for field in required_fields:
            if not data.get(field):
                return jsonify({"status": "error", "message": f"Missing required field: {field}"}), 400
        
        # Validate data types for required fields
        try:
            admin_id = int(data["admin_id"])
            sales_id = int(data["sales_id"])
        except (ValueError, TypeError):
            return jsonify({"status": "error", "message": "admin_id and sales_id must be integers"}), 400
        
        # Verify admin exists
        admin_user = Admin.query.get(admin_id)
        if not admin_user:
            return jsonify({"status": "error", "message": "Admin not found"}), 404
        
        # Verify that sales exists and belongs to this admin
        sales_user = db.session.get(Sales, sales_id)
        if not sales_user:
            return jsonify({"status": "error", "message": "Sales user not found"}), 404
        
        if sales_user.admin_id != admin_id:
            return jsonify({"status": "error", "message": "Sales user does not belong to specified admin"}), 400
        
        # Handle optional fields with defaults
        name = data.get("name", "").strip() if data.get("name") else "N/A"
        phone_number = data.get("phone_number", "").strip() if data.get("phone_number") else "N/A"
        mail_id = data.get("mail_id", "").strip() if data.get("mail_id") else "johndoe@example.com"
        service_query = data.get("service_query", "").strip() if data.get("service_query") else "N/A"
        source = data.get("source", "reference").strip() if data.get("source") else "reference"
        closure = data.get("closure", "pending").strip() if data.get("closure") else "pending"
        
        # Create and save query
        query = Query(
            sales_id=sales_id,
            admin_id=admin_id,
            name=name,
            phone_number=phone_number,
            service_query=service_query,
            mail_id=mail_id,
            source=source,
            closure=closure
        )
        
        db.session.add(query)
        db.session.commit()
        
        # Send notification to sales person
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

# API endpoint for website lead form (admin id or integration_slug in URL)
@app.route("/api/website/lead/<admin_identifier>", methods=["POST"])
def api_website_lead(admin_identifier):
    """
    Endpoint for website lead form submissions.
    URL uses admin integration_slug (or numeric id). Uses admin's bucket sales, source='website'.
    """
    try:
        admin_user = get_admin_by_integration_identifier(admin_identifier)
        if not admin_user:
            return jsonify({"status": "error", "message": "Admin not found"}), 404
        admin_id = admin_user.id
        # Check if request has JSON content
        if not request.is_json:
            return jsonify({"status": "error", "message": "Content-Type must be application/json"}), 400
        
        data = request.json
        
        # Validate required fields
        required_fields = ["name", "phone_number", "service_query", "mail_id"]
        for field in required_fields:
            if not data.get(field):
                return jsonify({"status": "error", "message": f"Missing required field: {field}"}), 400
        
        sales_id = get_admin_sales_id(admin_id)
        source = "website"
        date_of_enquiry = get_ist_now()
        
        # Verify admin bucket sales exists
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
            source=data['source'] if 'source' in data else source,
            closure=data.get("closure", "pending").strip(),
            date_of_enquiry=date_of_enquiry
        )
        
        db.session.add(query)
        db.session.commit()
        
        # Reassign from default sales to actual sales person (if auto-assignment is enabled)
        if AUTO_ASSIGN:
            try:
                assign_sales_rep_to_query(query.id)
                # Refresh query to get updated sales_id after reassignment
                db.session.refresh(query)
            except Exception:
                pass
        
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

def _create_webhook_fixed_lead(source: str, admin_id: int):
    """
    Create a webhook lead with fixed values:
    sales_id = admin's bucket (from DB), date_of_enquiry=now, closure='pending',
    name/phone/mail fixed, and service_query as received JSON payload.
    """
    try:
        if not request.is_json:
            return jsonify({"status": "error", "message": "Content-Type must be application/json"}), 400

        payload = request.get_json() or {}
        sales_id = get_admin_sales_id(admin_id)
        date_of_enquiry = get_ist_now()

        admin_user = db.session.get(Admin, admin_id)
        if not admin_user:
            return jsonify({"status": "error", "message": "Admin not found"}), 404

        sales_user = db.session.get(Sales, sales_id)
        if not sales_user:
            return jsonify({"status": "error", "message": "Sales user not found"}), 404

        query = Query(
            sales_id=sales_id,
            admin_id=admin_id,
            name="John Doe",
            phone_number="987654321",
            service_query=json.dumps(payload, default=str),
            mail_id="johndoe@example.com",
            source=source,
            closure="pending",
            date_of_enquiry=date_of_enquiry
        )

        db.session.add(query)
        db.session.commit()

        # Reassign from default sales to actual sales person (if enabled).
        if AUTO_ASSIGN:
            try:
                assign_sales_rep_to_query(query.id)
                db.session.refresh(query)
            except Exception:
                pass

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

@app.route("/api/webhook/magic-bricks/<admin_identifier>", methods=["POST"])
def api_webhook_magic_bricks(admin_identifier):
    admin_user = get_admin_by_integration_identifier(admin_identifier)
    if not admin_user:
        return jsonify({"status": "error", "message": "Admin not found"}), 404
    return _create_webhook_fixed_lead("magic bricks", admin_user.id)

@app.route("/api/webhook/99acres/<admin_identifier>", methods=["POST"])
def api_webhook_99acres(admin_identifier):
    admin_user = get_admin_by_integration_identifier(admin_identifier)
    if not admin_user:
        return jsonify({"status": "error", "message": "Admin not found"}), 404
    return _create_webhook_fixed_lead("99acres", admin_user.id)

@app.route("/api/webhook/housing/<admin_identifier>", methods=["POST"])
def api_webhook_housing(admin_identifier):
    admin_user = get_admin_by_integration_identifier(admin_identifier)
    if not admin_user:
        return jsonify({"status": "error", "message": "Admin not found"}), 404
    return _create_webhook_fixed_lead("housing", admin_user.id)

# API endpoint for Google Forms submissions (admin id or integration_slug in URL)
@app.route("/api/formAdd/<admin_identifier>", methods=["POST"])
def api_form_add(admin_identifier):
    """
    Endpoint for Google Forms submissions via Apps Script.
    URL uses admin integration_slug (or numeric id). Uses admin's bucket sales, source from payload or 'cold approach'.
    """
    try:
        admin_user = get_admin_by_integration_identifier(admin_identifier)
        if not admin_user:
            return jsonify({"status": "error", "message": "Admin not found"}), 404
        admin_id = admin_user.id
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
        # Convert to string first in case it's an integer or other type
        mail_id = str(data.get("mail_id", "")).strip() if data.get("mail_id") else ""
        if not mail_id:
            mail_id = "johndoe@example.com"
        
        sales_id = get_admin_sales_id(admin_id)
        
        # Normalize source to match exact values used in the system
        # Google Form dropdown values: GMB, Justdial, Facebook, Website, Reference, Cold Approach,
        # Youtube, Other, 99acres, Magic Bricks, Housing
        # System values: Gmb, justdial, facebook, website, reference, cold approach, youtube,
        # 99acres, magic bricks, housing
        def normalize_source(source_str):
            if not source_str:
                return "cold approach"
            # Convert to string first in case it's an integer or other type
            source_str = str(source_str).strip()
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
                "99acres": "99acres",
                "Magic Bricks": "magic bricks",
                "Housing": "housing",
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
                "99 acres": "99acres",
                "99acres": "99acres",
                "magic bricks": "magic bricks",
                "magicbricks": "magic bricks",
                "housing": "housing",
                "other": "cold approach",
            }
            # First try exact match, then try lowercase match
            return source_map.get(source_str, source_map.get(source_lower, "cold approach"))
        
        # Use source from payload if provided, otherwise default to 'cold approach'
        # Convert to string first in case it's an integer or other type
        source_input = str(data.get("source", "")).strip() if data.get("source") else ""
        source = normalize_source(source_input)
        date_of_enquiry = get_ist_now()
        
        # Verify sales exists
        sales_user = Sales.query.get(sales_id)
        if not sales_user:
            return jsonify({"status": "error", "message": "Sales user not found"}), 404
        
        # Convert all fields to strings before stripping (Google Sheets may send integers)
        name = str(data["name"]).strip()
        phone_number = str(data["phone_number"]).strip()
        service_query = str(data["service_query"]).strip()
        closure = str(data.get("closure", "pending")).strip()
        
        # Create and save query
        query = Query(
            sales_id=sales_id,
            admin_id=admin_id,
            name=name,
            phone_number=phone_number,
            service_query=service_query,
            mail_id=mail_id,
            source=source,
            closure=closure,
            date_of_enquiry=date_of_enquiry
        )
        
        db.session.add(query)
        db.session.commit()
        
        # Reassign from default sales to actual sales person (if auto-assignment is enabled)
        if AUTO_ASSIGN:
            try:
                assign_sales_rep_to_query(query.id)
                # Refresh query to get updated sales_id after reassignment
                db.session.refresh(query)
            except Exception:
                pass
        
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
# WebView FCM helpers (session-authenticated)
def _generate_mobile_token(user: Sales) -> str:
    import secrets
    return f"s_{user.id}_" + secrets.token_hex(24)

def _require_json_fields(data, fields):
    missing = [f for f in fields if not data.get(f)]
    if missing:
        return f"Missing required field(s): {', '.join(missing)}"
    return None


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

# ------------------------

def _upsert_device_token_for_sales(sales_id: int, fcm_token: str, platform: str = "unknown", app_version: str = ""):
    target = DeviceToken.query.filter_by(sales_id=sales_id).first()
    if target:
        target.device_token = fcm_token
        target.is_active = True
        target.last_seen_at = get_ist_now()
        if platform:
            target.platform = platform
        if app_version:
            target.app_version = app_version
        return target

    target = DeviceToken(
        sales_id=sales_id,
        device_token=fcm_token,
        platform=platform,
        app_version=app_version,
        is_active=True,
        last_seen_at=get_ist_now(),
    )
    db.session.add(target)
    return target

def _serialize_sales_devices(sales_id: int):
    devices = DeviceToken.query.filter_by(sales_id=sales_id).order_by(DeviceToken.updated_at.desc()).all()
    return [{
        "id": d.id,
        "device_type": d.platform,
        "device_name": d.app_version,
        "is_active": d.is_active,
        "last_active": d.last_seen_at.isoformat() if d.last_seen_at else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    } for d in devices]

def _upsert_device_token_for_admin(admin_id: int, fcm_token: str, platform: str = "unknown", app_version: str = ""):
    target = AdminDeviceToken.query.filter_by(admin_id=admin_id).first()
    if target:
        target.device_token = fcm_token
        target.is_active = True
        target.last_seen_at = get_ist_now()
        if platform:
            target.platform = platform
        if app_version:
            target.app_version = app_version
        return target

    target = AdminDeviceToken(
        admin_id=admin_id,
        device_token=fcm_token,
        platform=platform,
        app_version=app_version,
        is_active=True,
        last_seen_at=get_ist_now(),
    )
    db.session.add(target)
    return target

def _serialize_admin_devices(admin_id: int):
    devices = AdminDeviceToken.query.filter_by(admin_id=admin_id).order_by(AdminDeviceToken.updated_at.desc()).all()
    return [{
        "id": d.id,
        "device_type": d.platform,
        "device_name": d.app_version,
        "is_active": d.is_active,
        "last_active": d.last_seen_at.isoformat() if d.last_seen_at else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    } for d in devices]

# WebView/session-authenticated FCM endpoints
@app.route('/api/webview/register-token', methods=['POST'])
@login_required
def api_webview_register_token():
    user_type = session.get('user_type')
    if user_type not in ('sales', 'admin'):
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    if not request.is_json:
        return jsonify({"success": False, "message": "Content-Type must be application/json"}), 400

    data = request.get_json() or {}
    fcm_token = (data.get("fcm_token") or data.get("device_token") or "").strip()
    platform = (data.get("device_type") or data.get("platform") or "webview").strip()
    app_version = (data.get("app_version") or data.get("device_name") or "").strip()

    if not fcm_token:
        return jsonify({"success": False, "message": "FCM token is required"}), 400

    try:
        if user_type == 'sales' and isinstance(current_user, Sales):
            _upsert_device_token_for_sales(
                sales_id=current_user.id,
                fcm_token=fcm_token,
                platform=platform,
                app_version=app_version,
            )
        elif user_type == 'admin' and isinstance(current_user, Admin):
            _upsert_device_token_for_admin(
                admin_id=current_user.id,
                fcm_token=fcm_token,
                platform=platform,
                app_version=app_version,
            )
        else:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        db.session.commit()
        return jsonify({"success": True, "message": "FCM token registered successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/webview/remove-token', methods=['POST'])
@login_required
def api_webview_remove_token():
    user_type = session.get('user_type')
    if user_type not in ('sales', 'admin'):
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    if not request.is_json:
        return jsonify({"success": False, "message": "Content-Type must be application/json"}), 400

    data = request.get_json() or {}
    fcm_token = (data.get("fcm_token") or data.get("device_token") or "").strip()

    try:
        if user_type == 'sales' and isinstance(current_user, Sales):
            if fcm_token:
                rec = DeviceToken.query.filter_by(sales_id=current_user.id, device_token=fcm_token).first()
                if rec:
                    db.session.delete(rec)
            else:
                DeviceToken.query.filter_by(sales_id=current_user.id).delete()
        elif user_type == 'admin' and isinstance(current_user, Admin):
            if fcm_token:
                rec = AdminDeviceToken.query.filter_by(admin_id=current_user.id, device_token=fcm_token).first()
                if rec:
                    db.session.delete(rec)
            else:
                AdminDeviceToken.query.filter_by(admin_id=current_user.id).delete()
        else:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        db.session.commit()
        return jsonify({"success": True, "message": "FCM token(s) removed successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/webview/devices', methods=['GET'])
@login_required
def api_webview_devices():
    user_type = session.get('user_type')
    if user_type not in ('sales', 'admin'):
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    try:
        if user_type == 'sales' and isinstance(current_user, Sales):
            devices = _serialize_sales_devices(current_user.id)
        elif user_type == 'admin' and isinstance(current_user, Admin):
            devices = _serialize_admin_devices(current_user.id)
        else:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        return jsonify({"success": True, "devices": devices}), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

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


def _send_fcm_with_fallback(token_rows, id_attr: str, title: str, body: str, data: dict, owner_label: str) -> int:
    if firebase_admin is None:
        return 0
    if not token_rows:
        return 0

    stale_ids = []
    payload = {k: str(v) for k, v in (data or {}).items()}
    for row in token_rows:
        token_id = getattr(row, id_attr)
        try:
            message = _fb_messaging.Message(
                notification=_fb_messaging.Notification(title=title, body=body),
                token=row.device_token,
                data=payload
            )
            _fb_messaging.send(message)
            return 1
        except Exception as e:
            err = str(e).lower()
            if 'registration-token-not-registered' in err or 'requested entity was not found' in err:
                stale_ids.append(row.id)
                print(f"FCM stale token for {owner_label}={token_id}, token_id={row.id}: {e}")
            else:
                print(f"FCM send error for {owner_label}={token_id}, token_id={row.id}: {e}")

    if stale_ids:
        try:
            model = DeviceToken if owner_label == "sales_id" else AdminDeviceToken
            model.query.filter(model.id.in_(stale_ids)).update({"is_active": False}, synchronize_session=False)
            db.session.commit()
        except Exception as cleanup_exc:
            db.session.rollback()
            print(f"FCM stale token cleanup error for {owner_label}: {cleanup_exc}")
    return 0

def send_notification_to_sales_device(sales_id: int, title: str, body: str, data: dict) -> int:
    token_rows = DeviceToken.query.filter_by(sales_id=sales_id, is_active=True).order_by(DeviceToken.updated_at.desc()).all()
    return _send_fcm_with_fallback(token_rows, "sales_id", title, body, data, "sales_id")

def send_notification_to_admin_device(admin_id: int, title: str, body: str, data: dict) -> int:
    token_rows = AdminDeviceToken.query.filter_by(admin_id=admin_id, is_active=True).order_by(AdminDeviceToken.updated_at.desc()).all()
    return _send_fcm_with_fallback(token_rows, "admin_id", title, body, data, "admin_id")

def notify_query_assignment(q: Query, previous_sales_id: int | None = None) -> int:
    total_sent = 0
    base_data = {"query_id": str(q.id), "name": q.name, "phone": q.phone_number}
    admin_bucket_sales_id = get_admin_sales_id(q.admin_id)

    # Normal assignment to a sales person (not in admin bucket).
    if q.sales_id != admin_bucket_sales_id:
        total_sent += send_notification_to_sales_device(
            q.sales_id,
            'New Query Assigned',
            f"{q.name} - {q.service_query[:30]}",
            base_data,
        )
    else:
        # Assigned to admin sales bucket: notify admin + admin-sales device tokens.
        total_sent += send_notification_to_admin_device(
            q.admin_id,
            'New Query in Admin Queue',
            f"{q.name} - {q.service_query[:30]}",
            base_data,
        )
        total_sent += send_notification_to_sales_device(
            admin_bucket_sales_id,
            'New Query in Admin Queue',
            f"{q.name} - {q.service_query[:30]}",
            base_data,
        )

    # Reassignment notifications.
    if previous_sales_id is not None and previous_sales_id != q.sales_id:
        if previous_sales_id != admin_bucket_sales_id:
            total_sent += send_notification_to_sales_device(
                previous_sales_id,
                'Query Reassigned',
                f"Query #{q.id} moved to another assignee.",
                {"query_id": str(q.id), "new_sales_id": str(q.sales_id)},
            )
        else:
            total_sent += send_notification_to_admin_device(
                q.admin_id,
                'Query Reassigned From Admin Queue',
                f"Query #{q.id} assigned to sales #{q.sales_id}.",
                {"query_id": str(q.id), "new_sales_id": str(q.sales_id)},
            )

    return total_sent

def send_new_query_notification_to_sales(sales_id: int, q: Query):
    # Backward-compatible wrapper used across existing call-sites.
    return notify_query_assignment(q)

def assign_sales_rep_to_query(query_id):
    """
    Reassigns a query from admin bucket to the next sales rep in rotation.
    Finds all sales reps for the query's admin (excluding admin's bucket sales),
    determines the last assigned sales rep, and assigns the query to the next in rotation.
    """
    query = Query.query.get(query_id)
    if not query:
        return
    
    admin_id = query.admin_id
    admin_bucket_sales_id = get_admin_sales_id(admin_id)
    
    # Get all sales reps for this admin, excluding admin bucket sales
    all_sales_reps = Sales.query.filter_by(admin_id=admin_id).filter(
        Sales.id != admin_bucket_sales_id
    ).order_by(Sales.id).all()
    
    # If no sales reps available, keep the current assignment
    if not all_sales_reps:
        return
    
    # Get the most recently created query for this admin (excluding current)
    # to determine which sales rep was last assigned (excluding admin bucket)
    last_query = Query.query.filter(
        Query.admin_id == admin_id,
        Query.id != query_id,
        Query.sales_id != admin_bucket_sales_id
    ).order_by(Query.id.desc()).first()
    
    # Get list of sales rep IDs in rotation order
    sales_ids = [sr.id for sr in all_sales_reps]
    
    # Determine the next sales rep in rotation
    if last_query and last_query.sales_id in sales_ids:
        # Find the index of the last assigned sales rep
        last_sales_id = last_query.sales_id
        try:
            last_index = sales_ids.index(last_sales_id)
            # Get the next sales rep in rotation (wrap around if at the end)
            next_index = (last_index + 1) % len(sales_ids)
            next_sales_rep_id = sales_ids[next_index]
        except ValueError:
            # Last sales rep not in current list, start from first
            next_sales_rep_id = sales_ids[0]
    else:
        # No previous query or last query was admin sales, start from first sales rep
        next_sales_rep_id = sales_ids[0]
    
    # Update the query's sales_id
    query.sales_id = next_sales_rep_id
    db.session.commit()


@app.route('/api/debug/sales_tokens/<int:sales_id>', methods=['GET'])
def debug_sales_tokens(sales_id):
    tokens = [d.device_token for d in DeviceToken.query.filter_by(sales_id=sales_id, is_active=True).all()]
    return jsonify({"sales_id": sales_id, "tokens": tokens})

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



# Daily Report Routes

@app.route('/api/sales/daily-report/view', methods=['POST'])
@login_required
def api_sales_view_daily_report():
    """API endpoint for sales to view their daily report for a specific date"""
    if session.get('user_type') != 'sales' or not isinstance(current_user, Sales):
        return jsonify({"status": "error", "message": "Access denied"}), 403
    
    try:
        data = request.json
        if not data or 'report_date' not in data:
            return jsonify({"status": "error", "message": "Missing report_date"}), 400
        
        report_date_str = data['report_date']
        report_date = datetime.strptime(report_date_str, '%Y-%m-%d').date()
        
        daily_report = DailyReport.query.filter_by(
            sales_id=current_user.id,
            report_date=report_date
        ).first()
        
        if daily_report:
            return jsonify({
                "status": "success",
                "report": daily_report.report_text,
                "report_date": daily_report.report_date.strftime('%d-%m-%y'),
                "updated_at": daily_report.updated_at.strftime('%d-%m-%y %H:%M')
            })
        else:
            return jsonify({
                "status": "success",
                "report": "",
                "report_date": report_date.strftime('%d-%m-%y'),
                "message": "No report found for this date"
            })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/sales/daily-report/update', methods=['POST'])
@login_required
def api_sales_update_daily_report():
    """API endpoint for sales to add/update today's daily report"""
    if session.get('user_type') != 'sales' or not isinstance(current_user, Sales):
        return jsonify({"status": "error", "message": "Access denied"}), 403
    
    try:
        data = request.json
        if not data or 'report_text' not in data:
            return jsonify({"status": "error", "message": "Missing report_text"}), 400
        
        report_text = data['report_text'].strip()
        if len(report_text) > 1000:
            return jsonify({"status": "error", "message": "Report text exceeds 1000 characters"}), 400
        
        if not report_text:
            return jsonify({"status": "error", "message": "Report text cannot be empty"}), 400
        
        today = get_ist_now().date()
        sales_record = db.session.get(Sales, current_user.id)
        if sales_record is None:
            return jsonify({"status": "error", "message": "Sales record not found"}), 404
        
        # Check if report exists for today
        daily_report = DailyReport.query.filter_by(
            sales_id=current_user.id,
            report_date=today
        ).first()
        
        if daily_report:
            # Update existing report
            daily_report.report_text = report_text
            daily_report.updated_at = get_ist_now()
        else:
            # Create new report
            daily_report = DailyReport(
                sales_id=current_user.id,
                admin_id=sales_record.admin_id,
                report_date=today,
                report_text=report_text
            )
            db.session.add(daily_report)
        
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "message": "Daily report updated successfully",
            "report_date": today.strftime('%d-%m-%y')
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/admin/daily-reports')
@login_required
def admin_daily_reports():
    """Admin view to see daily reports of all sales persons"""
    if session.get('user_type') != 'admin' or not isinstance(current_user, Admin):
        flash('Access denied')
        return redirect(url_for('index'))
    
    try:
        # Get selected date from query parameter, default to today
        selected_date_str = request.args.get('date', '')
        if selected_date_str:
            try:
                selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
            except ValueError:
                selected_date = get_ist_now().date()
        else:
            selected_date = get_ist_now().date()
        
        # Get all sales persons under this admin
        sales_people = Sales.query.filter_by(admin_id=current_user.id).all()
        
        # Get daily reports for selected date (handle case where table doesn't exist)
        reports_by_sales = {}
        try:
            daily_reports = DailyReport.query.filter(
                DailyReport.admin_id == current_user.id,
                DailyReport.report_date == selected_date
            ).all()
            # Create a dictionary mapping sales_id to report
            reports_by_sales = {dr.sales_id: dr for dr in daily_reports}
        except Exception as e:
            # Table might not exist yet, return empty dict
            print(f"Warning: Could not query DailyReport table: {e}")
            reports_by_sales = {}
        
        return render_template(
            'admin_daily_reports.html',
            sales_people=sales_people,
            reports_by_sales=reports_by_sales,
            selected_date=selected_date,
            selected_date_str=selected_date.strftime('%Y-%m-%d')
        )
    except Exception as e:
        flash(f'Error loading daily reports: {str(e)}')
        return redirect(url_for('admin_dashboard'))

def init_db():
    """Initialize database - create all tables if they don't exist"""
    with app.app_context():
        try:
            db.create_all()
            print("Database tables created/verified successfully")
            
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
        except Exception as e:
            print(f"Warning: Could not initialize database: {e}")

# Initialize database on app startup
init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=os.getenv('FLASK_ENV', False))
