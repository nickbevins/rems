from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, make_response, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, DateField, SelectField, BooleanField, TextAreaField, SelectMultipleField, FileField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Optional, Length, Email, EqualTo
from datetime import datetime, timedelta
import os
import pandas as pd
from dotenv import load_dotenv
import io
import csv
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

load_dotenv()

# Utility functions for auditing
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
    
    # Extract first character of each part
    initials = ''.join([part[0].upper() for part in parts if part and len(part) > 0])
    return initials[:3]  # Limit to 3 characters max

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
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
        print("WARNING: Using temporary SQLite database. Data will be lost on deployment!")
        print("Consider upgrading to a paid plan and adding a persistent disk, or use PostgreSQL.")
else:
    # Local development - use instance folder
    instance_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
    os.makedirs(instance_dir, exist_ok=True)
    db_path = os.path.join(instance_dir, 'physdb.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', f'sqlite:///{db_path}')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Database migration functions
def ensure_personnel_role(person, role_name):
    """Ensure a person has a specific role assigned"""
    if person.roles:
        current_roles = [role.strip().lower() for role in person.roles.split(',')]
        if role_name.lower() not in current_roles:
            person.roles = f"{person.roles}, {role_name}"
    else:
        person.roles = role_name

def get_or_create_personnel(contact_id, contact_name, contact_email, role_name):
    """Get existing personnel by ID or create new personnel with role assignment"""
    contact = None

    # First try to match by ID if provided
    if contact_id and str(contact_id).strip() and not pd.isna(contact_id):
        try:
            contact = Personnel.query.get(int(contact_id))
        except (ValueError, TypeError):
            pass

    # If no ID match and we have a name, try to find or create
    # Check for NaN before converting to string to avoid creating "nan" personnel
    if not contact and contact_name and not pd.isna(contact_name):
        contact_name = str(contact_name).strip()
        if contact_name:  # Ensure it's not an empty string after stripping
            contact_email = str(contact_email).strip() if (contact_email and not pd.isna(contact_email)) else None

            # Try to find existing by name
            contact = Personnel.query.filter_by(name=contact_name).first()

            if not contact:
                # Create new personnel record
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

def check_and_migrate_db():
    """Check database schema and apply migrations if needed"""
    try:
        with app.app_context():
            # Check if login_required column exists in personnel table
            inspector = db.inspect(db.engine)
            personnel_columns = [col['name'] for col in inspector.get_columns('personnel')]
            
            if 'login_required' not in personnel_columns:
                print("Adding login_required column to personnel table...")
                # Add the missing column with default value False
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE personnel ADD COLUMN login_required BOOLEAN DEFAULT 0"))
                    # Update existing ACTIVE users who have username and password to login_required=True
                    conn.execute(db.text("UPDATE personnel SET login_required = 1 WHERE username IS NOT NULL AND username != '' AND password_hash IS NOT NULL AND password_hash != '' AND is_active = 1"))
                    conn.commit()
                print("Successfully added login_required column and updated existing users")
            else:
                # Column exists - check if we need to update existing users
                # This handles the case where column was added but users weren't updated
                with db.engine.connect() as conn:
                    result = conn.execute(db.text("SELECT COUNT(*) FROM personnel WHERE username IS NOT NULL AND username != '' AND password_hash IS NOT NULL AND password_hash != '' AND is_active = 1 AND login_required = 0")).fetchone()
                    if result[0] > 0:
                        print(f"Updating {result[0]} existing active users to have login_required=True...")
                        conn.execute(db.text("UPDATE personnel SET login_required = 1 WHERE username IS NOT NULL AND username != '' AND password_hash IS NOT NULL AND password_hash != '' AND is_active = 1 AND login_required = 0"))
                        conn.commit()
                        print("Successfully updated existing users")
                    
                    # One-time correction: Reset inactive users back to login_required=FALSE
                    # This fixes the over-broad initial migration
                    inactive_result = conn.execute(db.text("SELECT COUNT(*) FROM personnel WHERE is_active = 0 AND login_required = 1")).fetchone()
                    if inactive_result[0] > 0:
                        print(f"Correcting {inactive_result[0]} inactive users to login_required=False...")
                        conn.execute(db.text("UPDATE personnel SET login_required = 0 WHERE is_active = 0"))
                        conn.commit()
                        print("Successfully corrected inactive users")
            
            # Check if submission_date column exists in compliance_tests table  
            if inspector.has_table('compliance_tests'):
                compliance_columns = [col['name'] for col in inspector.get_columns('compliance_tests')]
                if 'submission_date' not in compliance_columns:
                    print("Adding submission_date column to compliance_tests table...")
                    with db.engine.connect() as conn:
                        conn.execute(db.text("ALTER TABLE compliance_tests ADD COLUMN submission_date DATE"))
                        conn.commit()
                    print("Successfully added submission_date column")
            
            # Check if eq_phone column exists in equipment table
            if inspector.has_table('equipment'):
                equipment_columns = [col['name'] for col in inspector.get_columns('equipment')]
                if 'eq_phone' not in equipment_columns:
                    print("Adding eq_phone column to equipment table...")
                    with db.engine.connect() as conn:
                        conn.execute(db.text("ALTER TABLE equipment ADD COLUMN eq_phone VARCHAR(20)"))
                        conn.commit()
                    print("Successfully added eq_phone column")

                # Add new equipment columns for capital tracking
                if 'eq_rfrbdt' not in equipment_columns:
                    print("Adding eq_rfrbdt column to equipment table...")
                    with db.engine.connect() as conn:
                        conn.execute(db.text("ALTER TABLE equipment ADD COLUMN eq_rfrbdt DATE"))
                        conn.commit()
                    print("Successfully added eq_rfrbdt column")

                if 'eq_physcov' not in equipment_columns:
                    print("Adding eq_physcov column to equipment table...")
                    with db.engine.connect() as conn:
                        conn.execute(db.text("ALTER TABLE equipment ADD COLUMN eq_physcov BOOLEAN DEFAULT 1"))
                        # Set existing equipment to have physics coverage by default
                        conn.execute(db.text("UPDATE equipment SET eq_physcov = 1 WHERE eq_physcov IS NULL"))
                        conn.commit()
                    print("Successfully added eq_physcov column")

                if 'eq_capfund' not in equipment_columns:
                    print("Adding eq_capfund column to equipment table...")
                    with db.engine.connect() as conn:
                        conn.execute(db.text("ALTER TABLE equipment ADD COLUMN eq_capfund INTEGER"))
                        conn.commit()
                    print("Successfully added eq_capfund column")

                if 'eq_capecst' not in equipment_columns:
                    print("Adding eq_capecst column to equipment table...")
                    with db.engine.connect() as conn:
                        conn.execute(db.text("ALTER TABLE equipment ADD COLUMN eq_capecst INTEGER"))
                        conn.commit()
                    print("Successfully added eq_capecst column")

                if 'eq_capnote' not in equipment_columns:
                    print("Adding eq_capnote column to equipment table...")
                    with db.engine.connect() as conn:
                        conn.execute(db.text("ALTER TABLE equipment ADD COLUMN eq_capnote VARCHAR(140)"))
                        conn.commit()
                    print("Successfully added eq_capnote column")

            # Add estimated_capital_cost to equipment_subclasses table
            if inspector.has_table('equipment_subclasses'):
                subclass_columns = [col['name'] for col in inspector.get_columns('equipment_subclasses')]
                if 'estimated_capital_cost' not in subclass_columns:
                    print("Adding estimated_capital_cost column to equipment_subclasses table...")
                    with db.engine.connect() as conn:
                        conn.execute(db.text("ALTER TABLE equipment_subclasses ADD COLUMN estimated_capital_cost INTEGER"))
                        conn.commit()
                    print("Successfully added estimated_capital_cost column")

    except Exception as e:
        print(f"Error during database migration: {e}")

# Initialize database tables
def init_db():
    """Initialize database tables if they don't exist"""
    try:
        with app.app_context():
            db.create_all()
            print("Database tables created successfully")
            # Run migrations after creating tables
            check_and_migrate_db()
    except Exception as e:
        print(f"Error creating database tables: {e}")

# Don't initialize here - wait until all models are defined

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

# User loader function for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    return Personnel.query.get(int(user_id))

# Database Models

class Equipment(db.Model):
    __tablename__ = 'equipment'
    
    eq_id = db.Column(db.Integer, primary_key=True)
    
    # Foreign Key Relationships (replacing text fields)
    class_id = db.Column(db.Integer, db.ForeignKey('equipment_classes.id'), nullable=False)
    subclass_id = db.Column(db.Integer, db.ForeignKey('equipment_subclasses.id'), nullable=True)
    manufacturer_id = db.Column(db.Integer, db.ForeignKey('manufacturers.id'), nullable=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    facility_id = db.Column(db.Integer, db.ForeignKey('facilities.id'), nullable=True)
    
    # Personnel Foreign Keys
    contact_id = db.Column(db.Integer, db.ForeignKey('personnel.id'), nullable=True)
    supervisor_id = db.Column(db.Integer, db.ForeignKey('personnel.id'), nullable=True)
    physician_id = db.Column(db.Integer, db.ForeignKey('personnel.id'), nullable=True)
    
    # Equipment Details (still text fields)
    eq_mod = db.Column(db.String(200))
    eq_rm = db.Column(db.String(100))
    eq_phone = db.Column(db.String(20))
    eq_address = db.Column(db.Text)
    
    # Note: Personnel contact details are now stored in Personnel table
    # No additional contact info fields needed - use Personnel.email, phone, etc.
    
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
    eq_eoldate = db.Column(db.Date)
    eq_eeoldate = db.Column(db.Date)
    eq_retdate = db.Column(db.Date)
    eq_retired = db.Column(db.Boolean, default=False)
    
    # Compliance Information
    eq_physcov = db.Column(db.Boolean, default=True)  # Physics Coverage - default True for existing equipment
    eq_auditfreq = db.Column(db.String(200), default='Annual - TJC')  # Comma-separated list of frequencies
    eq_acrsite = db.Column(db.String(100))
    eq_acrunit = db.Column(db.String(100))
    eq_servlogin = db.Column(db.String(100))
    eq_servpwd = db.Column(db.String(100))

    # Technical Specifications / Capital Information
    eq_radcap = db.Column(db.Integer)  # Radiology Owned: 1=Yes, 0=No, NULL=N/A
    eq_capfund = db.Column(db.Integer)  # Replacement Funded: 1=Yes, 0=No, NULL=N/A
    eq_capcat = db.Column(db.Integer)
    eq_capcst = db.Column(db.Integer)  # Capital Cost (in thousands)
    eq_capecst = db.Column(db.Integer)  # Estimated Capital Cost from subclass (in thousands)
    eq_capnote = db.Column(db.String(140))  # Capital notes (max 140 chars)
    
    # Notes
    eq_notes = db.Column(db.Text)
    
    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
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
        from datetime import timedelta, datetime
        from dateutil.relativedelta import relativedelta
        import calendar

        today = datetime.now().date()

        # Find the most recent acceptance or annual test
        latest_test = ComplianceTest.query.filter(
            ComplianceTest.eq_id == self.eq_id,
            ComplianceTest.test_type.in_(['acceptance', 'annual', 'Acceptance', 'Annual'])
        ).order_by(ComplianceTest.test_date.desc()).first()

        if latest_test and self.eq_auditfreq:
            test_date = latest_test.test_date

            # Parse multiple audit frequencies (comma-separated)
            frequencies = [f.strip() for f in self.eq_auditfreq.split(',') if f.strip()]

            # Calculate due date for each frequency
            due_dates = []

            for freq in frequencies:
                if freq == 'Quarterly':
                    # End of month 3 months from test date
                    next_month = test_date + relativedelta(months=3)
                    last_day = calendar.monthrange(next_month.year, next_month.month)[1]
                    due_dates.append(next_month.replace(day=last_day))

                elif freq == 'Semiannual':
                    # End of month 6 months from test date
                    next_month = test_date + relativedelta(months=6)
                    last_day = calendar.monthrange(next_month.year, next_month.month)[1]
                    due_dates.append(next_month.replace(day=last_day))

                elif freq == 'Annual - ACR':
                    # 1 year + 2 months from test date
                    due_dates.append(test_date + relativedelta(months=14))

                elif freq == 'Annual - TJC':
                    # 1 year + 30 days from test date
                    due_dates.append(test_date + relativedelta(years=1) + timedelta(days=30))

                elif freq == 'Annual - ME':
                    # End of next calendar year
                    next_year = test_date.year + 1
                    due_dates.append(datetime(next_year, 12, 31).date())

            # Return the earliest due date
            if due_dates:
                return min(due_dates)

        # No acceptance or annual test found, or no audit frequency set
        return None
    
    def get_last_tested_date(self):
        """Get the date of the most recent acceptance or annual test."""
        from datetime import datetime

        today = datetime.now().date()

        # Find the most recent acceptance or annual test
        latest_test = ComplianceTest.query.filter(
            ComplianceTest.eq_id == self.eq_id,
            ComplianceTest.test_type.in_(['acceptance', 'annual', 'Acceptance', 'Annual'])
        ).order_by(ComplianceTest.test_date.desc()).first()

        return latest_test.test_date if latest_test else None
    
    def to_dict(self):
        return {
            'eq_id': self.eq_id,
            'eq_class': self.eq_class,
            'eq_subclass': self.eq_subclass,
            'eq_manu': self.eq_manu,
            'eq_mod': self.eq_mod,
            'eq_dept': self.eq_dept,
            'eq_rm': self.eq_rm,
            'eq_phone': self.eq_phone,
            'eq_fac': self.eq_fac,
            'eq_address': self.eq_address,
            'eq_contact': self.eq_contact,
            'eq_contactinfo': self.eq_contactinfo,
            'eq_sup': self.eq_sup,
            'eq_supinfo': self.eq_supinfo,
            'eq_physician': self.eq_physician,
            'eq_physicianinfo': self.eq_physicianinfo,
            'eq_assetid': self.eq_assetid,
            'eq_sn': self.eq_sn,
            'eq_mefac': self.eq_mefac,
            'eq_mereg': self.eq_mereg,
            'eq_mefacreg': self.eq_mefacreg,
            'eq_manid': self.eq_manid,
            'eq_mandt': self.eq_mandt.isoformat() if self.eq_mandt else None,
            'eq_instdt': self.eq_instdt.isoformat() if self.eq_instdt else None,
            'eq_eoldate': self.eq_eoldate.isoformat() if self.eq_eoldate else None,
            'eq_eeoldate': self.eq_eeoldate.isoformat() if self.eq_eeoldate else None,
            'eq_retdate': self.eq_retdate.isoformat() if self.eq_retdate else None,
            'eq_retired': self.eq_retired,
            'eq_auditfreq': self.eq_auditfreq,
            'eq_acrsite': self.eq_acrsite,
            'eq_acrunit': self.eq_acrunit,
            'eq_radcap': self.eq_radcap,
            'eq_capcat': self.eq_capcat,
            'eq_capcst': self.eq_capcst,
            'eq_notes': self.eq_notes
        }

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
    last_login = db.Column(db.DateTime)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
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
            # Filter out empty strings and strip whitespace
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
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'phone': self.phone,
            'roles': self.roles,
            'username': self.username,
            'is_active': self.is_active,
            'is_admin': self.is_admin,
            'login_required': self.login_required
        }

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    modified_by = db.Column(db.String(10))  # Personnel initials  
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    performed_by = db.relationship('Personnel', foreign_keys=[performed_by_id], backref='tests_performed')
    reviewed_by = db.relationship('Personnel', foreign_keys=[reviewed_by_id], backref='tests_reviewed')
    
    def get_status(self):
        """Calculate status based on test date"""
        if self.test_date > datetime.now().date():
            return 'Scheduled'
        else:
            return 'Completed'
    
    def get_test_type_display(self):
        """Get the proper display name for test type"""
        # Handle both old lowercase and new capitalized formats
        test_type_mapping = {
            # Old lowercase format
            'acceptance': 'Acceptance',
            'annual': 'Annual',
            'audit': 'Audit',
            'other': 'Other',
            'qc_review': 'QC Review',
            'retire': 'Retire',
            'shielding_design': 'Shielding Design',
            'submission': 'Submission',
            # New capitalized format (already correct)
            'Acceptance': 'Acceptance',
            'Annual': 'Annual',
            'Audit': 'Audit',
            'Other': 'Other',
            'QC Review': 'QC Review',
            'Retire': 'Retire',
            'Shielding Design': 'Shielding Design',
            'Submission': 'Submission'
        }
        return test_type_mapping.get(self.test_type, self.test_type)
    
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    modified_by_id = db.Column(db.Integer, db.ForeignKey('personnel.id'))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<EquipmentClass {self.id}: {self.name}>'

