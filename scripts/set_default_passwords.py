#!/usr/bin/env python3
"""
Script to set default passwords for existing personnel records
"""

import sys
import os
from werkzeug.security import generate_password_hash

# Add the current directory to Python path so we can import from app.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db, Personnel

def set_default_passwords():
    """Set default passwords for existing personnel records"""
    print("Setting default passwords for existing personnel...")
    print("=" * 50)
    
    with app.app_context():
        try:
            # Get all personnel records that don't have usernames yet
            personnel_records = Personnel.query.filter(Personnel.username.is_(None)).all()
            
            if not personnel_records:
                print("No personnel records found without usernames.")
                return True
            
            print(f"Found {len(personnel_records)} personnel records without login credentials:")
            for person in personnel_records:
                print(f"  - {person.name} ({person.email})")
            
            print("\nSetting up login credentials for these users...")
            
            updated_count = 0
            
            for person in personnel_records:
                # Create username from email (part before @)
                username = person.email.split('@')[0] if '@' in person.email else person.email
                
                # Check if this username already exists
                existing_user = Personnel.query.filter_by(username=username).first()
                if existing_user and existing_user.id != person.id:
                    print(f"  Warning: Username '{username}' already exists, skipping {person.name}")
                    continue
                
                # Set username and password
                person.username = username
                person.set_password("radiology")
                person.is_active = True
                # Don't make them admin by default (only nick.bevins should be admin)
                
                print(f"  Set up login for {person.name} - Username: {username}")
                updated_count += 1
            
            # Commit all changes
            db.session.commit()
            
            print(f"\nSuccessfully set up login credentials for {updated_count} personnel records!")
            print("Default password: radiology")
            print("All users are active and can log in")
            print("\nUsers can now login with their username and password 'radiology'")
            
            return True
            
        except Exception as e:
            print(f"Error setting default passwords: {e}")
            db.session.rollback()
            return False

if __name__ == "__main__":
    success = set_default_passwords()
    if not success:
        sys.exit(1)