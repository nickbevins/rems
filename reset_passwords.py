#!/usr/bin/env python3
"""
Script to reset all personnel passwords to the same value.
Run this script from the same directory as app.py
"""

import sys
import os
from werkzeug.security import generate_password_hash

# Add the current directory to Python path to import from app.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db, Personnel

def reset_all_passwords(new_password="password123"):
    """Reset all personnel passwords to the specified value"""
    
    with app.app_context():
        try:
            # Get all personnel with usernames (those who can log in)
            personnel = Personnel.query.filter(Personnel.username.isnot(None)).all()
            
            if not personnel:
                print("No personnel with usernames found.")
                return
            
            print(f"Found {len(personnel)} personnel with usernames:")
            for person in personnel:
                print(f"  - {person.name} (username: {person.username})")
            
            confirm = input(f"\nReset all passwords to '{new_password}'? (y/N): ")
            if confirm.lower() != 'y':
                print("Operation cancelled.")
                return
            
            # Update passwords
            updated_count = 0
            for person in personnel:
                person.set_password(new_password)
                updated_count += 1
                print(f"Updated password for {person.name} ({person.username})")
            
            # Commit changes
            db.session.commit()
            print(f"\nSuccessfully updated {updated_count} passwords.")
            
        except Exception as e:
            print(f"Error: {e}")
            db.session.rollback()
            return False
    
    return True

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Reset all personnel passwords')
    parser.add_argument('--password', default='password123', 
                       help='New password for all users (default: password123)')
    
    args = parser.parse_args()
    
    print("Personnel Password Reset Script")
    print("=" * 40)
    
    reset_all_passwords(args.password)