"""
Emergency password reset utility for REMS.

Use this script when a user (including admin) is locked out and cannot
reset their password through the web interface.

Usage:
    python scripts/reset_password.py <username>

Run from the application root directory (/opt/rems or wherever app.py lives).
"""

import sys
import os
import getpass
import argparse

# Add the parent directory to the path so we can import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db, Personnel, MIN_PASSWORD_LENGTH


def reset_password(username, new_password):
    with app.app_context():
        user = Personnel.query.filter_by(username=username).first()

        if not user:
            print(f"Error: No user found with username '{username}'")
            print("\nExisting usernames:")
            for p in Personnel.query.filter(Personnel.username != None).all():
                print(f"  {p.username} ({p.name})")
            sys.exit(1)

        user.set_password(new_password)
        db.session.commit()
        print(f"Password successfully reset for user '{username}' ({user.name})")


def main():
    parser = argparse.ArgumentParser(description="Reset a REMS user password")
    parser.add_argument("username", help="Username to reset")
    args = parser.parse_args()

    new_password = getpass.getpass(f"Enter new password for '{args.username}': ")
    confirm = getpass.getpass("Confirm new password: ")
    if new_password != confirm:
        print("Error: Passwords do not match.")
        sys.exit(1)

    if len(new_password) < MIN_PASSWORD_LENGTH:
        print(f"Error: Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        sys.exit(1)

    reset_password(args.username, new_password)


if __name__ == "__main__":
    main()
