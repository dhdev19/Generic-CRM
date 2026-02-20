from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone, timedelta
import os
import json
from io import BytesIO
import tempfile
import subprocess
import shutil
from config import config

# Optional: proposal/invoice generation (docxtpl, docx2pdf)
try:
    from docxtpl import DocxTemplate, RichText
    DOCXTPL_AVAILABLE = True
except ImportError:
    DocxTemplate = None
    RichText = None
    DOCXTPL_AVAILABLE = False
try:
    import pythoncom
    from docx2pdf import convert as docx2pdf_convert
    DOCX2PDF_AVAILABLE = True
except ImportError:
    DOCX2PDF_AVAILABLE = False
    pythoncom = None
import pymysql
from sqlalchemy import desc, or_

# IST timezone (GMT+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

def get_ist_now():
    """Get current time in IST (Indian Standard Time, GMT+5:30)"""
    return datetime.now(IST) 
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
# When False, queries are assigned to default sales (id=0)
AUTO_ASSIGN = os.environ.get('AUTO_ASSIGN', 'false').lower() == 'true'

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


def _proposal_allowed():
    """Allow proposal access for admin and sales only."""
    return session.get('user_type') in ('admin', 'sales')


def _proposal_doc_path(office):
    """Path to .docx template; office is 'lucknow' or 'bombay'. Looks in project root."""
    root = app.root_path
    if office == 'lucknow':
        return os.path.join(root, 'proposal.docx')
    return os.path.join(root, 'proposalMumbaiOffice.docx')


def _libreoffice_available():
    """True if LibreOffice (soffice) is installed for headless DOCX->PDF conversion."""
    for cmd in ('libreoffice', 'soffice'):
        if shutil.which(cmd):
            try:
                subprocess.run(
                    [cmd, '--version'],
                    capture_output=True,
                    timeout=5,
                )
                return True
            except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
                pass
    return False


def _pdf_export_available():
    """True if PDF export can be used (Windows docx2pdf or LibreOffice headless)."""
    if DOCX2PDF_AVAILABLE:
        return True
    return _libreoffice_available()


def _convert_docx_to_pdf_libreoffice(docx_path, pdf_path):
    """Convert DOCX to PDF using LibreOffice headless. Returns True on success."""
    out_dir = os.path.dirname(pdf_path)
    try:
        result = subprocess.run(
            [
                shutil.which('libreoffice') or shutil.which('soffice'),
                '--headless',
                '--convert-to', 'pdf',
                '--outdir', out_dir,
                docx_path,
            ],
            capture_output=True,
            timeout=60,
            cwd=out_dir,
        )
        base = os.path.splitext(os.path.basename(docx_path))[0]
        expected_pdf = os.path.join(out_dir, base + '.pdf')
        return result.returncode == 0 and os.path.isfile(expected_pdf)
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return False


@app.route('/proposal', methods=['GET'])
@login_required
def proposal_form():
    if not _proposal_allowed():
        flash('Access denied')
        return redirect(url_for('index'))
    return render_template('proposal_form.html', pdf_export_available=_pdf_export_available())