class EquipmentSubclass(db.Model):
    __tablename__ = 'equipment_subclasses'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('equipment_classes.id'), nullable=False)
    estimated_capital_cost = db.Column(db.Integer)  # Estimated capital cost in thousands
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    equipment_class = db.relationship('EquipmentClass', backref='subclasses')

    def __repr__(self):
        return f'<EquipmentSubclass {self.id}: {self.name}>'

class Department(db.Model):
    __tablename__ = 'departments'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Department {self.id}: {self.name}>'

class Facility(db.Model):
    __tablename__ = 'facilities'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    address = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Facility {self.id}: {self.name}>'

class Manufacturer(db.Model):
    __tablename__ = 'manufacturers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Manufacturer {self.id}: {self.name}>'

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
    eq_address = TextAreaField('Address', validators=[Optional()])
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
    eq_eeoldate = DateField('Estimated End of Life Date', validators=[Optional()])
    eq_retdate = DateField('Retirement Date', validators=[Optional()])
    eq_retired = BooleanField('Retired')
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
    eq_capcat = SelectField('Capital Category', choices=[
        ('', 'Select'),
        ('0', 'N/A'),
        ('1', 'Category 1'),
        ('2', 'Category 2'),
        ('3', 'Category 3')
    ], validators=[Optional()], coerce=lambda x: int(x) if x and x != '' else None)
    eq_capcst = IntegerField('Capital Cost (thousands $)', validators=[Optional()])
    eq_capnote = StringField('Capital Notes', validators=[Optional(), Length(max=140)])
    eq_notes = TextAreaField('Notes', validators=[Optional()])

class ComplianceTestForm(FlaskForm):
    test_type = SelectField('Test/Result/Event Type', choices=[
        ('Acceptance', 'Acceptance'),
        ('Annual', 'Annual'),
        ('Audit', 'Audit'),
        ('Other', 'Other'),
        ('QC Review', 'QC Review'),
        ('Retire', 'Retire'),
        ('Shielding Design', 'Shielding Design'),
        ('Submission', 'Submission')
    ], validators=[DataRequired()], default='Annual')
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

class PersonnelForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=200)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=200)])
    phone = StringField('Phone', validators=[Optional(), Length(max=50)])
    roles = SelectMultipleField('Roles', choices=[
        ('admin', 'Admin'),
        ('contact', 'Contact'),
        ('physician', 'Physician'),
        ('physicist', 'Physicist'),
        ('physics_assistant', 'Physics Assistant'),
        ('qa_technologist', 'QA Technologist'),
        ('supervisor', 'Supervisor')
    ], validators=[DataRequired()])
    login_required = BooleanField('Requires Login Access', default=False)
    username = StringField('Username', validators=[Optional(), Length(max=80)])
    password = PasswordField('Password', validators=[Optional(), Length(min=6)])
    is_admin = BooleanField('Admin User')
    is_active = BooleanField('Active', default=True)

class BulkPersonnelForm(FlaskForm):
    csv_file = FileField('CSV File', validators=[DataRequired()])

class PasswordChangeForm(FlaskForm):
    current_password = PasswordField('Current Password', validators=[DataRequired()])
    new_password = PasswordField('New Password', validators=[DataRequired(), Length(min=6)])
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

