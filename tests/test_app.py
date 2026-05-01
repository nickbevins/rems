"""
Integration tests for physdb Flask app.

Coverage areas:
  - Authentication: login success/failure, logout
  - Open redirect rejection in login `next` parameter
  - enforce_password_change blocks all routes except allowed endpoints
  - Role enforcement: viewer vs physicist on manage_equipment_required routes
  - CSV row limit rejection (>500 rows)
  - get_estimated_eol_date date arithmetic
"""
import io
import pytest
from datetime import date
from unittest.mock import MagicMock

from conftest import make_user, login


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class TestLogin:
    def test_valid_login_redirects_to_index(self, app, client):
        with app.app_context():
            make_user(username='alice', password='correct')
        resp = login(client, 'alice', 'correct')
        assert resp.status_code == 302
        assert resp.location.endswith('/')

    def test_wrong_password_stays_on_login(self, app, client):
        with app.app_context():
            make_user(username='bob', password='correct')
        resp = login(client, 'bob', 'wrong')
        assert resp.status_code == 200
        assert b'Invalid username or password' in resp.data

    def test_inactive_user_cannot_login(self, app, client):
        with app.app_context():
            make_user(username='carol', password='pw', is_active=False)
        resp = login(client, 'carol', 'pw')
        assert resp.status_code == 200
        assert b'Invalid username or password' in resp.data

    def test_login_required_false_cannot_login(self, app, client):
        """Personnel with login_required=False should not be able to log in."""
        with app.app_context():
            make_user(username='dave', password='pw', login_required=False)
        resp = login(client, 'dave', 'pw')
        assert resp.status_code == 200
        assert b'Invalid username or password' in resp.data


# ---------------------------------------------------------------------------
# Open redirect
# ---------------------------------------------------------------------------

