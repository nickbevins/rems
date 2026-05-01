# REMS - Radiation Equipment Management System

A comprehensive web-based application for managing radiology imaging equipment, compliance testing, personnel, and maintenance records.

## Features

### Equipment Management
- **Equipment Database**: Complete inventory of radiology equipment with detailed specifications
- **Asset Tracking**: Serial numbers, asset IDs, installation dates, and lifecycle information
- **Location Management**: Track equipment across multiple facilities, departments, and rooms
- **Contact Information**: Maintain contact details for equipment managers, supervisors, and physicians
- **Reference Data**: Manage facilities, departments, manufacturers, and equipment classes

### Personnel Management
- **User Accounts**: Role-based access control with secure authentication
- **Role Management**: Admin, physicist, supervisor, contact person, and other specialized roles
- **Password Management**: Secure password reset and change functionality
- **Import/Export**: Bulk personnel management with CSV files

### Compliance Testing
- **Test Scheduling**: Automated scheduling based on equipment audit frequencies
- **Compliance Dashboard**: View overdue and upcoming tests at a glance
- **Test Recording**: Detailed test result documentation with personnel tracking
- **Personnel Integration**: Track who performed and reviewed each test

### Data Management
- **CSV Import/Export**: Bulk operations for equipment, personnel, compliance tests, and facilities
- **Search & Filter**: Advanced filtering by equipment class, manufacturer, department, facility
- **Data Validation**: Ensure data integrity with built-in validation
- **Relationship Management**: Proper handling of equipment-personnel-facility relationships

### User Interface
- **Modern Web Interface**: Responsive design works on desktop and mobile devices
- **Dashboard**: Real-time overview of equipment status and compliance
- **Admin Interface**: Comprehensive management of reference data
- **Advanced Search**: Find equipment quickly with multiple filter options

## Installation

### Prerequisites
- Python 3.11 or higher
- pip package manager

### Setup Instructions

1. **Clone or Download the Project**
   ```bash
   cd /path/to/physdb
   ```

2. **Create Virtual Environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment**
   ```bash
   # Create a .env file with the following (SECRET_KEY is mandatory — app will not start without it):
   SECRET_KEY=your_secure_secret_key_here
   # Set FLASK_DEBUG=1 for local development only. Never set in production.
   FLASK_DEBUG=1
   ```

5. **Create the Admin Account**
   ```bash
   flask create-admin
   ```
   Interactive prompt creates the first admin user. Aborts safely if an admin already exists.

6. **Access the Application**
   - Navigate to `http://localhost:5000`

## Production Deployment

For on-premise installation with automatic startup, backups, and SSL, see [PRODUCTION_DEPLOYMENT_GUIDE.md](PRODUCTION_DEPLOYMENT_GUIDE.md).

**Note**: The application is fully compatible with air-gapped (offline) deployments. All necessary assets (Bootstrap, Font Awesome, D3.js) are included locally in `static/vendor/` and require no internet connectivity during runtime.

## Usage

### Starting the Application (Local)
```bash
python app.py
```

Access the application at `http://localhost:5000`

### Data Import/Export
1. **Facilities**: Import reference data first via Admin → Facilities
2. **Personnel**: Import users via Personnel → Import Personnel
3. **Equipment**: Import equipment data via Equipment → Import Data
4. **Compliance Tests**: Import test records via Compliance → Import Tests
5. **Export**: Download CSV files from any list view

### Equipment Management
- **Add Equipment**: Use the "Add New Equipment" form
- **Edit Equipment**: Click edit button on any equipment record
- **View Details**: Click on equipment ID to see complete information
- **Search**: Use filters to find specific equipment

### Compliance Testing
- **Add Tests**: From equipment detail page, click "Add Test"
- **View Dashboard**: Check compliance status across all equipment
- **Track Overdue**: Monitor equipment requiring immediate attention
- **Schedule Tests**: Set up recurring test schedules

## Database Schema

### Equipment Table
- Basic information (class, manufacturer, model)
- Location details (facility, department, room)
- Asset tracking (serial numbers, IDs, dates)
- Contact information (operators, supervisors, physicians)
- Technical specifications
- Compliance requirements

### Compliance Tests Table
- Test records linked to equipment
- Test types and frequencies
- Results and documentation
- Scheduling and notifications

## Configuration

### Environment Variables
- `SECRET_KEY`: Flask secret key for session security (**required** — app refuses to start without it)
- `DATABASE_URL`: Database connection string (defaults to `instance/physdb.db` SQLite)
- `FLASK_DEBUG`: Set to `1` for local development only; omit or set to `0` in production (`FLASK_ENV` is deprecated in Flask 2.x)
- `ITEMS_PER_PAGE`: Number of items displayed per page

### Database Options
- **SQLite** (default): File-based database, no separate server required. Suitable for most deployments.
- **MySQL/PostgreSQL**: Supported for larger deployments by setting the `DATABASE_URL` environment variable (e.g. `mysql+pymysql://user:pass@localhost/physdb` or a PostgreSQL connection string). If using MySQL, also add `PyMySQL` to `requirements.txt`.

