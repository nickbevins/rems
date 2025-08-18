#!/usr/bin/env python3
"""
Script to create the first admin user for PhysDB
Run this script after installing Flask-Login and before starting the application
"""

import sys
import os
from getpass import getpass

# Add the current directory to Python path so we can import from app.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db, Personnel

def create_admin_user():
    """Create the first admin user"""
    print("Creating first admin user for PhysDB")
    print("=" * 40)
    
    # Get user input
    username = input("Enter username (e.g., nick.bevins): ").strip()
    if not username:
        print("Username cannot be empty!")
        return False
    
    email = input("Enter email: ").strip()
    if not email:
        print("Email cannot be empty!")
        return False
    
    password = getpass("Enter password: ")
    if not password:
        print("Password cannot be empty!")
        return False
    
    confirm_password = getpass("Confirm password: ")
    if password != confirm_password:
        print("Passwords do not match!")
        return False
    
    # Create the database tables if they don't exist
    with app.app_context():
        try:
            # Create tables
            db.create_all()
            
            # Check if user already exists
            existing_user = Personnel.query.filter_by(username=username).first()
            existing_email = Personnel.query.filter_by(email=email).first()
            
            if existing_user:
                print(f"Username '{username}' already exists!")
                return False
            
            if existing_email:
                # Email exists, ask if we should update it with login credentials
                print(f"Email '{email}' already exists in personnel records.")
                update = input("Would you like to add login credentials to this existing record? (y/n): ").lower()
                if update == 'y':
                    # Update existing record
                    admin_user = existing_email
                    admin_user.username = username
                    admin_user.is_admin = True
                    admin_user.is_active = True
                    if not admin_user.roles or admin_user.roles.strip() == '':
                        admin_user.roles = 'admin'
                    admin_user.set_password(password)
                    
                    db.session.commit()
                    print(f"✓ Updated existing personnel record for '{email}' with admin login credentials!")
                    print(f"✓ Username: {username}")
                    print(f"✓ Admin privileges: Yes")
                    print(f"✓ Active: Yes")
                    print("\nYou can now start the application with: python app.py")
                    print(f"Then login at http://localhost:5000/login with username: {username}")
                    return True
                else:
                    print("Operation cancelled.")
                    return False
            
            # Create new admin user
            admin_user = Personnel(
                name=username.replace('.', ' ').title(),  # Convert nick.bevins to Nick Bevins
                username=username,
                email=email,
                is_admin=True,
                is_active=True,
                roles='admin'
            )
            admin_user.set_password(password)
            
            # Save to database
            db.session.add(admin_user)
            db.session.commit()
            
            print(f"✓ Admin user '{username}' created successfully!")
            print(f"✓ Email: {email}")
            print(f"✓ Admin privileges: Yes")
            print(f"✓ Active: Yes")
            print("\nYou can now start the application with: python app.py")
            print(f"Then login at http://localhost:5000/login with username: {username}")
            
            return True
            
        except Exception as e:
            print(f"Error creating admin user: {e}")
            return False

if __name__ == "__main__":
    success = create_admin_user()
    if not success:
        sys.exit(1)