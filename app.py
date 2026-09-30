from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_file, has_request_context, Response
from urllib.parse import urlparse, urljoin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import and_, desc, event, exc as sa_exc, func, inspect, or_, text
from sqlalchemy.orm import selectinload
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect, CSRFError
from wtforms import StringField, IntegerField, DateField, SelectField, BooleanField, TextAreaField, SelectMultipleField, FileField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Optional, Length, Email, EqualTo, NumberRange
from datetime import date, datetime, timedelta, timezone
import os
import pandas as pd
from dotenv import load_dotenv
from dateutil.relativedelta import relativedelta
import calendar
import io
import csv
import shutil
import sqlite3
import tempfile
import xlsxwriter
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from collections import defaultdict, deque
import threading
import time
from functools import wraps
from types import SimpleNamespace
import logging
import re

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_personnel_initials(name):
    """Extract initials from personnel name (e.g., 'Bevins, Nick' -> 'NB')"""
    if not name:
        return ''

    # Handle "Last, First" format by reversing order after comma
    if ',' in name:
        parts = [part.strip() for part in name.split(',')]
        # Reverse order: [Last, First] -> [First, Last]
        parts = parts[::-1]
        # Now split each part by spaces to handle multiple first/middle names
        all_parts = []
        for part in parts:
            all_parts.extend(part.split())
        parts = all_parts
    else:
        # Handle other formats (dots, underscores, spaces)
        parts = name.replace('.', ' ').replace('_', ' ').split()

    initials = ''.join([part[0].upper() for part in parts if part and len(part) > 0])
    return initials[:3]  # Limit to 3 characters max


def _generate_mefacreg(mefac, mereg):
    """Derive eq_mefacreg by combining trailing digits of eq_mefac and eq_mereg.

    Returns a '<mefac_digits>-<mereg_digits>' string, or None if either value
    is missing or contains no trailing digits.
    """
    if not mefac or not mereg:
        return None
    mefac_m = re.search(r'\d+$', mefac)
    mereg_m = re.search(r'\d+$', mereg)
    if mefac_m and mereg_m:
        return f"{mefac_m.group()}-{mereg_m.group()}"
    return None


class MockPagination:
    """Minimal pagination shim used when SQLAlchemy's paginate() is bypassed.

    Compatible with Flask-SQLAlchemy's Pagination object so templates need
    no changes when switching between real and mock pagination.
    """

    def __init__(self, items, page, pages):
        self.items = items
        self.total = len(items) if pages == 1 else None  # overridden below when needed
        self.page = page
        self.pages = pages
        self.has_prev = page > 1
        self.has_next = page < pages
        self.prev_num = page - 1 if page > 1 else None
        self.next_num = page + 1 if page < pages else None

    def iter_pages(self, *args, **kwargs):
        return range(max(1, self.page - 2), min(self.pages + 1, self.page + 3))

    @classmethod
    def show_all(cls, items):
        """Return a single-page MockPagination containing all items."""
        obj = cls(items, page=1, pages=1)
        obj.total = len(items)
        obj.has_next = False
        obj.iter_pages = lambda *a, **k: [1]
        return obj

    @classmethod
    def paginate(cls, items, page, per_page, total):
        """Return a MockPagination for a pre-sliced page of items."""
        pages = max(1, (total + per_page - 1) // per_page)
        obj = cls(items, page=page, pages=pages)
        obj.total = total
        obj.iter_pages = lambda *a, **k: range(max(1, page - 2), min(pages + 1, page + 3))
        return obj


app = Flask(__name__)
_secret_key = os.environ.get('SECRET_KEY')
if not _secret_key:
    raise RuntimeError("SECRET_KEY environment variable is not set. Set it in your .env file before starting the application.")
app.config['SECRET_KEY'] = _secret_key
# Use persistent database path for production
if 'RENDER' in os.environ:
    # On Render, check for persistent disk or PostgreSQL
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        # Use PostgreSQL or other provided database URL
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    elif os.path.exists('/var/data'):
        # Use persistent disk if mounted at /var/data
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////var/data/physdb.db'
    else:
        # Fallback to temp location (data will be lost on deploy)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/physdb.db'
        logger.warning("Using temporary SQLite database. Data will be lost on deployment!")
        logger.warning("Consider upgrading to a paid plan and adding a persistent disk, or use PostgreSQL.")
else:
    # Local development - use instance folder
    instance_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
    os.makedirs(instance_dir, exist_ok=True)
    db_path = os.path.join(instance_dir, 'physdb.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', f'sqlite:///{db_path}')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Session cookie hardening. Secure (HTTPS-only) is on for Render, or set
# SESSION_COOKIE_SECURE=1 for any other HTTPS deployment; plain-HTTP local dev
# would otherwise be unable to log in.
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = (
    'RENDER' in os.environ or os.environ.get('SESSION_COOKIE_SECURE') == '1'
)

# Behind a reverse proxy (Render's load balancer, or nginx on-prem) the client IP
# and scheme arrive in X-Forwarded-* headers. Trust exactly that many hops so the
# real IP reaches logs and login throttling; never trust them with no proxy in front,
# or clients could spoof their address.
_proxy_count = int(os.environ.get('TRUSTED_PROXY_COUNT', '1' if 'RENDER' in os.environ else '0'))
if _proxy_count:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=_proxy_count, x_proto=_proxy_count)

MAX_CSV_ROWS = 500  # Maximum rows allowed per CSV import

# Columns omitted from the Excel workbook export. The .sqlite3 backup keeps
# everything -- a backup you cannot restore logins from is not a backup.
EXPORT_EXCLUDED_COLUMNS = {
    'personnel': {'password_hash'},
}
EXCEL_MAX_DATA_ROWS = 1_048_575  # Excel's 1,048,576 sheet rows, minus the header
INVALID_SHEET_NAME_CHARS = '[]:*?/\\'  # characters Excel forbids in a worksheet name

db = SQLAlchemy(app)
# Every POST needs a token: forms carry csrf_token, fetch() sends the X-CSRFToken header
csrf = CSRFProtect(app)

def ensure_personnel_role(person, role_name):
    """Ensure a person has a specific role assigned"""
    if person.roles:
        current_roles = [role.strip().lower() for role in person.roles.split(',')]
        if role_name.lower() not in current_roles:
            person.roles = f"{person.roles}, {role_name}"
    else:
        person.roles = role_name

AUDIT_FREQUENCIES = ['Quarterly', 'Semiannual', 'Annual - ACR', 'Annual - TJC', 'Annual - ME']

def _int_or_none(val):
    """int(val), or None for blanks and anything that is not a whole number."""
    try:
        return int(str(val).strip()) if val not in (None, '') else None
    except (ValueError, TypeError):
        return None

def _redirect_to_equipment(eq_id, params):
    """Redirect to an equipment detail page, carrying the list filters in `params`
    (request.args or request.form) so Back returns to the same filtered list."""
    keep = {k: v for k, v in params.items() if k not in ('eq_id', 'redirect_to', 'csrf_token')}
    return redirect(url_for('equipment_detail', eq_id=eq_id, **keep))

# Tests whose date starts the audit clock for the next due date
DUE_DATE_TEST_TYPES = ('Acceptance', 'Annual')

def prime_last_tested_dates(equipment_list):
    """Load the last acceptance/annual test date for every item in one grouped query."""
    latest = dict(db.session.query(ComplianceTest.eq_id, func.max(ComplianceTest.test_date))
                  .filter(ComplianceTest.test_type.in_(DUE_DATE_TEST_TYPES))
                  .group_by(ComplianceTest.eq_id).all())
    for equipment in equipment_list:
        equipment._last_tested_date = latest.get(equipment.eq_id)
    return equipment_list

def _active_capital_categories():
    """Active capital categories by min_cost, loaded once per request."""
    if has_request_context():
        if not hasattr(request, '_capital_categories'):
            request._capital_categories = (CapitalCategory.query.filter_by(is_active=True)
                                           .order_by(CapitalCategory.min_cost).all())
        return request._capital_categories
    return CapitalCategory.query.filter_by(is_active=True).order_by(CapitalCategory.min_cost).all()

# Related rows shown on equipment pages; batch-loaded instead of one query per row
EQUIPMENT_RELATIONSHIPS = ('equipment_class', 'equipment_subclass', 'manufacturer', 'department',
                           'facility', 'contact', 'supervisor', 'physician')

def _active_lookups():
    """Active values of each equipment lookup table, by name."""
    lookups = {'classes': EquipmentClass, 'subclasses': EquipmentSubclass, 'manufacturers': Manufacturer,
               'departments': Department, 'facilities': Facility}
    return {key: model.query.filter_by(is_active=True).order_by(model.name).all() for key, model in lookups.items()}

def _filter_option_names():
    """Names for the list pages' filter dropdowns, as template keyword arguments."""
    return {key: [obj.name for obj in objs] for key, objs in _active_lookups().items()}

def _paginate(items, page, per_page, default_per_page):
    """Page a query, or a list already sorted in Python. show_all=true puts everything on one page."""
    page = max(page, 1)
    per_page = min(per_page, 1000) if per_page >= 1 else default_per_page
    if request.args.get('show_all') == 'true':
        return MockPagination.show_all(items if isinstance(items, list) else items.all())
    if isinstance(items, list):
        return MockPagination.paginate(items[(page - 1) * per_page:page * per_page],
                                       page=page, per_page=per_page, total=len(items))
    return items.paginate(page=page, per_page=per_page, error_out=False, max_per_page=1000)

def _dropdown_options(model, keep_id=None, condition=None):
    """Active rows (matching `condition`), plus the row a record has assigned now (`keep_id`)
    even if since deactivated, so saving a form never silently clears an existing assignment."""
    shown = model.is_active == True
    if condition is not None:
        shown = and_(shown, condition)
    if keep_id:
        shown = or_(shown, model.id == keep_id)
    return model.query.filter(shown).order_by(model.name).all()

def _option_label(obj):
    return obj.name if obj.is_active else f'{obj.name} (inactive)'

def _equipment_choices(equipment=None):
    """Dropdown options for equipment forms: active lookup values and personnel by role,
    plus whatever `equipment` has assigned now."""
    sources = {'classes': (EquipmentClass, None), 'subclasses': (EquipmentSubclass, None),
               'manufacturers': (Manufacturer, None), 'departments': (Department, None),
               'facilities': (Facility, None), 'contacts': (Personnel, 'contact'),
               'supervisors': (Personnel, 'supervisor'), 'physicians': (Personnel, 'physician')}
    choices = {}
    for field, (key, _) in EQUIPMENT_FORM_CHOICES.items():
        model, role = sources[key]
        condition = Personnel.roles.ilike(f'%{role}%') if role else None
        choices[key] = _dropdown_options(model, getattr(equipment, field, None), condition)
    return choices

# EquipmentForm field -> (_equipment_choices key, placeholder label)
EQUIPMENT_FORM_CHOICES = {
    'class_id': ('classes', 'Select Class'), 'subclass_id': ('subclasses', 'Select Subclass'),
    'manufacturer_id': ('manufacturers', 'Select Manufacturer'), 'department_id': ('departments', 'Select Department'),
    'facility_id': ('facilities', 'Select Facility'), 'contact_id': ('contacts', 'Select Contact'),
    'supervisor_id': ('supervisors', 'Select Supervisor'), 'physician_id': ('physicians', 'Select Physician'),
}

def _apply_equipment_rules(equipment):
    """Derived fields, applied by every path that saves equipment (forms, inline edits, import)."""
    if equipment.eq_retired and not equipment.eq_retdate:
        equipment.eq_retdate = datetime.now().date()  # retired with no date means retired today
    equipment.eq_mefacreg = _generate_mefacreg(equipment.eq_mefac, equipment.eq_mereg)

def _save_equipment_form(form, equipment):
    form.populate_obj(equipment)
    # The form gives a list of audit frequencies; they are stored comma-separated
    equipment.eq_auditfreq = ', '.join(equipment.eq_auditfreq or []) or None
    # Select fields submit '' for "none"; store NULL instead
    for field in EQUIPMENT_FORM_CHOICES:
        setattr(equipment, field, getattr(equipment, field) or None)
    _apply_equipment_rules(equipment)

def _set_equipment_form_choices(form, equipment=None):
    choices = _equipment_choices(equipment)
    for field, (key, placeholder) in EQUIPMENT_FORM_CHOICES.items():
        getattr(form, field).choices = [('', placeholder)] + [(str(o.id), _option_label(o)) for o in choices[key]]

def _join_equipment_lookups(query):
    """Outer-join each equipment lookup table exactly once, so filters and search
    can reference any of them without joining the same table twice."""
    return (query
            .outerjoin(EquipmentClass, Equipment.class_id == EquipmentClass.id)
            .outerjoin(EquipmentSubclass, Equipment.subclass_id == EquipmentSubclass.id)
            .outerjoin(Manufacturer, Equipment.manufacturer_id == Manufacturer.id)
            .outerjoin(Department, Equipment.department_id == Department.id)
            .outerjoin(Facility, Equipment.facility_id == Facility.id))

def _equipment_search_columns():
    """Columns the free-text search box matches against, on every equipment page."""
    return [
        EquipmentClass.name, EquipmentSubclass.name, Manufacturer.name, Department.name,
        Facility.name, Facility.facility_full, Equipment.eq_mod, Equipment.eq_rm,
        Equipment.eq_assetid, Equipment.eq_sn, Equipment.eq_mefac, Equipment.eq_mereg,
        Equipment.eq_mefacreg, Equipment.eq_manid, Equipment.eq_acrsite, Equipment.eq_acrunit,
        Equipment.eq_notes,
    ]

# Per-page defaults for the include/exclude toggles. A toggle missing from the
# query string takes its page's default; the capital page's JavaScript writes
# 'false' explicitly so its default-on toggles can be switched off.
_EQUIPMENT_VIEWS = {
    'list': {'include_planned': 'false'},
    'capital': {'include_planned': 'true', 'radiology_owned': 'true', 'replacement_funded': 'false'},
    'compliance': {},
    'all': {},
}

def _filtered_equipment_query(args, view='list', query=None):
    """Equipment query with the filters shared by the list, capital, compliance,
    and export pages applied from `args` (request.args).

    view='compliance' is fixed to active, covered, installed equipment; view='all'
    applies no status filters; the other views honor the include_* toggles. Pass `query` to filter something joined to
    Equipment (e.g. ComplianceTest.query.join(Equipment)).
    """
    defaults = _EQUIPMENT_VIEWS[view]
    toggle = lambda name, default='false': args.get(name, defaults.get(name, default)) == 'true'
    if query is None:
        query = Equipment.query.options(
            *[selectinload(getattr(Equipment, rel)) for rel in EQUIPMENT_RELATIONSHIPS])
    query = _join_equipment_lookups(query)

    search = (args.get('search') or '').strip()
    if search:
        term = f'%{search}%'
        query = query.filter(or_(*[col.ilike(term) for col in _equipment_search_columns()]))

    for param, column in (('eq_class', EquipmentClass.name), ('eq_subclass', EquipmentSubclass.name),
                          ('eq_manu', Manufacturer.name), ('eq_dept', Department.name),
                          ('eq_fac', Facility.name)):
        value = (args.get(param) or '').strip()
        if value:
            query = query.filter(column == value)

    if view == 'all':
        return query
    not_planned = or_(Equipment.eq_planned == False, Equipment.eq_planned.is_(None))
    if view == 'compliance' or not toggle('include_retired'):
        query = query.filter(and_(
            Equipment.eq_retired == False,
            or_(Equipment.eq_retdate.is_(None), Equipment.eq_retdate > date.today()),
        ))
    if view == 'compliance' or not toggle('include_noncovered'):
        query = query.filter(Equipment.eq_physcov == True)
    if view == 'compliance' or not toggle('include_planned'):
        query = query.filter(not_planned)

    if view == 'capital':
        if toggle('radiology_owned'):
            query = query.filter(Equipment.eq_radcap == 1)
        if not toggle('replacement_funded'):
            query = query.filter(or_(Equipment.eq_capfund == 0, Equipment.eq_capfund.is_(None)))
    return query