## Security Features
- CSRF protection on all forms
- Input validation and sanitization
- Secure session management with forced password change on first login
- SQL injection prevention via SQLAlchemy ORM
- XSS protection
- Open redirect prevention on login `next` parameter
- Role-based access control with route-level enforcement decorators
- Security audit logging for login success, failure, and logout events
- `SECRET_KEY` required at startup — no insecure fallback
- Service credentials (`eq_servlogin`/`eq_servpwd`) removed from database; automatic migration drops columns on startup
- CSV import row limit (500 rows) to prevent resource exhaustion
- Safe date parsing with `strptime('%Y-%m-%d')` — rejects arbitrary date strings
- Bulk personnel import creates contact records only — no login credentials are set during import; access must be granted individually through the UI
- Local dev server binds to `127.0.0.1` only; production traffic served via Gunicorn + NGINX

## Maintenance

### Database Backup
```bash
# Copy the SQLite database file
cp instance/physdb.db physdb_backup_$(date +%Y%m%d).db
```

### Log Files
- Application logs stored in `physdb.log`
- Error tracking and debugging information
- Performance monitoring data

## Troubleshooting

### Common Issues
1. **Database Connection**: Check DATABASE_URL in .env file
2. **Import Errors**: Verify CSV format matches template
3. **Permission Issues**: Ensure proper file permissions
4. **Performance**: Consider database indexing for large datasets

### Support
- Check log files for detailed error messages
- Verify all dependencies are installed
- Ensure database is properly initialized
- Contact system administrator for technical support

## Data Format

### Equipment CSV Import
Required: `equipment_class`

| Field | Description |
|---|---|
| `eq_id` | Equipment ID (for updating existing records) |
| `equipment_class` | Equipment class (CT, MRI, X-ray, etc.) — **required** |
| `equipment_subclass` | Equipment subclass |
| `manufacturer` | Manufacturer name |
| `eq_mod` | Model number |
| `department` | Department name |
| `eq_rm` | Room number |
| `facility` | Facility name |
| `facility_address` | Facility address |
| `contact_person` | Contact person name |
| `contact_email` | Contact person email |
| `supervisor` | Supervisor name |
| `supervisor_email` | Supervisor email |
| `physician` | Physician name |
| `physician_email` | Physician email |
| `eq_assetid` | Asset ID |
| `eq_sn` | Serial number |
| `eq_mefac` | ME facility |
| `eq_mereg` | ME registration |
| `eq_manid` | Manufacturer ID |
| `eq_mandt` | Manufacture date |
| `eq_instdt` | Installation date |
| `eq_eoldate` | End of life date |
| `eq_eeoldate` | Extended end of life date |
| `eq_retdate` | Retirement date |
| `eq_retired` | Retirement status (TRUE/FALSE) |
| `eq_auditfreq` | Audit frequency |
| `eq_acrsite` | ACR site number |
| `eq_acrunit` | ACR unit number |
| `eq_notes` | Notes |

### Personnel CSV Import
Required: `name`, `email`

Bulk import creates or updates **contact records only**. Login access (username, password, `login_required`) is configured per user through the personnel UI, not via CSV.

| Field | Description |
|---|---|
| `id` | Personnel ID (for updating existing records) |
| `name` | Full name |
| `email` | Email address |
| `phone` | Phone number |
| `roles` | Comma-separated roles: `contact`, `supervisor`, `physician`, `physicist`, `physics_assistant`, `qa_technologist` |

### Compliance Tests CSV Import
Required: `eq_id`, `test_type`, `test_date`

| Field | Description |
|---|---|
| `test_id` | Test ID (for updating existing records) |
| `eq_id` | Equipment ID |
| `test_type` | `acceptance`, `annual`, `audit`, `qc_review`, `shielding_design`, `submission`, `retire`, `other` |
| `test_date` | Test date |
| `report_date` | Report date |
| `submission_date` | Submission date |
| `performed_by_id` | Performer personnel ID |
| `reviewed_by_id` | Reviewer personnel ID |
| `notes` | Notes |

### Facilities CSV Import
Required: `name`

| Field | Description |
|---|---|
| `id` | Facility ID (for updating existing records) |
| `name` | Facility name |
| `address` | Address |
| `is_active` | Active status (TRUE/FALSE) |

### Date Format
All dates must be in `YYYY-MM-DD` format.

### Boolean Fields
Use `TRUE`/`FALSE` (also accepts `1`/`0`, `YES`/`Y`, case-insensitive).

## License

Copyright (c) 2026 Nick Bevins. All rights reserved.

## Running Tests

```bash
pip install pytest
pytest tests/ -v
```

Tests cover: authentication, open redirect rejection, role enforcement, `must_change_password` enforcement, CSV row limits, and date arithmetic. See `tests/test_app.py`.

## Version History

### v1.2.0
- Bulk personnel import no longer creates login credentials; contact records only — login access granted individually via UI
- `FLASK_ENV` deprecated; replaced with `FLASK_DEBUG`; local dev server binds `127.0.0.1` only
- Duplicate `eq_mefacreg` generation extracted to `_generate_mefacreg()` utility function
- `MockPagination` dynamic `type()` pattern replaced with a proper module-level class
- Redundant in-function `import re` statements removed (now top-level); missing `import logging` added
- Unused `today` variable removed from `get_last_tested_date()`

### v1.1.0
- Security hardening: removed default credentials, hardened SECRET_KEY handling, open redirect fix, audit logging, role enforcement, CSV row limits, safe date parsing
- Removed `eq_servlogin`/`eq_servpwd` from database and UI; automatic migration on startup via `check_and_migrate_db()`
- Integration test scaffold (`tests/`)

### v1.0.0
- Initial release
- Equipment database management
- Compliance testing system
- CSV import functionality
- Web-based interface
- Search and filtering capabilities

