import unittest
import tempfile
import os
from app import app, db, SuperAdmin, Admin, Sales, Query, FollowUp
from werkzeug.security import generate_password_hash
from datetime import datetime

class CRMTests(unittest.TestCase):
    
    def setUp(self):
        """Set up test database and client before each test"""
        # Create temporary database
        self.db_fd, self.db_path = tempfile.mkstemp()
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{self.db_path}'
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        
        self.app = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
        
        # Create all tables
        db.create_all()
        
        # Create test data
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
        
        # Create admin
        self.admin = Admin(
            name='Test Admin',
            username='testadmin',
            password_hash=generate_password_hash('password123')
        )
        db.session.add(self.admin)
        
        db.session.commit()
        
        # Create sales person (now we know admin.id)
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
        
        # Create test follow up
        self.followup = FollowUp(
            admin_id=self.admin.id,
            sales_id=self.sales.id,
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
        """Test removing sales person"""
        self.login_user('testadmin', 'password123', 'admin')
        response = self.app.get(f'/admin/remove-sales/{self.sales.id}', 
                               follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Sales person removed successfully', response.data)
        
        # Verify removed from database
        removed_sales = Sales.query.get(self.sales.id)
        self.assertIsNone(removed_sales)
    
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
        """Test successful query update by sales"""
        self.login_user('testsales', 'password123', 'sales')
        response = self.app.post(f'/sales/edit-query/{self.query.id}', data={
            'name': 'Sales Updated Customer',
            'phone_number': '6666666666',
            'service_query': 'Sales updated service query',
            'mail_id': 'salesupdated@example.com'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Query updated successfully', response.data)
        
        # Verify updated in database
        updated_query = Query.query.get(self.query.id)
        self.assertEqual(updated_query.name, 'Sales Updated Customer')
        self.assertEqual(updated_query.phone_number, '6666666666')
    
    def test_add_followup_page(self):
        """Test add followup page access"""
        self.login_user('testsales', 'password123', 'sales')
        response = self.app.get('/sales/add-followup')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Add New Follow Up', response.data)
    
    def test_add_followup_success(self):
        """Test successful followup creation"""
        self.login_user('testsales', 'password123', 'sales')
        response = self.app.post('/sales/add-followup', data={
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
        """Test super admin cannot access admin dashboard"""
        self.login_user('testsuperadmin', 'password123', 'super_admin')
        response = self.app.get('/admin/dashboard', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Access denied', response.data)
    
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
        # Create another sales person
        other_sales = Sales(
            admin_id=self.admin.id,
            name='Other Sales',
            username='othersales',
            password_hash=generate_password_hash('password123')
        )
        db.session.add(other_sales)
        db.session.commit()
        
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
        self.assertEqual(query.closure, 'not relevant')
    
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
        """Test removing sales person with associated queries"""
        self.login_user('testadmin', 'password123', 'admin')
        
        # Try to remove sales person who has queries
        response = self.app.get(f'/admin/remove-sales/{self.sales.id}', 
                               follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Sales person removed successfully', response.data)
        
        # Verify sales person removed
        removed_sales = Sales.query.get(self.sales.id)
        self.assertIsNone(removed_sales)
        
        # Verify associated query still exists (for data integrity)
        query = Query.query.get(self.query.id)
        self.assertIsNotNone(query)

if __name__ == '__main__':
    unittest.main()
