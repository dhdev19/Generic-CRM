import unittest
import tempfile
import os
import json

# Force SQLite for tests before app/db are used
os.environ['FLASK_ENV'] = 'development'

from app import (
    app, db, SuperAdmin, Admin, Sales, Query, FollowUp,
    DeviceToken, AdminDeviceToken, DailyReport,
    get_admin_sales_id, build_available_sources, SOURCE_OPTIONS,
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

class CRMTests(unittest.TestCase):
    
    def setUp(self):
        """Set up test database and client before each test"""
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{self.db_path}'
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['SECRET_KEY'] = 'test-secret'

        self.app = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()

        db.create_all()
        self.create_test_data()
    
    def tearDown(self):
        """Clean up after each test"""
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        os.close(self.db_fd)
        os.unlink(self.db_path)
    
    def create_test_data(self):
        """Create test users and data"""
        # Create super admin
        self.super_admin = SuperAdmin(
            name='Test Super Admin',
            username='testsuperadmin',
            password_hash=generate_password_hash('password123')
        )
        db.session.add(self.super_admin)
        
        # Create admin (password_plain_text required by model; integration_slug for integration URLs)
        self.admin = Admin(
            name='Test Admin',
            username='testadmin',
            password_hash=generate_password_hash('password123'),
            password_plain_text='password123'
        )
        self.admin.integration_slug = 'TestSlug12Ab'
        db.session.add(self.admin)
        db.session.commit()
        
        # Create admin bucket sales (Admin Queue) and link to admin
        self.admin_bucket_sales = Sales(
            admin_id=self.admin.id,
            name='Admin Queue',
            username='admin_queue_%d' % self.admin.id,
            password_hash=generate_password_hash('admin_queue_%d' % self.admin.id),
        )
        db.session.add(self.admin_bucket_sales)
        db.session.commit()
        self.admin.admin_sales_id = self.admin_bucket_sales.id
        db.session.commit()
        
        # Create regular sales person
        self.sales = Sales(
            admin_id=self.admin.id,
            name='Test Sales',
            username='testsales',
            password_hash=generate_password_hash('password123')
        )
        db.session.add(self.sales)
        db.session.commit()
        
        # Create test query
        self.query = Query(
            sales_id=self.sales.id,
            admin_id=self.admin.id,
            name='Test Customer',
            phone_number='1234567890',
            service_query='Test service query',
            mail_id='test@example.com'
        )
        db.session.add(self.query)
        db.session.commit()
        
        # Create test follow up (query_id required)
        self.followup = FollowUp(
            admin_id=self.admin.id,
            sales_id=self.sales.id,
            query_id=self.query.id,
            remark='Test follow up remark'
        )
        db.session.add(self.followup)
        db.session.commit()
    
    def login_user(self, username, password, user_type):
        """Helper method to login users"""
        return self.app.post('/login', data={
            'username': username,
            'password': password,
            'user_type': user_type
        }, follow_redirects=True)
    
    def test_index_page(self):
        """Test the main index page"""
        response = self.app.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'CRM System', response.data)
        self.assertIn(b'Login', response.data)
    
    def test_login_page(self):
        """Test the login page"""
        response = self.app.get('/login')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Login', response.data)
    
    def test_super_admin_login_success(self):
        """Test successful super admin login"""
        response = self.login_user('testsuperadmin', 'password123', 'super_admin')
        self.assertEqual(response.status_code, 200)
        # Should redirect to super admin dashboard
        self.assertIn(b'Super Admin Dashboard', response.data)
    
    def test_admin_login_success(self):
        """Test successful admin login"""
        response = self.login_user('testadmin', 'password123', 'admin')
        self.assertEqual(response.status_code, 200)
        # Should redirect to admin dashboard
        self.assertIn(b'Admin Dashboard', response.data)
    
    def test_sales_login_success(self):
        """Test successful sales login"""
        response = self.login_user('testsales', 'password123', 'sales')
        self.assertEqual(response.status_code, 200)
        # Should redirect to sales dashboard
        self.assertIn(b'Sales Dashboard', response.data)
    
    def test_login_invalid_credentials(self):
        """Test login with invalid credentials"""
        response = self.login_user('invalid', 'wrongpassword', 'super_admin')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Invalid username or password', response.data)
    
    def test_logout(self):
        """Test logout functionality"""
        # First login
        self.login_user('testsuperadmin', 'password123', 'super_admin')
        
        # Then logout
        response = self.app.get('/logout', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'CRM System', response.data)  # Back to index page
    
    # Super Admin Tests
    def test_super_admin_dashboard_access(self):
        """Test super admin dashboard access"""
        self.login_user('testsuperadmin', 'password123', 'super_admin')
        response = self.app.get('/super-admin/dashboard')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Super Admin Dashboard', response.data)
    
    def test_super_admin_dashboard_unauthorized(self):
        """Test super admin dashboard access without login"""
        response = self.app.get('/super-admin/dashboard', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Login', response.data)  # Redirected to login
    
    def test_add_super_admin_page(self):
        """Test add super admin page access"""
        self.login_user('testsuperadmin', 'password123', 'super_admin')
        response = self.app.get('/super-admin/add-super-admin')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Add New Super Admin', response.data)
    
    def test_add_super_admin_success(self):
        """Test successful super admin creation"""
        self.login_user('testsuperadmin', 'password123', 'super_admin')
        response = self.app.post('/super-admin/add-super-admin', data={
            'name': 'New Super Admin',
            'username': 'newsuperadmin',
            'password': 'newpassword123'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Super Admin added successfully', response.data)
        
        # Verify in database
        new_super_admin = SuperAdmin.query.filter_by(username='newsuperadmin').first()
        self.assertIsNotNone(new_super_admin)
        self.assertEqual(new_super_admin.name, 'New Super Admin')
    
    def test_add_super_admin_duplicate_username(self):
        """Test adding super admin with duplicate username"""
        self.login_user('testsuperadmin', 'password123', 'super_admin')
        response = self.app.post('/super-admin/add-super-admin', data={
            'name': 'Duplicate Admin',
            'username': 'testsuperadmin',  # Already exists
            'password': 'password123'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Username already exists', response.data)
    
    def test_add_admin_page(self):
        """Test add admin page access"""
        self.login_user('testsuperadmin', 'password123', 'super_admin')
        response = self.app.get('/super-admin/add-admin')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Add New Admin', response.data)
    
    def test_add_admin_success(self):
        """Test successful admin creation"""
        self.login_user('testsuperadmin', 'password123', 'super_admin')
        response = self.app.post('/super-admin/add-admin', data={
            'name': 'New Admin',
            'username': 'newadmin',
            'password': 'newpassword123'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Admin added successfully', response.data)
        
        # Verify in database
        new_admin = Admin.query.filter_by(username='newadmin').first()
        self.assertIsNotNone(new_admin)
        self.assertEqual(new_admin.name, 'New Admin')
    
    def test_remove_super_admin(self):
        """Test removing super admin"""
        self.login_user('testsuperadmin', 'password123', 'super_admin')
        
        # Create another super admin to remove
        another_super_admin = SuperAdmin(
            name='Another Super Admin',
            username='anothersuperadmin',
            password_hash=generate_password_hash('password123')
        )
        db.session.add(another_super_admin)
        db.session.commit()
        
        response = self.app.get(f'/super-admin/remove-super-admin/{another_super_admin.id}', 
                               follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Super Admin removed successfully', response.data)
        
        # Verify removed from database
        removed_admin = SuperAdmin.query.get(another_super_admin.id)
        self.assertIsNone(removed_admin)
    
    def test_remove_admin(self):
        """Test removing admin"""
        self.login_user('testsuperadmin', 'password123', 'super_admin')
        response = self.app.get(f'/super-admin/remove-admin/{self.admin.id}', 
                               follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Admin removed successfully', response.data)
        
        # Verify removed from database
        removed_admin = Admin.query.get(self.admin.id)
        self.assertIsNone(removed_admin)
    
    # Admin Tests
    def test_admin_dashboard_access(self):
        """Test admin dashboard access"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.get('/admin/dashboard')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Admin Dashboard', response.data)
    
    def test_add_sales_page(self):
        """Test add sales page access"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.get('/admin/add-sales')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Add New Sales Person', response.data)
    
    def test_add_sales_success(self):
        """Test successful sales person creation"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.post('/admin/add-sales', data={
            'name': 'New Sales Person',
            'username': 'newsales',
            'password': 'newpassword123'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Sales person added successfully', response.data)
        
        # Verify in database
        new_sales = Sales.query.filter_by(username='newsales').first()
        self.assertIsNotNone(new_sales)
        self.assertEqual(new_sales.name, 'New Sales Person')
        self.assertEqual(new_sales.admin_id, self.admin.id)
    
    def test_remove_sales(self):
        """Test removing regular sales person (not admin bucket)"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.get(f'/admin/remove-sales/{self.sales.id}',
                               follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Sales person removed successfully', response.data)
        
        # Verify removed from database
        removed_sales = Sales.query.get(self.sales.id)
        self.assertIsNone(removed_sales)

    def test_remove_admin_sales_forbidden(self):
        """Test that admin bucket (Admin Queue) cannot be removed"""
        self.login_user('testadmin', 'password123', 'admin')
        bucket_id = get_admin_sales_id(self.admin.id)
        self.assertNotEqual(bucket_id, 0, 'admin should have bucket sales')
        response = self.app.get(f'/admin/remove-sales/{bucket_id}',
                               follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Cannot remove Admin Queue', response.data)
        # Bucket still exists
        bucket = Sales.query.get(bucket_id)
        self.assertIsNotNone(bucket)
        self.assertEqual(bucket.name, 'Admin Queue')

    def test_change_admin_sales_password_forbidden(self):
        """Test that admin bucket (Admin Queue) password cannot be changed"""
        self.login_user('testadmin', 'password123', 'admin')
        bucket_id = get_admin_sales_id(self.admin.id)
        self.assertNotEqual(bucket_id, 0, 'admin should have bucket sales')
        response = self.app.post('/admin/change-sales-password', data={
            'sales_id': str(bucket_id),
            'new_password': 'newpass123',
            'confirm_password': 'newpass123'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Cannot change password for Admin Queue', response.data)
        # Bucket password unchanged (still original hash)
        bucket = Sales.query.get(bucket_id)
        self.assertIsNotNone(bucket)
        self.assertFalse(check_password_hash(bucket.password_hash, 'newpass123'))
    
    def test_add_query_page(self):
        """Test add query page access"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.get('/admin/add-query')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Add New Query', response.data)
    
    def test_add_query_success(self):
        """Test successful query creation"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.post('/admin/add-query', data={
            'sales_id': self.sales.id,
            'name': 'New Customer',
            'phone_number': '9876543210',
            'service_query': 'New service query',
            'mail_id': 'newcustomer@example.com'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Query added successfully', response.data)
        
        # Verify in database
        new_query = Query.query.filter_by(name='New Customer').first()
        self.assertIsNotNone(new_query)
        self.assertEqual(new_query.phone_number, '9876543210')
        self.assertEqual(new_query.admin_id, self.admin.id)
    
    def test_edit_query_page(self):
        """Test edit query page access"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.get(f'/admin/edit-query/{self.query.id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Edit Query', response.data)
    
    def test_edit_query_success(self):
        """Test successful query update"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.post(f'/admin/edit-query/{self.query.id}', data={
            'name': 'Updated Customer',
            'phone_number': '1111111111',
            'service_query': 'Updated service query',
            'mail_id': 'updated@example.com',
            'closure': 'yes'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Query updated successfully', response.data)
        
        # Verify updated in database
        updated_query = Query.query.get(self.query.id)
        self.assertEqual(updated_query.name, 'Updated Customer')
        self.assertEqual(updated_query.closure, 'yes')
    
    def test_remove_query(self):
        """Test removing query"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.get(f'/admin/remove-query/{self.query.id}', 
                               follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Query removed successfully', response.data)
        
        # Verify removed from database
        removed_query = Query.query.get(self.query.id)
        self.assertIsNone(removed_query)
    
    # Sales Tests
    def test_sales_dashboard_access(self):
        """Test sales dashboard access"""
        self.login_user('testsales', 'password123', 'sales')
        response = self.app.get('/sales/dashboard')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Sales Dashboard', response.data)
    
    def test_sales_add_query_page(self):
        """Test sales add query page access"""
        self.login_user('testsales', 'password123', 'sales')
        response = self.app.get('/sales/add-query')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Add New Query', response.data)
    
    def test_sales_add_query_success(self):
        """Test successful query creation by sales"""
        self.login_user('testsales', 'password123', 'sales')
        response = self.app.post('/sales/add-query', data={
            'name': 'Sales Customer',
            'phone_number': '5555555555',
            'service_query': 'Sales service query',
            'mail_id': 'salescustomer@example.com'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Query added successfully', response.data)
        
        # Verify in database
        new_query = Query.query.filter_by(name='Sales Customer').first()
        self.assertIsNotNone(new_query)
        self.assertEqual(new_query.sales_id, self.sales.id)
        self.assertEqual(new_query.admin_id, self.admin.id)
    
    def test_sales_edit_query_page(self):
        """Test sales edit query page access"""
        self.login_user('testsales', 'password123', 'sales')
        response = self.app.get(f'/sales/edit-query/{self.query.id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Edit Query', response.data)
    
    def test_sales_edit_query_success(self):
        """Test successful query update by sales (sales can only update closure)"""
        self.login_user('testsales', 'password123', 'sales')
        response = self.app.post(f'/sales/edit-query/{self.query.id}', data={
            'closure': 'Closed'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Query updated successfully', response.data)
        updated_query = Query.query.get(self.query.id)
        self.assertEqual(updated_query.closure, 'Closed')
        self.assertEqual(updated_query.name, 'Test Customer')
    
    def test_add_followup_page(self):
        """Test add followup page access"""
        self.login_user('testsales', 'password123', 'sales')
        response = self.app.get('/sales/add-followup')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Add New Follow Up', response.data)
    
    def test_add_followup_success(self):
        """Test successful followup creation"""
        self.login_user('testsales', 'password123', 'sales')
        from datetime import datetime, timezone, timedelta
        ist = timezone(timedelta(hours=5, minutes=30))
        date_str = datetime.now(ist).strftime('%Y-%m-%dT%H:%M')
        response = self.app.post('/sales/add-followup', data={
            'query_id': self.query.id,
            'date_of_contact': date_str,
            'remark': 'New follow up remark'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Follow up added successfully', response.data)
        
        # Verify in database
        new_followup = FollowUp.query.filter_by(remark='New follow up remark').first()
        self.assertIsNotNone(new_followup)
        self.assertEqual(new_followup.sales_id, self.sales.id)
        self.assertEqual(new_followup.admin_id, self.admin.id)
    
    # Access Control Tests
    def test_super_admin_access_admin_dashboard(self):
        """Test super admin cannot access admin dashboard (redirected to own dashboard)"""
        self.login_user('testsuperadmin', 'password123', 'super_admin')
        response = self.app.get('/admin/dashboard', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        # After redirect we land on super admin dashboard, not admin dashboard
        self.assertIn(b'Super Admin Dashboard', response.data)
    
    def test_admin_access_super_admin_dashboard(self):
        """Test admin cannot access super admin dashboard"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.get('/super-admin/dashboard', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Access denied', response.data)
    
    def test_sales_access_admin_dashboard(self):
        """Test sales cannot access admin dashboard"""
        self.login_user('testsales', 'password123', 'sales')
        response = self.app.get('/admin/dashboard', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Access denied', response.data)
    
    def test_unauthorized_query_edit(self):
        """Test sales cannot edit query not assigned to them"""
        # Create another sales person (not the admin bucket)
        other_sales = Sales(
            admin_id=self.admin.id,
            name='Other Sales',
            username='othersales',
            password_hash=generate_password_hash('password123')
        )
        db.session.add(other_sales)
        db.session.commit()
        self.assertNotEqual(other_sales.id, get_admin_sales_id(self.admin.id))
        
        # Create another query assigned to different sales person
        other_query = Query(
            sales_id=other_sales.id,
            admin_id=self.admin.id,
            name='Other Customer',
            phone_number='9999999999',
            service_query='Other service query',
            mail_id='other@example.com'
        )
        db.session.add(other_query)
        db.session.commit()
        
        # Try to edit with different sales user
        self.login_user('testsales', 'password123', 'sales')
        response = self.app.get(f'/sales/edit-query/{other_query.id}', 
                               follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Access denied', response.data)
    
    # Database Model Tests
    def test_super_admin_model(self):
        """Test SuperAdmin model"""
        super_admin = SuperAdmin.query.filter_by(username='testsuperadmin').first()
        self.assertIsNotNone(super_admin)
        self.assertEqual(super_admin.name, 'Test Super Admin')
        self.assertEqual(super_admin.username, 'testsuperadmin')
    
    def test_admin_model(self):
        """Test Admin model"""
        admin = Admin.query.filter_by(username='testadmin').first()
        self.assertIsNotNone(admin)
        self.assertEqual(admin.name, 'Test Admin')
        self.assertEqual(admin.username, 'testadmin')
    
    def test_sales_model(self):
        """Test Sales model"""
        sales = Sales.query.filter_by(username='testsales').first()
        self.assertIsNotNone(sales)
        self.assertEqual(sales.name, 'Test Sales')
        self.assertEqual(sales.username, 'testsales')
        self.assertEqual(sales.admin_id, self.admin.id)
    
    def test_query_model(self):
        """Test Query model"""
        query = Query.query.filter_by(name='Test Customer').first()
        self.assertIsNotNone(query)
        self.assertEqual(query.phone_number, '1234567890')
        self.assertEqual(query.service_query, 'Test service query')
        self.assertEqual(query.closure, 'pending')
    
    def test_followup_model(self):
        """Test FollowUp model"""
        followup = FollowUp.query.filter_by(remark='Test follow up remark').first()
        self.assertIsNotNone(followup)
        self.assertEqual(followup.admin_id, self.admin.id)
        self.assertEqual(followup.sales_id, self.sales.id)
    
    # Edge Cases
    def test_remove_self_super_admin(self):
        """Test super admin cannot remove themselves"""
        self.login_user('testsuperadmin', 'password123', 'super_admin')
        response = self.app.get(f'/super-admin/remove-super-admin/{self.super_admin.id}', 
                               follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Cannot remove yourself', response.data)
        
        # Verify still exists in database
        super_admin = SuperAdmin.query.get(self.super_admin.id)
        self.assertIsNotNone(super_admin)
    
    def test_remove_sales_with_queries(self):
        """Test removing sales person with associated queries (cascade delete)"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.get(f'/admin/remove-sales/{self.sales.id}',
                               follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Sales person removed successfully', response.data)
        removed_sales = Sales.query.get(self.sales.id)
        self.assertIsNone(removed_sales)
        # Current implementation deletes queries with this sales_id
        query = Query.query.get(self.query.id)
        self.assertIsNone(query)

    # API endpoint tests (admin_id in URL, admin sales from DB)
    def test_get_admin_sales_id(self):
        """Test get_admin_sales_id returns bucket for admin with bucket, 0 for none"""
        self.assertEqual(get_admin_sales_id(self.admin.id), self.admin_bucket_sales.id)
        # Non-existent admin
        self.assertEqual(get_admin_sales_id(99999), 0)

    def test_api_website_lead_success(self):
        """Test POST /api/website/lead/<admin_id> creates query with admin bucket sales"""
        payload = {
            'name': 'Web Lead',
            'phone_number': '1112223333',
            'service_query': 'Website enquiry',
            'mail_id': 'weblead@example.com'
        }
        response = self.app.post(
            f'/api/website/lead/{self.admin.id}',
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data.get('status'), 'success')
        self.assertIn('query_id', data)
        q = Query.query.get(data['query_id'])
        self.assertIsNotNone(q)
        self.assertEqual(q.admin_id, self.admin.id)
        self.assertEqual(q.sales_id, self.admin_bucket_sales.id)
        self.assertEqual(q.name, 'Web Lead')

    def test_api_website_lead_invalid_admin(self):
        """Test website lead with invalid admin_id returns 404"""
        response = self.app.post(
            '/api/website/lead/99999',
            data=json.dumps({
                'name': 'A', 'phone_number': '1', 'service_query': 'q', 'mail_id': 'a@b.com'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn(b'Admin not found', response.data)

    def test_api_form_add_success(self):
        """Test POST /api/formAdd/<admin_id> creates query with admin bucket sales"""
        payload = {
            'name': 'Form Lead',
            'phone_number': '4445556666',
            'service_query': 'Form enquiry'
        }
        response = self.app.post(
            f'/api/formAdd/{self.admin.id}',
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data.get('status'), 'success')
        q = Query.query.filter_by(name='Form Lead').first()
        self.assertIsNotNone(q)
        self.assertEqual(q.sales_id, self.admin_bucket_sales.id)

    def test_api_form_add_invalid_admin(self):
        """Test formAdd with invalid admin_id returns 404"""
        response = self.app.post(
            '/api/formAdd/99999',
            data=json.dumps({
                'name': 'A', 'phone_number': '1', 'service_query': 'q'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 404)

    def test_api_webhook_magic_bricks_success(self):
        """Test POST /api/webhook/magic-bricks/<admin_id> creates lead"""
        response = self.app.post(
            f'/api/webhook/magic-bricks/{self.admin.id}',
            data=json.dumps({'foo': 'bar'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data.get('status'), 'success')
        q = Query.query.filter_by(source='magic bricks').order_by(Query.id.desc()).first()
        self.assertIsNotNone(q)
        self.assertEqual(q.admin_id, self.admin.id)
        self.assertEqual(q.sales_id, self.admin_bucket_sales.id)

    def test_api_add_query_success(self):
        """Test POST /api/add_query with admin_id and sales_id in body"""
        payload = {
            'admin_id': self.admin.id,
            'sales_id': self.sales.id,
            'name': 'API Customer',
            'phone_number': '7778889999',
            'service_query': 'API query',
            'mail_id': 'api@example.com'
        }
        response = self.app.post(
            '/api/add_query',
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data.get('status'), 'success')
        q = Query.query.filter_by(name='API Customer').first()
        self.assertIsNotNone(q)
        self.assertEqual(q.sales_id, self.sales.id)
        self.assertEqual(q.admin_id, self.admin.id)

    def test_api_webhook_99acres_success(self):
        """Test POST /api/webhook/99acres/<admin_id> creates lead"""
        response = self.app.post(
            f'/api/webhook/99acres/{self.admin.id}',
            data=json.dumps({}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data.get('status'), 'success')
        q = Query.query.filter_by(source='99acres').order_by(Query.id.desc()).first()
        self.assertIsNotNone(q)
        self.assertEqual(q.sales_id, self.admin_bucket_sales.id)

    def test_api_webhook_housing_success(self):
        """Test POST /api/webhook/housing/<admin_id> creates lead"""
        response = self.app.post(
            f'/api/webhook/housing/{self.admin.id}',
            data=json.dumps({}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data.get('status'), 'success')
        q = Query.query.filter_by(source='housing').order_by(Query.id.desc()).first()
        self.assertIsNotNone(q)

    def test_api_website_lead_missing_fields(self):
        """Test website lead with missing required fields returns 400"""
        response = self.app.post(
            f'/api/website/lead/{self.admin.id}',
            data=json.dumps({'name': 'Only Name'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'Missing required field', response.data)

    def test_admin_dashboard_shows_admin_sales_id(self):
        """Test admin dashboard receives admin_sales_id so bucket has no delete button"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.get('/admin/dashboard')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Admin Queue', response.data)
        self.assertIn(b'Admin Dashboard', response.data)

    def test_api_add_query_missing_fields(self):
        """Test POST /api/add_query without admin_id/sales_id returns 400"""
        response = self.app.post(
            '/api/add_query',
            data=json.dumps({'name': 'X'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'Missing required field', response.data)

    def test_api_add_query_invalid_admin(self):
        """Test POST /api/add_query with invalid admin_id returns 404"""
        response = self.app.post(
            '/api/add_query',
            data=json.dumps({
                'admin_id': 99999,
                'sales_id': self.sales.id,
                'name': 'X',
                'phone_number': '1',
                'service_query': 'q',
                'mail_id': 'a@b.com'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn(b'Admin not found', response.data)

    # Debug and notify API tests (no real device token needed; dummy token for DB)
    def test_debug_session_development(self):
        """Test GET /debug-session returns development message when FLASK_ENV is development"""
        response = self.app.get('/debug-session')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'development', response.data)

    def test_api_debug_sales_tokens(self):
        """Test GET /api/debug/sales_tokens/<sales_id> returns tokens list (empty when none)"""
        response = self.app.get(f'/api/debug/sales_tokens/{self.sales.id}')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('tokens', data)
        self.assertEqual(data['sales_id'], self.sales.id)
        self.assertEqual(data['tokens'], [])

    def test_api_notify_sales(self):
        """Test POST /api/notify/sales/<sales_id> returns success and sent count (0 without tokens)"""
        response = self.app.post(
            f'/api/notify/sales/{self.sales.id}',
            data=json.dumps({'title': 'Test', 'body': 'Body'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data.get('status'), 'success')
        self.assertIn('sent', data)
        self.assertEqual(data['sent'], 0)

    def test_test_firebase(self):
        """Test GET /test-firebase returns JSON with firebase state"""
        response = self.app.get('/test-firebase')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('firebase_imported', data)

    def test_api_notify_test_token_missing(self):
        """Test POST /api/notify/test_token without token returns 400"""
        response = self.app.post(
            '/api/notify/test_token',
            data=json.dumps({}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'Token is required', response.data)

    def test_api_notify_test_token_with_token(self):
        """Test POST /api/notify/test_token with token (Firebase may not be init; expect 200 or 500)"""
        response = self.app.post(
            '/api/notify/test_token',
            data=json.dumps({'token': 'dummy-fcm-token-for-test'}),
            content_type='application/json'
        )
        self.assertIn(response.status_code, (200, 500))

    # WebView FCM endpoints (session auth; dummy token stored in DB only)
    def test_webview_register_token_sales(self):
        """Test sales can register a dummy FCM token via webview (no real device needed)"""
        self.login_user('testsales', 'password123', 'sales')
        response = self.app.post(
            '/api/webview/register-token',
            data=json.dumps({
                'fcm_token': 'test-fcm-dummy-sales',
                'platform': 'web',
                'app_version': 'test'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data.get('success', data.get('status') == 'success'))
        self.assertEqual(DeviceToken.query.filter_by(sales_id=self.sales.id).count(), 1)

    def test_webview_devices_sales(self):
        """Test sales can GET webview devices after registering token"""
        self.login_user('testsales', 'password123', 'sales')
        self.app.post(
            '/api/webview/register-token',
            data=json.dumps({'fcm_token': 'test-fcm-dummy-sales', 'platform': 'web'}),
            content_type='application/json'
        )
        response = self.app.get('/api/webview/devices')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data.get('success', data.get('status') == 'success'))
        self.assertIn('devices', data)
        self.assertGreaterEqual(len(data['devices']), 1)

    def test_webview_remove_token_sales(self):
        """Test sales can remove FCM token via webview"""
        self.login_user('testsales', 'password123', 'sales')
        self.app.post(
            '/api/webview/register-token',
            data=json.dumps({'fcm_token': 'test-fcm-to-remove', 'platform': 'web'}),
            content_type='application/json'
        )
        response = self.app.post(
            '/api/webview/remove-token',
            data=json.dumps({'fcm_token': 'test-fcm-to-remove'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(DeviceToken.query.filter_by(sales_id=self.sales.id).count(), 0)

    def test_webview_register_token_unauthorized(self):
        """Test webview register-token without login redirects to login (302)"""
        response = self.app.post(
            '/api/webview/register-token',
            data=json.dumps({'fcm_token': 'dummy'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers.get('Location', ''))

    # Daily report API
    def test_api_sales_daily_report_view(self):
        """Test sales can view daily report for a date (empty when none)"""
        self.login_user('testsales', 'password123', 'sales')
        from datetime import date
        today = date.today().strftime('%Y-%m-%d')
        response = self.app.post(
            '/api/sales/daily-report/view',
            data=json.dumps({'report_date': today}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data.get('status'), 'success')
        self.assertIn('report', data)

    def test_api_sales_daily_report_view_missing_date(self):
        """Test daily report view without report_date returns 400"""
        self.login_user('testsales', 'password123', 'sales')
        response = self.app.post(
            '/api/sales/daily-report/view',
            data=json.dumps({}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)

    def test_api_sales_daily_report_update(self):
        """Test sales can add/update daily report"""
        self.login_user('testsales', 'password123', 'sales')
        response = self.app.post(
            '/api/sales/daily-report/update',
            data=json.dumps({'report_text': 'Today I called 5 leads.'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data.get('status'), 'success')
        dr = DailyReport.query.filter_by(sales_id=self.sales.id).first()
        self.assertIsNotNone(dr)
        self.assertIn('5 leads', dr.report_text)

    def test_api_sales_daily_report_update_missing_text(self):
        """Test daily report update without report_text returns 400"""
        self.login_user('testsales', 'password123', 'sales')
        response = self.app.post(
            '/api/sales/daily-report/update',
            data=json.dumps({}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)

    def test_api_sales_daily_report_denied_for_admin(self):
        """Test admin cannot use sales daily report view API (403)"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.post(
            '/api/sales/daily-report/view',
            data=json.dumps({'report_date': '2025-01-01'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_daily_reports_page(self):
        """Test admin can open daily reports page"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.get('/admin/daily-reports')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'daily', response.data.lower())

    def test_admin_integrations_page(self):
        """Test admin can open integrations page and see endpoints with integration key"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.get('/admin/integrations')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Integrations', response.data)
        self.assertIn(b'integration key', response.data)
        self.assertIn(self.admin.integration_slug.encode(), response.data)
        self.assertIn(b'/api/website/lead/', response.data)
        self.assertIn(b'/api/formAdd/', response.data)

    def test_api_website_lead_by_slug(self):
        """Test POST /api/website/lead/<slug> creates query (integration key in URL)"""
        payload = {
            'name': 'Web Lead Slug',
            'phone_number': '1112223333',
            'service_query': 'Enquiry via slug',
            'mail_id': 'slug@example.com'
        }
        response = self.app.post(
            f'/api/website/lead/{self.admin.integration_slug}',
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data.get('status'), 'success')
        q = Query.query.filter_by(name='Web Lead Slug').first()
        self.assertIsNotNone(q)
        self.assertEqual(q.admin_id, self.admin.id)
        self.assertEqual(q.sales_id, self.admin_bucket_sales.id)

    # Admin analytics, add-followup, bulk-delete, update-query-sales, change password
    def test_admin_analytics_page(self):
        """Test admin can open analytics page"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.get('/admin/analytics')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Analytics', response.data)

    def test_sales_analytics_page(self):
        """Test sales can open analytics page"""
        self.login_user('testsales', 'password123', 'sales')
        response = self.app.get('/sales/analytics')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Analytics', response.data)

    def test_admin_add_followup_page(self):
        """Test admin can open add followup page"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.get('/admin/add-followup')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Follow', response.data)

    def test_admin_add_followup_success(self):
        """Test admin can add followup for a query"""
        self.login_user('testadmin', 'password123', 'admin')
        from datetime import datetime, timezone, timedelta
        ist = timezone(timedelta(hours=5, minutes=30))
        date_str = datetime.now(ist).strftime('%Y-%m-%dT%H:%M')
        response = self.app.post('/admin/add-followup', data={
            'query_id': self.query.id,
            'date_of_contact': date_str,
            'remark': 'Admin added follow up'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Follow up added successfully', response.data)
        fu = FollowUp.query.filter_by(remark='Admin added follow up').first()
        self.assertIsNotNone(fu)
        self.assertEqual(fu.query_id, self.query.id)

    def test_admin_update_query_sales_success(self):
        """Test admin can reassign query to another sales person"""
        other_sales = Sales(
            admin_id=self.admin.id,
            name='Other Sales',
            username='othersales',
            password_hash=generate_password_hash('password123')
        )
        db.session.add(other_sales)
        db.session.commit()
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.post(
            '/admin/update-query-sales',
            data=json.dumps({'query_id': self.query.id, 'sales_id': other_sales.id}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data.get('status'), 'success')
        db.session.refresh(self.query)
        self.assertEqual(self.query.sales_id, other_sales.id)

    def test_admin_update_query_sales_no_change(self):
        """Test admin update-query-sales with same sales_id returns no change"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.post(
            '/admin/update-query-sales',
            data=json.dumps({'query_id': self.query.id, 'sales_id': self.sales.id}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data.get('message'), 'No change needed')

    def test_admin_bulk_delete_queries_success(self):
        """Test admin can bulk delete own queries"""
        q2 = Query(
            sales_id=self.sales.id,
            admin_id=self.admin.id,
            name='To Delete',
            phone_number='9999999999',
            service_query='x',
            mail_id='x@x.com'
        )
        db.session.add(q2)
        db.session.commit()
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.post(
            '/admin/bulk-delete-queries',
            data=json.dumps({'query_ids': [q2.id]}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data.get('status'), 'success')
        self.assertEqual(data.get('deleted_count'), 1)
        self.assertIsNone(Query.query.get(q2.id))

    def test_admin_bulk_delete_queries_empty(self):
        """Test bulk delete with no query_ids returns 400"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.post(
            '/admin/bulk-delete-queries',
            data=json.dumps({}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)

    def test_admin_change_sales_password_success(self):
        """Test admin can change sales person password"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.post('/admin/change-sales-password', data={
            'sales_id': str(self.sales.id),
            'new_password': 'newpass123',
            'confirm_password': 'newpass123'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Password changed successfully', response.data)
        db.session.refresh(self.sales)
        self.assertTrue(check_password_hash(self.sales.password_hash, 'newpass123'))


if __name__ == '__main__':
    unittest.main()
