#!/usr/bin/env python3
"""
Test Runner for CRM System

This script provides different options for running tests:
- Run all tests
- Run specific test categories
- Run with coverage report
- Run with verbose output
"""

import sys
import os
import subprocess
import argparse
from pathlib import Path

def run_command(command, description):
    """Run a command and handle errors"""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {command}")
    print('='*60)
    
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print("✅ SUCCESS")
        if result.stdout:
            print("Output:")
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print("❌ FAILED")
        print(f"Error Code: {e.returncode}")
        if e.stdout:
            print("Stdout:")
            print(e.stdout)
        if e.stderr:
            print("Stderr:")
            print(e.stderr)
        return False

def check_dependencies():
    """Check if required testing dependencies are installed"""
    print("🔍 Checking testing dependencies...")
    
    try:
        import pytest
        print("✅ pytest is installed")
    except ImportError:
        print("❌ pytest is not installed. Installing...")
        run_command("pip install pytest", "Installing pytest")
    
    try:
        import coverage
        print("✅ coverage is installed")
    except ImportError:
        print("❌ coverage is not installed. Installing...")
        run_command("pip install coverage", "Installing coverage")

def run_basic_tests():
    """Run basic unittest tests"""
    return run_command("python -m unittest test_crm.py -v", "Basic unittest tests")

def run_pytest_tests():
    """Run tests with pytest"""
    return run_command("python -m pytest test_crm.py -v", "Pytest tests")

def run_coverage_tests():
    """Run tests with coverage report"""
    commands = [
        "coverage run --source=app test_crm.py",
        "coverage report",
        "coverage html"
    ]
    
    success = True
    for cmd in commands:
        if not run_command(cmd, f"Coverage: {cmd}"):
            success = False
    
    if success:
        print("\n📊 Coverage report generated!")
        print("📁 Open htmlcov/index.html in your browser to view detailed coverage")
    
    return success

def run_specific_tests(test_category):
    """Run specific test categories"""
    categories = {
        'auth': 'test_*login* test_*logout*',
        'super_admin': 'test_super_admin*',
        'admin': 'test_admin*',
        'sales': 'test_sales*',
        'models': 'test_*model*',
        'access': 'test_*access* test_*unauthorized*'
    }
    
    if test_category not in categories:
        print(f"❌ Unknown test category: {test_category}")
        print(f"Available categories: {', '.join(categories.keys())}")
        return False
    
    pattern = categories[test_category]
    return run_command(f"python -m pytest test_crm.py -k '{pattern}' -v", f"{test_category.title()} tests")

def main():
    """Main function to handle command line arguments"""
    parser = argparse.ArgumentParser(description='CRM System Test Runner')
    parser.add_argument('--type', choices=['basic', 'pytest', 'coverage'], 
                       default='basic', help='Type of test to run')
    parser.add_argument('--category', choices=['auth', 'super_admin', 'admin', 'sales', 'models', 'access'],
                       help='Run specific test category')
    parser.add_argument('--check-deps', action='store_true', 
                       help='Check and install testing dependencies')
    parser.add_argument('--all', action='store_true', 
                       help='Run all test types')
    
    args = parser.parse_args()
    
    print("🚀 CRM System Test Runner")
    print("=" * 40)
    
    # Check if test file exists
    if not Path("test_crm.py").exists():
        print("❌ test_crm.py not found!")
        print("Please make sure you're in the correct directory")
        sys.exit(1)
    
    # Check dependencies if requested
    if args.check_deps:
        check_dependencies()
    
    success = True
    
    if args.all:
        print("\n🔄 Running all test types...")
        success &= run_basic_tests()
        success &= run_pytest_tests()
        success &= run_coverage_tests()
    elif args.category:
        success = run_specific_tests(args.category)
    else:
        if args.type == 'basic':
            success = run_basic_tests()
        elif args.type == 'pytest':
            success = run_pytest_tests()
        elif args.type == 'coverage':
            success = run_coverage_tests()
    
    # Final summary
    print("\n" + "="*60)
    if success:
        print("🎉 All tests completed successfully!")
        print("✅ Your CRM system is working correctly!")
    else:
        print("❌ Some tests failed!")
        print("🔍 Check the output above for details")
        sys.exit(1)

if __name__ == '__main__':
    main()
