# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Commands

### Running the Application
```bash
python app.py
```
The application runs on `http://localhost:5000` by default.

### Environment Setup
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Unix/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Database Management
- Database is automatically created when running `python app.py`
- **Local development**: SQLite database file: `instance/physdb.db`
- **Production (Render)**: Uses persistent disk at `/var/data/physdb.db` or PostgreSQL via DATABASE_URL
- Database schema reference: `database_schema.sql`

### Admin Utilities
Scripts in `scripts/` folder for system administration:
- `reset_password.py`: Reset user passwords
- `list_users.py`: List all personnel/users

## Code Architecture

### Application Structure
- **Flask Application**: Single-file Flask app with SQLAlchemy ORM
- **Two Main Files**:
  - `app.py`: Full-featured application with all functionality
  - `app_simple.py`: Simplified version with core features
- **Database Models**: 
  - `Equipment`: Main model for radiology equipment tracking
  - `ComplianceTest`: Model for compliance testing records
- **Templates**: HTML templates in `templates/` directory using Jinja2
- **Static Assets**: CSS and JavaScript in `static/` directory

### Database Schema
The application uses SQLAlchemy with these key models:
- **Equipment** (`app.py:86-334`): Comprehensive equipment tracking with contact info, asset details, compliance requirements
- **ComplianceTest** (`app.py:335-392`): Testing records linked to equipment with scheduling and results
- **Personnel** (`app.py:454-549`): User management with roles and authentication
- **Reference Data Models**: EquipmentClass, EquipmentSubclass, Department, Facility, Manufacturer

### Key Features
- **Equipment Management**: CRUD operations for radiology equipment inventory
- **Compliance Testing**: Automated scheduling and tracking of equipment compliance tests
- **Personnel Management**: User accounts with role-based permissions
- **CSV Import/Export**: Bulk operations for equipment, personnel, compliance tests, and facilities
- **Search & Filtering**: Advanced filtering by equipment attributes
- **Dashboard**: Real-time compliance status overview
- **Admin Interface**: Manage reference data (facilities, departments, etc.)

### Forms and Validation
- Uses Flask-WTF for form handling with CSRF protection
- WTForms for field validation and form rendering
- Key forms: `EquipmentForm`, `ComplianceTestForm`, `BulkEditForm`

### Configuration
- Environment variables loaded via `python-dotenv`
- Key settings: `SECRET_KEY`, `DATABASE_URL`, `FLASK_ENV`
- Database URI defaults to SQLite: `sqlite:///physdb.db`

## Important Notes

### Testing
- **No existing test framework**: The codebase currently has no unit tests or testing infrastructure
- When adding tests, consider using pytest with fixtures for database testing
- All "test" references in the code relate to equipment compliance testing, not software testing

### Data Import/Export
- **Equipment**: Export/import with facility, personnel, and reference data relationships
- **Personnel**: Export/import with role-based permissions (admin account protected at ID 0)
- **Compliance Tests**: Export/import using personnel names instead of IDs for usability
- **Facilities**: Export/import for reference data management
- **Format Requirements**: 
  - Date format: YYYY-MM-DD
  - Boolean values: TRUE/FALSE
  - CSV files with proper headers (download sample formats from export functions)

### Deployment (Render.com)
- **Database Persistence**: Requires paid tier ($7+) with persistent disk mounted at `/var/data`
- **Environment Variables**: Set `RENDER=true` for production configuration
- **Database Options**: SQLite with persistent disk or PostgreSQL via `DATABASE_URL`
- **Manual Deploys**: Data persists across deployments with proper disk configuration

### Security
- CSRF protection enabled on all forms
- Password hashing with werkzeug.security
- Role-based access control (admin, physicist, etc.)
- Input validation through WTForms validators
- **Admin Account**: Protected at ID 0 to prevent import conflicts

### Development Notes
- Production deployment uses Gunicorn WSGI server via `Procfile`
- Database initialization handled automatically on startup
- Static file serving optimized for production
- No database migrations - schema managed through model definitions