# Authentication Routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = Personnel.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data) and user.is_active and user.login_required:
            login_user(user)
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            next_page = request.args.get('next')
            if not next_page or not next_page.startswith('/'):
                next_page = url_for('index')
            return redirect(next_page)
        else:
            flash('Invalid username or password.', 'error')
    
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = PasswordChangeForm()
    
    if form.validate_on_submit():
        # Verify current password
        if not current_user.check_password(form.current_password.data):
            flash('Current password is incorrect.', 'error')
            return render_template('change_password.html', form=form)
        
        # Update password
        current_user.set_password(form.new_password.data)
        
        try:
            db.session.commit()
            flash('Password changed successfully!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            flash('Error changing password. Please try again.', 'error')
    
    return render_template('change_password.html', form=form)

# Initialize database and create default admin after all models are defined
init_db()

# Create default admin user if none exists
def create_default_admin():
    """Create default admin user if no users exist at all"""
    try:
        with app.app_context():
            # Only create admin if database is completely empty
            if Personnel.query.count() == 0:
                admin_user = Personnel(
                    id=0,
                    name='Admin User',
                    email='admin@rems.com',
                    username='admin',
                    is_admin=True,
                    is_active=True,
                    login_required=True,
                    roles='admin'
                )
                admin_user.set_password('password123')
                db.session.add(admin_user)
                db.session.commit()
                print("Default admin user created with ID 0: admin/password123")
            else:
                print("Personnel exist - skipping default admin creation")
    except Exception as e:
        print(f"Error creating default admin: {e}")

# Create default admin after database initialization
create_default_admin()

# Routes
@app.route('/')
@login_required
def index():
    today = datetime.now().date()
    
    # Get active equipment (not retired, not past retirement date, and physics covered)
    from sqlalchemy import and_, or_
    active_equipment = Equipment.query.filter(
        and_(
            Equipment.eq_retired == False,
            Equipment.eq_physcov == True,
            or_(
                Equipment.eq_retdate.is_(None),
                Equipment.eq_retdate > today
            )
        )
    ).all()
    
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
            # Overdue
            overdue_count += 1
        elif next_due <= today + timedelta(days=90):
            # Upcoming within 90 days
            upcoming_count += 1
        else:
            # Compliant (next due date is more than 90 days away)
            compliant_count += 1

    # Get scheduled tests count (future dates only, for non-retired equipment)
    all_scheduled_tests = ScheduledTest.query.filter(
        ScheduledTest.scheduled_date >= today
    ).all()

    scheduled_tests_count = 0
    for test in all_scheduled_tests:
        equipment = Equipment.query.get(test.eq_id)
        if equipment and not (equipment.eq_retired or (equipment.eq_retdate and equipment.eq_retdate <= today)):
            scheduled_tests_count += 1

    return render_template('index.html',
                         overdue_count=overdue_count,
                         upcoming_count=upcoming_count,
                         compliant_count=compliant_count,
                         no_frequency_count=no_frequency_count,
                         scheduled_tests_count=scheduled_tests_count)

@app.route('/equipment')
@login_required
def equipment_list():
    from datetime import datetime
    from sqlalchemy import and_, or_
    
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    # Filters
    search = request.args.get('search', '').strip()
    eq_class = request.args.get('eq_class')
    eq_subclass = request.args.get('eq_subclass')
    eq_manu = request.args.get('eq_manu')
    eq_dept = request.args.get('eq_dept')
    eq_fac = request.args.get('eq_fac')
    include_retired = request.args.get('include_retired', 'false')  # Default to false
    include_noncovered = request.args.get('include_noncovered', 'false')  # Default to false
    
    # Multi-level sorting
    sort_fields = request.args.get('sort', 'eq_id').split(',')
    sort_orders = request.args.get('order', 'asc').split(',')
    
    # Build query with proper joins for relational data
    query = Equipment.query.join(
        EquipmentClass, Equipment.class_id == EquipmentClass.id, isouter=True
    ).join(
        EquipmentSubclass, Equipment.subclass_id == EquipmentSubclass.id, isouter=True
    ).join(
        Manufacturer, Equipment.manufacturer_id == Manufacturer.id, isouter=True
    ).join(
        Department, Equipment.department_id == Department.id, isouter=True
    ).join(
        Facility, Equipment.facility_id == Facility.id, isouter=True
    ).join(
        Personnel, Equipment.contact_id == Personnel.id, isouter=True
    )
    
    # Search across multiple fields including relational data
    if search:
        search_filter = or_(
            EquipmentClass.name.ilike(f'%{search}%'),
            EquipmentSubclass.name.ilike(f'%{search}%'),
            Manufacturer.name.ilike(f'%{search}%'),
            Equipment.eq_mod.ilike(f'%{search}%'),
            Department.name.ilike(f'%{search}%'),
            Equipment.eq_rm.ilike(f'%{search}%'),
            Facility.name.ilike(f'%{search}%'),
            Equipment.eq_address.ilike(f'%{search}%'),
            Equipment.eq_assetid.ilike(f'%{search}%'),
            Equipment.eq_sn.ilike(f'%{search}%'),
            Equipment.eq_mefac.ilike(f'%{search}%'),
            Equipment.eq_mereg.ilike(f'%{search}%'),
            Equipment.eq_mefacreg.ilike(f'%{search}%'),
            Equipment.eq_manid.ilike(f'%{search}%'),
            Equipment.eq_acrsite.ilike(f'%{search}%'),
            Equipment.eq_acrunit.ilike(f'%{search}%'),
            Equipment.eq_servlogin.ilike(f'%{search}%'),
            Equipment.eq_notes.ilike(f'%{search}%')
        )
        query = query.filter(search_filter)
    
    # Apply filters using relational data
    if eq_class:
        query = query.filter(EquipmentClass.name == eq_class)
    if eq_subclass:
        query = query.filter(EquipmentSubclass.name == eq_subclass)
    if eq_manu:
        query = query.filter(Manufacturer.name == eq_manu)
    if eq_dept:
        query = query.filter(Department.name == eq_dept)
    if eq_fac:
        query = query.filter(Facility.name == eq_fac)

    # By default, only show active equipment unless include_retired is checked
    if include_retired != 'true':
        query = query.filter(
            and_(
                Equipment.eq_retired == False,
                or_(
                    Equipment.eq_retdate.is_(None),
                    Equipment.eq_retdate > datetime.now().date()
                )
            )
        )

    # By default, only show physics-covered equipment unless include_noncovered is checked
    if include_noncovered != 'true':
        query = query.filter(Equipment.eq_physcov == True)

    # Apply multi-level sorting - map legacy sort fields to relational fields
    sort_mapping = {
        'eq_class': EquipmentClass.name,
        'eq_manu': Manufacturer.name,
        'eq_dept': Department.name,
        'eq_fac': Facility.name,
        'eq_subclass': EquipmentSubclass.name
    }
    
    # Build order by clauses for multiple sort levels
    order_clauses = []
    has_days_until_due_sort = False
    
    for i, sort_field in enumerate(sort_fields):
        sort_order = sort_orders[i] if i < len(sort_orders) else 'asc'
        
        if sort_field == 'days_until_due':
            # Special handling for calculated field - we'll sort this in Python after query
            has_days_until_due_sort = True
            continue
        elif sort_field in sort_mapping:
            sort_column = sort_mapping[sort_field]
        elif hasattr(Equipment, sort_field):
            sort_column = getattr(Equipment, sort_field)
        else:
            sort_column = Equipment.eq_id  # default
        
        if sort_order == 'desc':
            order_clauses.append(sort_column.desc())
        else:
            order_clauses.append(sort_column.asc())
    
    # Apply all sort clauses
    if order_clauses:
        query = query.order_by(*order_clauses)
    
    # Handle days_until_due sorting if present
    if has_days_until_due_sort:
        try:
            # Get all items for sorting
            all_equipment = query.all()
            
            # Calculate days until due for each equipment
            today = datetime.now().date()
            
            def get_days_until_due(eq):
                try:
                    if eq.eq_retired or (eq.eq_retdate and eq.eq_retdate <= today):
                        return 9999  # Put retired equipment at the end
                    
                    due_date = eq.get_next_due_date()
                    if due_date:
                        return (due_date - today).days
                    else:
                        return 9998  # Put equipment with no due date near the end
                except Exception as e:
                    # If there's any error calculating for this equipment, put it at the end
                    return 9997
            
            # Find the days_until_due sort order
            days_sort_order = 'asc'
            for i, field in enumerate(sort_fields):
                if field == 'days_until_due':
                    days_sort_order = sort_orders[i] if i < len(sort_orders) else 'asc'
                    break
            
            # Sort by days until due
            reverse_sort = (days_sort_order == 'desc')
            all_equipment.sort(key=get_days_until_due, reverse=reverse_sort)
        except Exception as e:
            # If sorting fails, fall back to regular query without days_until_due sorting
            has_days_until_due_sort = False
    
    # Handle pagination based on whether days_until_due sorting was successful
    if has_days_until_due_sort:
        # Create pagination manually
        total_items = len(all_equipment)
        if request.args.get('show_all') == 'true':
            equipment_items = all_equipment
            equipment = type('MockPagination', (), {
                'items': equipment_items,
                'total': total_items,
                'pages': 1,
                'page': 1,
                'has_prev': False,
                'has_next': False,
                'prev_num': None,
                'next_num': None,
                'iter_pages': lambda *args, **kwargs: [1]
            })()
        else:
            # Manual pagination
            per_page = int(request.args.get('per_page', 25))
            if per_page < 1:
                per_page = 25
            elif per_page > 1000:
                per_page = 1000
            
            page = int(request.args.get('page', 1))
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            equipment_items = all_equipment[start_idx:end_idx]
            
            total_pages = (total_items + per_page - 1) // per_page
            
            equipment = type('MockPagination', (), {
                'items': equipment_items,
                'total': total_items,
                'pages': total_pages,
                'page': page,
                'has_prev': page > 1,
                'has_next': page < total_pages,
                'prev_num': page - 1 if page > 1 else None,
                'next_num': page + 1 if page < total_pages else None,
                'iter_pages': lambda *args, **kwargs: range(max(1, page - 2), min(total_pages + 1, page + 3))
            })()
    else:
        # Handle pagination or show all normally
        if request.args.get('show_all') == 'true':
            # Get all items without pagination
            all_equipment = query.all()
            # Create a mock pagination object for template compatibility
            equipment = type('MockPagination', (), {
                'items': all_equipment,
                'total': len(all_equipment),
                'pages': 1,
                'page': 1,
                'has_prev': False,
                'has_next': False,
                'prev_num': None,
                'next_num': None,
                'iter_pages': lambda *args, **kwargs: [1]
            })()
        else:
            # Validate per_page range
            if per_page < 1:
                per_page = 25
            elif per_page > 1000:  # Reasonable maximum
                per_page = 1000
                
            equipment = query.paginate(
                page=page, 
                per_page=per_page, 
                error_out=False,
                max_per_page=1000
            )
    
    
    # Get values for filters from standardized lists
    classes = EquipmentClass.query.filter_by(is_active=True).order_by(EquipmentClass.name).all()
    subclasses = EquipmentSubclass.query.filter_by(is_active=True).order_by(EquipmentSubclass.name).all()
    manufacturers = Manufacturer.query.filter_by(is_active=True).order_by(Manufacturer.name).all()
    departments = Department.query.filter_by(is_active=True).order_by(Department.name).all()
    facilities = Facility.query.filter_by(is_active=True).order_by(Facility.name).all()
    
    return render_template('equipment_list.html', 
                         equipment=equipment,
                         classes=[c.name for c in classes],
                         subclasses=[s.name for s in subclasses],
                         manufacturers=[m.name for m in manufacturers],
                         departments=[d.name for d in departments],
                         facilities=[f.name for f in facilities],
                         today=datetime.now().date())

@app.route('/equipment/new', methods=['GET', 'POST'])
@login_required
@manage_equipment_required
def equipment_new():
    form = EquipmentForm()

    # Initialize eq_auditfreq to empty list for new equipment
    if request.method == 'GET':
        form.eq_auditfreq.data = []

    # Populate choices from standardized lists using IDs
    classes = EquipmentClass.query.filter_by(is_active=True).order_by(EquipmentClass.name).all()
    form.class_id.choices = [('', 'Select Class')] + [(str(c.id), c.name) for c in classes]
    
    subclasses = EquipmentSubclass.query.filter_by(is_active=True).order_by(EquipmentSubclass.name).all()
    form.subclass_id.choices = [('', 'Select Subclass')] + [(str(s.id), s.name) for s in subclasses]
    
    manufacturers = Manufacturer.query.filter_by(is_active=True).order_by(Manufacturer.name).all()
    form.manufacturer_id.choices = [('', 'Select Manufacturer')] + [(str(m.id), m.name) for m in manufacturers]
    
    departments = Department.query.filter_by(is_active=True).order_by(Department.name).all()
    form.department_id.choices = [('', 'Select Department')] + [(str(d.id), d.name) for d in departments]
    
    facilities = Facility.query.filter_by(is_active=True).order_by(Facility.name).all()
    form.facility_id.choices = [('', 'Select Facility')] + [(str(f.id), f.name) for f in facilities]
    
    # Populate personnel choices by role
    contacts = Personnel.query.filter(Personnel.roles.ilike('%contact%')).order_by(Personnel.name).all()
    form.contact_id.choices = [('', 'Select Contact')] + [(str(p.id), p.name) for p in contacts]
    
    supervisors = Personnel.query.filter(Personnel.roles.ilike('%supervisor%')).order_by(Personnel.name).all()
    form.supervisor_id.choices = [('', 'Select Supervisor')] + [(str(p.id), p.name) for p in supervisors]
    
    physicians = Personnel.query.filter(Personnel.roles.ilike('%physician%')).order_by(Personnel.name).all()
    form.physician_id.choices = [('', 'Select Physician')] + [(str(p.id), p.name) for p in physicians]
    
    if form.validate_on_submit():
        equipment = Equipment()
        form.populate_obj(equipment)

        # Convert audit frequency list to comma-separated string
        if isinstance(equipment.eq_auditfreq, list):
            equipment.eq_auditfreq = ', '.join(equipment.eq_auditfreq) if equipment.eq_auditfreq else None

        # Convert empty string foreign keys to None
        if not equipment.class_id:
            equipment.class_id = None
        if not equipment.subclass_id:
            equipment.subclass_id = None
        if not equipment.manufacturer_id:
            equipment.manufacturer_id = None
        if not equipment.department_id:
            equipment.department_id = None
        if not equipment.facility_id:
            equipment.facility_id = None
        if not equipment.contact_id:
            equipment.contact_id = None
        if not equipment.supervisor_id:
            equipment.supervisor_id = None
        if not equipment.physician_id:
            equipment.physician_id = None

        # Set estimated capital cost from subclass if subclass is selected
        if equipment.subclass_id:
            subclass = EquipmentSubclass.query.get(equipment.subclass_id)
            if subclass and subclass.estimated_capital_cost:
                equipment.eq_capecst = subclass.estimated_capital_cost

        # If equipment is marked as retired but has no retirement date, set it to today
        if equipment.eq_retired and not equipment.eq_retdate:
            equipment.eq_retdate = datetime.now().date()

        # Auto-generate eq_mefacreg from eq_mefac and eq_mereg
        if equipment.eq_mefac and equipment.eq_mereg:
            # Extract trailing numbers from eq_mefac (e.g., "ME-12345" -> "12345", "ABC123" -> "123")
            import re
            mefac_numbers = re.search(r'\d+$', equipment.eq_mefac)
            mefac_suffix = mefac_numbers.group() if mefac_numbers else ''
            # Extract trailing numbers from eq_mereg (e.g., "REG-67890" -> "67890", "XYZ890" -> "890")
            mereg_numbers = re.search(r'\d+$', equipment.eq_mereg)
            mereg_suffix = mereg_numbers.group() if mereg_numbers else ''
            # Combine them with hyphen (e.g., "123-456" format)
            if mefac_suffix and mereg_suffix:
                equipment.eq_mefacreg = f"{mefac_suffix}-{mereg_suffix}"
            else:
                equipment.eq_mefacreg = None
        else:
            equipment.eq_mefacreg = None

        db.session.add(equipment)
        db.session.commit()
        flash('Equipment added successfully!', 'success')
        return redirect(url_for('equipment_list'))

    return render_template('equipment_form.html', form=form, title='Add New Equipment')

@app.route('/equipment/<int:eq_id>')
@login_required
def equipment_detail(eq_id):
    equipment = Equipment.query.get_or_404(eq_id)
    
    # Add pagination for compliance tests
    test_page = request.args.get('test_page', 1, type=int)
    test_per_page = request.args.get('test_per_page', 10, type=int)
    
    # Query compliance tests with pagination
    tests_query = ComplianceTest.query.filter_by(eq_id=eq_id).order_by(ComplianceTest.test_date.desc())
    tests = tests_query.paginate(
        page=test_page,
        per_page=test_per_page,
        error_out=False,
        max_per_page=50
    )
    
    # Preserve search parameters for back navigation
    search_params = {
        'search': request.args.get('search', ''),
        'eq_class': request.args.get('eq_class', ''),
        'eq_subclass': request.args.get('eq_subclass', ''),
        'eq_manu': request.args.get('eq_manu', ''),
        'eq_dept': request.args.get('eq_dept', ''),
        'eq_fac': request.args.get('eq_fac', ''),
        'include_retired': request.args.get('include_retired', ''),
        'sort': request.args.get('sort', ''),
        'order': request.args.get('order', ''),
        'page': request.args.get('page', '')
    }

    # Check if user came from compliance page
    redirect_to = request.args.get('redirect_to', '')
    
    # Calculate next due test based on equipment's audit frequency (only for active equipment)
    next_test = None
    today = datetime.now().date()
    is_retired = equipment.eq_retired or (equipment.eq_retdate and equipment.eq_retdate <= today)

    if not is_retired:
        next_due_date = equipment.get_next_due_date()
        if next_due_date:
            # Create a fake test object for template compatibility
            class FakeTest:
                def __init__(self):
                    self.test_type = 'Annual'
                    self.next_due_date = next_due_date

                def get_test_type_display(self):
                    return 'Annual'

            next_test = FakeTest()

    # Get scheduled tests that are more than a month after the last test date
    all_scheduled = ScheduledTest.query.filter(
        ScheduledTest.eq_id == eq_id
    ).order_by(ScheduledTest.scheduled_date.asc()).all()

    # Filter to only include scheduled tests more than 30 days after last test
    scheduled_tests = []
    last_tested = equipment.get_last_tested_date()
    for test in all_scheduled:
        # Include if no previous test, or scheduled date is more than 30 days after last test
        if not last_tested or test.scheduled_date > last_tested + timedelta(days=30):
            scheduled_tests.append(test)

    return render_template('equipment_detail.html', equipment=equipment, tests=tests, next_test=next_test, today=today, search_params=search_params, scheduled_tests=scheduled_tests, redirect_to=redirect_to)

@app.route('/equipment/<int:eq_id>/edit', methods=['GET', 'POST'])
@login_required
@manage_equipment_required
def equipment_edit(eq_id):
    equipment = Equipment.query.get_or_404(eq_id)

    # For GET requests, pre-process the equipment data to ensure proper form population
    if request.method == 'GET':
        # Create a copy of equipment data with proper type conversions for SelectFields
        form_data = {}
        for field in equipment.__table__.columns:
            value = getattr(equipment, field.name)
            form_data[field.name] = value

        # Convert integer fields to strings for SelectField compatibility
        if equipment.eq_radcap is not None:
            form_data['eq_radcap'] = str(equipment.eq_radcap)
        if equipment.eq_capfund is not None:
            form_data['eq_capfund'] = str(equipment.eq_capfund)
        if equipment.eq_capcat is not None:
            form_data['eq_capcat'] = str(equipment.eq_capcat)

        # Convert comma-separated audit frequencies to list for SelectMultipleField
        if equipment.eq_auditfreq:
            form_data['eq_auditfreq'] = [f.strip() for f in equipment.eq_auditfreq.split(',')]
        else:
            form_data['eq_auditfreq'] = []

        form = EquipmentForm(data=form_data)
    else:
        form = EquipmentForm()

    # Populate choices from standardized lists using IDs
    classes = EquipmentClass.query.filter_by(is_active=True).order_by(EquipmentClass.name).all()
    form.class_id.choices = [('', 'Select Class')] + [(str(c.id), c.name) for c in classes]

    subclasses = EquipmentSubclass.query.filter_by(is_active=True).order_by(EquipmentSubclass.name).all()
    form.subclass_id.choices = [('', 'Select Subclass')] + [(str(s.id), s.name) for s in subclasses]

    manufacturers = Manufacturer.query.filter_by(is_active=True).order_by(Manufacturer.name).all()
    form.manufacturer_id.choices = [('', 'Select Manufacturer')] + [(str(m.id), m.name) for m in manufacturers]

    departments = Department.query.filter_by(is_active=True).order_by(Department.name).all()
    form.department_id.choices = [('', 'Select Department')] + [(str(d.id), d.name) for d in departments]

    facilities = Facility.query.filter_by(is_active=True).order_by(Facility.name).all()
    form.facility_id.choices = [('', 'Select Facility')] + [(str(f.id), f.name) for f in facilities]

    # Populate personnel choices by role
    contacts = Personnel.query.filter(Personnel.roles.ilike('%contact%')).order_by(Personnel.name).all()
    form.contact_id.choices = [('', 'Select Contact')] + [(str(p.id), p.name) for p in contacts]

    supervisors = Personnel.query.filter(Personnel.roles.ilike('%supervisor%')).order_by(Personnel.name).all()
    form.supervisor_id.choices = [('', 'Select Supervisor')] + [(str(p.id), p.name) for p in supervisors]

    physicians = Personnel.query.filter(Personnel.roles.ilike('%physician%')).order_by(Personnel.name).all()
    form.physician_id.choices = [('', 'Select Physician')] + [(str(p.id), p.name) for p in physicians]

    # Set form field values from equipment (needed for foreign key fields)
    if request.method == 'GET':
        form.class_id.data = str(equipment.class_id) if equipment.class_id else ''
        form.subclass_id.data = str(equipment.subclass_id) if equipment.subclass_id else ''
        form.manufacturer_id.data = str(equipment.manufacturer_id) if equipment.manufacturer_id else ''
        form.department_id.data = str(equipment.department_id) if equipment.department_id else ''
        form.facility_id.data = str(equipment.facility_id) if equipment.facility_id else ''
        form.contact_id.data = str(equipment.contact_id) if equipment.contact_id else ''
        form.supervisor_id.data = str(equipment.supervisor_id) if equipment.supervisor_id else ''
        form.physician_id.data = str(equipment.physician_id) if equipment.physician_id else ''
    
    if form.validate_on_submit():
        form.populate_obj(equipment)

        # Convert audit frequency list to comma-separated string
        if isinstance(equipment.eq_auditfreq, list):
            equipment.eq_auditfreq = ', '.join(equipment.eq_auditfreq) if equipment.eq_auditfreq else None

        # Convert empty string foreign keys to None
        if not equipment.class_id:
            equipment.class_id = None
        if not equipment.subclass_id:
            equipment.subclass_id = None
        if not equipment.manufacturer_id:
            equipment.manufacturer_id = None
        if not equipment.department_id:
            equipment.department_id = None
        if not equipment.facility_id:
            equipment.facility_id = None
        if not equipment.contact_id:
            equipment.contact_id = None
        if not equipment.supervisor_id:
            equipment.supervisor_id = None
        if not equipment.physician_id:
            equipment.physician_id = None

        # Set estimated capital cost from subclass if subclass is selected
        if equipment.subclass_id:
            subclass = EquipmentSubclass.query.get(equipment.subclass_id)
            if subclass and subclass.estimated_capital_cost:
                equipment.eq_capecst = subclass.estimated_capital_cost
        else:
            equipment.eq_capecst = None

        # If equipment is marked as retired but has no retirement date, set it to today
        if equipment.eq_retired and not equipment.eq_retdate:
            equipment.eq_retdate = datetime.now().date()

        # Auto-generate eq_mefacreg from eq_mefac and eq_mereg
        if equipment.eq_mefac and equipment.eq_mereg:
            # Extract trailing numbers from eq_mefac (e.g., "ME-12345" -> "12345", "ABC123" -> "123")
            import re
            mefac_numbers = re.search(r'\d+$', equipment.eq_mefac)
            mefac_suffix = mefac_numbers.group() if mefac_numbers else ''
            # Extract trailing numbers from eq_mereg (e.g., "REG-67890" -> "67890", "XYZ890" -> "890")
            mereg_numbers = re.search(r'\d+$', equipment.eq_mereg)
            mereg_suffix = mereg_numbers.group() if mereg_numbers else ''
            # Combine them with hyphen (e.g., "123-456" format)
            if mefac_suffix and mereg_suffix:
                equipment.eq_mefacreg = f"{mefac_suffix}-{mereg_suffix}"
            else:
                equipment.eq_mefacreg = None
        else:
            equipment.eq_mefacreg = None

        db.session.commit()
        flash('Equipment updated successfully!', 'success')

        # Preserve filter parameters when redirecting back
        filter_params = {k: v for k, v in request.args.items()}
        return redirect(url_for('equipment_detail', eq_id=eq_id, **filter_params))
    else:
        # Debug: Show form validation errors if form submission fails
        if request.method == 'POST':
            for field_name, errors in form.errors.items():
                for error in errors:
                    flash(f'Form validation error in {field_name}: {error}', 'error')
    
    return render_template('equipment_form.html', form=form, title='Edit Equipment', equipment=equipment)

@app.route('/api/equipment/<int:eq_id>/update-details', methods=['POST'])
@login_required
@manage_equipment_required
def update_equipment_details(eq_id):
    """AJAX endpoint to update equipment details card"""
    equipment = Equipment.query.get_or_404(eq_id)

    # Get form data from JSON
    data = request.get_json()

    # Update equipment fields
    equipment.class_id = int(data.get('class_id')) if data.get('class_id') else None
    equipment.subclass_id = int(data.get('subclass_id')) if data.get('subclass_id') else None
    equipment.manufacturer_id = int(data.get('manufacturer_id')) if data.get('manufacturer_id') else None
    equipment.eq_mod = data.get('eq_mod', '')
    equipment.department_id = int(data.get('department_id')) if data.get('department_id') else None
    equipment.eq_rm = data.get('eq_rm', '')
    equipment.eq_phone = data.get('eq_phone', '')
    equipment.facility_id = int(data.get('facility_id')) if data.get('facility_id') else None
    equipment.eq_assetid = data.get('eq_assetid', '')
    equipment.eq_sn = data.get('eq_sn', '')
    equipment.eq_mefac = data.get('eq_mefac', '')
    equipment.eq_mereg = data.get('eq_mereg', '')
    equipment.eq_manid = data.get('eq_manid', '')
    equipment.eq_auditfreq = data.get('eq_auditfreq', '')
    equipment.eq_acrsite = data.get('eq_acrsite', '')
    equipment.eq_acrunit = data.get('eq_acrunit', '')
    equipment.eq_notes = data.get('eq_notes', '')

    # Handle dates
    from dateutil import parser
    try:
        equipment.eq_mandt = parser.parse(data.get('eq_mandt')).date() if data.get('eq_mandt') else None
        equipment.eq_instdt = parser.parse(data.get('eq_instdt')).date() if data.get('eq_instdt') else None
        equipment.eq_eoldate = parser.parse(data.get('eq_eoldate')).date() if data.get('eq_eoldate') else None
        equipment.eq_eeoldate = parser.parse(data.get('eq_eeoldate')).date() if data.get('eq_eeoldate') else None
        equipment.eq_retdate = parser.parse(data.get('eq_retdate')).date() if data.get('eq_retdate') else None
    except:
        pass

    # Handle retired checkbox
    equipment.eq_retired = data.get('eq_retired') == 'true' or data.get('eq_retired') == True

    # Auto-generate eq_mefacreg from eq_mefac and eq_mereg
    if equipment.eq_mefac and equipment.eq_mereg:
        import re
        mefac_numbers = re.search(r'\d+$', equipment.eq_mefac)
        mefac_suffix = mefac_numbers.group() if mefac_numbers else ''
        mereg_numbers = re.search(r'\d+$', equipment.eq_mereg)
        mereg_suffix = mereg_numbers.group() if mereg_numbers else ''
        if mefac_suffix and mereg_suffix:
            equipment.eq_mefacreg = f"{mefac_suffix}-{mereg_suffix}"
        else:
            equipment.eq_mefacreg = None
    else:
        equipment.eq_mefacreg = None

    db.session.commit()

    return jsonify({'success': True, 'message': 'Equipment details updated successfully'})

@app.route('/api/equipment/<int:eq_id>/update-capital', methods=['POST'])
@login_required
@manage_equipment_required
def update_capital_details(eq_id):
    """AJAX endpoint to update capital details card"""
    equipment = Equipment.query.get_or_404(eq_id)

    # Get form data from JSON
    data = request.get_json()

    # Update capital fields
    equipment.eq_radcap = int(data.get('eq_radcap')) if data.get('eq_radcap') and data.get('eq_radcap') != '' else None
    equipment.eq_capcat = int(data.get('eq_capcat')) if data.get('eq_capcat') and data.get('eq_capcat') != '' else None
    equipment.eq_capcst = int(data.get('eq_capcst')) if data.get('eq_capcst') else None

    db.session.commit()

    return jsonify({'success': True, 'message': 'Capital details updated successfully'})

@app.route('/api/equipment/<int:eq_id>/update-contacts', methods=['POST'])
@login_required
@manage_equipment_required
def update_contact_info(eq_id):
    """AJAX endpoint to update contact information card"""
    equipment = Equipment.query.get_or_404(eq_id)

    # Get form data from JSON
    data = request.get_json()

    # Update contact fields
    equipment.contact_id = int(data.get('contact_id')) if data.get('contact_id') else None
    equipment.supervisor_id = int(data.get('supervisor_id')) if data.get('supervisor_id') else None
    equipment.physician_id = int(data.get('physician_id')) if data.get('physician_id') else None

    db.session.commit()

    return jsonify({'success': True, 'message': 'Contact information updated successfully'})

@app.route('/api/equipment/<int:eq_id>/form-data', methods=['GET'])
@login_required
def get_equipment_form_data(eq_id):
    """AJAX endpoint to get dropdown choices and current values for edit forms"""
    equipment = Equipment.query.get_or_404(eq_id)

    # Get all dropdown choices
    classes = EquipmentClass.query.filter_by(is_active=True).order_by(EquipmentClass.name).all()
    subclasses = EquipmentSubclass.query.filter_by(is_active=True).order_by(EquipmentSubclass.name).all()
    manufacturers = Manufacturer.query.filter_by(is_active=True).order_by(Manufacturer.name).all()
    departments = Department.query.filter_by(is_active=True).order_by(Department.name).all()
    facilities = Facility.query.filter_by(is_active=True).order_by(Facility.name).all()
    contacts = Personnel.query.filter(Personnel.roles.ilike('%contact%')).order_by(Personnel.name).all()
    supervisors = Personnel.query.filter(Personnel.roles.ilike('%supervisor%')).order_by(Personnel.name).all()
    physicians = Personnel.query.filter(Personnel.roles.ilike('%physician%')).order_by(Personnel.name).all()

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
            'eq_instdt': equipment.eq_instdt.strftime('%Y-%m-%d') if equipment.eq_instdt else '',
            'eq_eoldate': equipment.eq_eoldate.strftime('%Y-%m-%d') if equipment.eq_eoldate else '',
            'eq_eeoldate': equipment.eq_eeoldate.strftime('%Y-%m-%d') if equipment.eq_eeoldate else '',
            'eq_retdate': equipment.eq_retdate.strftime('%Y-%m-%d') if equipment.eq_retdate else '',
            'eq_retired': equipment.eq_retired,
            'eq_auditfreq': equipment.eq_auditfreq,
            'eq_acrsite': equipment.eq_acrsite,
            'eq_acrunit': equipment.eq_acrunit,
            'eq_notes': equipment.eq_notes,
            'eq_radcap': equipment.eq_radcap,
            'eq_capcat': equipment.eq_capcat,
            'eq_capcst': equipment.eq_capcst,
            'contact_id': equipment.contact_id,
            'supervisor_id': equipment.supervisor_id,
            'physician_id': equipment.physician_id,
        },
        'choices': {
            'classes': [{'id': c.id, 'name': c.name} for c in classes],
            'subclasses': [{'id': s.id, 'name': s.name} for s in subclasses],
            'manufacturers': [{'id': m.id, 'name': m.name} for m in manufacturers],
            'departments': [{'id': d.id, 'name': d.name} for d in departments],
            'facilities': [{'id': f.id, 'name': f.name} for f in facilities],
            'contacts': [{'id': p.id, 'name': p.name} for p in contacts],
            'supervisors': [{'id': p.id, 'name': p.name} for p in supervisors],
            'physicians': [{'id': p.id, 'name': p.name} for p in physicians],
            'audit_frequencies': ['Quarterly', 'Semiannual', 'Annual - ACR', 'Annual - TJC', 'Annual - ME'],
        }
    })