@app.route('/proposal/submit', methods=['POST'])
@login_required
def proposal_submit():
    if not _proposal_allowed() or not DOCXTPL_AVAILABLE:
        if not _proposal_allowed():
            return redirect(url_for('index'))
        flash('Proposal generation is not available. Install: pip install docxtpl')
        return redirect(url_for('proposal_form'))
    client_name = request.form.get('client_name', '').strip()
    initial_payment = request.form.get('initial_payment', '')
    office = request.form.get('office', 'lucknow')
    particulars = request.form.getlist('particular')
    amounts = request.form.getlist('amount')
    remarks = request.form.getlist('remark')
    items = []
    for p, a, r in zip(particulars, amounts, remarks):
        if (p or '').strip() and (a or '').strip():
            items.append({'particular': p.strip(), 'amount': a.strip(), 'remark': (r or '').strip()})
    doc_path = _proposal_doc_path(office)
    if not os.path.isfile(doc_path):
        flash(f'Proposal template not found: {os.path.basename(doc_path)}. Add it in the project root.')
        return redirect(url_for('proposal_form'))
    doc = DocxTemplate(doc_path)
    sub = doc.new_subdoc()
    table = sub.add_table(rows=1, cols=4)
    table.style = 'Table Grid'
    hdr = table.rows[0].cells
    hdr[0].text, hdr[1].text, hdr[2].text, hdr[3].text = 'Sr. No', 'Particular', 'Amount', 'Remark'
    for i, item in enumerate(items, 1):
        row = table.add_row().cells
        row[0].text, row[1].text, row[2].text, row[3].text = str(i), item['particular'], item['amount'], item['remark']
    context = {
        'client_name': client_name,
        'initial_payment': initial_payment,
        'budget_table': sub,
        'smm': request.form.get('smm') == 'true',
        'landing_page': request.form.get('landing_page') == 'true',
        'multipage_website': request.form.get('multipage_website') == 'true',
        'seo': request.form.get('seo') == 'true',
        'meta_ads': request.form.get('meta_ads') == 'true',
        'google_ads': request.form.get('google_ads') == 'true',
        'out1': request.form.get('out1') == 'true',
        'out2': request.form.get('out2') == 'true',
        'out3': request.form.get('out3') == 'true',
        'multiple_custom_outcomes': request.form.get('multiple_custom_outcomes') == 'true',
        'creatives': request.form.get('creatives', ''),
        'reels': request.form.get('reels', ''),
        'outcomes': request.form.getlist('outcomes') or [],
    }
    doc.render(context)
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    filename = f"{client_name.replace(' ', '_')}_proposal.docx"
    return buf.getvalue(), 200, {
        'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'Content-Disposition': f'attachment; filename="{filename}"',
    }


@app.route('/proposal/download_pdf', methods=['POST'])
@login_required
def proposal_download_pdf():
    if not _proposal_allowed():
        return redirect(url_for('index'))
    if not DOCXTPL_AVAILABLE:
        flash('Proposal DOCX is required. Install: pip install docxtpl')
        return redirect(url_for('proposal_form'))
    if not _pdf_export_available():
        flash('PDF export is not available. Use Download DOCX, or install LibreOffice (Linux/Mac) for PDF.')
        return redirect(url_for('proposal_form'))
    client_name = request.form.get('client_name', '').strip()
    initial_payment = request.form.get('initial_payment', '')
    office = request.form.get('office', 'lucknow')
    particulars = request.form.getlist('particular')
    amounts = request.form.getlist('amount')
    remarks = request.form.getlist('remark')
    items = []
    for p, a, r in zip(particulars, amounts, remarks):
        if (p or '').strip() and (a or '').strip():
            items.append({'particular': p.strip(), 'amount': a.strip(), 'remark': (r or '').strip()})
    doc_path = _proposal_doc_path(office)
    if not os.path.isfile(doc_path):
        flash(f'Proposal template not found: {os.path.basename(doc_path)}.')
        return redirect(url_for('proposal_form'))
    doc = DocxTemplate(doc_path)
    sub = doc.new_subdoc()
    table = sub.add_table(rows=1, cols=4)
    table.style = 'Table Grid'
    hdr = table.rows[0].cells
    hdr[0].text, hdr[1].text, hdr[2].text, hdr[3].text = 'Sr. No', 'Particular', 'Amount', 'Remark'
    for i, item in enumerate(items, 1):
        row = table.add_row().cells
        row[0].text, row[1].text, row[2].text, row[3].text = str(i), item['particular'], item['amount'], item['remark']
    context = {
        'client_name': client_name,
        'initial_payment': initial_payment,
        'budget_table': sub,
        'smm': request.form.get('smm') == 'true',
        'landing_page': request.form.get('landing_page') == 'true',
        'multipage_website': request.form.get('multipage_website') == 'true',
        'seo': request.form.get('seo') == 'true',
        'meta_ads': request.form.get('meta_ads') == 'true',
        'google_ads': request.form.get('google_ads') == 'true',
        'out1': request.form.get('out1') == 'true',
        'out2': request.form.get('out2') == 'true',
        'out3': request.form.get('out3') == 'true',
        'multiple_custom_outcomes': request.form.get('multiple_custom_outcomes') == 'true',
        'creatives': request.form.get('creatives', ''),
        'reels': request.form.get('reels', ''),
        'outcomes': request.form.getlist('outcomes') or [],
    }
    doc.render(context)
    with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as f:
        doc.save(f.name)
        temp_docx = f.name
    out_dir = os.path.dirname(temp_docx)
    base_name = os.path.splitext(os.path.basename(temp_docx))[0]
    temp_pdf = os.path.join(out_dir, base_name + '.pdf')
    pdf_generated = False
    try:
        if DOCX2PDF_AVAILABLE:
            try:
                pythoncom.CoInitialize()
                docx2pdf_convert(temp_docx, temp_pdf)
                pdf_generated = os.path.isfile(temp_pdf)
            except Exception:
                pass
            finally:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
        if not pdf_generated and _libreoffice_available():
            pdf_generated = _convert_docx_to_pdf_libreoffice(temp_docx, temp_pdf)
        if not pdf_generated:
            flash('PDF conversion failed. Use Download DOCX instead.')
            return redirect(url_for('proposal_form'))
        with open(temp_pdf, 'rb') as f:
            pdf_data = f.read()
        filename = f"{client_name.replace(' ', '_')}_proposal.pdf"
        return pdf_data, 200, {
            'Content-Type': 'application/pdf',
            'Content-Disposition': f'attachment; filename="{filename}"',
        }
    finally:
        for p in (temp_docx, temp_pdf):
            try:
                if p and os.path.isfile(p):
                    os.unlink(p)
            except Exception:
                pass


