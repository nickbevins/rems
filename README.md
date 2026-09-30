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
- **Active vs. Login Access**: Active means the person is still around (inactive people cannot log in and are left out of new equipment and test dropdowns, though existing assignments are kept); Requires Login Access means they have an account at all
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
- `SESSION_COOKIE_SECURE`: Set to `1` behind HTTPS so the session cookie is only sent over HTTPS (automatic on Render)
- `TRUSTED_PROXY_COUNT`: Number of reverse proxies in front of the app, e.g. `1` for NGINX (automatic `1` on Render). Leave unset when nothing sits in front, or clients could spoof their IP address

### Database Options
- **SQLite** (default): File-based database, no separate server required. Suitable for most deployments.
- **MySQL/PostgreSQL**: Supported for larger deployments by setting the `DATABASE_URL` environment variable (e.g. `mysql+pymysql://user:pass@localhost/physdb` or a PostgreSQL connection string). If using MySQL, also add `PyMySQL` to `requirements.txt`.

## Security Features
- CSRF protection on every POST (forms send `csrf_token`; in-page requests send the `X-CSRFToken` header)
- Input validation and sanitization
- Secure session management with forced password change on first login; session cookie is HttpOnly, SameSite=Lax, and Secure over HTTPS
- Failed logins throttled per client IP (10 per 15 minutes); logout requires POST
- Passwords must be at least 12 characters (existing shorter passwords keep working until changed)
- Deactivating someone or turning off their login access ends any session they already have open
- Database error details go to the server log, not the page; import errors name the row and the conflicting field
- Only admins can grant admin rights, set usernames or passwords, change active status, or edit/delete admin accounts; nobody can demote, deactivate, or delete their own account
- SQL injection prevention via SQLAlchemy ORM
- XSS protection: Jinja autoescaping, plus `escapeHtml()` (static/js/main.js) for HTML built in JavaScript
- Spreadsheet formula injection prevention: CSV exports prefix formula-like text with `'` (removed again on import); the Excel workbook writes all text literally
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

### Database Export and Backup

Admins can download the whole database from **Admin Dashboard → Database Export**, in two formats:

| Format | Use it for | Notes |
|---|---|---|
| `.sqlite3` backup | Restoring the application | Complete and restorable. Contains user accounts and password hashes — store it securely. |
| `.xlsx` workbook | Analysis in Excel | One worksheet per table, each formatted as a named Excel Table. Opens natively — no drivers, add-ins, or ODBC setup. Password hashes are excluded. |

The workbook is a point-in-time snapshot, not a live connection; download it again to refresh. To
query across tables in Excel, use **Data → Get Data → From File → From Workbook**, select the sheets
you need, then Merge Queries on the ID columns (e.g. `equipment.class_id` → `equipment_classes.id`).

The backup button uses SQLite's `VACUUM INTO`, which produces a transactionally consistent,
defragmented single file. Prefer it over copying `physdb.db` directly: a plain copy of a database in
WAL mode can capture a torn read and silently omit committed transactions that have not yet been
checkpointed. It is only available on SQLite; on another backend the button is disabled and you
should use that server's own backup tooling.

Scripted alternative for automated/offsite backups:

```bash
# Consistent snapshot from the CLI (do NOT use plain cp on a running app)
sqlite3 instance/physdb.db ".backup physdb_backup_$(date +%Y%m%d).db"
```

**Restoring:** stop the service first, and delete any existing `physdb.db-wal` and `physdb.db-shm`
alongside the target — a stale WAL paired with a restored database file is a corruption path. See
`PRODUCTION_DEPLOYMENT_GUIDE.md` for the full procedure.

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
Column names match the equipment export, so the way to edit in bulk is: export from the Equipment List (filters apply), edit the file, and import it.

- Rows whose `eq_id` exists update that record; a blank `eq_id` creates new equipment (`equipment_class` required)
- Only the columns present in the file change; a blank cell clears that field
- Each row is saved on its own; problem rows are reported with their row number and the rest still import
- Every cell is read as text, so values like room `101` or serial `00123` are kept exactly
- Dates: `YYYY-MM-DD`, or `M/D/YYYY` as Excel re-saves them
- Unrecognized column names are reported and ignored
- Export-only calculated columns (`eq_mefacreg`, `eq_eeoldate`, `eq_capecst`, `eq_capcat`) are ignored on import