@app.route('/compliance')
@login_required
def compliance_dashboard():
    today = datetime.now().date()
    overdue_tests = []
    upcoming_tests = []
    scheduled_tests = []
    
    # Get filter parameters from query string
    eq_class = request.args.get('eq_class', '').strip()
    eq_subclass = request.args.get('eq_subclass', '').strip()
    eq_fac = request.args.get('eq_fac', '').strip()
    search = request.args.get('search', '').strip()
    
    # Get days parameter from query string, default to 90
    try:
        days_ahead = int(request.args.get('days', 90))
        if days_ahead < 1:
            days_ahead = 90
    except (ValueError, TypeError):
        days_ahead = 90
    
    # Build base query for active equipment (not retired, not past retirement date, and physics covered)
    from sqlalchemy import and_, or_
    query = Equipment.query.filter(
        and_(
            Equipment.eq_retired == False,
            Equipment.eq_physcov == True,
            or_(
                Equipment.eq_retdate.is_(None),
                Equipment.eq_retdate > today
            )
        )
    )
    
    # Apply filters
    if eq_class:
        # Filter by equipment class name
        query = query.join(EquipmentClass, isouter=True).filter(
            EquipmentClass.name.ilike(f'%{eq_class}%')
        )
    
    if eq_subclass:
        # Filter by equipment subclass name
        query = query.join(EquipmentSubclass, isouter=True).filter(
            EquipmentSubclass.name.ilike(f'%{eq_subclass}%')
        )
    
    if eq_fac:
        # Filter by facility name
        query = query.join(Facility, isouter=True).filter(
            Facility.name.ilike(f'%{eq_fac}%')
        )
    
    if search:
        # Free text search across multiple fields
        search_term = f'%{search}%'
        query = query.outerjoin(EquipmentClass).outerjoin(Manufacturer).outerjoin(Department).outerjoin(Facility).filter(
            or_(
                Equipment.eq_mod.ilike(search_term),
                Equipment.eq_rm.ilike(search_term),
                Equipment.eq_assetid.ilike(search_term),
                Equipment.eq_sn.ilike(search_term),
                EquipmentClass.name.ilike(search_term),
                Manufacturer.name.ilike(search_term),
                Department.name.ilike(search_term),
                Facility.name.ilike(search_term)
            )
        )
    
    active_equipment = query.all()
    
    # Get filter choices for dropdowns
    classes = db.session.query(EquipmentClass.name).join(Equipment).filter(EquipmentClass.is_active == True).distinct().order_by(EquipmentClass.name).all()
    classes = [c[0] for c in classes if c[0]]
    
    subclasses = []
    if eq_class:
        # Get subclasses for specific class
        subclasses = db.session.query(EquipmentSubclass.name).join(Equipment).join(EquipmentClass).filter(
            EquipmentClass.name.ilike(f'%{eq_class}%'),
            EquipmentSubclass.is_active == True
        ).distinct().order_by(EquipmentSubclass.name).all()
        subclasses = [s[0] for s in subclasses if s[0]]
    else:
        # Get all subclasses
        subclasses = db.session.query(EquipmentSubclass.name).join(Equipment).filter(EquipmentSubclass.is_active == True).distinct().order_by(EquipmentSubclass.name).all()
        subclasses = [s[0] for s in subclasses if s[0]]
    
    facilities = db.session.query(Facility.name).join(Equipment).filter(Facility.is_active == True).distinct().order_by(Facility.name).all()
    facilities = [f[0] for f in facilities if f[0]]

    # Get all scheduled tests from ScheduledTest table
    all_scheduled_tests = ScheduledTest.query.order_by(ScheduledTest.scheduled_date.asc()).all()

    # Create a dictionary mapping equipment ID to earliest scheduled test
    # Only include scheduled dates that are more than a month after the last test date (or if no test exists)
    scheduled_by_equipment = {}
    for test in all_scheduled_tests:
        if test.eq_id not in scheduled_by_equipment:
            equipment = Equipment.query.get(test.eq_id)
            if equipment:
                last_tested = equipment.get_last_tested_date()
                # Include if no previous test, or scheduled date is more than 30 days after last test
                if not last_tested or test.scheduled_date > last_tested + timedelta(days=30):
                    scheduled_by_equipment[test.eq_id] = test

    # Add scheduled tests to the scheduled_tests list (future dates only)
    for test in all_scheduled_tests:
        if test.scheduled_date >= today:
            equipment = Equipment.query.get(test.eq_id)
            if equipment and not (equipment.eq_retired or (equipment.eq_retdate and equipment.eq_retdate <= today)):
                scheduled_tests.append((test, equipment))

    for equipment in active_equipment:
        next_due = equipment.get_next_due_date()
        
        if next_due:
            # Create a fake test object to maintain template compatibility
            class FakeComplianceTest:
                def __init__(self, next_due_date, last_tested_date):
                    self.test_type = 'Annual'
                    self.next_due_date = next_due_date
                    self.last_tested_date = last_tested_date
                
                def get_test_type_display(self):
                    return 'Annual'
            
            last_tested = equipment.get_last_tested_date()
            fake_test = FakeComplianceTest(next_due, last_tested)
            
            if next_due < today:
                # Overdue
                overdue_tests.append((fake_test, equipment))
            elif next_due <= today + timedelta(days=days_ahead):
                # Upcoming within specified days
                upcoming_tests.append((fake_test, equipment))
    
    # Sort by due date
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

@app.route('/compliance/test/<int:eq_id>/new', methods=['GET', 'POST'])
@login_required
@manage_compliance_required
def compliance_test_new(eq_id):
    equipment = Equipment.query.get_or_404(eq_id)
    form = ComplianceTestForm()
    
    # Get redirect parameter from URL
    redirect_to = request.args.get('redirect_to', 'equipment')
    
    # Populate personnel choices
    # For performed_by: physics assistant or physicist
    performed_by_personnel = Personnel.query.filter(
        Personnel.roles.ilike('%physics_assistant%') | 
        Personnel.roles.ilike('%physicist%')
    ).order_by(Personnel.name).all()
    form.performed_by_id.choices = [('', 'Select...')] + [(p.id, p.name) for p in performed_by_personnel]
    
    # For reviewing physicist: physicist only
    reviewed_by_personnel = Personnel.query.filter(Personnel.roles.ilike('%physicist%')).order_by(Personnel.name).all()
    form.reviewed_by_id.choices = [('', 'Select...')] + [(p.id, p.name) for p in reviewed_by_personnel]
    
    if form.validate_on_submit():
        test = ComplianceTest()
        form.populate_obj(test)
        test.eq_id = eq_id
        
        # Personnel IDs are already handled by coerce function
        # Empty strings are converted to None by the form's coerce parameter
        
        # Add audit info
        if current_user.is_authenticated:
            user_initials = extract_personnel_initials(current_user.name)
            test.created_by = user_initials
            test.modified_by = user_initials
        
        db.session.add(test)
        db.session.commit()
        flash('Compliance test added successfully!', 'success')

        # Redirect based on parameter
        if redirect_to == 'compliance':
            return redirect(url_for('compliance_dashboard'))
        else:
            # Preserve filter parameters when redirecting back
            filter_params = {k: v for k, v in request.args.items() if k != 'redirect_to'}
            return redirect(url_for('equipment_detail', eq_id=eq_id, **filter_params))
    
    return render_template('compliance_test_form.html', form=form, equipment=equipment, title='Add Compliance Test', redirect_to=redirect_to, test=None)

@app.route('/compliance/test/<int:test_id>/edit', methods=['GET', 'POST'])
@login_required
@manage_compliance_required
def compliance_test_edit(test_id):
    test = ComplianceTest.query.get_or_404(test_id)
    equipment = Equipment.query.get_or_404(test.eq_id)
    form = ComplianceTestForm(obj=test)
    
    # Get redirect parameter from URL
    redirect_to = request.args.get('redirect_to', 'equipment')
    
    # Populate personnel choices
    # For performed_by: physics assistant or physicist
    performed_by_personnel = Personnel.query.filter(
        Personnel.roles.ilike('%physics_assistant%') | 
        Personnel.roles.ilike('%physicist%')
    ).order_by(Personnel.name).all()
    form.performed_by_id.choices = [('', 'Select...')] + [(p.id, p.name) for p in performed_by_personnel]
    
    # For reviewing physicist: physicist only
    reviewed_by_personnel = Personnel.query.filter(Personnel.roles.ilike('%physicist%')).order_by(Personnel.name).all()
    form.reviewed_by_id.choices = [('', 'Select...')] + [(p.id, p.name) for p in reviewed_by_personnel]
    
    if form.validate_on_submit():
        form.populate_obj(test)
        
        # Add audit info for modification
        if current_user.is_authenticated:
            user_initials = extract_personnel_initials(current_user.name)
            test.modified_by = user_initials
        
        db.session.commit()
        flash('Compliance test updated successfully!', 'success')

        # Redirect based on parameter
        if redirect_to == 'compliance':
            return redirect(url_for('compliance_dashboard'))
        else:
            # Preserve filter parameters when redirecting back
            filter_params = {k: v for k, v in request.args.items() if k != 'redirect_to'}
            return redirect(url_for('equipment_detail', eq_id=test.eq_id, **filter_params))
    
    return render_template('compliance_test_form.html', form=form, equipment=equipment, title='Edit Compliance Test', redirect_to=redirect_to, test=test)

@app.route('/compliance/test/<int:test_id>/delete', methods=['POST'])
@login_required
@manage_compliance_required
def compliance_test_delete(test_id):
    test = ComplianceTest.query.get_or_404(test_id)
    eq_id = test.eq_id

    # Get redirect parameter from form or URL
    redirect_to = request.form.get('redirect_to') or request.args.get('redirect_to', 'equipment')

    db.session.delete(test)
    db.session.commit()
    flash('Compliance test deleted successfully!', 'success')

    # Redirect based on parameter
    if redirect_to == 'compliance':
        return redirect(url_for('compliance_dashboard'))
    else:
        # Preserve filter parameters from POST form data
        filter_params = {k: v for k, v in request.form.items() if k not in ['redirect_to', 'csrf_token']}
        return redirect(url_for('equipment_detail', eq_id=eq_id, **filter_params))

@app.route('/schedule/test/<int:eq_id>/new', methods=['GET', 'POST'])
@login_required
@manage_compliance_required
def schedule_test_new(eq_id):
    equipment = Equipment.query.get_or_404(eq_id)
    form = ScheduleTestForm()

    # Get redirect parameter from URL
    redirect_to = request.args.get('redirect_to', 'equipment')

    if form.validate_on_submit():
        scheduled_test = ScheduledTest()
        form.populate_obj(scheduled_test)
        scheduled_test.eq_id = eq_id

        # Add user stamp
        if current_user.is_authenticated:
            scheduled_test.created_by_id = current_user.id
            scheduled_test.modified_by_id = current_user.id

        db.session.add(scheduled_test)
        db.session.commit()
        flash('Test scheduled successfully!', 'success')

        # Redirect based on parameter
        if redirect_to == 'compliance':
            return redirect(url_for('compliance_dashboard'))
        else:
            # Preserve filter parameters when redirecting back
            filter_params = {k: v for k, v in request.args.items() if k != 'redirect_to'}
            return redirect(url_for('equipment_detail', eq_id=eq_id, **filter_params))

    return render_template('schedule_test_form.html', form=form, equipment=equipment, title='Schedule Test', redirect_to=redirect_to, scheduled_test=None)