CSV_FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')

def _csv_safe(value):
    """Export-side: prefix text that spreadsheet apps would run as a formula with
    a quote, so it opens as plain text. _csv_str removes the quote on import."""
    if isinstance(value, str) and value.startswith(CSV_FORMULA_PREFIXES):
        return "'" + value
    return value

def _csv_cell(value):
    """Format one exported value: blank for None, TRUE/FALSE, ISO dates, formula-safe text."""
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(value, date):
        return value.isoformat()
    return _csv_safe(value)

def _csv_download(name, headers, rows, timestamped=True):
    """CSV attachment named `name`_<timestamp>.csv (or `name`.csv)."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows([_csv_cell(v) for v in row] for row in rows)
    suffix = datetime.now().strftime('_%Y%m%d_%H%M%S') if timestamped else ''
    return Response(output.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename={name}{suffix}.csv'})

def _csv_str(val):
    """Stripped string for a CSV cell; '' for blanks. Undoes _csv_safe's quote."""
    if val is None or (not isinstance(val, str) and pd.isna(val)):
        return ''
    cell = str(val).strip()
    if len(cell) > 1 and cell[0] == "'" and cell[1] in '=+-@':
        cell = cell[1:]
    return cell

def _read_csv_upload(file):
    """Read an uploaded CSV with every cell as a stripped string ('' when blank).

    Reading as text keeps values like room '101' and serial '00123' intact (pandas
    would otherwise guess numbers and store 101.0 / 123.0). utf-8-sig drops the
    byte-order mark Excel adds, which would otherwise rename the first column.
    """
    df = pd.read_csv(file, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    df.columns = [str(c).strip() for c in df.columns]
    return df.apply(lambda col: col.map(_csv_str))

def get_or_create_personnel(contact_id, contact_name, contact_email, role_name):
    """Get existing personnel by ID or create new personnel with role assignment"""
    contact = None

    if contact_id and str(contact_id).strip() and not pd.isna(contact_id):
        try:
            contact = db.session.get(Personnel, int(contact_id))
        except (ValueError, TypeError):
            pass

    # Check for NaN before converting to string to avoid creating "nan" personnel
    if not contact and contact_name and not pd.isna(contact_name):
        contact_name = str(contact_name).strip()
        if contact_name:  # Ensure it's not an empty string after stripping
            contact_email = str(contact_email).strip() if (contact_email and not pd.isna(contact_email)) else None

            contact = Personnel.query.filter_by(name=contact_name).first()

            if not contact:
                if not contact_email:
                    return None  # caller reports it; email is required for a new person
                contact = Personnel(
                    name=contact_name,
                    email=contact_email,
                    roles=role_name,
                    is_active=True,
                    login_required=False
                )
                db.session.add(contact)
                db.session.flush()
            else:
                # Ensure role is assigned (don't update email from equipment import)
                ensure_personnel_role(contact, role_name)

    return contact

LEGACY_TEST_TYPES = {
    'acceptance': 'Acceptance', 'annual': 'Annual', 'audit': 'Audit', 'other': 'Other',
    'qc_review': 'QC Review', 'retire': 'Retire', 'shielding_design': 'Shielding Design',
    'submission': 'Submission',
}

def check_and_migrate_db():
    """Apply incremental schema migrations to existing databases."""
    inspector = inspect(db.engine)

    equipment_cols = {c['name'] for c in inspector.get_columns('equipment')}
    personnel_cols = {c['name'] for c in inspector.get_columns('personnel')}
    facility_cols = {c['name'] for c in inspector.get_columns('facilities')}

    with db.engine.begin() as conn:
        # Drop eq_servlogin and eq_servpwd — service credentials must not be stored in the app DB.
        # Drop eq_address, eq_eeoldate, eq_capcat, eq_capecst — never shown; the facility address,
        # estimated EOL, capital category, and estimated cost are all derived instead.
        for col in ('eq_servlogin', 'eq_servpwd', 'eq_address', 'eq_eeoldate', 'eq_capcat', 'eq_capecst'):
            if col in equipment_cols:
                conn.execute(text(f'ALTER TABLE equipment DROP COLUMN {col}'))
                logger.info("Migration: dropped column equipment.%s", col)

        # Add must_change_password to personnel (added in v1.1.0)
        if 'must_change_password' not in personnel_cols:
            conn.execute(text('ALTER TABLE personnel ADD COLUMN must_change_password BOOLEAN DEFAULT 0'))
            logger.info("Migration: added column personnel.must_change_password")

        # Add last_login to personnel (added in v1.1.0)
        if 'last_login' not in personnel_cols:
            conn.execute(text('ALTER TABLE personnel ADD COLUMN last_login DATETIME'))
            logger.info("Migration: added column personnel.last_login")

        # Add facility_full to facilities — full name for reports; name stays the short display name
        if 'facility_full' not in facility_cols:
            conn.execute(text('ALTER TABLE facilities ADD COLUMN facility_full VARCHAR(300)'))
            logger.info("Migration: added column facilities.facility_full")

        # Normalize test types from the old lowercase codes to the names the form uses
        for old, new in LEGACY_TEST_TYPES.items():
            result = conn.execute(text('UPDATE compliance_tests SET test_type = :new WHERE test_type = :old'),
                                  {'new': new, 'old': old})
            if result.rowcount:
                logger.info("Migration: renamed %d compliance tests from %r to %r", result.rowcount, old, new)

        # 'admin' is no longer a role; admin rights come only from personnel.is_admin
        rows = conn.execute(text("SELECT id, roles FROM personnel WHERE roles LIKE '%admin%'")).all()
        for person_id, roles in rows:
            kept = [r.strip() for r in roles.split(',') if r.strip() and r.strip().lower() != 'admin']
            conn.execute(text('UPDATE personnel SET roles = :roles WHERE id = :id'),
                         {'roles': ', '.join(kept), 'id': person_id})
        if rows:
            logger.info("Migration: removed the 'admin' role from %d personnel records", len(rows))


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    # Checked on every request, so deactivating someone or turning off their login
    # access also ends any session they already have open.
    user = db.session.get(Personnel, int(user_id))
    return user if user and user.can_log_in else None

# Database Models

class Equipment(db.Model):
    __tablename__ = 'equipment'

    eq_id = db.Column(db.Integer, primary_key=True)

    # Foreign Key Relationships
    class_id = db.Column(db.Integer, db.ForeignKey('equipment_classes.id'), nullable=False)
    subclass_id = db.Column(db.Integer, db.ForeignKey('equipment_subclasses.id'), nullable=True)
    manufacturer_id = db.Column(db.Integer, db.ForeignKey('manufacturers.id'), nullable=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    facility_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)

    # Personnel Foreign Keys
    contact_id = db.Column(db.Integer, db.ForeignKey('personnel.id'), nullable=True)
    supervisor_id = db.Column(db.Integer, db.ForeignKey('personnel.id'), nullable=True)
    physician_id = db.Column(db.Integer, db.ForeignKey('personnel.id'), nullable=True)

    # Equipment Details
    eq_mod = db.Column(db.String(200))
    eq_rm = db.Column(db.String(100))
    eq_phone = db.Column(db.String(20))

    # Asset Information
    eq_assetid = db.Column(db.String(100))
    eq_sn = db.Column(db.String(200))
    eq_mefac = db.Column(db.String(100))
    eq_mereg = db.Column(db.String(100))
    eq_mefacreg = db.Column(db.String(100))
    eq_manid = db.Column(db.String(100))

    # Important Dates
    eq_mandt = db.Column(db.Date)
    eq_rfrbdt = db.Column(db.Date)  # Refurbish Date
    eq_instdt = db.Column(db.Date)
    eq_eoldate = db.Column(db.Date)  # Estimated EOL is calculated: get_estimated_eol_date()
    eq_retdate = db.Column(db.Date)
    eq_retired = db.Column(db.Boolean, default=False)
    eq_planned = db.Column(db.Boolean, default=False)  # Planned equipment not yet installed

    # Compliance Information
    eq_physcov = db.Column(db.Boolean, default=True)  # Physics Coverage - default True for existing equipment
    eq_auditfreq = db.Column(db.String(200), default='Annual - TJC')  # Comma-separated list of frequencies
    eq_acrsite = db.Column(db.String(100))
    eq_acrunit = db.Column(db.String(100))

    # Technical Specifications / Capital Information
    eq_radcap = db.Column(db.Integer)  # Radiology Owned: 1=Yes, 0=No, NULL=N/A
    eq_capfund = db.Column(db.Integer)  # Replacement Funded: 1=Yes, 0=No, NULL=N/A
    eq_capcst = db.Column(db.Integer)  # Capital Cost (in thousands)
    eq_capyr = db.Column(db.Integer)  # Capital Year (4-digit year)
    eq_captype = db.Column(db.String(20), default='Replacement')  # Capital Type: Replacement or Upgrade
    eq_capnote = db.Column(db.String(140))  # Capital notes (max 140 chars)

    # Notes
    eq_notes = db.Column(db.Text)

    # Metadata
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    compliance_tests = db.relationship('ComplianceTest', backref='equipment', lazy=True, cascade='all, delete-orphan')

    # Foreign Key Relationships
    equipment_class = db.relationship('EquipmentClass', backref='equipment')
    equipment_subclass = db.relationship('EquipmentSubclass', backref='equipment')
    manufacturer = db.relationship('Manufacturer', backref='equipment')
    department = db.relationship('Department', backref='equipment')
    facility = db.relationship('Facility', backref='equipment')

    # Personnel Relationships (multiple foreign keys to same table)
    contact = db.relationship('Personnel', foreign_keys=[contact_id], backref='contact_equipment')
    supervisor = db.relationship('Personnel', foreign_keys=[supervisor_id], backref='supervised_equipment')
    physician = db.relationship('Personnel', foreign_keys=[physician_id], backref='physician_equipment')

    def __repr__(self):
        class_name = self.equipment_class.name if self.equipment_class else 'Unknown Class'
        manu_name = self.manufacturer.name if self.manufacturer else 'Unknown Manufacturer'
        return f'<Equipment {self.eq_id}: {class_name} - {manu_name} {self.eq_mod}>'

    def get_next_due_date(self):
        """Get the next due date based on the most recent acceptance or annual test.
        If multiple audit frequencies are set, returns the earliest due date."""

        test_date = self.get_last_tested_date()
        if not test_date or not self.eq_auditfreq:
            # No acceptance or annual test found, or no audit frequency set
            return None

        due_dates = []
        for freq in (f.strip() for f in self.eq_auditfreq.split(',')):
            if freq == 'Quarterly':
                # End of month 3 months from test date
                next_month = test_date + relativedelta(months=3)
                due_dates.append(next_month.replace(day=calendar.monthrange(next_month.year, next_month.month)[1]))
            elif freq == 'Semiannual':
                # End of month 6 months from test date
                next_month = test_date + relativedelta(months=6)
                due_dates.append(next_month.replace(day=calendar.monthrange(next_month.year, next_month.month)[1]))
            elif freq == 'Annual - ACR':
                # 1 year + 2 months from test date
                due_dates.append(test_date + relativedelta(months=14))
            elif freq == 'Annual - TJC':
                # 1 year + 30 days from test date
                due_dates.append(test_date + relativedelta(years=1) + timedelta(days=30))
            elif freq == 'Annual - ME':
                # End of next calendar year
                due_dates.append(date(test_date.year + 1, 12, 31))

        return min(due_dates) if due_dates else None

    def get_last_tested_date(self):
        """Date of the most recent acceptance or annual test.

        Cached on the instance (cleared whenever SQLAlchemy expires it, e.g. on
        commit). prime_last_tested_dates() fills the cache for a whole list in one
        query, so pages that show many rows do not run a query per row.
        """
        if '_last_tested_date' not in self.__dict__:
            self._last_tested_date = db.session.query(func.max(ComplianceTest.test_date)).filter(
                ComplianceTest.eq_id == self.eq_id,
                ComplianceTest.test_type.in_(DUE_DATE_TEST_TYPES),
            ).scalar()
        return self._last_tested_date

    def get_estimated_cost(self):
        """Get estimated capital cost from subclass (dynamic)"""
        if self.equipment_subclass:
            return self.equipment_subclass.estimated_capital_cost
        return None

    def get_display_cost(self):
        """Get display cost - actual if available, otherwise estimated"""
        if self.eq_capcst:
            return self.eq_capcst
        return self.get_estimated_cost()

    def get_capital_category(self):
        """Calculate capital category dynamically based on costs"""
        cost = self.get_display_cost()
        if not cost:
            return None

        for category in _active_capital_categories():
            if category.max_cost is None:
                if cost >= category.min_cost:
                    return category
            else:
                if category.min_cost <= cost <= category.max_cost:
                    return category
        return None

    def get_estimated_eol_date(self):
        """Calculate estimated end of life date from subclass expected lifetime"""
        if not self.equipment_subclass or not self.equipment_subclass.expected_lifetime:
            return None

        # Get the latest date from manufacture, install, or refurbish
        latest_date = None
        if self.eq_rfrbdt:
            latest_date = self.eq_rfrbdt
        if self.eq_instdt and (not latest_date or self.eq_instdt > latest_date):
            latest_date = self.eq_instdt
        if self.eq_mandt and (not latest_date or self.eq_mandt > latest_date):
            latest_date = self.eq_mandt

        if not latest_date:
            return None

        return latest_date + relativedelta(years=self.equipment_subclass.expected_lifetime)

@event.listens_for(Equipment, 'expire')
@event.listens_for(Equipment, 'refresh')
def _clear_last_tested_cache(target, *args):
    target.__dict__.pop('_last_tested_date', None)

class Personnel(UserMixin, db.Model):
    __tablename__ = 'personnel'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=False, unique=True)
    phone = db.Column(db.String(50))
    roles = db.Column(db.String(500))  # Comma-separated roles

    # Authentication fields
    username = db.Column(db.String(80), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)
    login_required = db.Column(db.Boolean, default=False)  # True if this person needs login access
    must_change_password = db.Column(db.Boolean, default=False)  # True forces password change on next login
    last_login = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<Personnel {self.id}: {self.name}>'

    def get_roles_list(self):
        """Return roles as a list"""
        if self.roles and self.roles.strip():
            return [role.strip() for role in self.roles.split(',') if role.strip()]
        return []

    def set_roles_list(self, roles_list):
        """Set roles from a list"""
        if roles_list is not None and len(roles_list) > 0:
            clean_roles = [role.strip() for role in roles_list if role and role.strip()]
            self.roles = ', '.join(clean_roles) if clean_roles else ''
        else:
            self.roles = ''

    def set_password(self, password):
        """Set password hash"""
        if password:
            self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Check password against hash"""
        if self.password_hash:
            return check_password_hash(self.password_hash, password)
        return False

    @property
    def can_log_in(self):
        """Login needs an active person, with login access turned on and credentials set."""
        return bool(self.is_active and self.login_required and self.username and self.password_hash)

    def has_role(self, role):
        """Check if user has a specific role"""
        return role in self.get_roles_list() or self.is_admin

    def can_manage_equipment(self):
        """Check if user can create/edit/delete equipment"""
        return self.is_admin or self.has_role('physicist') or self.has_role('physics_assistant')

    def can_manage_compliance(self):
        """Check if user can create/edit/delete compliance tests"""
        return self.is_admin or self.has_role('physicist') or self.has_role('physics_assistant')

    def can_manage_personnel(self):
        """Check if user can create/edit/delete personnel records"""
        return self.is_admin or self.has_role('physicist') or self.has_role('physics_assistant')

    def can_view_equipment(self):
        """Check if user can view equipment"""
        return True  # All authenticated users can view equipment

    def can_view_personnel(self):
        """Check if user can view personnel records"""
        return True  # All authenticated users can view personnel

    def can_view_compliance(self):
        """Check if user can view compliance tests"""
        return True  # All authenticated users can view compliance tests

class ComplianceTest(db.Model):
    __tablename__ = 'compliance_tests'

    test_id = db.Column(db.Integer, primary_key=True)
    eq_id = db.Column(db.Integer, db.ForeignKey('equipment.eq_id'), nullable=False)
    test_type = db.Column(db.String(100), nullable=False)
    test_date = db.Column(db.Date, nullable=False)
    report_date = db.Column(db.Date, nullable=True)
    submission_date = db.Column(db.Date, nullable=True)
    performed_by_id = db.Column(db.Integer, db.ForeignKey('personnel.id'))
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('personnel.id'))
    notes = db.Column(db.Text)

    # Audit fields
    created_by = db.Column(db.String(10))  # Personnel initials
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    modified_by = db.Column(db.String(10))  # Personnel initials
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    performed_by = db.relationship('Personnel', foreign_keys=[performed_by_id], backref='tests_performed')
    reviewed_by = db.relationship('Personnel', foreign_keys=[reviewed_by_id], backref='tests_reviewed')

    def get_status(self):
        """Calculate status based on test date"""
        if self.test_date > datetime.now().date():
            return 'Scheduled'
        else:
            return 'Completed'

    def __repr__(self):
        return f'<ComplianceTest {self.test_id}: {self.test_type} for Equipment {self.eq_id}>'

class ScheduledTest(db.Model):
    __tablename__ = 'scheduled_tests'

    schedule_id = db.Column(db.Integer, primary_key=True)
    eq_id = db.Column(db.Integer, db.ForeignKey('equipment.eq_id'), nullable=False)
    scheduled_date = db.Column(db.Date, nullable=False)
    scheduling_date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text)

    # Audit fields
    created_by_id = db.Column(db.Integer, db.ForeignKey('personnel.id'))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    modified_by_id = db.Column(db.Integer, db.ForeignKey('personnel.id'))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    equipment = db.relationship('Equipment', backref='scheduled_tests')
    created_by = db.relationship('Personnel', foreign_keys=[created_by_id], backref='schedules_created')
    modified_by = db.relationship('Personnel', foreign_keys=[modified_by_id], backref='schedules_modified')

    def __repr__(self):
        return f'<ScheduledTest {self.schedule_id}: Equipment {self.eq_id} scheduled for {self.scheduled_date}>'

# Standardized Options Models
class EquipmentClass(db.Model):
    __tablename__ = 'equipment_classes'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<EquipmentClass {self.id}: {self.name}>'

class EquipmentSubclass(db.Model):
    __tablename__ = 'equipment_subclasses'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('equipment_classes.id'), nullable=False)
    estimated_capital_cost = db.Column(db.Integer)  # Estimated capital cost in thousands
    expected_lifetime = db.Column(db.Integer)  # Expected lifetime in years
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    equipment_class = db.relationship('EquipmentClass', backref='subclasses')

    def __repr__(self):
        return f'<EquipmentSubclass {self.id}: {self.name}>'

class Department(db.Model):
    __tablename__ = 'departments'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<Department {self.id}: {self.name}>'

class Facility(db.Model):
    __tablename__ = 'facilities'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    facility_full = db.Column(db.String(300))
    address = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<Facility {self.id}: {self.name}>'

class Manufacturer(db.Model):
    __tablename__ = 'manufacturers'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<Manufacturer {self.id}: {self.name}>'

class CapitalCategory(db.Model):
    __tablename__ = 'capital_categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    min_cost = db.Column(db.Integer, nullable=False)  # In thousands
    max_cost = db.Column(db.Integer)  # In thousands, NULL means unlimited
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<CapitalCategory {self.id}: {self.name}>'

    def cost_range_display(self):
        """Return formatted cost range for display"""
        min_display = f"${self.min_cost * 1000:,}"
        if self.max_cost:
            max_display = f"${self.max_cost * 1000:,}"
            return f"{min_display} - {max_display}"
        else:
            return f"{min_display}+"

# Forms
class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])


class EquipmentForm(FlaskForm):
    class_id = SelectField('Equipment Class', choices=[], validators=[DataRequired()])
    subclass_id = SelectField('Subclass', choices=[], validators=[Optional()])
    manufacturer_id = SelectField('Manufacturer', choices=[], validators=[Optional()])
    eq_mod = StringField('Model', validators=[Optional(), Length(max=200)])
    department_id = SelectField('Department', choices=[], validators=[Optional()])
    eq_rm = StringField('Room', validators=[Optional(), Length(max=100)])
    eq_phone = StringField('Phone', validators=[Optional(), Length(max=20)])
    facility_id = SelectField('Facility', choices=[], validators=[Optional()])
    contact_id = SelectField('Contact Person', choices=[], validators=[Optional()])
    supervisor_id = SelectField('Supervisor', choices=[], validators=[Optional()])
    physician_id = SelectField('Physician', choices=[], validators=[Optional()])
    eq_assetid = StringField('Asset ID', validators=[Optional(), Length(max=100)])
    eq_sn = StringField('Serial Number', validators=[Optional(), Length(max=200)])
    eq_mefac = StringField('ME Facility', validators=[Optional(), Length(max=100)])
    eq_mereg = StringField('ME Registration', validators=[Optional(), Length(max=100)])
    eq_mefacreg = StringField('ME Facility Registration', validators=[Optional(), Length(max=100)])
    eq_manid = StringField('Manufacturer ID', validators=[Optional(), Length(max=100)])
    eq_mandt = DateField('Manufacture Date', validators=[Optional()])
    eq_rfrbdt = DateField('Refurbish Date', validators=[Optional()])
    eq_instdt = DateField('Installation Date', validators=[Optional()])
    eq_eoldate = DateField('End of Life Date', validators=[Optional()])
    eq_retdate = DateField('Retirement Date', validators=[Optional()])
    eq_retired = BooleanField('Retired')
    eq_planned = BooleanField('Planned (not yet installed)')
    eq_physcov = BooleanField('Physics Coverage', default=True)
    eq_auditfreq = SelectMultipleField('Audit Frequencies', choices=[
        ('Quarterly', 'Quarterly'),
        ('Semiannual', 'Semiannual'),
        ('Annual - ACR', 'Annual - ACR'),
        ('Annual - TJC', 'Annual - TJC'),
        ('Annual - ME', 'Annual - ME')
    ], validators=[Optional()])
    eq_acrsite = StringField('ACR Site', validators=[Optional(), Length(max=100)])
    eq_acrunit = StringField('ACR Unit', validators=[Optional(), Length(max=100)])
    eq_radcap = SelectField('Radiology Owned', choices=[
        ('', 'N/A'),
        ('0', 'No'),
        ('1', 'Yes')
    ], validators=[Optional()], coerce=lambda x: int(x) if x and x != '' else None)
    eq_capfund = SelectField('Replacement Funded', choices=[
        ('', 'N/A'),
        ('0', 'No'),
        ('1', 'Yes')
    ], validators=[Optional()], coerce=lambda x: int(x) if x and x != '' else None)
    eq_capcst = IntegerField('Capital Cost (thousands $)', validators=[Optional()])
    eq_capyr = IntegerField('Capital Year', validators=[Optional(), NumberRange(min=1900, max=2100, message='Must be a 4-digit year')])
    eq_captype = SelectField('Capital Type', choices=[
        ('Replacement', 'Replacement'),
        ('Upgrade', 'Upgrade')
    ], validators=[Optional()], default='Replacement')
    eq_capnote = StringField('Capital Notes', validators=[Optional(), Length(max=140)])
    eq_notes = TextAreaField('Notes', validators=[Optional()])

COMPLIANCE_TEST_TYPES = ['Acceptance', 'Annual', 'Audit', 'Other', 'QC Review', 'Retire',
                         'Shielding Design', 'Submission']

class ComplianceTestForm(FlaskForm):
    test_type = SelectField('Test/Result/Event Type', choices=[(t, t) for t in COMPLIANCE_TEST_TYPES],
                            validators=[DataRequired()], default='Annual')
    test_date = DateField('Test Date', validators=[DataRequired()])
    report_date = DateField('Report Date', validators=[Optional()])
    submission_date = DateField('Submission Date', validators=[Optional()])
    performed_by_id = SelectField('Performed By', choices=[], validators=[Optional()], coerce=lambda x: int(x) if x else None)
    reviewed_by_id = SelectField('Reviewing Physicist', choices=[], validators=[Optional()], coerce=lambda x: int(x) if x else None)
    notes = TextAreaField('Comments', validators=[Optional()])

class ScheduleTestForm(FlaskForm):
    scheduled_date = DateField('Scheduled Test Date', validators=[DataRequired()])
    scheduling_date = DateField('Scheduling Date', validators=[DataRequired()], default=lambda: datetime.now().date())
    notes = TextAreaField('Notes', validators=[Optional()])

MIN_PASSWORD_LENGTH = 12

class PersonnelForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=200)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=200)])
    phone = StringField('Phone', validators=[Optional(), Length(max=50)])
    roles = SelectMultipleField('Roles', choices=[
        ('contact', 'Contact'),
        ('physician', 'Physician'),
        ('physicist', 'Physicist'),
        ('physics_assistant', 'Physics Assistant'),
        ('qa_technologist', 'QA Technologist'),
        ('supervisor', 'Supervisor')
    ], validators=[DataRequired()])
    login_required = BooleanField('Requires Login Access', default=False)
    username = StringField('Username', validators=[Optional(), Length(max=80)])
    password = PasswordField('Password', validators=[Optional(), Length(min=MIN_PASSWORD_LENGTH)])
    is_admin = BooleanField('Admin User')
    is_active = BooleanField('Active', default=True)

class CsvUploadForm(FlaskForm):
    csv_file = FileField('CSV File', validators=[DataRequired()])

class PasswordChangeForm(FlaskForm):
    current_password = PasswordField('Current Password', validators=[DataRequired()])
    new_password = PasswordField('New Password', validators=[DataRequired(), Length(min=MIN_PASSWORD_LENGTH)])
    confirm_password = PasswordField('Confirm New Password', validators=[
        DataRequired(),
        EqualTo('new_password', message='Passwords must match')
    ])
    submit = SubmitField('Change Password')

# Access Control Decorators
def admin_required(f):
    """Decorator for admin-only routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def manage_equipment_required(f):
    """Decorator for equipment management routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.can_manage_equipment():
            flash('Equipment management access required.', 'error')
            return redirect(url_for('equipment_list'))
        return f(*args, **kwargs)
    return decorated_function

def manage_compliance_required(f):
    """Decorator for compliance management routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.can_manage_compliance():
            flash('Compliance management access required.', 'error')
            return redirect(url_for('compliance_dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def manage_personnel_required(f):
    """Decorator for personnel management routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.can_manage_personnel():
            flash('Personnel management access required.', 'error')
            return redirect(url_for('personnel_list'))
        return f(*args, **kwargs)
    return decorated_function

# Enforce password change before any other action
@app.before_request
def enforce_password_change():
    if current_user.is_authenticated and getattr(current_user, 'must_change_password', False):
        allowed = {'change_password', 'logout', 'static'}
        if request.endpoint not in allowed:
            flash('You must set a new password before continuing.', 'warning')
            return redirect(url_for('change_password'))

def _is_safe_redirect(target):
    """True if `target` stays on this site (guards redirects built from user input)."""
    if not target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ('http', 'https') and ref.netloc == test.netloc

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    logger.warning("CSRF rejected path=%s ip=%s reason=%s", request.path, request.remote_addr, e.description)
    message = 'Your session expired or the form was out of date. Please try again.'
    if request.is_json:
        return jsonify({'success': False, 'message': message}), 400
    flash(message, 'error')
    back = request.referrer if _is_safe_redirect(request.referrer) else url_for('index')
    return redirect(back)

class LoginThrottle:
    """Sliding-window limit on failed logins per client IP.

    In memory, so it resets on restart and each gunicorn worker counts on its own
    (Render runs one). Keyed by IP rather than username so an attacker cannot lock
    a real user out of their account.
    """

    def __init__(self, max_failures=10, window_seconds=15 * 60):
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key, now):
        attempts = self._failures[key]
        while attempts and attempts[0] <= now - self.window:
            attempts.popleft()
        if not attempts:
            del self._failures[key]
        return attempts

    def retry_after(self, key):
        """Seconds until `key` may try again, or 0 if it is not blocked."""
        now = time.monotonic()
        with self._lock:
            attempts = self._prune(key, now)
            if len(attempts) < self.max_failures:
                return 0
            return int(attempts[0] + self.window - now) + 1

    def record_failure(self, key):
        with self._lock:
            self._failures[key].append(time.monotonic())

    def reset(self, key=None):
        with self._lock:
            if key is None:
                self._failures.clear()
            else:
                self._failures.pop(key, None)

login_throttle = LoginThrottle()

# Authentication Routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = LoginForm()
    if form.validate_on_submit():
        client_ip = request.remote_addr
        wait = login_throttle.retry_after(client_ip)
        if wait:
            logger.warning("AUTH login_throttled username=%s ip=%s", form.username.data, client_ip)
            flash(f'Too many failed login attempts. Try again in {wait // 60 + 1} minutes.', 'error')
            return render_template('login.html', form=form), 429

        user = Personnel.query.filter_by(username=form.username.data).first()
        if user and user.can_log_in and user.check_password(form.password.data):
            login_throttle.reset(client_ip)
            login_user(user)
            user.last_login = datetime.now(timezone.utc)
            db.session.commit()
            logger.info("AUTH login_success user=%s ip=%s", user.username, client_ip)

            next_page = request.args.get('next')
            if not _is_safe_redirect(next_page):
                next_page = url_for('index')
            return redirect(next_page)
        else:
            login_throttle.record_failure(client_ip)
            logger.warning("AUTH login_failed username=%s ip=%s", form.username.data, client_ip)
            flash('Invalid username or password.', 'error')

    return render_template('login.html', form=form)

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logger.info("AUTH logout user=%s ip=%s", current_user.username, request.remote_addr)
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = PasswordChangeForm()

    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash('Current password is incorrect.', 'error')
            return render_template('change_password.html', form=form)

        # Update password and clear any forced-change flag
        current_user.set_password(form.new_password.data)
        current_user.must_change_password = False

        try:
            db.session.commit()
            flash('Password changed successfully!', 'success')
            return redirect(url_for('index'))
        except sa_exc.SQLAlchemyError as e:
            db.session.rollback()
            logger.error("Error changing password for user %s: %s", current_user.username, e)
            flash('Error changing password. Please try again.', 'error')

    return render_template('change_password.html', form=form)

@app.cli.command('create-admin')
def create_admin_command():
    """One-time setup: create the initial admin account.

    Run once after first deployment:
        flask create-admin
    """
    import click
    with app.app_context():
        if Personnel.query.filter_by(is_admin=True).first():
            click.echo('An admin account already exists. Aborting.')
            return
        name = click.prompt('Full name')
        email = click.prompt('Email')
        username = click.prompt('Username')
        password = click.prompt('Password', hide_input=True, confirmation_prompt=True)
        while len(password) < MIN_PASSWORD_LENGTH:
            click.echo(f'Password must be at least {MIN_PASSWORD_LENGTH} characters.')
            password = click.prompt('Password', hide_input=True, confirmation_prompt=True)
        admin = Personnel(
            name=name,
            email=email,
            username=username,
            is_active=True,
            is_admin=True,
            login_required=True,
            must_change_password=False,
            roles=''
        )
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        click.echo(f'Admin account "{username}" created successfully.')

# Routes
@app.route('/')
@login_required
def index():
    today = datetime.now().date()

    # Active equipment: not retired, physics covered, and installed
    active_equipment = prime_last_tested_dates(_filtered_equipment_query({}, view='compliance').all())

    overdue_count = 0
    upcoming_count = 0
    compliant_count = 0
    no_frequency_count = 0

    for equipment in active_equipment:
        next_due = equipment.get_next_due_date()
        if next_due is None:
            # No test history or no frequency set
            no_frequency_count += 1
        elif next_due < today:
            overdue_count += 1
        elif next_due <= today + timedelta(days=90):
            upcoming_count += 1
        else:
            # Compliant (next due date is more than 90 days away)
            compliant_count += 1

    # Future scheduled tests for equipment that is not retired
    scheduled_tests_count = ScheduledTest.query.join(Equipment).filter(
        ScheduledTest.scheduled_date >= today,
        Equipment.eq_retired == False,
        or_(Equipment.eq_retdate.is_(None), Equipment.eq_retdate > today),
    ).count()

    return render_template('index.html',
                         overdue_count=overdue_count,
                         upcoming_count=upcoming_count,
                         compliant_count=compliant_count,
                         no_frequency_count=no_frequency_count,
                         scheduled_tests_count=scheduled_tests_count)

# Sort keys the list pages accept that are not Equipment column names
LOOKUP_SORT_COLUMNS = {
    'eq_class': EquipmentClass.name, 'eq_subclass': EquipmentSubclass.name, 'eq_manu': Manufacturer.name,
    'eq_dept': Department.name, 'eq_fac': Facility.name,
}

@app.route('/equipment')
@login_required
def equipment_list():
    today = datetime.now().date()
    query = _filtered_equipment_query(request.args, view='list')

    # Multi-level sort, e.g. ?sort=eq_class,eq_mod&order=asc,desc
    fields, orders = request.args.get('sort', 'eq_id').split(','), request.args.get('order', 'asc').split(',')
    sorts = [(f, orders[i] if i < len(orders) else 'asc') for i, f in enumerate(fields)]
    order_clauses = []
    for field, order in sorts:
        if field == 'days_until_due':
            continue  # calculated; sorted in Python below
        column = LOOKUP_SORT_COLUMNS.get(field)
        if column is None:
            column = Equipment.__table__.columns.get(field, Equipment.eq_id)
        order_clauses.append(column.desc() if order == 'desc' else column.asc())
    query = query.order_by(*order_clauses)

    days_order = next((order for field, order in sorts if field == 'days_until_due'), None)
    if days_order:
        def days_until_due(eq):
            if eq.eq_retired or (eq.eq_retdate and eq.eq_retdate <= today):
                return 9999  # retired last
            due = eq.get_next_due_date()
            return (due - today).days if due else 9998  # no due date just before retired
        # A stable sort keeps the database order among equal days
        items = sorted(prime_last_tested_dates(query.all()), key=days_until_due, reverse=days_order == 'desc')
    else:
        items = query
    equipment = _paginate(items, request.args.get('page', 1, type=int),
                          request.args.get('per_page', 20, type=int), default_per_page=25)

    prime_last_tested_dates(equipment.items)  # the table shows each row's next due date
    return render_template('equipment_list.html', equipment=equipment, today=today, **_filter_option_names())

@app.route('/equipment/new', methods=['GET', 'POST'])
@login_required
@manage_equipment_required
def equipment_new():
    form = EquipmentForm()
    if request.method == 'GET':
        form.eq_auditfreq.data = []  # new equipment starts with no audit frequencies
    _set_equipment_form_choices(form)

    if form.validate_on_submit():
        equipment = Equipment()
        _save_equipment_form(form, equipment)
        db.session.add(equipment)
        db.session.commit()
        flash('Equipment added successfully!', 'success')
        return redirect(url_for('equipment_list'))

    return render_template('equipment_form.html', form=form, title='Add New Equipment')

@app.route('/equipment/<int:eq_id>')
@login_required
def equipment_detail(eq_id):
    equipment = db.get_or_404(Equipment, eq_id)

    tests = ComplianceTest.query.filter_by(eq_id=eq_id).order_by(ComplianceTest.test_date.desc()).paginate(
        page=request.args.get('test_page', 1, type=int), per_page=request.args.get('test_per_page', 10, type=int),
        error_out=False, max_per_page=50)

    # The list filters ride along so Back returns to the same filtered list
    search_params = {k: request.args.get(k, '') for k in (
        'search', 'eq_class', 'eq_subclass', 'eq_manu', 'eq_dept', 'eq_fac', 'include_retired',
        'include_noncovered', 'include_planned', 'sort', 'order', 'page')}
    redirect_to = request.args.get('redirect_to', '')  # 'compliance' when opened from the dashboard

    today = datetime.now().date()
    is_retired = equipment.eq_retired or (equipment.eq_retdate and equipment.eq_retdate <= today)
    next_due_date = None if is_retired else equipment.get_next_due_date()
    next_test = SimpleNamespace(next_due_date=next_due_date) if next_due_date else None

    # Scheduled tests, except ones within 30 days after the last test (already done)
    last_tested = equipment.get_last_tested_date()
    scheduled_tests = [t for t in ScheduledTest.query.filter_by(eq_id=eq_id).order_by(ScheduledTest.scheduled_date)
                       if not last_tested or t.scheduled_date > last_tested + timedelta(days=30)]

    return render_template('equipment_detail.html', equipment=equipment, tests=tests, next_test=next_test, today=today, search_params=search_params, scheduled_tests=scheduled_tests, redirect_to=redirect_to)

@app.route('/equipment/<int:eq_id>/edit', methods=['GET', 'POST'])
@login_required
@manage_equipment_required
def equipment_edit(eq_id):
    equipment = db.get_or_404(Equipment, eq_id)

    if request.method == 'GET':
        # Select fields compare as strings, and audit frequencies are a list in the form
        form_data = {c.name: getattr(equipment, c.name) for c in equipment.__table__.columns}
        for field in ('eq_radcap', 'eq_capfund', *EQUIPMENT_FORM_CHOICES):
            value = form_data[field]
            form_data[field] = str(value) if value is not None else ''
        form_data['eq_auditfreq'] = [f.strip() for f in (equipment.eq_auditfreq or '').split(',') if f.strip()]
        form = EquipmentForm(data=form_data)
    else:
        form = EquipmentForm()
    _set_equipment_form_choices(form, equipment)

    if form.validate_on_submit():
        _save_equipment_form(form, equipment)
        db.session.commit()
        flash('Equipment updated successfully!', 'success')
        return _redirect_to_equipment(eq_id, request.args)
    for field_name, errors in form.errors.items():
        for error in errors:
            flash(f'Form validation error in {field_name}: {error}', 'error')

    return render_template('equipment_form.html', form=form, title='Edit Equipment', equipment=equipment)

@app.route('/api/equipment/<int:eq_id>/update-details', methods=['POST'])
@login_required
@manage_equipment_required
def update_equipment_details(eq_id):
    """AJAX endpoint to update equipment details card"""
    equipment = db.get_or_404(Equipment, eq_id)

    data = request.get_json(silent=True) or {}

    class_id = _int_or_none(data.get('class_id'))
    if class_id is None:
        return jsonify({'success': False, 'message': 'Equipment class is required.'}), 400

    equipment.class_id = class_id
    equipment.subclass_id = _int_or_none(data.get('subclass_id'))
    equipment.manufacturer_id = _int_or_none(data.get('manufacturer_id'))
    equipment.eq_mod = data.get('eq_mod', '')
    equipment.department_id = _int_or_none(data.get('department_id'))
    equipment.eq_rm = data.get('eq_rm', '')
    equipment.eq_phone = data.get('eq_phone', '')
    equipment.facility_id = _int_or_none(data.get('facility_id'))
    equipment.eq_assetid = data.get('eq_assetid', '')
    equipment.eq_sn = data.get('eq_sn', '')
    equipment.eq_mefac = data.get('eq_mefac', '')
    equipment.eq_mereg = data.get('eq_mereg', '')
    equipment.eq_manid = data.get('eq_manid', '')
    frequencies = [f.strip() for f in str(data.get('eq_auditfreq') or '').split(',')]
    equipment.eq_auditfreq = ', '.join(f for f in frequencies if f in AUDIT_FREQUENCIES) or None
    equipment.eq_acrsite = data.get('eq_acrsite', '')
    equipment.eq_acrunit = data.get('eq_acrunit', '')
    equipment.eq_notes = data.get('eq_notes', '')

    # Handle dates — input type="date" always sends YYYY-MM-DD
    def _parse_iso_date(val):
        if not val:
            return None
        try:
            return datetime.strptime(str(val).strip(), '%Y-%m-%d').date()
        except (ValueError, OverflowError) as exc:
            logger.warning("Invalid date value ignored: %r — %s", val, exc)
            return None

    equipment.eq_mandt = _parse_iso_date(data.get('eq_mandt'))
    equipment.eq_rfrbdt = _parse_iso_date(data.get('eq_rfrbdt'))
    equipment.eq_instdt = _parse_iso_date(data.get('eq_instdt'))
    equipment.eq_eoldate = _parse_iso_date(data.get('eq_eoldate'))
    equipment.eq_retdate = _parse_iso_date(data.get('eq_retdate'))

    equipment.eq_retired = data.get('eq_retired') == 'true' or data.get('eq_retired') == True
    equipment.eq_planned = data.get('eq_planned') == 'true' or data.get('eq_planned') == True
    equipment.eq_physcov = data.get('eq_physcov') == 'true' or data.get('eq_physcov') == True

    _apply_equipment_rules(equipment)

    db.session.commit()

    return jsonify({'success': True, 'message': 'Equipment details updated successfully'})

@app.route('/api/equipment/<int:eq_id>/update-capital', methods=['POST'])
@login_required
@manage_equipment_required
def update_capital_details(eq_id):
    """AJAX endpoint to update capital details card"""
    equipment = db.get_or_404(Equipment, eq_id)

    data = request.get_json(silent=True) or {}

    capyr = _int_or_none(data.get('eq_capyr'))
    if capyr is not None and not 1900 <= capyr <= 2100:
        return jsonify({'success': False, 'message': 'Capital year must be a 4-digit year.'}), 400

    equipment.eq_radcap = _int_or_none(data.get('eq_radcap'))
    equipment.eq_capfund = _int_or_none(data.get('eq_capfund'))
    equipment.eq_capcst = _int_or_none(data.get('eq_capcst'))
    equipment.eq_capyr = capyr
    if data.get('eq_captype') in ('Replacement', 'Upgrade'):
        equipment.eq_captype = data['eq_captype']
    equipment.eq_capnote = str(data.get('eq_capnote') or '')[:140] or None

    db.session.commit()

    return jsonify({'success': True, 'message': 'Capital details updated successfully'})

@app.route('/api/equipment/<int:eq_id>/update-contacts', methods=['POST'])
@login_required
@manage_equipment_required
def update_contact_info(eq_id):
    """AJAX endpoint to update contact information card"""
    equipment = db.get_or_404(Equipment, eq_id)

    data = request.get_json(silent=True) or {}

    equipment.contact_id = _int_or_none(data.get('contact_id'))
    equipment.supervisor_id = _int_or_none(data.get('supervisor_id'))
    equipment.physician_id = _int_or_none(data.get('physician_id'))

    db.session.commit()

    return jsonify({'success': True, 'message': 'Contact information updated successfully'})

@app.route('/api/equipment/<int:eq_id>/form-data', methods=['GET'])
@login_required
def get_equipment_form_data(eq_id):
    """AJAX endpoint to get dropdown choices and current values for edit forms"""
    equipment = db.get_or_404(Equipment, eq_id)

    choices = _equipment_choices(equipment)

    return jsonify({
        'equipment': {
            'eq_id': equipment.eq_id,
            'class_id': equipment.class_id,
            'subclass_id': equipment.subclass_id,
            'manufacturer_id': equipment.manufacturer_id,
            'eq_mod': equipment.eq_mod,
            'department_id': equipment.department_id,
            'eq_rm': equipment.eq_rm,
            'eq_phone': equipment.eq_phone,
            'facility_id': equipment.facility_id,
            'eq_assetid': equipment.eq_assetid,
            'eq_sn': equipment.eq_sn,
            'eq_mefac': equipment.eq_mefac,
            'eq_mereg': equipment.eq_mereg,
            'eq_manid': equipment.eq_manid,
            'eq_mandt': equipment.eq_mandt.strftime('%Y-%m-%d') if equipment.eq_mandt else '',
            'eq_rfrbdt': equipment.eq_rfrbdt.strftime('%Y-%m-%d') if equipment.eq_rfrbdt else '',
            'eq_instdt': equipment.eq_instdt.strftime('%Y-%m-%d') if equipment.eq_instdt else '',
            'eq_eoldate': equipment.eq_eoldate.strftime('%Y-%m-%d') if equipment.eq_eoldate else '',
            'eq_retdate': equipment.eq_retdate.strftime('%Y-%m-%d') if equipment.eq_retdate else '',
            'eq_retired': equipment.eq_retired,
            'eq_planned': equipment.eq_planned,
            'eq_physcov': equipment.eq_physcov,
            'eq_auditfreq': equipment.eq_auditfreq,
            'eq_acrsite': equipment.eq_acrsite,
            'eq_acrunit': equipment.eq_acrunit,
            'eq_notes': equipment.eq_notes,
            'eq_radcap': equipment.eq_radcap,
            'eq_capfund': equipment.eq_capfund,
            'eq_capcst': equipment.eq_capcst,
            'eq_capecst': equipment.get_estimated_cost(),
            'eq_capyr': equipment.eq_capyr,
            'eq_captype': equipment.eq_captype,
            'eq_capnote': equipment.eq_capnote,
            'contact_id': equipment.contact_id,
            'supervisor_id': equipment.supervisor_id,
            'physician_id': equipment.physician_id,
        },
        'choices': {
            **{key: [{'id': obj.id, 'name': _option_label(obj)} for obj in objs] for key, objs in choices.items()},
            'audit_frequencies': AUDIT_FREQUENCIES,
        }
    })

@app.route('/capital')
@login_required
def capital_planning():
    today = datetime.now().date()
    query = _filtered_equipment_query(request.args, view='capital')
    sort_param, order_param = request.args.get('sort', ''), request.args.get('order', '')
    sorts = list(zip(sort_param.split(','), order_param.split(','))) if sort_param and order_param else []

    # Days until EOL and cost are calculated, so those sorts run in Python (None = blank)
    def days_until_eol(eq):
        eol = eq.eq_eoldate or eq.get_estimated_eol_date()
        return (eol - today).days if eol else None
    calculated = {'years_until_eol': days_until_eol, 'eq_capcst': lambda eq: eq.get_display_cost() or None}
    if any(field in calculated for field, _ in sorts):
        items = query.all()
        for field, order in reversed(sorts):  # last key first, so the first key wins
            if field in calculated:
                value = calculated[field]
                items.sort(key=lambda eq, value=value: (value(eq) is None, value(eq) or 0),
                           reverse=order == 'desc')
    else:
        for field, order in sorts:
            column = LOOKUP_SORT_COLUMNS.get(field, Equipment.eq_rm if field == 'eq_rm' else None)
            if column is not None:
                query = query.order_by(desc(column) if order == 'desc' else column)
        items = query
    equipment = _paginate(items, request.args.get('page', 1, type=int),
                          request.args.get('per_page', 25, type=int), default_per_page=25)
    return render_template('capital_planning.html', equipment=equipment, today=today, **_filter_option_names())

@app.route('/capital/bubble')
@login_required
def capital_bubble():
    return render_template('capital_bubble.html')

@app.route('/capital/bubble-data')
@login_required
def capital_bubble_data():
    current_year = datetime.now().year
    equipment_list = _filtered_equipment_query(request.args, view='capital').all()

    points = []
    for eq in equipment_list:
        eol_date = eq.eq_eoldate or eq.get_estimated_eol_date()
        display_cost = eq.get_display_cost()
        if eol_date and display_cost:
            points.append({
                'category': eq.equipment_class.name if eq.equipment_class else 'Unknown',
                'year': max(eol_date.year, current_year),  # past-due units plot in the current year
                'cost': display_cost,
                'facility': eq.facility.name if eq.facility else 'Unknown',
                'room': eq.eq_rm or 'Unknown',
                'eolDate': eol_date.strftime('%Y-%m-%d'),
                'isEstimated': not eq.eq_eoldate,
            })

    return jsonify({'data': points})

@app.route('/compliance')
@login_required
def compliance_dashboard():
    today = datetime.now().date()
    overdue_tests = []
    upcoming_tests = []
    scheduled_tests = []

    eq_class = request.args.get('eq_class', '').strip()
    eq_subclass = request.args.get('eq_subclass', '').strip()
    eq_fac = request.args.get('eq_fac', '').strip()
    search = request.args.get('search', '').strip()

    try:
        days_ahead = int(request.args.get('days', 90))
        if days_ahead < 1:
            days_ahead = 90
    except (ValueError, TypeError):
        days_ahead = 90

    query = _filtered_equipment_query(request.args, view='compliance')

    active_equipment = query.all()

    classes = db.session.query(EquipmentClass.name).join(Equipment).filter(EquipmentClass.is_active == True).distinct().order_by(EquipmentClass.name).all()
    classes = [c[0] for c in classes if c[0]]

    subclasses = []
    if eq_class:
        subclasses = db.session.query(EquipmentSubclass.name).join(Equipment).join(EquipmentClass).filter(
            EquipmentClass.name.ilike(f'%{eq_class}%'),
            EquipmentSubclass.is_active == True
        ).distinct().order_by(EquipmentSubclass.name).all()
        subclasses = [s[0] for s in subclasses if s[0]]
    else:
        subclasses = db.session.query(EquipmentSubclass.name).join(Equipment).filter(EquipmentSubclass.is_active == True).distinct().order_by(EquipmentSubclass.name).all()
        subclasses = [s[0] for s in subclasses if s[0]]

    facilities = db.session.query(Facility.name).join(Equipment).filter(Facility.is_active == True).distinct().order_by(Facility.name).all()
    facilities = [f[0] for f in facilities if f[0]]

    # Get all scheduled tests, with their equipment, and every needed test date in one query
    all_scheduled_tests = (ScheduledTest.query.options(selectinload(ScheduledTest.equipment))
                           .order_by(ScheduledTest.scheduled_date.asc()).all())
    prime_last_tested_dates(set(active_equipment) | {t.equipment for t in all_scheduled_tests if t.equipment})

    # Map each equipment ID to its earliest scheduled test. Only include scheduled
    # dates more than a month after the last test date (or if no test exists).
    scheduled_by_equipment = {}
    for test in all_scheduled_tests:
        if test.eq_id not in scheduled_by_equipment and test.equipment:
            last_tested = test.equipment.get_last_tested_date()
            if not last_tested or test.scheduled_date > last_tested + timedelta(days=30):
                scheduled_by_equipment[test.eq_id] = test

    for test in all_scheduled_tests:
        equipment = test.equipment
        if test.scheduled_date >= today and equipment and not (
                equipment.eq_retired or (equipment.eq_retdate and equipment.eq_retdate <= today)):
            scheduled_tests.append((test, equipment))

    for equipment in active_equipment:
        next_due = equipment.get_next_due_date()

        if next_due:
            fake_test = SimpleNamespace(next_due_date=next_due,
                                        last_tested_date=equipment.get_last_tested_date())

            if next_due < today:
                overdue_tests.append((fake_test, equipment))
            elif next_due <= today + timedelta(days=days_ahead):
                upcoming_tests.append((fake_test, equipment))

    overdue_tests.sort(key=lambda x: x[0].next_due_date)
    upcoming_tests.sort(key=lambda x: x[0].next_due_date)
    scheduled_tests.sort(key=lambda x: x[0].scheduled_date)

    return render_template('compliance_dashboard.html',
                         overdue_tests=overdue_tests,
                         upcoming_tests=upcoming_tests,
                         scheduled_tests=scheduled_tests,
                         scheduled_by_equipment=scheduled_by_equipment,
                         today=today,
                         days_ahead=days_ahead,
                         classes=classes,
                         subclasses=subclasses,
                         facilities=facilities,
                         eq_class=eq_class,
                         eq_subclass=eq_subclass,
                         eq_fac=eq_fac,
                         search=search)

def _redirect_after_test_change(eq_id, params):
    """Back to the compliance dashboard or the equipment page, whichever the user came from.
    `params` is request.args (after a form) or request.form (after a delete button)."""
    redirect_to = params.get('redirect_to') or request.args.get('redirect_to', 'equipment')
    if redirect_to == 'compliance':
        return redirect(url_for('compliance_dashboard'))
    return _redirect_to_equipment(eq_id, params)

def _personnel_choices(roles, keep_id=None):
    people = _dropdown_options(Personnel, keep_id, or_(*[Personnel.roles.ilike(f'%{r}%') for r in roles]))
    return [('', 'Select...')] + [(p.id, _option_label(p)) for p in people]

def _compliance_test_form(equipment, test):
    """Add (test=None) or edit a compliance test for `equipment`."""
    form = ComplianceTestForm(obj=test)
    form.performed_by_id.choices = _personnel_choices(('physics_assistant', 'physicist'),
                                                      test.performed_by_id if test else None)
    form.reviewed_by_id.choices = _personnel_choices(('physicist',), test.reviewed_by_id if test else None)

    if form.validate_on_submit():
        is_new = test is None
        if is_new:
            test = ComplianceTest(eq_id=equipment.eq_id)
            db.session.add(test)
        form.populate_obj(test)  # the personnel selects coerce '' to None
        initials = extract_personnel_initials(current_user.name)
        test.modified_by = initials
        if is_new:
            test.created_by = initials
        db.session.commit()
        flash(f'Compliance test {"added" if is_new else "updated"} successfully!', 'success')
        return _redirect_after_test_change(equipment.eq_id, request.args)

    return render_template('compliance_test_form.html', form=form, equipment=equipment, test=test,
                           title='Edit Compliance Test' if test else 'Add Compliance Test',
                           redirect_to=request.args.get('redirect_to', 'equipment'))

@app.route('/compliance/test/<int:eq_id>/new', methods=['GET', 'POST'])
@login_required
@manage_compliance_required
def compliance_test_new(eq_id):
    return _compliance_test_form(db.get_or_404(Equipment, eq_id), None)

@app.route('/compliance/test/<int:test_id>/edit', methods=['GET', 'POST'])
@login_required
@manage_compliance_required
def compliance_test_edit(test_id):
    test = db.get_or_404(ComplianceTest, test_id)
    return _compliance_test_form(db.get_or_404(Equipment, test.eq_id), test)

@app.route('/compliance/test/<int:test_id>/delete', methods=['POST'])
@login_required
@manage_compliance_required
def compliance_test_delete(test_id):
    test = db.get_or_404(ComplianceTest, test_id)
    eq_id = test.eq_id  # read before the delete expires the object
    db.session.delete(test)
    db.session.commit()
    flash('Compliance test deleted successfully!', 'success')
    return _redirect_after_test_change(eq_id, request.form)

def _schedule_test_form(equipment, scheduled_test):
    """Add (scheduled_test=None) or edit a scheduled test for `equipment`."""
    form = ScheduleTestForm(obj=scheduled_test)
    if form.validate_on_submit():
        is_new = scheduled_test is None
        if is_new:
            scheduled_test = ScheduledTest(eq_id=equipment.eq_id, created_by_id=current_user.id)
            db.session.add(scheduled_test)
        form.populate_obj(scheduled_test)
        scheduled_test.modified_by_id = current_user.id
        db.session.commit()
        flash('Test scheduled successfully!' if is_new else 'Scheduled test updated successfully!', 'success')
        return _redirect_after_test_change(equipment.eq_id, request.args)

    return render_template('schedule_test_form.html', form=form, equipment=equipment, scheduled_test=scheduled_test,
                           title='Edit Scheduled Test' if scheduled_test else 'Schedule Test',
                           redirect_to=request.args.get('redirect_to', 'equipment'))

@app.route('/schedule/test/<int:eq_id>/new', methods=['GET', 'POST'])
@login_required
@manage_compliance_required
def schedule_test_new(eq_id):
    return _schedule_test_form(db.get_or_404(Equipment, eq_id), None)

@app.route('/schedule/test/<int:schedule_id>/edit', methods=['GET', 'POST'])
@login_required
@manage_compliance_required
def schedule_test_edit(schedule_id):
    scheduled_test = db.get_or_404(ScheduledTest, schedule_id)
    return _schedule_test_form(db.get_or_404(Equipment, scheduled_test.eq_id), scheduled_test)

@app.route('/schedule/test/<int:schedule_id>/delete', methods=['POST'])
@login_required
@manage_compliance_required
def schedule_test_delete(schedule_id):
    scheduled_test = db.get_or_404(ScheduledTest, schedule_id)
    eq_id = scheduled_test.eq_id  # read before the delete expires the object
    db.session.delete(scheduled_test)
    db.session.commit()
    flash('Scheduled test deleted successfully!', 'success')
    return _redirect_after_test_change(eq_id, request.form)

@app.route('/api/subclasses')
@login_required
def api_subclasses():
    eq_class = request.args.get('eq_class')
    class_id = request.args.get('class_id')

    if eq_class:
        # Get subclasses for specific class (by name - for equipment list filtering)
        class_obj = EquipmentClass.query.filter_by(name=eq_class).first()
        if class_obj:
            subclasses = EquipmentSubclass.query.filter_by(
                class_id=class_obj.id, is_active=True
            ).order_by(EquipmentSubclass.name).all()
        else:
            subclasses = []
    elif class_id:
        # Get subclasses for specific class (by ID - for equipment forms). `keep` is the form's
        # current subclass, listed even if since deactivated so saving doesn't clear it.
        keep_id = _int_or_none(request.args.get('keep'))
        subclasses = EquipmentSubclass.query.filter(
            EquipmentSubclass.class_id == _int_or_none(class_id),
            or_(EquipmentSubclass.is_active == True, EquipmentSubclass.id == keep_id)
        ).order_by(EquipmentSubclass.name).all()
    else:
        subclasses = EquipmentSubclass.query.filter_by(is_active=True).order_by(EquipmentSubclass.name).all()

    if class_id:
        # Return id/name pairs for forms
        subclass_list = [{'id': s.id, 'name': _option_label(s)} for s in subclasses]
    else:
        # Return names only, for the list page filters
        subclass_list = [s.name for s in subclasses]

    return jsonify(subclass_list)

def _related(relationship, attr='name'):
    """Export getter for an attribute of a related row, blank when there is none."""
    return lambda eq: getattr(getattr(eq, relationship), attr, None) if getattr(eq, relationship) else None

# (header, getter) for each exported column; getter None means the Equipment column of that name.
# The header names are also the import's column names.
EQUIPMENT_EXPORT_COLUMNS = [
    ('eq_id', None), ('equipment_class', _related('equipment_class')),
    ('equipment_subclass', _related('equipment_subclass')), ('manufacturer', _related('manufacturer')),
    ('eq_mod', None), ('department', _related('department')), ('eq_rm', None), ('eq_phone', None),
    ('facility', _related('facility')), ('facility_full', _related('facility', 'facility_full')),
    ('facility_address', _related('facility', 'address')),
    ('contact_id', None), ('contact_person', _related('contact')), ('contact_email', _related('contact', 'email')),
    ('supervisor_id', None), ('supervisor', _related('supervisor')),
    ('supervisor_email', _related('supervisor', 'email')),
    ('physician_id', None), ('physician', _related('physician')), ('physician_email', _related('physician', 'email')),
    ('eq_assetid', None), ('eq_sn', None), ('eq_mefac', None), ('eq_mereg', None), ('eq_mefacreg', None),
    ('eq_manid', None), ('eq_mandt', None), ('eq_rfrbdt', None), ('eq_instdt', None), ('eq_eoldate', None),
    ('eq_eeoldate', lambda eq: eq.get_estimated_eol_date()), ('eq_retdate', None),
    ('eq_retired', lambda eq: bool(eq.eq_retired)), ('eq_planned', lambda eq: bool(eq.eq_planned)),
    ('eq_physcov', lambda eq: bool(eq.eq_physcov)), ('eq_auditfreq', None), ('eq_acrsite', None),
    ('eq_acrunit', None), ('eq_radcap', None), ('eq_capfund', None), ('eq_capcst', None),
    ('eq_capecst', lambda eq: eq.get_estimated_cost()), ('eq_capyr', None), ('eq_captype', None),
    ('eq_capcat', lambda eq: getattr(eq.get_capital_category(), 'name', None)), ('eq_capnote', None),
    ('eq_notes', None),
]

@app.route('/export-equipment')
@login_required
def export_equipment():
    # Match the page the export was launched from (list or capital planning)
    view = 'capital' if request.args.get('view') == 'capital' else 'list'
    equipment_list = _filtered_equipment_query(request.args, view=view).all()
    rows = ([getter(eq) if getter else getattr(eq, header) for header, getter in EQUIPMENT_EXPORT_COLUMNS]
            for eq in equipment_list)
    return _csv_download('equipment_export', [h for h, _ in EQUIPMENT_EXPORT_COLUMNS], rows)

# Equipment CSV import. Column names match /export-equipment, so export -> edit ->
# import is the bulk-edit workflow: rows with a known eq_id update that record,
# only the columns present in the file change, and a blank cell clears the field.
EQUIPMENT_TEXT_COLUMNS = ('eq_mod', 'eq_rm', 'eq_phone', 'eq_assetid', 'eq_sn', 'eq_mefac', 'eq_mereg',
                          'eq_manid', 'eq_acrsite', 'eq_acrunit', 'eq_capnote', 'eq_notes')
EQUIPMENT_DATE_COLUMNS = ('eq_mandt', 'eq_rfrbdt', 'eq_instdt', 'eq_eoldate', 'eq_retdate')
EQUIPMENT_BOOL_COLUMNS = {'eq_retired': False, 'eq_planned': False, 'eq_physcov': True}  # value when blank
EQUIPMENT_INT_COLUMNS = ('eq_radcap', 'eq_capfund', 'eq_capcst', 'eq_capyr')
EQUIPMENT_PERSONNEL_COLUMNS = (
    # role, equipment attribute, id column, name column, email column
    ('contact', 'contact_id', 'contact_id', 'contact_person', 'contact_email'),
    ('supervisor', 'supervisor_id', 'supervisor_id', 'supervisor', 'supervisor_email'),
    ('physician', 'physician_id', 'physician_id', 'physician', 'physician_email'),
)
# Written by the export for reference but calculated, so ignored on import
EQUIPMENT_CALCULATED_COLUMNS = {'eq_mefacreg', 'eq_eeoldate', 'eq_capecst', 'eq_capcat'}
EQUIPMENT_IMPORT_COLUMNS = (
    {'eq_id', 'equipment_class', 'equipment_subclass', 'manufacturer', 'department',
     'facility', 'facility_full', 'facility_address', 'eq_auditfreq', 'eq_captype'}
    | set(EQUIPMENT_TEXT_COLUMNS) | set(EQUIPMENT_DATE_COLUMNS) | set(EQUIPMENT_BOOL_COLUMNS)
    | set(EQUIPMENT_INT_COLUMNS) | {c for cols in EQUIPMENT_PERSONNEL_COLUMNS for c in cols[2:]}
)
CSV_DATE_FORMATS = ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y')  # ISO, plus what Excel re-saves dates as
CSV_TRUE, CSV_FALSE = {'TRUE', 'YES', 'Y', '1'}, {'FALSE', 'NO', 'N', '0'}

def _parse_csv_date(value, column=None):
    for fmt in CSV_DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    prefix = f'{column}: ' if column else ''
    raise ValueError(f"{prefix}'{value}' is not a date (use YYYY-MM-DD)")

def _get_or_create_named(model, name, **attrs):
    """Find a lookup row by name (plus any extra filters), creating it if missing."""
    obj = model.query.filter_by(name=name, **attrs).first()
    if not obj:
        obj = model(name=name, **attrs)
        db.session.add(obj)
        db.session.flush()
    return obj

def _apply_equipment_row(row, columns):
    """Apply one import row. Returns (equipment, is_new, warnings); raises
    ValueError when the row cannot be imported at all."""
    warnings = []
    has = columns.__contains__

    eq_id = _int_or_none(row.get('eq_id'))
    if row.get('eq_id') and eq_id is None:
        raise ValueError(f"eq_id '{row['eq_id']}' is not a number")
    equipment = db.session.get(Equipment, eq_id) if eq_id is not None else None
    is_new = equipment is None
    if is_new:
        equipment = Equipment(eq_id=eq_id)

    class_name = row.get('equipment_class', '')
    if class_name:
        equipment.class_id = _get_or_create_named(EquipmentClass, class_name).id
    elif is_new or has('equipment_class'):
        raise ValueError('equipment_class is required')

    if has('equipment_subclass'):
        name = row['equipment_subclass']
        equipment.subclass_id = (_get_or_create_named(EquipmentSubclass, name, class_id=equipment.class_id).id
                                 if name else None)
    for column, model, attr in (('manufacturer', Manufacturer, 'manufacturer_id'),
                                ('department', Department, 'department_id')):
        if has(column):
            setattr(equipment, attr, _get_or_create_named(model, row[column]).id if row[column] else None)
    if has('facility'):
        name = row['facility']
        if not name:
            equipment.facility_id = None
        else:
            facility = Facility.query.filter_by(name=name).first()
            if not facility:
                # Full name and address are only used when the import creates the facility
                facility = Facility(name=name, facility_full=row.get('facility_full', ''),
                                    address=row.get('facility_address', ''))
                db.session.add(facility)
                db.session.flush()
            equipment.facility_id = facility.id

    for role, attr, id_col, name_col, email_col in EQUIPMENT_PERSONNEL_COLUMNS:
        if not (has(id_col) or has(name_col)):
            continue
        person_id, name = row.get(id_col, ''), row.get(name_col, '')
        if not person_id and not name:
            setattr(equipment, attr, None)
            continue
        person = get_or_create_personnel(person_id, name, row.get(email_col, ''), role)
        if person:
            setattr(equipment, attr, person.id)
        else:
            warnings.append(f"{role} '{name or person_id}' was not found, and a new person needs "
                            f"an email in {email_col}; {role} left unchanged")

    for column in EQUIPMENT_TEXT_COLUMNS:
        if has(column):
            setattr(equipment, column, row[column] or None)

    for column in EQUIPMENT_DATE_COLUMNS:
        if has(column):
            try:
                setattr(equipment, column, _parse_csv_date(row[column]) if row[column] else None)
            except ValueError as e:
                warnings.append(f'{column}: {e}; left unchanged')

    for column, blank_value in EQUIPMENT_BOOL_COLUMNS.items():
        if has(column):
            flag = row[column].upper()
            if not flag:
                setattr(equipment, column, blank_value)
            elif flag in CSV_TRUE or flag in CSV_FALSE:
                setattr(equipment, column, flag in CSV_TRUE)
            else:
                warnings.append(f"{column}: '{row[column]}' is not TRUE/FALSE; left unchanged")

    for column in EQUIPMENT_INT_COLUMNS:
        if has(column):
            value = _int_or_none(row[column])
            if row[column] and value is None:
                warnings.append(f"{column}: '{row[column]}' is not a whole number; left unchanged")
            elif column in ('eq_radcap', 'eq_capfund') and value not in (None, 0, 1):
                warnings.append(f"{column}: use 1 (yes), 0 (no), or blank; left unchanged")
            elif column == 'eq_capyr' and value is not None and not 1900 <= value <= 2100:
                warnings.append(f"eq_capyr: '{value}' is not a 4-digit year; left unchanged")
            else:
                setattr(equipment, column, value)

    if has('eq_auditfreq'):
        entries = [f.strip() for f in row['eq_auditfreq'].split(',') if f.strip()]
        invalid = [f for f in entries if f not in AUDIT_FREQUENCIES]
        if invalid:
            warnings.append(f"eq_auditfreq: unknown {', '.join(invalid)} (valid: {', '.join(AUDIT_FREQUENCIES)}); "
                            'left unchanged')
        else:
            equipment.eq_auditfreq = ', '.join(entries) or None

    if has('eq_captype'):
        captype = row['eq_captype'] or 'Replacement'
        if captype in ('Replacement', 'Upgrade'):
            equipment.eq_captype = captype
        else:
            warnings.append(f"eq_captype: '{captype}' must be Replacement or Upgrade; left unchanged")

    _apply_equipment_rules(equipment)
    return equipment, is_new, warnings

def _flash_row_messages(messages, category, limit=8):
    for message in messages[:limit]:
        flash(message, category)
    if len(messages) > limit:
        flash(f'... and {len(messages) - limit} more (see the server log)', category)
    for message in messages:
        logger.info("Import %s: %s", category, message)

def _database_error_message(error):
    """A readable reason for a rejected row, without the raw database error text."""
    match = re.search(r'(UNIQUE|NOT NULL) constraint failed: \w+\.(\w+)', str(getattr(error, 'orig', '')))
    if not match:
        return 'the database rejected this row'
    kind, column = match.groups()
    if kind == 'UNIQUE':
        return f'another record already has this {column}'
    return f'{column} is required'

def _run_csv_import(file, apply_row, noun, required=(), known=None):
    """Import an uploaded CSV one row at a time, flashing a summary and any problems.

    apply_row(row, columns) returns (record, is_new, warnings) or raises ValueError
    to skip the row. Each row commits on its own, so one bad row does not undo the
    others. Returns False if the file itself was rejected (the reason is flashed).
    """
    if not file or not file.filename:
        flash('No file selected', 'error')
        return False
    if not file.filename.lower().endswith('.csv'):
        flash('Please select a CSV file', 'error')
        return False
    try:
        df = _read_csv_upload(file)
    except (ValueError, UnicodeDecodeError, pd.errors.ParserError) as e:
        flash(f'Could not read the CSV file: {e}', 'error')
        return False
    if len(df) > MAX_CSV_ROWS:
        flash(f'CSV exceeds the maximum of {MAX_CSV_ROWS} rows ({len(df)} rows found). '
              'Split the file and import in batches.', 'error')
        return False
    columns = set(df.columns)
    missing = [c for c in required if c not in columns]
    if missing:
        flash(f'Missing required columns: {", ".join(missing)}', 'error')
        return False
    if known is not None and columns - known:
        flash(f"Ignored unrecognized columns: {', '.join(sorted(columns - known))}", 'warning')

    created = updated = skipped = 0
    errors, warnings = [], []
    for index, row in df.iterrows():
        line = index + 2  # spreadsheet row number: 1-based, after the header
        if not any(row.values):
            skipped += 1
            continue
        try:
            record, is_new, row_warnings = apply_row(row, columns)
            if is_new:
                db.session.add(record)
            db.session.commit()
        except ValueError as e:
            db.session.rollback()
            errors.append(f'Row {line}: {e}')
            continue
        except sa_exc.SQLAlchemyError as e:
            db.session.rollback()
            logger.error("CSV import (%s) row %s failed: %s", noun, line, e)
            errors.append(f'Row {line}: {_database_error_message(e)}')
            continue
        created += is_new
        updated += not is_new
        warnings.extend(f'Row {line}: {w}' for w in row_warnings)

    summary = f'Imported {created} new and updated {updated} existing {noun}'
    if skipped:
        summary += f', skipped {skipped} empty rows'
    flash(summary + '.', 'info' if not errors else 'warning')  # info stays on screen to be read
    _flash_row_messages(errors, 'error')
    _flash_row_messages(warnings, 'warning')
    return True

@app.route('/import-data', methods=['GET', 'POST'])
@login_required
@manage_equipment_required
def import_data():
    if request.method == 'POST':
        if _run_csv_import(request.files.get('file'), _apply_equipment_row, 'equipment records',
                           known=EQUIPMENT_IMPORT_COLUMNS | EQUIPMENT_CALCULATED_COLUMNS):
            return redirect(url_for('equipment_list'))
        return redirect(request.url)
    return render_template('import_data.html')

@app.route('/personnel')
@login_required
def personnel_list():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    search = request.args.get('search', '').strip()
    role_filter = request.args.get('role')

    query = Personnel.query

    if search:
        query = query.filter(Personnel.name.ilike(f'%{search}%') |
                           Personnel.email.ilike(f'%{search}%'))

    if role_filter:
        query = query.filter(Personnel.roles.ilike(f'%{role_filter}%'))

    query = query.order_by(Personnel.name)

    personnel = query.paginate(page=page, per_page=per_page, error_out=False)

    all_roles = db.session.query(Personnel.roles).filter(Personnel.roles.isnot(None), Personnel.roles != '').all()
    role_set = set()
    for role_row in all_roles:
        if role_row[0] and role_row[0].strip():
            roles = [r.strip() for r in role_row[0].split(',')]
            role_set.update(roles)

    return render_template('personnel_list.html',
                         personnel=personnel,
                         search=search,
                         role_filter=role_filter,
                         available_roles=sorted(role_set))

def _apply_personnel_form(personnel, form):
    """Copy the submitted PersonnelForm onto `personnel`, honoring who may change what.

    Active is whether the person is still around: inactive people cannot log in and are left out of
    new dropdown choices. Requires Login Access is whether they have an account at all.
    Login credentials, admin rights, and active status are admin-only. Anyone else with personnel rights manages contact details and
    non-admin roles, so they cannot grant themselves or others more access.
    Returns an error message, or None if the form was applied.
    """
    roles = list(form.roles.data or [])
    if not roles:
        return 'Select at least one role.'

    if current_user.is_admin:
        if personnel.id == current_user.id and not (form.is_admin.data and form.is_active.data
                                                    and form.login_required.data):
            return 'You cannot remove your own admin rights or login access, or deactivate your own account.'
        if form.login_required.data:
            if not form.username.data:
                return 'A username is required for login access.'
            if not personnel.password_hash and not form.password.data:
                return 'A password is required when enabling login for this account.'

    personnel.name = form.name.data
    personnel.email = form.email.data
    personnel.phone = form.phone.data
    personnel.set_roles_list(roles)

    if current_user.is_admin:
        personnel.username = form.username.data or None
        personnel.is_admin = form.is_admin.data
        personnel.is_active = form.is_active.data
        personnel.login_required = form.login_required.data
        if form.password.data:
            personnel.set_password(form.password.data)
    return None

def _can_modify_personnel(personnel):
    """Non-admins may not edit or delete admin accounts."""
    return current_user.is_admin or not personnel.is_admin

@app.route('/personnel/new', methods=['GET', 'POST'])
@login_required
@manage_personnel_required
def new_personnel():
    form = PersonnelForm()
    if form.validate_on_submit():
        personnel = Personnel(is_active=True, login_required=False)
        error = _apply_personnel_form(personnel, form)
        if error:
            flash(error, 'error')
        else:
            try:
                db.session.add(personnel)
                db.session.commit()
                flash('Personnel added successfully!', 'success')
                return redirect(url_for('personnel_list'))
            except sa_exc.SQLAlchemyError as e:
                db.session.rollback()
                logger.error("Error adding personnel: %s", e)
                flash('Error adding personnel. Email or username may already exist.', 'error')

    return render_template('personnel_form.html', form=form, title='Add Personnel', min_password_length=MIN_PASSWORD_LENGTH)

@app.route('/personnel/<int:id>')
@login_required
def personnel_detail(id):
    personnel = db.get_or_404(Personnel, id)
    return render_template('personnel_detail.html', personnel=personnel)

@app.route('/personnel/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@manage_personnel_required
def edit_personnel(id):
    personnel = db.get_or_404(Personnel, id)
    if not _can_modify_personnel(personnel):
        flash('Only admins can edit admin accounts.', 'error')
        return redirect(url_for('personnel_detail', id=id))

    form = PersonnelForm(obj=personnel)
    if request.method == 'GET':
        form.roles.data = personnel.get_roles_list()

    if form.validate_on_submit():
        error = _apply_personnel_form(personnel, form)
        if error:
            flash(error, 'error')
        else:
            try:
                db.session.commit()
                flash('Personnel updated successfully!', 'success')
                return redirect(url_for('personnel_detail', id=id))
            except sa_exc.SQLAlchemyError as e:
                db.session.rollback()
                logger.error("Error updating personnel id=%s: %s", id, e)
                flash('Error updating personnel.', 'error')

    return render_template('personnel_form.html', form=form, title='Edit Personnel', personnel=personnel, min_password_length=MIN_PASSWORD_LENGTH)

@app.route('/personnel/<int:id>/delete', methods=['POST'])
@login_required
@manage_personnel_required
def delete_personnel(id):
    personnel = db.get_or_404(Personnel, id)
    if personnel.id == current_user.id:
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('personnel_detail', id=id))
    if not _can_modify_personnel(personnel):
        flash('Only admins can delete admin accounts.', 'error')
        return redirect(url_for('personnel_detail', id=id))
    try:
        db.session.delete(personnel)
        db.session.commit()
        flash('Personnel deleted successfully!', 'success')
    except sa_exc.SQLAlchemyError as e:
        db.session.rollback()
        logger.error("Error deleting personnel id=%s: %s", id, e)
        flash('Error deleting personnel.', 'error')

    return redirect(url_for('personnel_list'))


@app.route('/export-personnel')
@login_required
def export_personnel():
    # One TRUE/FALSE column per role, which the personnel import reads back
    rows = ([p.id, p.name, p.email, p.phone, bool(p.login_required)]
            + [role in p.get_roles_list() for role in PERSONNEL_ROLES]
            for p in Personnel.query.all())
    return _csv_download('personnel', ['id', 'name', 'email', 'phone', 'login_required'] + PERSONNEL_ROLES, rows)

PERSONNEL_ROLES = ['contact', 'supervisor', 'physician', 'physicist', 'physics_assistant', 'qa_technologist']

def _apply_personnel_row(row, columns):
    """Contact details and roles only; login access is configured in the UI."""
    name, email = row.get('name', ''), row.get('email', '')
    if not name or not email:
        raise ValueError('name and email are required')
    person_id = _int_or_none(row.get('id'))
    person = (db.session.get(Personnel, person_id) if person_id else None) \
        or Personnel.query.filter_by(email=email).first()
    if person and not _can_modify_personnel(person):
        raise ValueError(f'only admins can change the admin account for {person.name}')
    is_new = person is None
    if is_new:
        person = Personnel(id=person_id or None, is_active=True, login_required=False)

    person.name, person.email = name, email
    if 'phone' in columns:
        person.phone = row['phone'] or None
    # Roles as one comma-separated column, or TRUE/FALSE columns as the export writes them
    if row.get('roles'):
        roles = [r.strip() for r in row['roles'].split(',') if r.strip()]
    elif columns & set(PERSONNEL_ROLES):
        roles = [r for r in PERSONNEL_ROLES if row.get(r, '').upper() in CSV_TRUE]
    else:
        roles = None
    if roles is not None:
        # Admin rights come only from is_admin (set in the UI), never from import
        person.set_roles_list([r for r in roles if r.lower() != 'admin'])
    return person, is_new, []

@app.route('/import-personnel', methods=['GET', 'POST'])
@login_required
@manage_personnel_required
def import_personnel():
    form = CsvUploadForm()
    if form.validate_on_submit():
        known = {'id', 'name', 'email', 'phone', 'roles', 'login_required', 'admin', *PERSONNEL_ROLES}
        if _run_csv_import(form.csv_file.data, _apply_personnel_row, 'personnel records',
                           required=('name', 'email'), known=known):
            flash('Login access must be configured individually through the personnel UI.', 'info')
            return redirect(url_for('personnel_list'))
    return render_template('import_personnel.html', form=form)


@app.route('/export-compliance')
@login_required
def export_compliance():
    if request.args.get('sample', 'false').lower() == 'true':
        headers = ['eq_id', 'test_type', 'test_date', 'report_date', 'submission_date',
                   'performed_by_id', 'reviewed_by_id', 'notes']
        return _csv_download('compliance_tests_template', headers, [], timestamped=False)

    # IDs are what the import reads; the names beside them are for people reading the file
    headers = ['test_id', 'eq_id', 'test_type', 'test_date', 'report_date', 'submission_date',
               'performed_by_id', 'performed_by', 'reviewed_by_id', 'reviewed_by', 'notes',
               'created_by', 'created_at', 'modified_by', 'updated_at']
    query = _filtered_equipment_query(request.args, view='all', query=ComplianceTest.query.join(Equipment))
    tests = query.options(selectinload(ComplianceTest.performed_by), selectinload(ComplianceTest.reviewed_by)) \
                 .order_by(ComplianceTest.test_date.desc()).all()
    rows = ([t.test_id, t.eq_id, t.test_type, t.test_date, t.report_date, t.submission_date,
             t.performed_by_id, getattr(t.performed_by, 'name', None),
             t.reviewed_by_id, getattr(t.reviewed_by, 'name', None), t.notes,
             t.created_by, t.created_at, t.modified_by, t.updated_at] for t in tests)
    filtered = any(request.args.get(k, '').strip() for k in ('eq_class', 'eq_subclass', 'eq_fac', 'search'))
    return _csv_download('compliance_tests_filtered' if filtered else 'compliance_tests', headers, rows)

# In compliance imports a blank optional cell leaves the value alone; one of these empties it
CSV_CLEAR = {'CLEAR', 'NULL', 'NONE'}

def _equipment_id_cell(row):
    eq_id = _int_or_none(row.get('eq_id'))
    if eq_id is None or not db.session.get(Equipment, eq_id):
        raise ValueError(f"equipment ID '{row.get('eq_id', '')}' not found")
    return eq_id

def _required_date_cell(row, column):
    if not row.get(column):
        raise ValueError(f'{column} is required')
    return _parse_csv_date(row[column], column)

def _apply_compliance_row(row, columns):
    warnings = []
    test_id = _int_or_none(row.get('test_id'))
    test = db.session.get(ComplianceTest, test_id) if test_id else None
    is_new = test is None
    if is_new:
        test = ComplianceTest()

    if row['test_type'] not in COMPLIANCE_TEST_TYPES:
        raise ValueError(f"test_type '{row['test_type']}' is not one of: {', '.join(COMPLIANCE_TEST_TYPES)}")
    test.eq_id = _equipment_id_cell(row)
    test.test_type = row['test_type']
    test.test_date = _required_date_cell(row, 'test_date')

    for column in ('report_date', 'submission_date', 'performed_by_id', 'reviewed_by_id', 'notes'):
        value = row.get(column, '')
        if not value:
            continue
        if value.upper() in CSV_CLEAR:
            setattr(test, column, None)
        elif column.endswith('_date'):
            setattr(test, column, _parse_csv_date(value, column))
        elif column.endswith('_id'):
            person_id = _int_or_none(value)
            if person_id is not None and db.session.get(Personnel, person_id):
                setattr(test, column, person_id)
            else:
                warnings.append(f"{column}: no personnel with ID '{value}'; left unchanged")
        else:
            test.notes = value

    initials = extract_personnel_initials(current_user.name)
    test.modified_by = initials
    if is_new:
        test.created_by = initials
    return test, is_new, warnings

@app.route('/import-compliance', methods=['GET', 'POST'])
@login_required
@manage_compliance_required
def import_compliance():
    form = CsvUploadForm()
    if form.validate_on_submit():
        # The export's name and audit columns are for reading; they are not imported
        known = {'test_id', 'eq_id', 'test_type', 'test_date', 'report_date', 'submission_date',
                 'performed_by_id', 'reviewed_by_id', 'notes', 'performed_by', 'reviewed_by',
                 'created_by', 'created_at', 'modified_by', 'updated_at'}
        if _run_csv_import(form.csv_file.data, _apply_compliance_row, 'compliance tests',
                           required=('eq_id', 'test_type', 'test_date'), known=known):
            return redirect(url_for('compliance_dashboard'))

    # Personnel IDs for the help text
    return render_template('import_compliance.html', form=form,
                           performed_by_personnel=_dropdown_options(Personnel, condition=or_(
                               Personnel.roles.ilike('%physics_assistant%'), Personnel.roles.ilike('%physicist%'))),
                           reviewed_by_personnel=_dropdown_options(Personnel, condition=Personnel.roles.ilike('%physicist%')))

@app.route('/export-scheduled-tests')
@login_required
def export_scheduled_tests():
    headers = ['schedule_id', 'eq_id', 'scheduled_date', 'scheduling_date', 'notes',
               'created_by', 'created_at', 'modified_by', 'updated_at']
    rows = ([t.schedule_id, t.eq_id, t.scheduled_date, t.scheduling_date, t.notes,
             getattr(t.created_by, 'name', None), t.created_at, getattr(t.modified_by, 'name', None), t.updated_at]
            for t in ScheduledTest.query.all())
    return _csv_download('scheduled_tests', headers, rows)

def _apply_schedule_row(row, columns):
    schedule_id = _int_or_none(row.get('schedule_id'))
    test = db.session.get(ScheduledTest, schedule_id) if schedule_id else None
    is_new = test is None
    if is_new:
        test = ScheduledTest(created_by_id=current_user.id)
    test.eq_id = _equipment_id_cell(row)
    test.scheduled_date = _required_date_cell(row, 'scheduled_date')
    test.scheduling_date = _required_date_cell(row, 'scheduling_date')
    if row.get('notes'):
        test.notes = row['notes']
    test.modified_by_id = current_user.id
    return test, is_new, []

@app.route('/import-scheduled-tests', methods=['POST'])
@login_required
@manage_compliance_required
def import_scheduled_tests():
    known = {'schedule_id', 'eq_id', 'scheduled_date', 'scheduling_date', 'notes',
             'created_by', 'created_at', 'modified_by', 'updated_at'}
    _run_csv_import(request.files.get('file'), _apply_schedule_row, 'scheduled tests',
                    required=('eq_id', 'scheduled_date', 'scheduling_date'), known=known)
    return redirect(url_for('compliance_dashboard'))

@app.route('/export-facilities')
@login_required
@admin_required
def export_facilities():
    rows = ([f.id, f.name, f.facility_full, f.address, f.is_active]
            for f in Facility.query.filter_by(is_active=True).all())
    return _csv_download('facilities_export', ['id', 'name', 'facility_full', 'address', 'is_active'], rows)

def _apply_facility_row(row, columns):
    """Columns missing from the CSV leave existing values alone."""
    name = row.get('name', '')
    if not name:
        raise ValueError('name is required')
    facility_id = _int_or_none(row.get('id'))
    facility = (db.session.get(Facility, facility_id) if facility_id else None) \
        or Facility.query.filter_by(name=name).first()
    is_new = facility is None
    if is_new:
        facility = Facility(id=facility_id or None, is_active=True)

    if 'facility_full' in columns:
        if _facility_full_taken(row['facility_full'], facility.id):
            raise ValueError(f'facility_full "{row["facility_full"]}" is already used by another facility')
        facility.facility_full = row['facility_full']
    facility.name = name
    if 'address' in columns:
        facility.address = row['address']
    if 'is_active' in columns:
        facility.is_active = (row['is_active'] or 'TRUE').upper() in CSV_TRUE | {'T'}
    return facility, is_new, []

@app.route('/import-facilities', methods=['GET', 'POST'])
@login_required
@admin_required
def import_facilities():
    if request.method == 'POST':
        if _run_csv_import(request.files.get('csv_file'), _apply_facility_row, 'facilities', required=('name',),
                           known={'id', 'name', 'facility_full', 'address', 'is_active'}):
            return redirect(url_for('admin_facilities'))
    return render_template('import_facilities.html')

# Admin Routes
@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    classes_count = EquipmentClass.query.filter_by(is_active=True).count()
    subclasses_count = EquipmentSubclass.query.filter_by(is_active=True).count()
    departments_count = Department.query.filter_by(is_active=True).count()
    facilities_count = Facility.query.filter_by(is_active=True).count()
    manufacturers_count = Manufacturer.query.filter_by(is_active=True).count()
    capital_categories_count = CapitalCategory.query.filter_by(is_active=True).count()

    return render_template('admin_dashboard.html',
                         classes_count=classes_count,
                         subclasses_count=subclasses_count,
                         departments_count=departments_count,
                         facilities_count=facilities_count,
                         manufacturers_count=manufacturers_count,
                         capital_categories_count=capital_categories_count,
                         backup_available=_is_sqlite_backend())


def _is_sqlite_backend():
    """True when the configured database is a SQLite file we can snapshot."""
    return db.engine.url.get_backend_name() == 'sqlite'


def _safe_sheet_name(name):
    """Coerce a table name into something Excel will accept as a worksheet name."""
    cleaned = ''.join(ch for ch in name if ch not in INVALID_SHEET_NAME_CHARS)
    return (cleaned or 'sheet')[:31]


def _export_columns(table):
    """Columns of `table` to include in the workbook, with secrets removed."""
    excluded = EXPORT_EXCLUDED_COLUMNS.get(table.name, set())
    return [c for c in table.columns if c.name not in excluded]


@app.route('/admin/database/backup')
@login_required
@admin_required
def admin_backup_database():
    """Download a consistent, self-contained snapshot of the SQLite database.

    Uses VACUUM INTO rather than copying the file: a plain copy of a database
    in WAL mode can produce a torn read, and drops any committed transaction
    that has not yet been checkpointed into the main file. VACUUM INTO folds
    the WAL in and emits a defragmented single file with no -wal/-shm sidecars.
    """
    if not _is_sqlite_backend():
        flash('Database backup is only available for SQLite databases. '
              'Use your database server\'s own backup tooling instead.', 'error')
        return redirect(url_for('admin_dashboard'))

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'rems_backup_{timestamp}.sqlite3'
    temp_dir = tempfile.mkdtemp(prefix='rems_backup_')
    # VACUUM INTO refuses to overwrite, so the target must not exist yet.
    target_path = os.path.join(temp_dir, filename)

    try:
        if sqlite3.sqlite_version_info >= (3, 27, 0):
            # VACUUM cannot run inside a transaction, so bypass the session.
            with db.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
                conn.exec_driver_sql('VACUUM INTO ?', (target_path,))
        else:
            # Pre-3.27 fallback: the online backup API, which is also WAL-safe.
            raw = db.engine.raw_connection()
            try:
                dest = sqlite3.connect(target_path)
                try:
                    raw.driver_connection.backup(dest)
                finally:
                    dest.close()
            finally:
                raw.close()

        with open(target_path, 'rb') as fh:
            payload = fh.read()
    except (sa_exc.SQLAlchemyError, sqlite3.Error, OSError) as e:
        logger.error("Database backup failed for user %s: %s", current_user.username, e)
        flash('Error creating database backup. The details are in the server log.', 'error')
        return redirect(url_for('admin_dashboard'))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    # This file contains every password hash in the system - worth an audit line.
    logger.info("Database backup downloaded by %s (%d bytes)", current_user.username, len(payload))

    return send_file(
        io.BytesIO(payload),
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.sqlite3',
    )


@app.route('/admin/database/workbook')
@login_required
@admin_required
def admin_export_workbook():
    """Download the whole database as an .xlsx workbook, one sheet per table.

    Driven off SQLAlchemy metadata so new columns appear automatically. Written
    with xlsxwriter rather than pandas because pandas coerces integer columns
    containing NULLs to float (foreign keys would render as '3.0') and cannot
    emit named Excel Tables, which are what make the sheets usable from
    Power Query.
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'rems_export_{timestamp}.xlsx'

    buffer = io.BytesIO()
    # Write every string literally: xlsxwriter otherwise turns text starting with '='
    # into a live formula (formula injection) and URL-like text into hyperlinks.
    workbook = xlsxwriter.Workbook(buffer, {'in_memory': True,
                                            'strings_to_formulas': False,
                                            'strings_to_urls': False})
    try:
        header_fmt = workbook.add_format({'bold': True})
        datetime_fmt = workbook.add_format({'num_format': 'yyyy-mm-dd hh:mm'})
        date_fmt = workbook.add_format({'num_format': 'yyyy-mm-dd'})

        readme = workbook.add_worksheet('_README')
        summary = []

        for table in db.metadata.sorted_tables:  # FK-dependency order: lookups first
            columns = _export_columns(table)
            if not columns:
                continue

            result = db.session.execute(table.select().with_only_columns(*columns))
            rows = result.all()
            truncated = len(rows) > EXCEL_MAX_DATA_ROWS
            if truncated:
                logger.warning("Table %s truncated to %d rows in workbook export",
                               table.name, EXCEL_MAX_DATA_ROWS)
                rows = rows[:EXCEL_MAX_DATA_ROWS]

            sheet_name = _safe_sheet_name(table.name)
            worksheet = workbook.add_worksheet(sheet_name)
            widths = [len(c.name) for c in columns]

            for row_idx, row in enumerate(rows, start=1):
                for col_idx, value in enumerate(row):
                    if value is None:
                        worksheet.write_blank(row_idx, col_idx, None)
                        continue
                    if isinstance(value, datetime):
                        worksheet.write_datetime(row_idx, col_idx, value, datetime_fmt)
                        widths[col_idx] = max(widths[col_idx], 16)
                        continue
                    if isinstance(value, date):
                        worksheet.write_datetime(row_idx, col_idx, value, date_fmt)
                        widths[col_idx] = max(widths[col_idx], 10)
                        continue
                    worksheet.write(row_idx, col_idx, value)
                    widths[col_idx] = max(widths[col_idx], len(str(value)))

            # add_table writes the header row itself. Its range must always
            # include one row beyond the header, even when the table is empty.
            worksheet.add_table(0, 0, max(len(rows), 1), len(columns) - 1, {
                'name': f'tbl_{sheet_name}',
                'columns': [{'header': c.name} for c in columns],
            })
            worksheet.freeze_panes(1, 0)
            for col_idx, width in enumerate(widths):
                worksheet.set_column(col_idx, col_idx, min(max(width + 2, 8), 50))

            summary.append((table.name, len(rows), truncated))

        _write_workbook_readme(readme, header_fmt, summary)
        workbook.close()
    except Exception:
        # Close on the way out so xlsxwriter does not leak its temp files.
        try:
            workbook.close()
        except Exception:
            pass
        raise

    logger.info("Excel workbook exported by %s (%d tables)", current_user.username, len(summary))

    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


def _write_workbook_readme(worksheet, header_fmt, summary):
    """Fill the leading _README sheet of the workbook export."""
    worksheet.set_column(0, 0, 26)
    worksheet.set_column(1, 1, 60)

    excluded = ', '.join(
        f'{table}.{column}'
        for table, columns in EXPORT_EXCLUDED_COLUMNS.items()
        for column in sorted(columns)
    )
    lines = [
        ('REMS database export', None),
        ('Exported at', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        ('Exported by', current_user.username or current_user.name),
        ('Source database', db.engine.url.get_backend_name()),
        (None, None),
        ('Snapshot', 'This is a point-in-time copy, not a live connection. '
                     'Re-download to refresh the data.'),
        ('Omitted for security', excluded),
        (None, None),
        ('Querying in Excel', 'Data > Get Data > From File > From Workbook, pick this file,'),
        (None, 'select the sheets you need, then Merge Queries on the ID columns'),
        (None, '(e.g. equipment.class_id -> equipment_classes.id).'),
        (None, None),
        ('Table', 'Rows'),
    ]
    row_idx = 0
    for label, value in lines:
        if label is not None:
            worksheet.write(row_idx, 0, label, header_fmt)
        if value is not None:
            worksheet.write(row_idx, 1, value)
        row_idx += 1

    for name, count, truncated in summary:
        worksheet.write(row_idx, 0, name)
        worksheet.write(row_idx, 1, f'{count} (TRUNCATED)' if truncated else count)
        row_idx += 1


# ---------------------------------------------------------------------------
# Admin lookup tables: classes, subclasses, departments, facilities,
# manufacturers, capital categories. They share one set of list / add / edit /
# deactivate / activate routes and two templates, driven by LOOKUP_TABLES.
# ---------------------------------------------------------------------------

class LookupField:
    """An editable column on a lookup table, beyond the shared `name`."""

    def __init__(self, attr, label, kind='text', required=False, help='', maxlength=None, options=None):
        self.attr, self.label, self.kind = attr, label, kind  # kind: text, textarea, int, select
        self.required, self.help, self.maxlength = required, help, maxlength
        self.options = options  # select only: callable returning [(value, label)]

    def parse(self, raw):
        """Submitted text -> stored value; raises ValueError with a message."""
        raw = (raw or '').strip()
        if not raw:
            if self.required:
                raise ValueError(f'{self.label} is required')
            return '' if self.kind in ('text', 'textarea') else None
        if self.kind in ('int', 'select'):
            value = _int_or_none(raw)
            if value is None or value < 0:
                raise ValueError(f'{self.label} must be a whole number')
            return value
        return raw


class LookupTable:
    def __init__(self, model, slug, singular, plural, icon, name_help='', name_maxlength=100,
                 fields=(), columns=(), unique_within=(), validate=None, note=''):
        self.model, self.slug, self.icon = model, slug, icon
        self.singular, self.plural = singular, plural
        self.name_help, self.name_maxlength = name_help, name_maxlength
        self.fields = list(fields)
        self.columns = list(columns)          # extra list columns: (heading, callable(item) -> text or None)
        self.unique_within = unique_within    # name is unique only within these fields (e.g. class_id)
        self.validate = validate              # callable(values, item_id) -> error message or None
        self.note = note                      # shown on the add/edit form
        # Endpoint names match the old per-table routes, e.g. admin_facilities, admin_edit_facility
        self.key = singular.lower().replace(' ', '_')
        self.list_endpoint = 'admin_' + plural.lower().replace(' ', '_')

    def endpoint(self, action):
        return f'admin_{action}_{self.key}'

    def find_by_name(self, values):
        filters = {'name': values['name'], **{f: values[f] for f in self.unique_within}}
        return self.model.query.filter_by(**filters).first()


def _validate_facility(values, item_id):
    if _facility_full_taken(values['facility_full'], item_id):
        return 'Full Facility name is already used by another facility'

def _validate_capital_category(values, item_id):
    if values['max_cost'] is not None and values['max_cost'] <= values['min_cost']:
        return 'Maximum cost must be greater than minimum cost'
    overlap = check_capital_category_overlap(values['min_cost'], values['max_cost'], item_id)
    if overlap:
        return f'Range overlaps with existing category "{overlap.name}" ({overlap.cost_range_display()})'

def _thousands(value):
    return f'${value * 1000:,}' if value else None

LOOKUP_TABLES = [
    LookupTable(EquipmentClass, 'equipment-classes', 'Equipment Class', 'Equipment Classes', 'fa-tags'),
    LookupTable(
        EquipmentSubclass, 'equipment-subclasses', 'Equipment Subclass', 'Equipment Subclasses', 'fa-layer-group',
        name_help='Unique within its equipment class',
        fields=[
            LookupField('class_id', 'Equipment Class', 'select', required=True,
                        options=lambda: [(c.id, c.name) for c in
                                         EquipmentClass.query.filter_by(is_active=True).order_by(EquipmentClass.name)]),
            LookupField('estimated_capital_cost', 'Estimated Capital Cost (thousands $)', 'int',
                        help='Default estimated cost for equipment in this subclass (optional)'),
            LookupField('expected_lifetime', 'Expected Lifetime (years)', 'int',
                        help='Used to estimate end of life when no EOL date is set (optional)'),
        ],
        columns=[('Equipment Class', lambda s: s.equipment_class.name if s.equipment_class else None),
                 ('Est. Capital Cost', lambda s: _thousands(s.estimated_capital_cost)),
                 ('Expected Lifetime', lambda s: f'{s.expected_lifetime} years' if s.expected_lifetime else None)],
        unique_within=('class_id',)),
    LookupTable(Department, 'departments', 'Department', 'Departments', 'fa-building'),
    LookupTable(
        Facility, 'facilities', 'Facility', 'Facilities', 'fa-hospital', name_maxlength=200,
        name_help='Short name shown throughout the app',
        fields=[
            LookupField('facility_full', 'Full Facility', maxlength=300,
                        help='Optional full facility name, shown on the equipment details page and used on reports'),
            LookupField('address', 'Address', 'textarea', maxlength=500, help='Optional facility address'),
        ],
        columns=[('Full Facility', lambda f: f.facility_full), ('Address', lambda f: f.address)],
        validate=_validate_facility),
    LookupTable(Manufacturer, 'manufacturers', 'Manufacturer', 'Manufacturers', 'fa-industry'),
    LookupTable(
        CapitalCategory, 'capital-categories', 'Capital Category', 'Capital Categories', 'fa-tags',
        name_maxlength=50, name_help='For example "A", "B", or "Category 1"',
        fields=[
            LookupField('min_cost', 'Minimum Cost (thousands $)', 'int', required=True,
                        help='In thousands, e.g. 100 for $100,000'),
            LookupField('max_cost', 'Maximum Cost (thousands $)', 'int',
                        help='Leave blank for no upper limit (e.g. "$500,000+")'),
        ],
        columns=[('Cost Range', lambda c: c.cost_range_display())],
        validate=_validate_capital_category,
        note='Cost ranges cannot overlap between active categories.'),
]


def _facility_full_taken(facility_full, facility_id=None):
    """True if another facility already uses this Full Facility name (they map 1-to-1)."""
    if not facility_full:
        return False
    other = Facility.query.filter(Facility.facility_full == facility_full).first()
    return other is not None and other.id != facility_id

def check_capital_category_overlap(min_cost, max_cost, exclude_id=None):
    """First active category whose cost range overlaps [min_cost, max_cost], or None.

    Bounds are inclusive (get_capital_category matches min_cost <= cost <= max_cost),
    and a max of None means no upper limit.
    """
    query = CapitalCategory.query.filter_by(is_active=True)
    if exclude_id:
        query = query.filter(CapitalCategory.id != exclude_id)
    no_limit = float('inf')
    for cat in query.all():
        if min_cost <= (cat.max_cost if cat.max_cost is not None else no_limit) and \
                cat.min_cost <= (max_cost if max_cost is not None else no_limit):
            return cat
    return None


def _lookup_form_values(table):
    """Parse the submitted add/edit form. Returns (values, error)."""
    values = {'name': request.form.get('name', '').strip()}
    if not values['name']:
        return values, 'Name is required'
    for field in table.fields:
        try:
            values[field.attr] = field.parse(request.form.get(field.attr))
        except ValueError as e:
            return values, str(e)
    return values, None

def _render_lookup_form(table, item, values):
    return render_template('admin_lookup_form.html', table=table, item=item, values=values)

def _register_lookup_routes(table):
    base = f'/admin/{table.slug}'

    def list_view():
        items = table.model.query.order_by(table.model.name).all()
        return render_template('admin_lookup_list.html', table=table, items=items)

    def add_view():
        if request.method == 'GET':
            return _render_lookup_form(table, None, {})
        values, error = _lookup_form_values(table)
        existing = table.find_by_name(values) if not error else None
        if not error and existing and existing.is_active:
            error = f'{table.singular} "{values["name"]}" already exists'
        if not error and table.validate:
            error = table.validate(values, existing.id if existing else None)
        if error:
            flash(error, 'error')
            return _render_lookup_form(table, None, values)
        if existing:
            # Re-adding a deactivated name brings it back with the new values
            item, message = existing, f'{table.singular} reactivated'
            item.is_active = True
        else:
            item, message = table.model(), f'{table.singular} added'
            db.session.add(item)
        for attr, value in values.items():
            setattr(item, attr, value)
        db.session.commit()
        flash(message, 'success')
        return redirect(url_for(table.list_endpoint))

    def edit_view(item_id):
        item = db.get_or_404(table.model, item_id)
        if request.method == 'GET':
            return _render_lookup_form(table, item, {})
        values, error = _lookup_form_values(table)
        if not error:
            existing = table.find_by_name(values)
            if existing and existing.id != item.id:
                error = f'{table.singular} "{values["name"]}" already exists'
        if not error and table.validate:
            error = table.validate(values, item.id)
        if error:
            flash(error, 'error')
            return _render_lookup_form(table, item, values)
        if all(getattr(item, attr) == value for attr, value in values.items()):
            flash('No changes made', 'info')
        else:
            for attr, value in values.items():
                setattr(item, attr, value)
            db.session.commit()
            flash(f'{table.singular} updated', 'success')
        return redirect(url_for(table.list_endpoint))

    def set_active_view(item_id, active):
        item = db.get_or_404(table.model, item_id)
        item.is_active = active
        db.session.commit()
        flash(f'{table.singular} {"activated" if active else "deactivated"}', 'success')
        return redirect(url_for(table.list_endpoint))

    guard = lambda view: login_required(admin_required(view))
    app.add_url_rule(base, table.list_endpoint, guard(list_view))
    app.add_url_rule(f'{base}/add', table.endpoint('add'), guard(add_view), methods=['GET', 'POST'])
    app.add_url_rule(f'{base}/<int:item_id>/edit', table.endpoint('edit'), guard(edit_view),
                     methods=['GET', 'POST'])
    app.add_url_rule(f'{base}/<int:item_id>/delete', table.endpoint('delete'),
                     guard(lambda item_id: set_active_view(item_id, False)), methods=['POST'])
    app.add_url_rule(f'{base}/<int:item_id>/activate', table.endpoint('activate'),
                     guard(lambda item_id: set_active_view(item_id, True)), methods=['POST'])

for _table in LOOKUP_TABLES:
    _register_lookup_routes(_table)

# Auto-initialize database on import (for production)
try:
    with app.app_context():
        db.create_all()
        check_and_migrate_db()
except sa_exc.SQLAlchemyError as e:
    logger.error("Database initialization error: %s", e)

if __name__ == '__main__':
    # Tables and migrations were already applied at import time (above).
    # host='127.0.0.1' binds only loopback for local dev; production traffic
    # is served through gunicorn (see PRODUCTION_DEPLOYMENT_GUIDE.md).
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    port = int(os.environ.get('PORT', 5000))
    app.run(host='127.0.0.1', port=port, debug=debug_mode)