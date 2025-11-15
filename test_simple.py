#!/usr/bin/env python3
"""
Simple Test Runner for CRM System

This script provides a simple way to run tests without complex options.
Just run: python test_simple.py
"""

import unittest
import sys
import os

def main():
    """Run all tests with simple output"""
    print("🧪 CRM System - Simple Test Runner")
    print("=" * 50)
    
    # Check if test file exists
    if not os.path.exists("test_crm.py"):
        print("❌ test_crm.py not found!")
        print("Please make sure you're in the correct directory")
        sys.exit(1)
    
    # Check if app.py exists
    if not os.path.exists("app.py"):
        print("❌ app.py not found!")
        print("Please make sure you're in the correct directory")
        sys.exit(1)
    
    print("✅ Test files found")
    print("🚀 Starting tests...\n")
    
    # Discover and run tests
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName('test_crm')
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Summary
    print("\n" + "=" * 50)
    if result.wasSuccessful():
        print("🎉 All tests passed!")
        print(f"✅ Ran {result.testsRun} tests successfully")
        print("🚀 Your CRM system is working correctly!")
    else:
        print("❌ Some tests failed!")
        print(f"⚠️  {len(result.failures)} failures, {len(result.errors)} errors")
        print("🔍 Check the output above for details")
        sys.exit(1)

if __name__ == '__main__':
    main()
