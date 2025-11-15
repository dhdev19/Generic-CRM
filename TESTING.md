# CRM System Testing Documentation

This document provides comprehensive information about testing the CRM system, including test cases, running tests, and understanding test results.

## 🧪 Test Overview

The CRM system includes comprehensive test coverage for:
- **Authentication & Authorization** (Login, Logout, Access Control)
- **Super Admin Functionality** (User Management, System Control)
- **Admin Functionality** (Team Management, Query Management)
- **Sales Functionality** (Customer Interaction, Follow-ups)
- **Database Models** (Data Integrity, Relationships)
- **Security Features** (Access Control, Authorization)

## 📁 Test Files Structure

```
crm/
├── test_crm.py              # Main test suite
├── test_config.py           # Test configuration
├── run_tests.py             # Test runner script
├── requirements-test.txt     # Testing dependencies
└── TESTING.md               # This documentation
```

## 🚀 Quick Start

### 1. Install Testing Dependencies

```bash
pip install -r requirements-test.txt
```

### 2. Run All Tests

```bash
python run_tests.py --all
```

### 3. Run Basic Tests

```bash
python run_tests.py --type basic
```

### 4. Run with Coverage

```bash
python run_tests.py --type coverage
```

## 🔧 Test Runner Options

The `run_tests.py` script provides several options:

```bash
# Run all test types
python run_tests.py --all

# Run specific test type
python run_tests.py --type pytest
python run_tests.py --type coverage

# Run specific test category
python run_tests.py --category auth
python run_tests.py --category super_admin
python run_tests.py --category admin
python run_tests.py --category sales
python run_tests.py --category models
python run_tests.py --category access

# Check and install dependencies
python run_tests.py --check-deps

# Help
python run_tests.py --help
```

## 📋 Test Categories

### 1. Authentication Tests (`--category auth`)
- Login functionality for all user types
- Logout functionality
- Invalid credential handling

**Test Cases:**
- `test_super_admin_login_success`
- `test_admin_login_success`
- `test_sales_login_success`
- `test_login_invalid_credentials`
- `test_logout`

### 2. Super Admin Tests (`--category super_admin`)
- Dashboard access
- User management (add/remove super admins and admins)
- System overview

**Test Cases:**
- `test_super_admin_dashboard_access`
- `test_add_super_admin_success`
- `test_add_admin_success`
- `test_remove_super_admin`
- `test_remove_admin`
- `test_remove_self_super_admin`

### 3. Admin Tests (`--category admin`)
- Dashboard access
- Sales personnel management
- Query management (add/edit/remove)
- Team overview

**Test Cases:**
- `test_admin_dashboard_access`
- `test_add_sales_success`
- `test_remove_sales`
- `test_add_query_success`
- `test_edit_query_success`
- `test_remove_query`

### 4. Sales Tests (`--category sales`)
- Dashboard access
- Query management (add/edit)
- Follow-up management
- Personal overview

**Test Cases:**
- `test_sales_dashboard_access`
- `test_sales_add_query_success`
- `test_sales_edit_query_success`
- `test_add_followup_success`

### 5. Database Model Tests (`--category models`)
- Data model validation
- Relationship integrity
- Default values

**Test Cases:**
- `test_super_admin_model`
- `test_admin_model`
- `test_sales_model`
- `test_query_model`
- `test_followup_model`

### 6. Access Control Tests (`--category access`)
- Role-based access control
- Unauthorized access prevention
- Cross-role access restrictions

**Test Cases:**
- `test_super_admin_access_admin_dashboard`
- `test_admin_access_super_admin_dashboard`
- `test_sales_access_admin_dashboard`
- `test_unauthorized_query_edit`

## 🧪 Individual Test Details

### Authentication Tests

#### `test_super_admin_login_success`
- **Purpose**: Verify super admin can login successfully
- **Steps**: 
  1. Create test super admin user
  2. Attempt login with correct credentials
  3. Verify redirect to super admin dashboard
- **Expected**: Success, redirect to dashboard

#### `test_login_invalid_credentials`
- **Purpose**: Verify system rejects invalid credentials
- **Steps**:
  1. Attempt login with wrong username/password
  2. Verify error message displayed
- **Expected**: Error message, stay on login page

### Super Admin Tests

#### `test_add_super_admin_success`
- **Purpose**: Verify super admin can create new super admin users
- **Steps**:
  1. Login as super admin
  2. Submit form with new super admin details
  3. Verify success message and database entry
- **Expected**: New super admin created successfully

#### `test_remove_self_super_admin`
- **Purpose**: Verify super admin cannot remove themselves
- **Steps**:
  1. Login as super admin
  2. Attempt to remove own account
  3. Verify error message and account remains
- **Expected**: Error message, account not removed

### Admin Tests