@app.route('/schedule/test/<int:schedule_id>/edit', methods=['GET', 'POST'])
@login_required
@manage_compliance_required
def schedule_test_edit(schedule_id):
    scheduled_test = ScheduledTest.query.get_or_404(schedule_id)
    equipment = Equipment.query.get_or_404(scheduled_test.eq_id)
    form = ScheduleTestForm(obj=scheduled_test)

    # Get redirect parameter from URL
    redirect_to = request.args.get('redirect_to', 'equipment')

    if form.validate_on_submit():
        form.populate_obj(scheduled_test)

        # Update user stamp
        if current_user.is_authenticated:
            scheduled_test.modified_by_id = current_user.id

        db.session.commit()
        flash('Scheduled test updated successfully!', 'success')

        # Redirect based on parameter
        if redirect_to == 'compliance':
            return redirect(url_for('compliance_dashboard'))
        else:
            # Preserve filter parameters when redirecting back
            filter_params = {k: v for k, v in request.args.items() if k != 'redirect_to'}
            return redirect(url_for('equipment_detail', eq_id=scheduled_test.eq_id, **filter_params))

    return render_template('schedule_test_form.html', form=form, equipment=equipment, title='Edit Scheduled Test', redirect_to=redirect_to, scheduled_test=scheduled_test)

@app.route('/schedule/test/<int:schedule_id>/delete', methods=['POST'])
@login_required
@manage_compliance_required
def schedule_test_delete(schedule_id):
    scheduled_test = ScheduledTest.query.get_or_404(schedule_id)
    eq_id = scheduled_test.eq_id

    # Get redirect parameter from form or URL
    redirect_to = request.form.get('redirect_to') or request.args.get('redirect_to', 'equipment')

    db.session.delete(scheduled_test)
    db.session.commit()
    flash('Scheduled test deleted successfully!', 'success')

    # Redirect based on parameter
    if redirect_to == 'compliance':
        return redirect(url_for('compliance_dashboard'))
    else:
        # Preserve filter parameters from POST form data
        filter_params = {k: v for k, v in request.form.items() if k not in ['redirect_to', 'csrf_token']}
        return redirect(url_for('equipment_detail', eq_id=eq_id, **filter_params))

@app.route('/api/equipment')
def api_equipment():
    equipment = Equipment.query.all()
    return jsonify([eq.to_dict() for eq in equipment])

@app.route('/api/subclasses')
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
        # Get subclasses for specific class (by ID - for equipment forms)
        subclasses = EquipmentSubclass.query.filter_by(
            class_id=int(class_id), is_active=True
        ).order_by(EquipmentSubclass.name).all()
    else:
        # Get all subclasses
        subclasses = EquipmentSubclass.query.filter_by(is_active=True).order_by(EquipmentSubclass.name).all()

    # Return different format based on request
    if class_id:
        # Return id/name pairs for forms
        subclass_list = [{'id': s.id, 'name': s.name} for s in subclasses]
    else:
        # Return names only for list filtering (backward compatibility)
        subclass_list = [s.name for s in subclasses]

    return jsonify(subclass_list)

@app.route('/api/facility/<int:facility_id>/address')
def api_facility_address(facility_id):
    """API endpoint to get facility address by ID"""
    facility = Facility.query.get(facility_id)
    if facility:
        return jsonify({'address': facility.address or ''})
    return jsonify({'address': ''}), 404

@app.route('/export-equipment')
def export_equipment():
    from sqlalchemy import and_, or_
    # Get all equipment or apply filters like in equipment_list
    eq_class = request.args.get('eq_class')
    eq_manu = request.args.get('eq_manu')
    eq_dept = request.args.get('eq_dept')
    eq_fac = request.args.get('eq_fac')
    include_retired = request.args.get('include_retired', 'false')
    
    # Build query with proper joins for relational data (same as equipment_list)
    query = Equipment.query.join(
        EquipmentClass, Equipment.class_id == EquipmentClass.id, isouter=True
    ).join(
        EquipmentSubclass, Equipment.subclass_id == EquipmentSubclass.id, isouter=True
    ).join(
        Manufacturer, Equipment.manufacturer_id == Manufacturer.id, isouter=True
    ).join(
        Department, Equipment.department_id == Department.id, isouter=True
    ).join(
        Facility, Equipment.facility_id == Facility.id, isouter=True
    ).join(
        Personnel, Equipment.contact_id == Personnel.id, isouter=True
    )
    
    # Apply filters using relational data
    if eq_class:
        query = query.filter(EquipmentClass.name == eq_class)
    if eq_manu:
        query = query.filter(Manufacturer.name == eq_manu)
    if eq_dept:
        query = query.filter(Department.name == eq_dept)
    if eq_fac:
        query = query.filter(Facility.name == eq_fac)
    
    # By default, only show active equipment unless include_retired is checked
    if include_retired != 'true':
        query = query.filter(
            and_(
                Equipment.eq_retired == False,
                or_(
                    Equipment.eq_retdate.is_(None),
                    Equipment.eq_retdate > datetime.now().date()
                )
            )
        )
    
    equipment_list = query.all()
    
    # Create CSV content
    from io import StringIO
    import csv
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Write header - using relational field names
    headers = [
        'eq_id', 'equipment_class', 'equipment_subclass', 'manufacturer', 'eq_mod', 'department', 'eq_rm', 'eq_phone', 'facility', 'facility_address',
        'contact_id', 'contact_person', 'contact_email', 'supervisor_id', 'supervisor', 'supervisor_email', 'physician_id', 'physician', 'physician_email',
        'eq_assetid', 'eq_sn', 'eq_mefac', 'eq_mereg', 'eq_mefacreg', 'eq_manid',
        'eq_mandt', 'eq_rfrbdt', 'eq_instdt', 'eq_eoldate', 'eq_eeoldate', 'eq_retdate', 'eq_retired',
        'eq_physcov', 'eq_auditfreq', 'eq_acrsite', 'eq_acrunit', 'eq_radcap', 'eq_capfund', 'eq_capcat', 'eq_capcst', 'eq_capecst', 'eq_capnote', 'eq_notes'
    ]
    writer.writerow(headers)
    
    # Write data - using relational data
    for eq in equipment_list:
        row = [
            eq.eq_id, 
            eq.equipment_class.name if eq.equipment_class else '',
            eq.equipment_subclass.name if eq.equipment_subclass else '',
            eq.manufacturer.name if eq.manufacturer else '',
            eq.eq_mod or '',
            eq.department.name if eq.department else '',
            eq.eq_rm or '',
            eq.eq_phone or '',
            eq.facility.name if eq.facility else '',
            eq.facility.address if eq.facility else '',
            eq.contact_id if eq.contact_id else '',
            eq.contact.name if eq.contact else '',
            eq.contact.email if eq.contact else '',
            eq.supervisor_id if eq.supervisor_id else '',
            eq.supervisor.name if eq.supervisor else '',
            eq.supervisor.email if eq.supervisor else '',
            eq.physician_id if eq.physician_id else '',
            eq.physician.name if eq.physician else '',
            eq.physician.email if eq.physician else '',
            eq.eq_assetid or '', eq.eq_sn or '', eq.eq_mefac or '', eq.eq_mereg or '', eq.eq_mefacreg or '', eq.eq_manid or '',
            eq.eq_mandt.strftime('%Y-%m-%d') if eq.eq_mandt else '',
            eq.eq_rfrbdt.strftime('%Y-%m-%d') if eq.eq_rfrbdt else '',
            eq.eq_instdt.strftime('%Y-%m-%d') if eq.eq_instdt else '',
            eq.eq_eoldate.strftime('%Y-%m-%d') if eq.eq_eoldate else '',
            eq.eq_eeoldate.strftime('%Y-%m-%d') if eq.eq_eeoldate else '',
            eq.eq_retdate.strftime('%Y-%m-%d') if eq.eq_retdate else '',
            'TRUE' if eq.eq_retired else 'FALSE',
            'TRUE' if eq.eq_physcov else 'FALSE',
            eq.eq_auditfreq or '', eq.eq_acrsite or '', eq.eq_acrunit or '',
            eq.eq_radcap if eq.eq_radcap is not None else '',
            eq.eq_capfund if eq.eq_capfund is not None else '',
            eq.eq_capcat if eq.eq_capcat is not None else '',
            eq.eq_capcst or '',
            eq.eq_capecst or '',
            eq.eq_capnote or '',
            eq.eq_notes or ''
        ]
        writer.writerow(row)
    
    # Create response
    from flask import Response
    csv_content = output.getvalue()
    output.close()
    
    # Generate filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'equipment_export_{timestamp}.csv'
    
    return Response(
        csv_content,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )

@app.route('/bulk-edit', methods=['GET', 'POST'])
def bulk_edit():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)
        
        if file and file.filename.endswith('.csv'):
            try:
                # Read CSV file
                content = file.read().decode('utf-8')
                csv_reader = csv.DictReader(StringIO(content))
                
                # Update data
                updated_count = 0
                error_count = 0
                errors = []
                
                for row in csv_reader:
                    try:
                        # Get equipment ID
                        eq_id = row.get('eq_id')
                        if not eq_id or eq_id == '':
                            continue
                        
                        # Find existing equipment
                        equipment = Equipment.query.get(int(eq_id))
                        if not equipment:
                            error_count += 1
                            errors.append(f"Equipment ID {eq_id} not found")
                            continue
                        
                        # Update fields - handle both new and legacy CSV formats
                        # Equipment Class
                        eq_class_val = row.get('Equipment Class') or row.get('eq_class')
                        if eq_class_val and str(eq_class_val).strip():
                            class_name = str(eq_class_val).strip()
                            equipment_class = EquipmentClass.query.filter_by(name=class_name).first()
                            if not equipment_class:
                                equipment_class = EquipmentClass(name=class_name)
                                db.session.add(equipment_class)
                                db.session.flush()
                            equipment.class_id = equipment_class.id
                        
                        # Equipment Subclass
                        eq_subclass_val = row.get('Equipment Subclass') or row.get('eq_subclass')
                        if eq_subclass_val and str(eq_subclass_val).strip():
                            subclass_name = str(eq_subclass_val).strip()
                            equipment_subclass = EquipmentSubclass.query.filter_by(name=subclass_name).first()
                            if not equipment_subclass:
                                equipment_subclass = EquipmentSubclass(name=subclass_name)
                                db.session.add(equipment_subclass)
                                db.session.flush()
                            equipment.subclass_id = equipment_subclass.id
                        
                        # Manufacturer
                        eq_manu_val = row.get('Manufacturer') or row.get('eq_manu')
                        if eq_manu_val and str(eq_manu_val).strip():
                            manu_name = str(eq_manu_val).strip()
                            manufacturer = Manufacturer.query.filter_by(name=manu_name).first()
                            if not manufacturer:
                                manufacturer = Manufacturer(name=manu_name)
                                db.session.add(manufacturer)
                                db.session.flush()
                            equipment.manufacturer_id = manufacturer.id
                        
                        # Department
                        eq_dept_val = row.get('Department') or row.get('eq_dept')
                        if eq_dept_val and str(eq_dept_val).strip():
                            dept_name = str(eq_dept_val).strip()
                            department = Department.query.filter_by(name=dept_name).first()
                            if not department:
                                department = Department(name=dept_name)
                                db.session.add(department)
                                db.session.flush()
                            equipment.department_id = department.id
                        
                        # Facility
                        eq_fac_val = row.get('Facility') or row.get('eq_fac')
                        if eq_fac_val and str(eq_fac_val).strip():
                            fac_name = str(eq_fac_val).strip()
                            facility = Facility.query.filter_by(name=fac_name).first()
                            if not facility:
                                fac_address = row.get('Facility Address') or row.get('eq_address') or ''
                                facility = Facility(name=fac_name, address=str(fac_address).strip())
                                db.session.add(facility)
                                db.session.flush()
                            equipment.facility_id = facility.id
                        
                        # Contact Personnel (using ID-based matching)
                        contact_id = row.get('contact_id')
                        contact_name = row.get('contact_person') or row.get('Primary Contact') or row.get('eq_contact')
                        contact_email = row.get('contact_email') or row.get('Contact Email') or row.get('eq_contactinfo')
                        
                        contact = get_or_create_personnel(contact_id, contact_name, contact_email, 'contact')
                        if contact:
                            equipment.contact_id = contact.id
                        
                        # Direct fields
                        equipment.eq_mod = str(row.get('eq_mod', '')).strip()
                        equipment.eq_rm = str(row.get('eq_rm', '')).strip()
                        equipment.eq_phone = str(row.get('eq_phone', '')).strip()
                        equipment.eq_assetid = str(row.get('eq_assetid', '')).strip()
                        equipment.eq_sn = str(row.get('eq_sn', '')).strip()
                        equipment.eq_mefac = str(row.get('eq_mefac', '')).strip()
                        equipment.eq_mereg = str(row.get('eq_mereg', '')).strip()
                        equipment.eq_mefacreg = str(row.get('eq_mefacreg', '')).strip()
                        equipment.eq_manid = str(row.get('eq_manid', '')).strip()
                        
                        # Handle dates
                        date_fields = ['eq_mandt', 'eq_instdt', 'eq_eoldate', 'eq_eeoldate', 'eq_retdate']
                        for field in date_fields:
                            date_val = str(row.get(field, '')).strip()
                            if date_val and date_val != '':
                                try:
                                    # Try different date formats
                                    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y'):
                                        try:
                                            date_obj = datetime.strptime(date_val, fmt).date()
                                            setattr(equipment, field, date_obj)
                                            break
                                        except ValueError:
                                            continue
                                except:
                                    pass
                            else:
                                setattr(equipment, field, None)
                        
                        # Handle boolean
                        retired_val = str(row.get('eq_retired', '')).strip().upper()
                        equipment.eq_retired = retired_val in ('TRUE', 'YES', '1')
                        
                        # Handle audit frequency (string field - can be comma-separated)
                        audit_freq = str(row.get('eq_auditfreq', '')).strip()
                        if audit_freq and audit_freq != '':
                            valid_frequencies = ['Quarterly', 'Semiannual', 'Annual - ACR', 'Annual - TJC', 'Annual - ME']

                            # Check if it's comma-separated (multiple frequencies)
                            if ',' in audit_freq:
                                # Validate all frequencies in the list
                                freq_list = [f.strip() for f in audit_freq.split(',')]
                                valid_freqs = [f for f in freq_list if f in valid_frequencies]
                                if valid_freqs:
                                    equipment.eq_auditfreq = ', '.join(valid_freqs)
                                else:
                                    equipment.eq_auditfreq = 'Annual - TJC'  # Default
                            elif audit_freq in valid_frequencies:
                                # Single valid frequency
                                equipment.eq_auditfreq = audit_freq
                            else:
                                # Try to convert from old integer format
                                try:
                                    freq_int = int(float(audit_freq))
                                    if freq_int <= 3:
                                        equipment.eq_auditfreq = 'Quarterly'
                                    elif freq_int <= 6:
                                        equipment.eq_auditfreq = 'Semiannual'
                                    elif freq_int == 14:
                                        equipment.eq_auditfreq = 'Annual - ACR'
                                    else:
                                        equipment.eq_auditfreq = 'Annual - TJC'
                                except:
                                    equipment.eq_auditfreq = 'Annual - TJC'  # Default
                        else:
                            equipment.eq_auditfreq = None
                        
                        # Handle integers
                        int_fields = ['eq_radcap', 'eq_capcat', 'eq_capcst']
                        for field in int_fields:
                            val = str(row.get(field, '')).strip()
                            if val and val != '':
                                try:
                                    setattr(equipment, field, int(float(val)))
                                except:
                                    setattr(equipment, field, None)
                            else:
                                setattr(equipment, field, None)
                        
                        equipment.eq_acrsite = str(row.get('eq_acrsite', '')).strip()
                        equipment.eq_acrunit = str(row.get('eq_acrunit', '')).strip()
                        equipment.eq_notes = str(row.get('eq_notes', '')).strip()
                        
                        updated_count += 1
                        
                    except Exception as e:
                        error_count += 1
                        errors.append(f"Error updating equipment ID {eq_id}: {str(e)}")
                
                db.session.commit()
                
                success_message = f'Successfully updated {updated_count} equipment records!'
                if error_count > 0:
                    success_message += f' ({error_count} errors)'
                
                flash(success_message, 'success')
                
                if errors:
                    for error in errors[:5]:  # Show first 5 errors
                        flash(error, 'warning')
                    if len(errors) > 5:
                        flash(f'... and {len(errors) - 5} more errors', 'warning')
                
                return redirect(url_for('equipment_list'))
                
            except Exception as e:
                flash(f'Error processing file: {str(e)}', 'error')
                return redirect(request.url)
        
        flash('Please select a CSV file', 'error')
    
    return render_template('bulk_edit.html')

