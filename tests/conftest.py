"""
Test configuration for physdb.

The app checks SECRET_KEY at import time, so env vars must be set before
importing app.py. conftest.py is loaded before test modules, making it the
right place for this setup.
"""
import os
import sys

# Must be set before importing app
os.environ.setdefault('SECRET_KEY', 'test-secret-key-not-for-production')
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from app import app as flask_app, db, Personnel


@pytest.fixture()
def app():
    flask_app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'WTF_CSRF_ENABLED': False,
        'SERVER_NAME': 'localhost',
    })
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def make_user(
    username='testuser',
    password='password123',
    is_admin=False,
    roles='',
    is_active=True,
    login_required=True,
    must_change_password=False,
):
    """Create and persist a Personnel record for testing."""
    user = Personnel(
        name='Test User',
        email=f'{username}@example.com',
        username=username,
        is_admin=is_admin,
        roles=roles,
        is_active=is_active,
        login_required=login_required,
        must_change_password=must_change_password,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def login(client, username='testuser', password='password123'):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=False)