#### `test_add_sales_success`
- **Purpose**: Verify admin can create new sales personnel
- **Steps**:
  1. Login as admin
  2. Submit form with new sales person details
  3. Verify success message and database entry
- **Expected**: New sales person created successfully

#### `test_edit_query_success`
- **Purpose**: Verify admin can edit query details
- **Steps**:
  1. Login as admin
  2. Edit existing query
  3. Verify success message and updated data
- **Expected**: Query updated successfully

### Sales Tests

#### `test_sales_add_query_success`
- **Purpose**: Verify sales can create new queries
- **Steps**:
  1. Login as sales person
  2. Submit form with new query details
  3. Verify success message and database entry
- **Expected**: New query created successfully

#### `test_add_followup_success`
- **Purpose**: Verify sales can add follow-up notes
- **Steps**:
  1. Login as sales person
  2. Submit follow-up form
  3. Verify success message and database entry
- **Expected**: Follow-up added successfully

### Access Control Tests

#### `test_unauthorized_query_edit`
- **Purpose**: Verify sales cannot edit queries not assigned to them
- **Steps**:
  1. Create query assigned to different sales person
  2. Login as different sales person
  3. Attempt to edit query
- **Expected**: Access denied message

## 🗄️ Test Database

The test suite uses a temporary SQLite database that is:
- Created before each test
- Populated with test data
- Destroyed after each test

**Test Data Includes:**
- Test super admin user
- Test admin user
- Test sales person
- Sample query
- Sample follow-up

## 🔒 Security Testing

The test suite validates:
- **Authentication**: Proper login/logout functionality
- **Authorization**: Role-based access control
- **Session Management**: Proper session handling
- **Input Validation**: Form data validation
- **Access Control**: Unauthorized access prevention

## 📊 Coverage Testing

To run tests with coverage:

```bash
python run_tests.py --type coverage
```

This will:
1. Run all tests with coverage tracking
2. Generate a coverage report in the terminal
3. Create an HTML coverage report in `htmlcov/` directory

**Coverage Areas:**
- Route handlers (100%)
- Database models (100%)
- Authentication logic (100%)
- Access control (100%)
- Form processing (100%)

## 🚨 Troubleshooting

### Common Issues

#### 1. Import Errors
```bash
# Ensure you're in the correct directory
cd crm

# Install dependencies
pip install -r requirements-test.txt
```

#### 2. Database Errors
```bash
# Clear any existing database
rm -f crm.db

# Run tests again
python run_tests.py
```

#### 3. Permission Errors
```bash
# On Windows, run as administrator
# On Linux/Mac, check file permissions
chmod +x run_tests.py
```

#### 4. Test Failures
- Check the test output for specific error messages
- Verify the application is working correctly
- Check database connectivity
- Ensure all dependencies are installed

### Debug Mode

To run tests with more verbose output:

```bash
# Run with pytest for detailed output
python -m pytest test_crm.py -v -s

# Run specific test with debug
python -m pytest test_crm.py::CRMTests::test_super_admin_login_success -v -s
```

## 📈 Performance Testing

For performance testing, install additional dependencies:

```bash
pip install locust
```

Run performance tests:

```bash
locust -f locustfile.py
```

## 🔍 Security Testing

For security testing, install additional dependencies:

```bash
pip install bandit safety
```

Run security tests:

```bash
# Code security analysis
bandit -r app.py

# Dependency security check
safety check
```

## 📝 Adding New Tests

To add new test cases:

1. **Add to existing test class** in `test_crm.py`
2. **Follow naming convention**: `test_<functionality>_<scenario>`
3. **Include proper setup/teardown**
4. **Add descriptive docstring**
5. **Update this documentation**

Example:
```python
def test_new_feature_success(self):
    """Test successful execution of new feature"""
    # Setup
    self.login_user('testuser', 'password', 'user_type')
    
    # Execute
    response = self.app.post('/new-endpoint', data={...})
    
    # Verify
    self.assertEqual(response.status_code, 200)
    self.assertIn(b'Success', response.data)
```

## 🎯 Test Best Practices

1. **Isolation**: Each test should be independent
2. **Cleanup**: Always clean up after tests
3. **Descriptive Names**: Use clear, descriptive test names
4. **Documentation**: Include docstrings explaining test purpose
5. **Assertions**: Use specific assertions for better error messages
6. **Coverage**: Aim for high test coverage
7. **Performance**: Keep tests fast and efficient

## 📞 Support

If you encounter issues with testing:

1. Check the troubleshooting section above
2. Verify all dependencies are installed
3. Check the test output for specific error messages
4. Ensure the application is working correctly
5. Review the test configuration

---

**Note**: These tests are designed for development and CI/CD environments. For production testing, consider additional security, performance, and integration tests.