@app.route('/import-data', methods=['GET', 'POST'])
def import_data():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)
        
        if file and file.filename.endswith('.csv'):
            try:
                # Read CSV file
                df = pd.read_csv(file)
                
                # Import data
                imported_count = 0
                updated_count = 0
                skipped_count = 0
                for index, row in df.iterrows():
                    # Skip completely empty rows
                    if row.isna().all():
                        print(f"Skipping empty row {index + 1}")
                        skipped_count += 1
                        continue
                    
                    # Require Equipment Class - this is mandatory data (match export format)
                    eq_class = row.get('equipment_class') or row.get('Equipment Class') or row.get('eq_class')
                    if pd.isna(eq_class) or eq_class == '' or str(eq_class).strip() == '':
                        print(f"Row {index + 1}: Missing equipment_class. Available columns: {list(row.index)}")
                        skipped_count += 1
                        continue
                    
                    # Check if equipment with this ID already exists
                    eq_id = row.get('eq_id')
                    if pd.notna(eq_id) and eq_id != '':
                        try:
                            equipment = Equipment.query.get(int(eq_id))
                            if equipment:
                                # Update existing equipment
                                is_update = True
                            else:
                                # Create new equipment with specified ID
                                equipment = Equipment()
                                equipment.eq_id = int(eq_id)
                                is_update = False
                        except (ValueError, TypeError):
                            # Invalid ID, create new equipment
                            equipment = Equipment()
                            is_update = False
                    else:
                        # No ID provided, create new equipment
                        equipment = Equipment()
                        is_update = False
                    
                    # Map CSV columns to database fields - match export format
                    # Equipment Class
                    eq_class_val = row.get('equipment_class') or row.get('Equipment Class') or row.get('eq_class')
                    if eq_class_val and str(eq_class_val).strip():
                        class_name = str(eq_class_val).strip()
                        equipment_class = EquipmentClass.query.filter_by(name=class_name).first()
                        if not equipment_class:
                            equipment_class = EquipmentClass(name=class_name)
                            db.session.add(equipment_class)
                            db.session.flush()  # Get the ID
                        equipment.class_id = equipment_class.id
                    
                    # Equipment Subclass (only if we have a class)
                    eq_subclass_val = row.get('equipment_subclass') or row.get('Equipment Subclass') or row.get('eq_subclass')
                    if eq_subclass_val and str(eq_subclass_val).strip() and hasattr(equipment, 'class_id') and equipment.class_id:
                        subclass_name = str(eq_subclass_val).strip()
                        equipment_subclass = EquipmentSubclass.query.filter_by(name=subclass_name).first()
                        if not equipment_subclass:
                            equipment_subclass = EquipmentSubclass(name=subclass_name, class_id=equipment.class_id)
                            db.session.add(equipment_subclass)
                            db.session.flush()
                        equipment.subclass_id = equipment_subclass.id
                    
                    # Manufacturer
                    eq_manu_val = row.get('manufacturer') or row.get('Manufacturer') or row.get('eq_manu')
                    if eq_manu_val and str(eq_manu_val).strip():
                        manu_name = str(eq_manu_val).strip()
                        manufacturer = Manufacturer.query.filter_by(name=manu_name).first()
                        if not manufacturer:
                            manufacturer = Manufacturer(name=manu_name)
                            db.session.add(manufacturer)
                            db.session.flush()
                        equipment.manufacturer_id = manufacturer.id
                    
                    # Department
                    eq_dept_val = row.get('department') or row.get('Department') or row.get('eq_dept')
                    if eq_dept_val and str(eq_dept_val).strip():
                        dept_name = str(eq_dept_val).strip()
                        department = Department.query.filter_by(name=dept_name).first()
                        if not department:
                            department = Department(name=dept_name)
                            db.session.add(department)
                            db.session.flush()
                        equipment.department_id = department.id
                    
                    # Facility
                    eq_fac_val = row.get('facility') or row.get('Facility') or row.get('eq_fac')
                    if eq_fac_val and str(eq_fac_val).strip():
                        fac_name = str(eq_fac_val).strip()
                        facility = Facility.query.filter_by(name=fac_name).first()
                        if not facility:
                            # Try to get address from CSV
                            fac_address = row.get('facility_address') or row.get('Facility Address') or row.get('eq_address') or ''
                            facility = Facility(name=fac_name, address=str(fac_address).strip())
                            db.session.add(facility)
                            db.session.flush()
                        equipment.facility_id = facility.id
                    
                    # Contact Personnel (using ID-based matching)
                    contact_id = row.get('contact_id')
                    contact_name = row.get('contact_person') or row.get('Primary Contact') or row.get('eq_contact')
                    contact_email = row.get('contact_email') or row.get('Contact Email') or row.get('eq_contactinfo')
                    
                    contact = get_or_create_personnel(contact_id, contact_name, contact_email, 'contact')
                    if contact:
                        equipment.contact_id = contact.id
                    
                    # Supervisor Personnel (using ID-based matching)
                    supervisor_id = row.get('supervisor_id')
                    supervisor_name = row.get('supervisor') or row.get('eq_sup')
                    supervisor_email = row.get('supervisor_email') or row.get('eq_supinfo')
                    
                    supervisor = get_or_create_personnel(supervisor_id, supervisor_name, supervisor_email, 'supervisor')
                    if supervisor:
                        equipment.supervisor_id = supervisor.id
                    
                    # Physician Personnel (using ID-based matching)
                    physician_id = row.get('physician_id')
                    physician_name = row.get('physician') or row.get('eq_physician')
                    physician_email = row.get('physician_email') or row.get('eq_physicianinfo')
                    
                    physician = get_or_create_personnel(physician_id, physician_name, physician_email, 'physician')
                    if physician:
                        equipment.physician_id = physician.id
                    
                    # Model and Room - direct fields
                    equipment.eq_mod = row.get('eq_mod')
                    equipment.eq_rm = row.get('eq_rm')
                    equipment.eq_phone = row.get('eq_phone')
                    equipment.eq_assetid = row.get('eq_assetid')
                    equipment.eq_sn = row.get('eq_sn')
                    equipment.eq_mefac = row.get('eq_mefac')
                    equipment.eq_mereg = row.get('eq_mereg')
                    equipment.eq_mefacreg = row.get('eq_mefacreg')
                    equipment.eq_manid = row.get('eq_manid')
                    
                    # Handle dates
                    date_fields = ['eq_mandt', 'eq_rfrbdt', 'eq_instdt', 'eq_eoldate', 'eq_eeoldate', 'eq_retdate']
                    for field in date_fields:
                        date_val = row.get(field)
                        if pd.notna(date_val) and date_val != '':
                            try:
                                setattr(equipment, field, pd.to_datetime(date_val).date())
                            except:
                                pass

                    # Handle boolean fields
                    retired_val = row.get('eq_retired')
                    if pd.notna(retired_val):
                        # Handle various boolean representations
                        if isinstance(retired_val, bool):
                            equipment.eq_retired = retired_val
                        elif isinstance(retired_val, (int, float)):
                            # Handle numeric values: 1 = True, 0 = False
                            equipment.eq_retired = bool(retired_val)
                        else:
                            # Handle string values
                            str_val = str(retired_val).strip().upper()
                            equipment.eq_retired = str_val in ['TRUE', '1', 'YES', 'Y']
                    else:
                        equipment.eq_retired = False

                    physcov_val = row.get('eq_physcov')
                    if pd.notna(physcov_val):
                        if isinstance(physcov_val, bool):
                            equipment.eq_physcov = physcov_val
                        elif isinstance(physcov_val, (int, float)):
                            equipment.eq_physcov = bool(physcov_val)
                        else:
                            str_val = str(physcov_val).strip().upper()
                            equipment.eq_physcov = str_val in ['TRUE', '1', 'YES', 'Y']
                    else:
                        equipment.eq_physcov = True  # Default to covered
                    
                    # If equipment is retired but has no retirement date, set it to today
                    if equipment.eq_retired and not equipment.eq_retdate:
                        equipment.eq_retdate = datetime.now().date()
                    
                    # Handle audit frequency (string field - can be comma-separated)
                    audit_freq = row.get('eq_auditfreq')
                    if pd.notna(audit_freq) and audit_freq != '':
                        audit_freq_str = str(audit_freq).strip()
                        valid_frequencies = ['Quarterly', 'Semiannual', 'Annual - ACR', 'Annual - TJC', 'Annual - ME']

                        # Check if it's comma-separated (multiple frequencies)
                        if ',' in audit_freq_str:
                            # Validate all frequencies in the list
                            freq_list = [f.strip() for f in audit_freq_str.split(',')]
                            valid_freqs = [f for f in freq_list if f in valid_frequencies]
                            if valid_freqs:
                                equipment.eq_auditfreq = ', '.join(valid_freqs)
                            else:
                                equipment.eq_auditfreq = 'Annual - TJC'  # Default
                        elif audit_freq_str in valid_frequencies:
                            # Single valid frequency
                            equipment.eq_auditfreq = audit_freq_str
                        else:
                            # Try to convert from old integer format
                            try:
                                freq_int = int(float(audit_freq_str))
                                if freq_int <= 3:
                                    equipment.eq_auditfreq = 'Quarterly'
                                elif freq_int <= 6:
                                    equipment.eq_auditfreq = 'Semiannual'
                                elif freq_int == 14:
                                    equipment.eq_auditfreq = 'Annual - ACR'
                                else:
                                    equipment.eq_auditfreq = 'Annual - TJC'
                            except:
                                equipment.eq_auditfreq = 'Annual - TJC'  # Default
                    
                    # Handle integers
                    int_fields = ['eq_radcap', 'eq_capfund', 'eq_capcat', 'eq_capcst', 'eq_capecst']
                    for field in int_fields:
                        val = row.get(field)
                        if pd.notna(val) and val != '':
                            try:
                                setattr(equipment, field, int(val))
                            except:
                                pass

                    equipment.eq_acrsite = row.get('eq_acrsite')
                    equipment.eq_acrunit = row.get('eq_acrunit')
                    equipment.eq_capnote = row.get('eq_capnote')
                    equipment.eq_notes = row.get('eq_notes')
                    
                    if not is_update:
                        db.session.add(equipment)
                        imported_count += 1
                    else:
                        updated_count += 1
                
                db.session.commit()
                
                # Build success message
                messages = []
                if imported_count > 0:
                    messages.append(f'imported {imported_count} new equipment records')
                if updated_count > 0:
                    messages.append(f'updated {updated_count} existing equipment records')
                if skipped_count > 0:
                    messages.append(f'skipped {skipped_count} empty rows')
                
                success_message = 'Successfully ' + ', '.join(messages) + '!'
                flash(success_message, 'success')
                return redirect(url_for('equipment_list'))
                
            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                print(f"Equipment import error: {error_details}")
                flash(f'Error importing data: {str(e)}. Check logs for details.', 'error')
                return redirect(request.url)
        
        flash('Please select a CSV file', 'error')
    
    return render_template('import_data.html')

@app.route('/personnel')
@login_required
def personnel_list():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    # Filters
    search = request.args.get('search', '').strip()
    role_filter = request.args.get('role')
    
    # Base query
    query = Personnel.query
    
    # Apply filters
    if search:
        query = query.filter(Personnel.name.ilike(f'%{search}%') | 
                           Personnel.email.ilike(f'%{search}%'))
    
    if role_filter:
        query = query.filter(Personnel.roles.ilike(f'%{role_filter}%'))

    # Sort alphabetically by name
    query = query.order_by(Personnel.name)

    # Pagination
    personnel = query.paginate(page=page, per_page=per_page, error_out=False)
    
    # Get unique roles for filter dropdown
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

@app.route('/personnel/new', methods=['GET', 'POST'])
@login_required
@manage_personnel_required
def new_personnel():
    form = PersonnelForm()
    if form.validate_on_submit():
        personnel = Personnel(
            name=form.name.data,
            email=form.email.data,
            phone=form.phone.data,
            username=form.username.data if form.username.data else None,
            is_admin=form.is_admin.data,
            is_active=form.is_active.data,
            login_required=form.login_required.data
        )
        personnel.set_roles_list(form.roles.data)

        # Set password - use provided password or default to "radiology"
        password = form.password.data if form.password.data else "radiology"
        if form.username.data:  # Only set password if username is provided
            personnel.set_password(password)

        try:
            db.session.add(personnel)
            db.session.commit()
            flash('Personnel added successfully!', 'success')
            return redirect(url_for('personnel_list'))
        except Exception as e:
            db.session.rollback()
            flash('Error adding personnel. Email or username may already exist.', 'error')

    return render_template('personnel_form.html', form=form, title='Add Personnel')

@app.route('/personnel/<int:id>')
@login_required
def personnel_detail(id):
    personnel = Personnel.query.get_or_404(id)
    return render_template('personnel_detail.html', personnel=personnel)