# Invoice (admin only)
INVOICE_TEMPLATE_UP = 'Billing.docx'
INVOICE_TEMPLATE_OTHER_STATE = 'BillingOther.docx'


def _invoice_allowed():
    """Invoice is admin only."""
    return session.get('user_type') == 'admin'


@app.route('/invoice', methods=['GET'])
@login_required
def invoice_form():
    if not _invoice_allowed():
        flash('Access denied')
        return redirect(url_for('index'))
    return render_template('invoice_form.html')


@app.route('/invoice/generate', methods=['POST'])
@login_required
def invoice_generate():
    if not _invoice_allowed():
        return redirect(url_for('index'))
    if not DOCXTPL_AVAILABLE or RichText is None:
        flash('Invoice generation requires docxtpl. Install: pip install docxtpl')
        return redirect(url_for('invoice_form'))
    invoice_type = (request.form.get('invoice_type') or 'up').strip().lower()
    is_other_state = invoice_type == 'other'
    template_name = INVOICE_TEMPLATE_OTHER_STATE if is_other_state else INVOICE_TEMPLATE_UP
    doc_path = os.path.join(app.root_path, template_name)
    if not os.path.isfile(doc_path):
        flash(f'Invoice template not found: {template_name}. Add it in the project root.')
        return redirect(url_for('invoice_form'))
    hsn_list = request.form.getlist('hsn_sac[]')
    desc_list = request.form.getlist('description[]')
    rate_list = request.form.getlist('rate[]')
    qty_list = request.form.getlist('quantity[]')
    if not hsn_list or not desc_list or not rate_list or not qty_list:
        flash('Add at least one invoice item.')
        return redirect(url_for('invoice_form'))
    total_amount = 0.0
    hsn_text = RichText()
    desc_text = RichText()
    rate_text = RichText()
    total_text = RichText()
    for i, (hsn, desc, rate, qty) in enumerate(zip(hsn_list, desc_list, rate_list, qty_list)):
        try:
            rate_f = float(rate)
            qty_f = float(qty)
        except (ValueError, TypeError):
            continue
        item_total = rate_f * qty_f
        total_amount += item_total
        if i > 0:
            hsn_text.add('\n')
            desc_text.add('\n')
            rate_text.add('\n')
            total_text.add('\n')
        hsn_text.add(str(hsn).strip())
        desc_text.add(str(desc).strip())
        rate_text.add(str(round(rate_f, 2)))
        total_text.add(str(round(item_total, 2)))
    try:
        discount = float(request.form.get('discount') or 0)
        other_charges = float(request.form.get('other_charges') or 0)
    except (ValueError, TypeError):
        discount = 0.0
        other_charges = 0.0
    taxable_value = total_amount - discount
    base_context = {
        'customer_name': request.form.get('customer_name', ''),
        'customer_address': request.form.get('customer_address', ''),
        'cust_gst': request.form.get('cust_gst', ''),
        'place_of_supply': request.form.get('place_of_supply', ''),
        'invoice_number': request.form.get('invoice_number', ''),
        'date': request.form.get('date', ''),
        'hsn_sac': hsn_text,
        'description': desc_text,
        'rate': rate_text,
        'total': total_text,
        'total_taxable': round(total_amount, 2),
        'discount': round(discount, 2),
        'other_charges': round(other_charges, 2),
        'grand_total': 0,  # set below
    }
    if is_other_state:
        igst = taxable_value * 0.18
        grand_total = taxable_value + igst + other_charges
        base_context['grand_total'] = round(grand_total, 2)
        base_context['igst'] = round(igst, 2)
        # BillingOther.docx has no cgst/sgst fields
        context = base_context
    else:
        cgst = taxable_value * 0.09
        sgst = taxable_value * 0.09
        grand_total = taxable_value + cgst + sgst + other_charges
        base_context['grand_total'] = round(grand_total, 2)
        base_context['cgst'] = round(cgst, 2)
        base_context['sgst'] = round(sgst, 2)
        # Billing.docx has no igst field
        context = base_context
    doc = DocxTemplate(doc_path)
    doc.render(context)
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    download_name = f"Invoice_{request.form.get('invoice_number', 'invoice').replace(' ', '_')}.docx"
    return buf.getvalue(), 200, {
        'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'Content-Disposition': f'attachment; filename="{download_name}"',
    }


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
    
    return render_template(
        'admin_dashboard.html',
        sales_persons=sales_persons,
        queries_by_month=queries_by_month,
        month_keys=month_keys,
        current_month_year=current_month_year,
        queries_list=queries_list,
        followups_by_query=followups_by_query,
        search_query=search_query,
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
        date_of_enquiry = get_ist_now()
        
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
    Create a webhook lead with fixed values as requested:
    sales_id=0, date_of_enquiry=now, closure='pending',
    name/phone/mail fixed, and service_query as received JSON payload.
    """
    try:
        if not request.is_json:
            return jsonify({"status": "error", "message": "Content-Type must be application/json"}), 400

        payload = request.get_json() or {}
        sales_id = 0
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

@app.route("/api/webhook/magic-bricks/<int:admin_id>", methods=["POST"])
@app.route("/api/webhook/magic-bricks", methods=["POST"])
def api_webhook_magic_bricks(admin_id=3):
    return _create_webhook_fixed_lead("magic bricks", int(admin_id))

@app.route("/api/webhook/99acres/<int:admin_id>", methods=["POST"])
@app.route("/api/webhook/99acres", methods=["POST"])
def api_webhook_99acres(admin_id=3):
    return _create_webhook_fixed_lead("99acres", int(admin_id))

@app.route("/api/webhook/housing/<int:admin_id>", methods=["POST"])
@app.route("/api/webhook/housing", methods=["POST"])
def api_webhook_housing(admin_id=3):
    return _create_webhook_fixed_lead("housing", int(admin_id))

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
        # Convert to string first in case it's an integer or other type
        mail_id = str(data.get("mail_id", "")).strip() if data.get("mail_id") else ""
        if not mail_id:
            mail_id = "johndoe@example.com"
        
        # Hardcoded values - same as website endpoint
        admin_id = 3
        sales_id = 0
        
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
        
        # Verify admin exists
        admin_user = Admin.query.get(admin_id)
        if not admin_user:
            return jsonify({"status": "error", "message": "Admin not found"}), 404
        
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
#             last_seen_at=get_ist_now(),
#         )
#         db.session.add(rec)
#     db.session.commit()
#     return jsonify({"status":"success","token":token, "sales_id": user.id, "name": user.name})


@app.route('/api/mobile/login', methods=['POST'])
def api_mobile_login():
    if not request.is_json:
        return jsonify({"status":"error","message":"Content-Type must be application/json"}), 400

    data = request.get_json() or {}
    err = _require_json_fields(data, ["username", "password"])
    if err:
        return jsonify({"status":"error","message":err}), 400

    user = Sales.query.filter_by(username=data["username"]).first()
    if not user or not check_password_hash(user.password_hash, data["password"]):
        return jsonify({"status":"error","message":"Invalid credentials"}), 401

    # Issue a simple bearer token (DB-less). In production, use JWT.
    token = _generate_mobile_token(user)

    # Backward compatible: if device details are sent at login, upsert token.
    device_token = data.get("device_token")
    if device_token:
        _upsert_device_token_for_sales(
            sales_id=user.id,
            fcm_token=str(device_token).strip(),
            platform=(data.get("device_type") or data.get("platform") or "unknown"),
            app_version=(data.get("app_version") or data.get("device_name") or ""),
        )

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

def _upsert_device_token_for_sales(sales_id: int, fcm_token: str, platform: str = "unknown", app_version: str = ""):
    primary = DeviceToken.query.filter_by(sales_id=sales_id).order_by(DeviceToken.updated_at.desc(), DeviceToken.id.desc()).first()
    token_row = DeviceToken.query.filter_by(device_token=fcm_token).first()
    target = primary or token_row

    if target is None:
        target = DeviceToken(
            sales_id=sales_id,
            device_token=fcm_token,
            platform=platform,
            app_version=app_version,
            is_active=True,
            last_seen_at=get_ist_now(),
        )
        db.session.add(target)
    else:
        target.sales_id = sales_id
        target.device_token = fcm_token
        target.is_active = True
        target.last_seen_at = get_ist_now()
        if platform:
            target.platform = platform
        if app_version:
            target.app_version = app_version

    # Enforce one token row per sales user by deleting all extra rows.
    extra_rows = DeviceToken.query.filter(
        DeviceToken.sales_id == sales_id,
        DeviceToken.id != target.id
    ).all()
    for row in extra_rows:
        db.session.delete(row)
    duplicate_token_rows = DeviceToken.query.filter(
        DeviceToken.device_token == fcm_token,
        DeviceToken.id != target.id
    ).all()
    for row in duplicate_token_rows:
        db.session.delete(row)
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
    primary = AdminDeviceToken.query.filter_by(admin_id=admin_id).order_by(AdminDeviceToken.updated_at.desc(), AdminDeviceToken.id.desc()).first()
    token_row = AdminDeviceToken.query.filter_by(device_token=fcm_token).first()
    target = primary or token_row

    if target is None:
        target = AdminDeviceToken(
            admin_id=admin_id,
            device_token=fcm_token,
            platform=platform,
            app_version=app_version,
            is_active=True,
            last_seen_at=get_ist_now(),
        )
        db.session.add(target)
    else:
        target.admin_id = admin_id
        target.device_token = fcm_token
        target.is_active = True
        target.last_seen_at = get_ist_now()
        if platform:
            target.platform = platform
        if app_version:
            target.app_version = app_version

    # Enforce one token row per admin user by deleting all extra rows.
    extra_rows = AdminDeviceToken.query.filter(
        AdminDeviceToken.admin_id == admin_id,
        AdminDeviceToken.id != target.id
    ).all()
    for row in extra_rows:
        db.session.delete(row)
    duplicate_token_rows = AdminDeviceToken.query.filter(
        AdminDeviceToken.device_token == fcm_token,
        AdminDeviceToken.id != target.id
    ).all()
    for row in duplicate_token_rows:
        db.session.delete(row)
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

@app.route('/api/mobile/register-token', methods=['POST'])
def api_mobile_register_token():
    """Register or update an FCM token for the authenticated sales user."""
    sales_user = _auth_sales_from_header()
    if not sales_user:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    if not request.is_json:
        return jsonify({"status": "error", "message": "Content-Type must be application/json"}), 400

    data = request.get_json() or {}
    fcm_token = (data.get("fcm_token") or data.get("device_token") or "").strip()
    platform = (data.get("device_type") or data.get("platform") or "unknown").strip()
    app_version = (data.get("app_version") or data.get("device_name") or "").strip()

    if not fcm_token:
        return jsonify({"status": "error", "message": "FCM token is required"}), 400

    try:
        _upsert_device_token_for_sales(
            sales_id=sales_user.id,
            fcm_token=fcm_token,
            platform=platform,
            app_version=app_version,
        )

        db.session.commit()
        return jsonify({"status": "success", "message": "FCM token registered successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/mobile/remove-token', methods=['POST'])
def api_mobile_remove_token():
    """Remove one or all FCM tokens for the authenticated sales user."""
    sales_user = _auth_sales_from_header()
    if not sales_user:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    if not request.is_json:
        return jsonify({"status": "error", "message": "Content-Type must be application/json"}), 400

    data = request.get_json() or {}
    fcm_token = (data.get("fcm_token") or data.get("device_token") or "").strip()

    try:
        if fcm_token:
            rec = DeviceToken.query.filter_by(sales_id=sales_user.id, device_token=fcm_token).first()
            if rec:
                db.session.delete(rec)
        else:
            DeviceToken.query.filter_by(sales_id=sales_user.id).delete()

        db.session.commit()
        return jsonify({"status": "success", "message": "FCM token(s) removed successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/mobile/devices', methods=['GET'])
def api_mobile_devices():
    """List FCM device rows for the authenticated sales user."""
    sales_user = _auth_sales_from_header()
    if not sales_user:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    try:
        result = _serialize_sales_devices(sales_user.id)
        return jsonify({"status": "success", "devices": result}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

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

    # Normal assignment to a sales person.
    if q.sales_id != 0:
        total_sent += send_notification_to_sales_device(
            q.sales_id,
            'New Query Assigned',
            f"{q.name} - {q.service_query[:30]}",
            base_data,
        )
    else:
        # Assigned to admin sales bucket (sales_id=0): notify admin + admin-sales token.
        total_sent += send_notification_to_admin_device(
            q.admin_id,
            'New Query in Admin Queue',
            f"{q.name} - {q.service_query[:30]}",
            base_data,
        )
        total_sent += send_notification_to_sales_device(
            0,
            'New Query in Admin Queue',
            f"{q.name} - {q.service_query[:30]}",
            base_data,
        )

    # Reassignment notifications.
    if previous_sales_id is not None and previous_sales_id != q.sales_id:
        if previous_sales_id != 0:
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
    Reassigns a query from default sales to the next sales rep in rotation.
    This function finds all sales reps for the query's admin (excluding admin sales with id=0),
    determines the last assigned sales rep by checking the most recent query,
    and assigns the query to the next sales rep in rotation.
    """
    query = Query.query.get(query_id)
    if not query:
        return
    
    admin_id = query.admin_id
    current_sales_id = query.sales_id
    
    # Get all sales reps for this admin, excluding admin sales (id=0)
    # We need all sales reps (not excluding current) to determine rotation order
    all_sales_reps = Sales.query.filter_by(admin_id=admin_id).filter(
        Sales.id != 0  # Exclude admin sales
    ).order_by(Sales.id).all()
    
    # If no sales reps available, keep the current assignment
    if not all_sales_reps:
        return
    
    # Get the most recently created query for this admin (excluding the current query)
    # to determine which sales rep was last assigned (excluding admin sales)
    last_query = Query.query.filter(
        Query.admin_id == admin_id,
        Query.id != query_id,
        Query.sales_id != 0  # Exclude admin sales
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
