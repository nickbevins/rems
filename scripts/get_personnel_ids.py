#!/usr/bin/env python3
"""
Script to list all personnel IDs and names for bulk upload reference
"""

import sys
import os

# Add the current directory to Python path so we can import from app.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db, Personnel

def list_personnel_ids():
    """List all personnel IDs and names for CSV reference"""
    print("Personnel IDs for Bulk Upload:")
    print("=" * 50)
    
    with app.app_context():
        try:
            personnel = Personnel.query.order_by(Personnel.id).all()
            
            if not personnel:
                print("No personnel found in database.")
                return
            
            print(f"{'ID':<5} {'Name':<25} {'Email':<35} {'Roles'}")
            print("-" * 80)
            
            for person in personnel:
                roles = person.roles if person.roles else 'No roles'
                print(f"{person.id:<5} {person.name:<25} {person.email:<35} {roles}")
            
            print(f"\nTotal personnel records: {len(personnel)}")
            print("\nUse these IDs in your CSV for performed_by_id and reviewed_by_id (reviewing physicist) columns.")
            
        except Exception as e:
            print(f"Error listing personnel: {e}")

if __name__ == "__main__":
    list_personnel_ids()