@app.route('/personnel/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@manage_personnel_required
def edit_personnel(id):
    personnel = Personnel.query.get_or_404(id)
    form = PersonnelForm(obj=personnel)
    
    if request.method == 'GET':
        form.roles.data = personnel.get_roles_list()
        form.username.data = personnel.username
        form.is_admin.data = personnel.is_admin
        form.is_active.data = personnel.is_active
        form.login_required.data = personnel.login_required

    if form.validate_on_submit():
        personnel.name = form.name.data
        personnel.email = form.email.data
        personnel.phone = form.phone.data
        personnel.username = form.username.data if form.username.data else None
        personnel.is_admin = form.is_admin.data
        personnel.is_active = form.is_active.data
        personnel.login_required = form.login_required.data
        personnel.set_roles_list(form.roles.data)

        if form.password.data:
            personnel.set_password(form.password.data)

        try:
            db.session.commit()
            flash('Personnel updated successfully!', 'success')
            return redirect(url_for('personnel_detail', id=id))
        except Exception as e:
            db.session.rollback()
            flash('Error updating personnel.', 'error')

    return render_template('personnel_form.html', form=form, title='Edit Personnel', personnel=personnel)

@app.route('/personnel/<int:id>/delete', methods=['POST'])
@login_required
@manage_personnel_required
def delete_personnel(id):
    personnel = Personnel.query.get_or_404(id)
    try:
        db.session.delete(personnel)
        db.session.commit()
        flash('Personnel deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error deleting personnel.', 'error')
    
    return redirect(url_for('personnel_list'))


@app.route('/export-personnel')
def export_personnel():
    personnel = Personnel.query.all()
    
    # Define all possible roles
    all_roles = ['admin', 'contact', 'supervisor', 'physician', 'physicist', 'physics_assistant', 'qa_technologist']
    
    # Create CSV data
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write headers - basic info plus each role as a column
    headers = ['id', 'name', 'email', 'phone', 'login_required'] + all_roles
    writer.writerow(headers)
    
    # Write data
    for person in personnel:
        # Get person's roles as a list
        person_roles = person.get_roles_list()
        
        # Build row with basic info
        row = [
            person.id,
            person.name,
            person.email,
            person.phone,
            'TRUE' if person.login_required else 'FALSE'
        ]
        
        # Add true/false for each role
        for role in all_roles:
            row.append('TRUE' if role in person_roles else 'FALSE')
        
        writer.writerow(row)
    
    # Create response with timestamped filename
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'personnel_{timestamp}.csv'
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-Type'] = 'text/csv'
    
    return response

@app.route('/import-personnel', methods=['GET', 'POST'])
def import_personnel():
    form = BulkPersonnelForm()
    
    if form.validate_on_submit():
        file = form.csv_file.data
        
        try:
            # Read CSV
            df = pd.read_csv(file)
            
            # Expected columns
            required_columns = ['name', 'email']
            optional_columns = ['id', 'phone', 'login_required', 'roles']
            
            # Check required columns
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                flash(f'Missing required columns: {", ".join(missing_columns)}', 'error')
                return render_template('import_personnel.html', form=form)
            
            # Process each row
            imported_count = 0
            error_count = 0
            
            for index, row in df.iterrows():
                try:
                    # Skip completely empty rows
                    if row.isna().all():
                        print(f"Skipping empty row {index + 1}")
                        continue
                    
                    # Skip rows with empty name or email (required fields)
                    if pd.isna(row.get('name')) or pd.isna(row.get('email')) or str(row.get('name')).strip() == '' or str(row.get('email')).strip() == '':
                        print(f"Skipping row {index + 1}: Missing name or email")
                        continue
                    
                    # Check if personnel already exists by ID or email
                    personnel_id = row.get('id')
                    email = row['email']
                    
                    # Don't overwrite existing users - check by ID first, then email
                    personnel = None
                    is_new_user = True
                    
                    if personnel_id and not pd.isna(personnel_id):
                        personnel = Personnel.query.get(int(personnel_id))
                        if personnel:
                            is_new_user = False
                    
                    if not personnel:
                        # Check by email to avoid duplicates
                        personnel = Personnel.query.filter_by(email=email).first()
                        if personnel:
                            is_new_user = False
                    
                    if not personnel:
                        # Create new personnel only if doesn't exist
                        personnel = Personnel()
                        # Set ID if provided in CSV (but skip ID 0 which is reserved for admin)
                        if personnel_id and not pd.isna(personnel_id) and int(personnel_id) != 0:
                            personnel.id = int(personnel_id)
                        is_new_user = True
                    
                    # Set basic fields
                    personnel.name = row['name']
                    personnel.email = row['email']
                    personnel.phone = row.get('phone', '')
                    
                    # Handle login_required field
                    if 'login_required' in row and not pd.isna(row['login_required']):
                        personnel.login_required = str(row['login_required']).upper() == 'TRUE'
                    else:
                        personnel.login_required = False
                    
                    # Handle roles - check for both formats (comma-separated OR individual columns)
                    if 'roles' in row and not pd.isna(row['roles']):
                        # Simple comma-separated format
                        personnel.roles = row['roles']
                    else:
                        # Individual role columns (TRUE/FALSE format from export)
                        role_list = []
                        all_roles = ['admin', 'contact', 'supervisor', 'physician', 'physicist', 'physics_assistant', 'qa_technologist']
                        for role in all_roles:
                            if role in row and str(row[role]).upper() == 'TRUE':
                                role_list.append(role)
                        personnel.roles = ', '.join(role_list)
                    
                    # Set default login credentials for NEW users only
                    
                    if not personnel.username:
                        # Create username from email (part before @)
                        username = row['email'].split('@')[0].lower()
                        personnel.username = username
                    
                    # Set default password only for NEW users (don't overwrite existing passwords)
                    if is_new_user or not personnel.password_hash:
                        personnel.set_password('password123')
                    
                    personnel.is_active = True
                    
                    # Set admin status based on roles
                    if personnel.roles and 'admin' in personnel.roles.lower():
                        personnel.is_admin = True
                    
                    if is_new_user:
                        db.session.add(personnel)
                        imported_count += 1
                    
                except Exception as e:
                    error_count += 1
                    continue
            
            # Commit all changes
            db.session.commit()
            
            flash(f'Successfully imported {imported_count} personnel records. All users can log in with password "password123". {error_count} errors.', 'success')
            return redirect(url_for('personnel_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error processing file: {str(e)}', 'error')
    
    return render_template('import_personnel.html', form=form)

@app.route('/export-compliance')
def export_compliance():
    # Check if this is a request for sample template
    sample = request.args.get('sample', 'false').lower() == 'true'
    
    # Create CSV data
    output = io.StringIO()
    writer = csv.writer(output)
    
    if sample:
        # For sample template, use simplified headers matching import requirements
        headers = ['eq_id', 'test_type', 'test_date', 'report_date', 'submission_date', 'performed_by_id', 'reviewed_by_id', 'notes']
        writer.writerow(headers)
        
        # Create response for template
        response = make_response(output.getvalue())
        filename = 'compliance_tests_template.csv'
    else:
        # For full export, use complete headers with audit fields
        headers = ['test_id', 'eq_id', 'test_type', 'test_date', 'report_date', 'submission_date', 'performed_by', 'reviewed_by', 'notes', 'created_by', 'created_at', 'modified_by', 'updated_at']
        writer.writerow(headers)
        
        # Write data for all compliance tests
        compliance_tests = ComplianceTest.query.all()
        for test in compliance_tests:
            # Get personnel names from IDs
            performed_by_name = ''
            if test.performed_by_id:
                performed_by = Personnel.query.get(test.performed_by_id)
                performed_by_name = performed_by.name if performed_by else ''
                
            reviewed_by_name = ''
            if test.reviewed_by_id:
                reviewed_by = Personnel.query.get(test.reviewed_by_id)
                reviewed_by_name = reviewed_by.name if reviewed_by else ''
            
            writer.writerow([
                test.test_id,
                test.eq_id,
                test.test_type,
                test.test_date.strftime('%Y-%m-%d') if test.test_date else '',
                test.report_date.strftime('%Y-%m-%d') if test.report_date else '',
                test.submission_date.strftime('%Y-%m-%d') if test.submission_date else '',
                performed_by_name,
                reviewed_by_name,
                test.notes if test.notes else '',
                test.created_by if test.created_by else '',
                test.created_at.strftime('%Y-%m-%d %H:%M:%S') if test.created_at else '',
                test.modified_by if test.modified_by else '',
                test.updated_at.strftime('%Y-%m-%d %H:%M:%S') if test.updated_at else ''
            ])
        
        # Create response for full export
        response = make_response(output.getvalue())
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'compliance_tests_with_audit_{timestamp}.csv'
    
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-Type'] = 'text/csv'
    
    return response

class BulkComplianceForm(FlaskForm):
    csv_file = FileField('CSV File', validators=[DataRequired()])

@app.route('/import-compliance', methods=['GET', 'POST'])
@login_required
def import_compliance():
    form = BulkComplianceForm()
    
    if form.validate_on_submit():
        file = form.csv_file.data
        
        if file and file.filename.endswith('.csv'):
            try:
                # Read CSV
                df = pd.read_csv(file)
                
                # Expected columns
                required_columns = ['eq_id', 'test_type', 'test_date']
                optional_columns = ['test_id', 'report_date', 'submission_date', 'performed_by_id', 'reviewed_by_id', 'notes']
                
                # Check required columns
                missing_columns = [col for col in required_columns if col not in df.columns]
                if missing_columns:
                    flash(f'Missing required columns: {", ".join(missing_columns)}', 'error')
                    return redirect(request.url)
                
                # Process each row
                imported_count = 0
                error_count = 0
                
                for index, row in df.iterrows():
                    try:
                        # Check if updating existing test
                        test_id = row.get('test_id')
                        is_update = False
                        if test_id and not pd.isna(test_id):
                            test = ComplianceTest.query.get(int(test_id))
                            if not test:
                                # Create new test
                                test = ComplianceTest()
                            else:
                                is_update = True
                        else:
                            # Create new test
                            test = ComplianceTest()
                        
                        # Set fields
                        eq_id = int(row['eq_id'])
                        equipment = Equipment.query.get(eq_id)
                        if not equipment:
                            error_count += 1
                            available_ids = [str(eq.eq_id) for eq in Equipment.query.all()]
                            print(f"Row {index + 1}: Equipment ID {eq_id} not found. Available equipment IDs: {', '.join(available_ids[:10])}")
                            continue
                        
                        test.eq_id = eq_id
                        test.test_type = row['test_type']
                        test.test_date = pd.to_datetime(row['test_date']).date()
                        
                        # Handle optional report_date
                        if 'report_date' in row and not pd.isna(row['report_date']):
                            report_date_str = str(row['report_date']).strip().upper()
                            if report_date_str in ['CLEAR', 'NULL', 'NONE', '']:
                                test.report_date = None
                            elif row['report_date']:
                                test.report_date = pd.to_datetime(row['report_date']).date()
                        
                        # Handle optional submission_date
                        if 'submission_date' in row and not pd.isna(row['submission_date']):
                            submission_date_str = str(row['submission_date']).strip().upper()
                            if submission_date_str in ['CLEAR', 'NULL', 'NONE', '']:
                                test.submission_date = None
                            elif row['submission_date']:
                                test.submission_date = pd.to_datetime(row['submission_date']).date()
                        
                        # Handle performed_by_id 
                        performed_by_val = row.get('performed_by_id')
                        if performed_by_val and not pd.isna(performed_by_val):
                            performed_by_str = str(performed_by_val).strip().upper()
                            if performed_by_str in ['CLEAR', 'NULL', 'NONE', '']:
                                test.performed_by_id = None
                            else:
                                try:
                                    performed_by_id = int(performed_by_str)
                                    personnel_record = Personnel.query.get(performed_by_id)
                                    if personnel_record:
                                        test.performed_by_id = performed_by_id
                                    else:
                                        print(f"Warning: Personnel ID {performed_by_id} not found for performed_by in row {index + 1}")
                                except ValueError:
                                    print(f"Warning: Invalid personnel ID '{performed_by_val}' for performed_by in row {index + 1}")
                        
                        # Handle reviewed_by_id
                        reviewed_by_val = row.get('reviewed_by_id')
                        if reviewed_by_val and not pd.isna(reviewed_by_val):
                            reviewed_by_str = str(reviewed_by_val).strip().upper()
                            if reviewed_by_str in ['CLEAR', 'NULL', 'NONE', '']:
                                test.reviewed_by_id = None
                            else:
                                try:
                                    reviewed_by_id = int(reviewed_by_str)
                                    personnel_record = Personnel.query.get(reviewed_by_id)
                                    if personnel_record:
                                        test.reviewed_by_id = reviewed_by_id
                                    else:
                                        print(f"Warning: Personnel ID {reviewed_by_id} not found for reviewed_by in row {index + 1}")
                                except ValueError:
                                    print(f"Warning: Invalid personnel ID '{reviewed_by_val}' for reviewed_by in row {index + 1}")
                        
                        if 'notes' in row and not pd.isna(row['notes']):
                            notes_str = str(row['notes']).strip().upper()
                            if notes_str in ['CLEAR', 'NULL', 'NONE']:
                                test.notes = None
                            else:
                                test.notes = row['notes']
                        
                        # Add audit info based on current user
                        if current_user.is_authenticated:
                            user_initials = extract_personnel_initials(current_user.name)
                            if not is_update:
                                # New record
                                test.created_by = user_initials
                                test.modified_by = user_initials
                            else:
                                # Updating existing record
                                test.modified_by = user_initials
                        
                        if not test_id or pd.isna(test_id):
                            db.session.add(test)
                        else:
                            # For existing tests, make sure they're tracked by the session
                            db.session.merge(test)
                        imported_count += 1
                        
                    except Exception as e:
                        error_count += 1
                        print(f"Error processing row {index + 1}: {str(e)}")
                        continue
                
                # Commit all changes
                db.session.commit()
                
                flash(f'Successfully imported {imported_count} compliance tests. {error_count} errors.', 'success')
                return redirect(url_for('compliance_dashboard'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Error processing file: {str(e)}', 'error')
        else:
            flash('Please select a CSV file', 'error')
    
    # Get personnel for help text
    performed_by_personnel = Personnel.query.filter(
        Personnel.roles.ilike('%physics_assistant%') | 
        Personnel.roles.ilike('%physicist%')
    ).order_by(Personnel.name).all()
    
    reviewed_by_personnel = Personnel.query.filter(Personnel.roles.ilike('%physicist%')).order_by(Personnel.name).all()
    
    return render_template('import_compliance.html',
                         form=form,
                         performed_by_personnel=performed_by_personnel,
                         reviewed_by_personnel=reviewed_by_personnel)

@app.route('/export-scheduled-tests')
@login_required
def export_scheduled_tests():
    # Create CSV data
    output = io.StringIO()
    writer = csv.writer(output)

    # Headers matching the ScheduledTest model
    headers = ['schedule_id', 'eq_id', 'scheduled_date', 'scheduling_date', 'notes', 'created_by', 'created_at', 'modified_by', 'updated_at']
    writer.writerow(headers)

    # Write data for all scheduled tests
    scheduled_tests = ScheduledTest.query.all()
    for test in scheduled_tests:
        writer.writerow([
            test.schedule_id,
            test.eq_id,
            test.scheduled_date.strftime('%Y-%m-%d') if test.scheduled_date else '',
            test.scheduling_date.strftime('%Y-%m-%d') if test.scheduling_date else '',
            test.notes if test.notes else '',
            test.created_by.name if test.created_by else '',
            test.created_at.strftime('%Y-%m-%d %H:%M:%S') if test.created_at else '',
            test.modified_by.name if test.modified_by else '',
            test.updated_at.strftime('%Y-%m-%d %H:%M:%S') if test.updated_at else ''
        ])

    # Create response for full export
    response = make_response(output.getvalue())
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'scheduled_tests_{timestamp}.csv'

    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-Type'] = 'text/csv'

    return response

@app.route('/import-scheduled-tests', methods=['POST'])
@login_required
@manage_compliance_required
def import_scheduled_tests():
    if 'file' not in request.files:
        flash('No file uploaded', 'error')
        return redirect(url_for('compliance_dashboard'))

    file = request.files['file']

    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('compliance_dashboard'))

    if file and file.filename.endswith('.csv'):
        try:
            # Read CSV
            df = pd.read_csv(file)

            # Expected columns
            required_columns = ['eq_id', 'scheduled_date', 'scheduling_date']
            optional_columns = ['schedule_id', 'notes']

            # Check required columns
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                flash(f'Missing required columns: {", ".join(missing_columns)}', 'error')
                return redirect(url_for('compliance_dashboard'))

            # Process each row
            imported_count = 0
            updated_count = 0
            error_count = 0

            for index, row in df.iterrows():
                try:
                    # Check if updating existing scheduled test
                    schedule_id = row.get('schedule_id')
                    is_update = False
                    if schedule_id and not pd.isna(schedule_id):
                        test = ScheduledTest.query.get(int(schedule_id))
                        if not test:
                            # Create new test
                            test = ScheduledTest()
                        else:
                            is_update = True
                    else:
                        # Create new test
                        test = ScheduledTest()

                    # Set fields
                    eq_id = int(row['eq_id'])
                    equipment = Equipment.query.get(eq_id)
                    if not equipment:
                        error_count += 1
                        print(f"Row {index + 1}: Equipment ID {eq_id} not found")
                        continue

                    test.eq_id = eq_id
                    test.scheduled_date = pd.to_datetime(row['scheduled_date']).date()
                    test.scheduling_date = pd.to_datetime(row['scheduling_date']).date()

                    # Optional fields
                    if 'notes' in row and not pd.isna(row['notes']):
                        test.notes = row['notes']

                    # Add user stamps
                    if current_user.is_authenticated:
                        if not is_update:
                            # New record
                            test.created_by_id = current_user.id
                            test.modified_by_id = current_user.id
                        else:
                            # Updating existing record
                            test.modified_by_id = current_user.id

                    db.session.add(test)

                    if is_update:
                        updated_count += 1
                    else:
                        imported_count += 1

                except Exception as e:
                    error_count += 1
                    print(f"Error processing row {index + 1}: {str(e)}")
                    continue

            # Commit all changes
            db.session.commit()

            if error_count > 0:
                flash(f'Import completed with errors. Imported: {imported_count}, Updated: {updated_count}, Errors: {error_count}', 'warning')
            else:
                flash(f'Successfully imported {imported_count} and updated {updated_count} scheduled tests!', 'success')

        except Exception as e:
            db.session.rollback()
            flash(f'Error importing CSV: {str(e)}', 'error')

    else:
        flash('Please upload a CSV file', 'error')

    return redirect(url_for('compliance_dashboard'))

@app.route('/export-facilities')
@login_required
@admin_required
def export_facilities():
    facilities = Facility.query.filter_by(is_active=True).all()
    
    # Create CSV data
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write headers
    headers = ['id', 'name', 'address', 'is_active']
    writer.writerow(headers)
    
    # Write data
    for facility in facilities:
        writer.writerow([
            facility.id,
            facility.name,
            facility.address or '',
            facility.is_active
        ])
    
    # Create response
    output.seek(0)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'facilities_export_{timestamp}.csv'
    
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-Type'] = 'text/csv'
    
    return response

@app.route('/import-facilities', methods=['GET', 'POST'])
@login_required
@admin_required
def import_facilities():
    if request.method == 'POST':
        file = request.files.get('csv_file')
        
        if file and file.filename.endswith('.csv'):
            try:
                # Read CSV
                df = pd.read_csv(file)
                
                # Expected columns
                required_columns = ['name']
                optional_columns = ['id', 'address', 'is_active']
                
                # Check required columns
                missing_columns = [col for col in required_columns if col not in df.columns]
                if missing_columns:
                    flash(f'Missing required columns: {", ".join(missing_columns)}', 'error')
                    return redirect(request.url)
                
                # Process each row
                imported_count = 0
                error_count = 0
                
                for index, row in df.iterrows():
                    try:
                        # Check if facility exists by ID or name
                        facility_id = row.get('id')
                        name = row['name']
                        
                        facility = None
                        if facility_id and not pd.isna(facility_id):
                            facility = Facility.query.get(int(facility_id))
                        
                        if not facility:
                            # Check by name to avoid duplicates
                            facility = Facility.query.filter_by(name=name).first()
                        
                        if not facility:
                            # Create new facility
                            facility = Facility()
                            if facility_id and not pd.isna(facility_id):
                                facility.id = int(facility_id)
                            is_new = True
                        else:
                            is_new = False
                        
                        # Set fields
                        facility.name = name
                        facility.address = row.get('address', '')
                        is_active_val = row.get('is_active', 'TRUE')
                        if isinstance(is_active_val, bool):
                            facility.is_active = is_active_val
                        else:
                            facility.is_active = str(is_active_val).upper() in ['TRUE', 'T', '1', 'YES']
                        
                        if is_new:
                            db.session.add(facility)
                        imported_count += 1
                        
                    except Exception as e:
                        error_count += 1
                        print(f"Error processing facility row {index + 1}: {str(e)}")
                        continue
                
                # Commit all changes
                db.session.commit()
                
                flash(f'Successfully imported {imported_count} facilities. {error_count} errors.', 'success')
                return redirect(url_for('admin_facilities'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Error processing file: {str(e)}', 'error')
        else:
            flash('Please select a CSV file', 'error')
    
    return render_template('import_facilities.html')

# Admin Routes
@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    # Get counts for each standardized list
    classes_count = EquipmentClass.query.filter_by(is_active=True).count()
    subclasses_count = EquipmentSubclass.query.filter_by(is_active=True).count()
    departments_count = Department.query.filter_by(is_active=True).count()
    facilities_count = Facility.query.filter_by(is_active=True).count()
    manufacturers_count = Manufacturer.query.filter_by(is_active=True).count()
    
    return render_template('admin_dashboard.html',
                         classes_count=classes_count,
                         subclasses_count=subclasses_count,
                         departments_count=departments_count,
                         facilities_count=facilities_count,
                         manufacturers_count=manufacturers_count)

@app.route('/admin/equipment-classes')
@login_required
@admin_required
def admin_equipment_classes():
    classes = EquipmentClass.query.filter_by(is_active=True).order_by(EquipmentClass.name).all()
    return render_template('admin_equipment_classes.html', classes=classes)

@app.route('/admin/equipment-classes/add', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_add_equipment_class():
    if request.method == 'POST':
        name = request.form['name'].strip()
        if name:
            # Check if already exists
            existing = EquipmentClass.query.filter_by(name=name).first()
            if existing:
                if existing.is_active:
                    flash('Equipment class already exists', 'error')
                else:
                    # Reactivate existing
                    existing.is_active = True
                    db.session.commit()
                    flash('Equipment class reactivated', 'success')
            else:
                new_class = EquipmentClass(name=name)
                db.session.add(new_class)
                db.session.commit()
                flash('Equipment class added', 'success')
        return redirect(url_for('admin_equipment_classes'))
    
    return render_template('admin_add_equipment_class.html')

@app.route('/admin/equipment-classes/<int:class_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_equipment_class(class_id):
    eq_class = EquipmentClass.query.get_or_404(class_id)
    if request.method == 'POST':
        name = request.form['name'].strip()
        if name and name != eq_class.name:
            # Check if new name already exists
            existing = EquipmentClass.query.filter_by(name=name).first()
            if existing and existing.id != class_id:
                flash('Equipment class name already exists', 'error')
            else:
                eq_class.name = name
                db.session.commit()
                flash('Equipment class updated', 'success')
                return redirect(url_for('admin_equipment_classes'))
        elif name == eq_class.name:
            flash('No changes made', 'info')
            return redirect(url_for('admin_equipment_classes'))
    
    return render_template('admin_edit_equipment_class.html', eq_class=eq_class)

@app.route('/admin/equipment-classes/<int:class_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_equipment_class(class_id):
    eq_class = EquipmentClass.query.get_or_404(class_id)
    eq_class.is_active = False
    db.session.commit()
    flash('Equipment class deactivated', 'success')
    return redirect(url_for('admin_equipment_classes'))

@app.route('/admin/equipment-subclasses')
@login_required
@admin_required
def admin_equipment_subclasses():
    subclasses = EquipmentSubclass.query.filter_by(is_active=True).order_by(EquipmentSubclass.name).all()
    return render_template('admin_equipment_subclasses.html', subclasses=subclasses)

@app.route('/admin/equipment-subclasses/add', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_add_equipment_subclass():
    classes = EquipmentClass.query.filter_by(is_active=True).order_by(EquipmentClass.name).all()
    
    if request.method == 'POST':
        name = request.form['name'].strip()
        class_id = request.form.get('equipment_class_id')
        estimated_capital_cost = request.form.get('estimated_capital_cost')

        if name and class_id:
            try:
                class_id = int(class_id)
                # Check if already exists for this class
                existing = EquipmentSubclass.query.filter_by(name=name, class_id=class_id).first()
                if existing:
                    if existing.is_active:
                        flash('Subclass already exists for this class', 'error')
                    else:
                        existing.is_active = True
                        # Update estimated capital cost if provided
                        if estimated_capital_cost and estimated_capital_cost.strip():
                            try:
                                existing.estimated_capital_cost = int(estimated_capital_cost)
                            except ValueError:
                                pass
                        db.session.commit()
                        flash('Subclass reactivated', 'success')
                else:
                    new_subclass = EquipmentSubclass(name=name, class_id=class_id)
                    # Set estimated capital cost if provided
                    if estimated_capital_cost and estimated_capital_cost.strip():
                        try:
                            new_subclass.estimated_capital_cost = int(estimated_capital_cost)
                        except ValueError:
                            pass
                    db.session.add(new_subclass)
                    db.session.commit()
                    flash('Subclass added', 'success')
            except ValueError:
                flash('Invalid class selection', 'error')
        return redirect(url_for('admin_equipment_subclasses'))
    
    return render_template('admin_add_equipment_subclass.html', classes=classes)

@app.route('/admin/equipment-subclasses/<int:subclass_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_equipment_subclass(subclass_id):
    subclass = EquipmentSubclass.query.get_or_404(subclass_id)
    classes = EquipmentClass.query.filter_by(is_active=True).order_by(EquipmentClass.name).all()
    
    if request.method == 'POST':
        name = request.form['name'].strip()
        class_id = request.form.get('equipment_class_id')
        estimated_capital_cost = request.form.get('estimated_capital_cost')

        if name and class_id:
            try:
                class_id = int(class_id)
                # Check if new combination already exists
                existing = EquipmentSubclass.query.filter_by(name=name, class_id=class_id).first()
                if existing and existing.id != subclass_id:
                    flash('Subclass name already exists for this class', 'error')
                else:
                    subclass.name = name
                    subclass.class_id = class_id
                    # Update estimated capital cost
                    if estimated_capital_cost and estimated_capital_cost.strip():
                        try:
                            subclass.estimated_capital_cost = int(estimated_capital_cost)
                        except ValueError:
                            subclass.estimated_capital_cost = None
                    else:
                        subclass.estimated_capital_cost = None
                    db.session.commit()
                    flash('Subclass updated', 'success')
                    return redirect(url_for('admin_equipment_subclasses'))
            except ValueError:
                flash('Invalid class selection', 'error')

    return render_template('admin_edit_equipment_subclass.html', subclass=subclass, classes=classes)

@app.route('/admin/equipment-subclasses/<int:subclass_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_equipment_subclass(subclass_id):
    subclass = EquipmentSubclass.query.get_or_404(subclass_id)
    subclass.is_active = False
    db.session.commit()
    flash('Subclass deactivated', 'success')
    return redirect(url_for('admin_equipment_subclasses'))

@app.route('/admin/departments')
@login_required
@admin_required
def admin_departments():
    departments = Department.query.filter_by(is_active=True).order_by(Department.name).all()
    return render_template('admin_departments.html', departments=departments)

@app.route('/admin/departments/add', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_add_department():
    if request.method == 'POST':
        name = request.form['name'].strip()
        if name:
            existing = Department.query.filter_by(name=name).first()
            if existing:
                if existing.is_active:
                    flash('Department already exists', 'error')
                else:
                    existing.is_active = True
                    db.session.commit()
                    flash('Department reactivated', 'success')
            else:
                new_dept = Department(name=name)
                db.session.add(new_dept)
                db.session.commit()
                flash('Department added', 'success')
        return redirect(url_for('admin_departments'))
    
    return render_template('admin_add_department.html')

@app.route('/admin/departments/<int:dept_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_department(dept_id):
    dept = Department.query.get_or_404(dept_id)
    if request.method == 'POST':
        name = request.form['name'].strip()
        if name and name != dept.name:
            existing = Department.query.filter_by(name=name).first()
            if existing and existing.id != dept_id:
                flash('Department name already exists', 'error')
            else:
                dept.name = name
                db.session.commit()
                flash('Department updated', 'success')
                return redirect(url_for('admin_departments'))
        elif name == dept.name:
            flash('No changes made', 'info')
            return redirect(url_for('admin_departments'))
    
    return render_template('admin_edit_department.html', dept=dept)

@app.route('/admin/departments/<int:dept_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_department(dept_id):
    dept = Department.query.get_or_404(dept_id)
    dept.is_active = False
    db.session.commit()
    flash('Department deactivated', 'success')
    return redirect(url_for('admin_departments'))

@app.route('/admin/facilities')
@login_required
@admin_required
def admin_facilities():
    facilities = Facility.query.filter_by(is_active=True).order_by(Facility.name).all()
    return render_template('admin_facilities.html', facilities=facilities)

@app.route('/admin/facilities/add', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_add_facility():
    if request.method == 'POST':
        name = request.form['name'].strip()
        address = request.form.get('address', '').strip()
        if name:
            existing = Facility.query.filter_by(name=name).first()
            if existing:
                if existing.is_active:
                    flash('Facility already exists', 'error')
                else:
                    existing.is_active = True
                    existing.address = address
                    db.session.commit()
                    flash('Facility reactivated', 'success')
            else:
                new_facility = Facility(name=name, address=address)
                db.session.add(new_facility)
                db.session.commit()
                flash('Facility added', 'success')
        return redirect(url_for('admin_facilities'))
    
    return render_template('admin_add_facility.html')

@app.route('/admin/facilities/<int:facility_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_facility(facility_id):
    facility = Facility.query.get_or_404(facility_id)
    if request.method == 'POST':
        name = request.form['name'].strip()
        address = request.form.get('address', '').strip()
        
        if name and name != facility.name:
            existing = Facility.query.filter_by(name=name).first()
            if existing and existing.id != facility_id:
                flash('Facility name already exists', 'error')
            else:
                facility.name = name
                facility.address = address
                db.session.commit()
                flash('Facility updated', 'success')
                return redirect(url_for('admin_facilities'))
        elif name == facility.name:
            # Check if only address changed
            if address != (facility.address or ''):
                facility.address = address
                db.session.commit()
                flash('Facility updated', 'success')
                return redirect(url_for('admin_facilities'))
            else:
                flash('No changes made', 'info')
                return redirect(url_for('admin_facilities'))
    
    return render_template('admin_edit_facility.html', facility=facility)

@app.route('/admin/facilities/<int:facility_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_facility(facility_id):
    facility = Facility.query.get_or_404(facility_id)
    facility.is_active = False
    db.session.commit()
    flash('Facility deactivated', 'success')
    return redirect(url_for('admin_facilities'))

@app.route('/admin/manufacturers')
@login_required
@admin_required
def admin_manufacturers():
    manufacturers = Manufacturer.query.filter_by(is_active=True).order_by(Manufacturer.name).all()
    return render_template('admin_manufacturers.html', manufacturers=manufacturers)

@app.route('/admin/manufacturers/add', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_add_manufacturer():
    if request.method == 'POST':
        name = request.form['name'].strip()
        if name:
            existing = Manufacturer.query.filter_by(name=name).first()
            if existing:
                if existing.is_active:
                    flash('Manufacturer already exists', 'error')
                else:
                    existing.is_active = True
                    db.session.commit()
                    flash('Manufacturer reactivated', 'success')
            else:
                new_mfr = Manufacturer(name=name)
                db.session.add(new_mfr)
                db.session.commit()
                flash('Manufacturer added', 'success')
        return redirect(url_for('admin_manufacturers'))
    
    return render_template('admin_add_manufacturer.html')

@app.route('/admin/manufacturers/<int:mfr_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_manufacturer(mfr_id):
    mfr = Manufacturer.query.get_or_404(mfr_id)
    if request.method == 'POST':
        name = request.form['name'].strip()
        if name and name != mfr.name:
            existing = Manufacturer.query.filter_by(name=name).first()
            if existing and existing.id != mfr_id:
                flash('Manufacturer name already exists', 'error')
            else:
                mfr.name = name
                db.session.commit()
                flash('Manufacturer updated', 'success')
                return redirect(url_for('admin_manufacturers'))
        elif name == mfr.name:
            flash('No changes made', 'info')
            return redirect(url_for('admin_manufacturers'))
    
    return render_template('admin_edit_manufacturer.html', mfr=mfr)

@app.route('/admin/manufacturers/<int:mfr_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_manufacturer(mfr_id):
    mfr = Manufacturer.query.get_or_404(mfr_id)
    mfr.is_active = False
    db.session.commit()
    flash('Manufacturer deactivated', 'success')
    return redirect(url_for('admin_manufacturers'))

# Auto-initialize database on import (for production)
try:
    with app.app_context():
        db.create_all()
        check_and_migrate_db()
except Exception as e:
    print(f"Database initialization error: {e}")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        check_and_migrate_db()
    # Only run debug mode in development
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=debug_mode)