| Field | Description |
|---|---|
| `eq_id` | Equipment ID (blank for new equipment) |
| `equipment_class` | Equipment class (CT, MRI, X-ray, etc.) — **required** for new equipment |
| `equipment_subclass` | Subclass, matched within the class |
| `manufacturer`, `department` | Lookup names (created if new) |
| `facility` | Facility name; `facility_full` and `facility_address` are used only when the import creates the facility |
| `contact_id`, `contact_person`, `contact_email` | Contact, matched by ID then name; a new person needs an email. Same pattern for `supervisor*` and `physician*` |
| `eq_mod`, `eq_rm`, `eq_phone`, `eq_assetid`, `eq_sn`, `eq_mefac`, `eq_mereg`, `eq_manid`, `eq_acrsite`, `eq_acrunit`, `eq_notes` | Text fields |
| `eq_mandt`, `eq_rfrbdt`, `eq_instdt`, `eq_eoldate`, `eq_retdate` | Manufacture, refurbish, install, end-of-life, and retirement dates |
| `eq_retired`, `eq_planned`, `eq_physcov` | TRUE/FALSE (blank: not retired, not planned, physics covered) |
| `eq_auditfreq` | Comma-separated: Quarterly, Semiannual, Annual - ACR, Annual - TJC, Annual - ME |
| `eq_radcap`, `eq_capfund` | Radiology owned / replacement funded: 1, 0, or blank |
| `eq_capcst`, `eq_capyr`, `eq_captype`, `eq_capnote` | Capital cost (thousands), year, Replacement/Upgrade, notes |

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
| `facility_full` | Full Facility name (shown on equipment details; column omitted = existing values kept) |
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

Tests cover: authentication and login throttling, open redirect rejection, role and personnel-permission enforcement, CSRF, output escaping, `must_change_password` enforcement, CSV import/export round trips, shared equipment filters, startup migrations, and date arithmetic. See `tests/test_app.py`.

## Version History

### v1.3.1
- **Personnel**: equipment and compliance test dropdowns list active people and lookup values only, plus whatever the record already has assigned (marked "(inactive)"), so saving never clears an existing assignment; turning off login access now ends an open session; login access requires a username and password; admins cannot turn off their own login access; personnel list and details show one status (Inactive, Login Enabled, Login Required (Not Configured), or Contact Only)
- **Messages**: only green success confirmations close on their own; help boxes on the import and admin pages, import summaries, and info, warning, and error messages stay until closed
- **Security**: minimum password length raised from 6 to 12; raw database error text no longer shown in the backup and import messages

### v1.3.0
- **Full Facility**: new `facilities.facility_full` for the formal facility name, set in admin, shown on the equipment details page, and exported/imported as `facility_full`
- **Security**: CSRF protection on every form; personnel permissions (only admins manage logins, admin rights, and admin accounts; the `admin` role is gone — `is_admin` is the only source of admin rights); XSS fixes on the equipment details inline editor and the capital bubble chart; formula-injection-safe exports; secure session cookie and proxy headers on Render; failed-login throttling; POST-only logout
- **Import**: bulk edit merged into the equipment import (update by `eq_id`, only listed columns change); cells read as text; per-row errors instead of failing the whole file; Excel BOM and `M/D/YYYY` dates handled; compliance test types validated; legacy column-name aliases removed
- **Bugs**: compliance dashboard/export crash when combining a filter with search; exports now match the page's filters (list or capital planning); inline retire sets the retirement date; capital category overlap check at open-ended boundaries; bad query parameters no longer cause errors
- **Cleanup**: the six admin lookup tables share one set of routes and two templates (`LOOKUP_TABLES` in app.py); all CSV imports share one row-by-row runner and all CSV exports one download helper; compliance export now includes `performed_by_id`/`reviewed_by_id` so it re-imports cleanly; one shared equipment filter query for the list, capital, compliance, and export pages; dashboard, compliance, list, and export pages use a fixed number of queries instead of several per row; startup migration drops unused columns (`eq_address`, `eq_eeoldate`, `eq_capcat`, `eq_capecst`) and renames old lowercase test types; unused `/api/equipment`, `/api/equipment/search`, and `/api/facility/<id>/address` routes removed

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

