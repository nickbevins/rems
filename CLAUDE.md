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
- SQLite database file: `instance/physdb.db`
- Database schema reference: `database_schema.sql`

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
- **Equipment** (`app.py:21-119`): Comprehensive equipment tracking with contact info, asset details, compliance requirements
- **ComplianceTest** (`app.py:121-138`): Testing records linked to equipment with scheduling and results

### Key Features
- **Equipment Management**: CRUD operations for radiology equipment inventory
- **Compliance Testing**: Automated scheduling and tracking of equipment compliance tests
- **CSV Import**: Bulk import functionality for equipment data
- **Search & Filtering**: Advanced filtering by equipment attributes
- **Dashboard**: Real-time compliance status overview

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

### Data Import
- CSV import functionality expects specific column format (see README.md)
- Date format: YYYY-MM-DD
- Boolean values: TRUE/FALSE

### Security
- CSRF protection enabled on all forms
- Uses secure session management
- Input validation through WTForms validators
- **Note**: Service passwords stored in `eq_servpwd` field - consider encryption for production use

### Development Notes
- The application uses Flask's development server - not suitable for production
- Database migrations are not implemented - schema changes require manual updates
- Static file serving handled by Flask (consider CDN for production)