class TestOpenRedirect:
    def test_external_next_param_ignored(self, app, client):
        with app.app_context():
            make_user(username='eve', password='pw')
        resp = client.post(
            '/login?next=https://evil.example.com/steal',
            data={'username': 'eve', 'password': 'pw'},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        location = resp.location
        assert 'evil.example.com' not in location

    def test_relative_next_param_accepted(self, app, client):
        with app.app_context():
            make_user(username='frank', password='pw')
        resp = client.post(
            '/login?next=/equipment',
            data={'username': 'frank', 'password': 'pw'},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert 'evil' not in resp.location


# ---------------------------------------------------------------------------
# Unauthenticated access
# ---------------------------------------------------------------------------

class TestUnauthenticatedAccess:
    PROTECTED_ROUTES = [
        '/equipment/new',
        '/import-data',
        '/import-personnel',
        '/export-equipment',
        '/change-password',
    ]

    @pytest.mark.parametrize('route', PROTECTED_ROUTES)
    def test_redirects_to_login(self, client, route):
        resp = client.get(route, follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.location


# ---------------------------------------------------------------------------
# enforce_password_change
# ---------------------------------------------------------------------------

class TestPasswordChangeEnforcement:
    def _login_must_change(self, app, client):
        with app.app_context():
            make_user(username='grace', password='pw', must_change_password=True)
        login(client, 'grace', 'pw')

    def test_blocked_from_index(self, app, client):
        self._login_must_change(app, client)
        resp = client.get('/', follow_redirects=False)
        assert resp.status_code == 302
        assert 'change-password' in resp.location

    def test_change_password_itself_is_allowed(self, app, client):
        self._login_must_change(app, client)
        resp = client.get('/change-password', follow_redirects=False)
        # Should render the form, not redirect away
        assert resp.status_code == 200

    def test_logout_is_allowed(self, app, client):
        self._login_must_change(app, client)
        resp = client.get('/logout', follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.location


# ---------------------------------------------------------------------------
# Role enforcement
# ---------------------------------------------------------------------------

class TestRoleEnforcement:
    def test_viewer_cannot_access_equipment_new(self, app, client):
        """A user with no manage roles should be redirected away from /equipment/new."""
        with app.app_context():
            make_user(username='viewer', password='pw', roles='viewer')
        login(client, 'viewer', 'pw')
        resp = client.get('/equipment/new', follow_redirects=False)
        assert resp.status_code == 302
        assert 'equipment' in resp.location  # redirected to equipment_list

    def test_physicist_can_access_equipment_new(self, app, client):
        with app.app_context():
            make_user(username='phys', password='pw', roles='physicist')
        login(client, 'phys', 'pw')
        resp = client.get('/equipment/new', follow_redirects=False)
        # Should render the form (200), not be redirected
        assert resp.status_code == 200

    def test_admin_can_access_equipment_new(self, app, client):
        with app.app_context():
            make_user(username='admin', password='pw', is_admin=True)
        login(client, 'admin', 'pw')
        resp = client.get('/equipment/new', follow_redirects=False)
        assert resp.status_code == 200

    def test_viewer_cannot_access_import_personnel(self, app, client):
        with app.app_context():
            make_user(username='viewer2', password='pw', roles='viewer')
        login(client, 'viewer2', 'pw')
        resp = client.get('/import-personnel', follow_redirects=False)
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# CSV row limit
# ---------------------------------------------------------------------------

def _make_csv(num_rows, columns=None):
    """Return a BytesIO CSV with the given number of data rows."""
    if columns is None:
        columns = ['equipment_class', 'eq_mod']
    buf = io.BytesIO()
    header = ','.join(columns) + '\n'
    buf.write(header.encode())
    for i in range(num_rows):
        row = ','.join([f'value{i}'] * len(columns)) + '\n'
        buf.write(row.encode())
    buf.seek(0)
    return buf


class TestCSVRowLimit:
    def _login_physicist(self, app, client):
        with app.app_context():
            make_user(username='phys_csv', password='pw', roles='physicist')
        login(client, 'phys_csv', 'pw')

    def test_import_data_rejects_over_500_rows(self, app, client):
        self._login_physicist(app, client)
        csv_data = _make_csv(501)
        resp = client.post(
            '/import-data',
            data={'file': (csv_data, 'big.csv', 'text/csv')},
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        assert b'exceeds the maximum of 500 rows' in resp.data

    def test_import_data_accepts_500_rows(self, app, client):
        self._login_physicist(app, client)
        csv_data = _make_csv(500)
        resp = client.post(
            '/import-data',
            data={'file': (csv_data, 'ok.csv', 'text/csv')},
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        assert b'exceeds the maximum' not in resp.data

    def test_import_personnel_rejects_over_500_rows(self, app, client):
        with app.app_context():
            make_user(username='phys_pcsv', password='pw', roles='physicist')
        login(client, 'phys_pcsv', 'pw')
        csv_data = _make_csv(501, columns=['name', 'email'])
        resp = client.post(
            '/import-personnel',
            data={'csv_file': (csv_data, 'big.csv', 'text/csv')},
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        assert b'exceeds the maximum of 500 rows' in resp.data


# ---------------------------------------------------------------------------
# Date arithmetic — get_estimated_eol_date
# ---------------------------------------------------------------------------

class TestEstimatedEolDate:
    """
    get_estimated_eol_date picks the latest of eq_mandt/eq_instdt/eq_rfrbdt
    and adds equipment_subclass.expected_lifetime years.
    """

    def _make_equipment_stub(self, mandt=None, instdt=None, rfrbdt=None, lifetime=None):
        from app import Equipment
        eq = Equipment.__new__(Equipment)
        eq.eq_mandt = mandt
        eq.eq_instdt = instdt
        eq.eq_rfrbdt = rfrbdt
        subclass = MagicMock()
        subclass.expected_lifetime = lifetime
        eq.equipment_subclass = subclass
        return eq

    def test_returns_none_without_subclass(self, app):
        from app import Equipment
        with app.app_context():
            eq = Equipment.__new__(Equipment)
            eq.equipment_subclass = None
            assert eq.get_estimated_eol_date() is None

    def test_returns_none_without_dates(self, app):
        with app.app_context():
            eq = self._make_equipment_stub(lifetime=10)
            assert eq.get_estimated_eol_date() is None

    def test_uses_manufacture_date(self, app):
        with app.app_context():
            eq = self._make_equipment_stub(mandt=date(2010, 6, 15), lifetime=10)
            result = eq.get_estimated_eol_date()
            assert result == date(2020, 6, 15)

    def test_uses_latest_of_mandt_and_instdt(self, app):
        with app.app_context():
            # instdt is later — should be used as the base
            eq = self._make_equipment_stub(
                mandt=date(2010, 1, 1),
                instdt=date(2012, 3, 20),
                lifetime=5,
            )
            result = eq.get_estimated_eol_date()
            assert result == date(2017, 3, 20)

    def test_rfrbdt_takes_precedence_when_latest(self, app):
        with app.app_context():
            eq = self._make_equipment_stub(
                mandt=date(2010, 1, 1),
                instdt=date(2012, 1, 1),
                rfrbdt=date(2015, 6, 1),
                lifetime=8,
            )
            result = eq.get_estimated_eol_date()
            assert result == date(2023, 6, 1)

    def test_lifetime_zero_returns_base_date(self, app):
        with app.app_context():
            eq = self._make_equipment_stub(mandt=date(2015, 1, 1), lifetime=0)
            result = eq.get_estimated_eol_date()
            assert result == date(2015, 1, 1)
