#!/usr/bin/env python3
"""
Script to list all personnel with login credentials.
Run this script from the same directory as app.py
"""

import sys
import os

# Add the current directory to Python path to import from app.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db, Personnel

def list_users():
    """List all personnel with usernames"""
    
    with app.app_context():
        try:
            # Get all personnel with usernames (those who can log in)
            personnel = Personnel.query.filter(Personnel.username.isnot(None)).all()
            
            if not personnel:
                print("No personnel with usernames found.")
                return
            
            print(f"Found {len(personnel)} personnel with login credentials:")
            print("=" * 60)
            
            for person in personnel:
                status = "Active" if person.is_active else "Inactive"
                admin = "Yes" if person.is_admin else "No"
                print(f"Name: {person.name}")
                print(f"Username: {person.username}")
                print(f"Email: {person.email}")
                print(f"Status: {status}")
                print(f"Admin: {admin}")
                print(f"Roles: {person.roles or 'None'}")
                print("-" * 40)
            
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    return True

if __name__ == "__main__":
    print("Personnel Login Credentials List")
    print("=" * 40)
    list_users()