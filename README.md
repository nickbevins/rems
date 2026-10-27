# REMS - Radiation Equipment Management System

A web application for medical physics groups to track radiology imaging equipment, compliance
testing, capital replacement planning, and the people involved. It is a single Flask app with a
SQLite database, so you can run it on a laptop, a small Linux server, or a hosting platform such
as Render.

## Features

### Equipment
- **Inventory**: equipment class and subclass, manufacturer, model, serial and asset numbers, and manufacture, install, end-of-life, and retirement dates
- **Location**: facility, department, and room
- **Regulatory IDs**: ACR site/unit codes and state facility/registration numbers
- **Contacts**: a contact person, supervisor, and physician for each unit
- **Planned, retired, and non-covered units**: kept in the database and hidden from lists unless you turn on the matching filter
- **Search and filters**: by class, subclass, manufacturer, department, facility, and free text; exports use the same filters

### Compliance Testing
- **Test history**: Acceptance, Annual, Audit, QC Review, Shielding Design, Submission, Retire, and Other entries, with test, report, and submission dates and who performed and reviewed each one
- **Due dates**: calculated from each unit's audit frequencies (Quarterly, Semiannual, Annual - ACR, Annual - TJC, Annual - ME) and its last Acceptance or Annual test
- **Compliance dashboard**: lists overdue units, units due within 90 days, and scheduled tests; the home page shows the same counts
- **Scheduling**: you schedule tests yourself, one date at a time, from the equipment list or compliance dashboard. REMS does not create schedules or send email; the dashboards show what is due

### Capital Planning
- **Replacement list**: end-of-life date (entered, or estimated from the subclass's expected lifetime), replacement cost, year, and funding status
- **Cost categories**: units grouped into the capital categories you define by cost range
- **Bubble chart**: replacement cost by year and equipment class

### Personnel
- **Contact list with roles**: contact, supervisor, physician, physicist, physics assistant, QA technologist
- **Login accounts**: optional per person, with an admin flag for full access
- **Active vs. login access**: inactive people cannot log in and are left out of new equipment and test dropdowns, though existing assignments are kept; login access controls whether a person has an account at all
- **Passwords**: users change their own; admins set or reset them in the Personnel pages and can require a new password at next login

### Data Management
- **CSV import and export** for equipment, personnel, compliance tests, scheduled tests, and facilities. Exports re-import cleanly, so bulk editing is export, edit, import
- **Database backup**: admins download a restorable `.sqlite3` copy from the Admin page
- **Excel workbook**: one worksheet per table, for analysis in Excel
- **Reference data**: admins manage equipment classes and subclasses, facilities, departments, manufacturers, and capital categories

The app needs no internet access while running. Bootstrap, SortableJS, and D3.js are bundled in
`static/vendor/`, and icons are inline SVG.

## Quick Start (Local)

Requires Python 3.11 or newer (tested on 3.13) and Git.

1. **Get the code**
   ```bash
   git clone <repository-url> rems
   cd rems
   ```

2. **Create a virtual environment and install dependencies**
   ```bash
   python -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Create your `.env` file**
   ```bash
   cp .env.example .env            # Windows: copy .env.example .env
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
   Paste the printed value into `.env` as `SECRET_KEY`. The app will not start without one.
   `.env.example` also sets `FLASK_DEBUG=1`, which is fine on your own machine and must never be
   used on a server.

4. **Create the first admin account**
   ```bash
   flask create-admin
   ```
   This prompts for a name, email, username, and password, and creates the database
   (`instance/physdb.db`) if it does not exist yet. There are no default credentials. It stops if
   an admin already exists.

5. **Start the app**
   ```bash
   python app.py
   ```
   Open `http://localhost:5000` and log in. The development server only listens on
   `127.0.0.1`, so other computers cannot reach it.

## Configuration

Settings are read from environment variables, or from `.env` in the app directory.

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | none (required) | Signs session cookies. Use a long random value and keep it secret. Changing it logs everyone out. |
| `DATABASE_URL` | `sqlite:///instance/physdb.db` | Database location (see [Database](#database)) |
| `FLASK_DEBUG` | off | `1` turns on the debugger and auto-reload for local development. Never set it on a server. |
| `SESSION_COOKIE_SECURE` | off | `1` sends the session cookie only over HTTPS. Set it whenever the site is served over HTTPS. |
| `TRUSTED_PROXY_COUNT` | `0` | Number of reverse proxies in front of the app (e.g. `1` for NGINX, `2` on Render). REMS then takes the client IP from the `X-Forwarded-For` header and the scheme from `X-Forwarded-Proto`. Leave it at `0` when nothing sits in front, or clients could fake their IP address. |
| `PORT` | `5000` | Port for `python app.py`. Hosting platforms set this for you. |

**On Render**, REMS detects the `RENDER` environment variable that Render sets. It then sets
`SESSION_COOKIE_SECURE` and `TRUSTED_PROXY_COUNT=2` on its own and keeps the database on the
persistent disk at `/var/data`. On any other host, set these yourself.

### Database

SQLite is the supported and tested database. It is a single file, needs no database server, and
easily handles a group of a few dozen users. Tables are created on first start, and schema changes
from new versions are applied automatically at startup, so upgrading needs no manual migration step.

`DATABASE_URL` can point to another database that SQLAlchemy supports, but that is untested. You
would need to add its driver (e.g. `psycopg` or `PyMySQL`) to `requirements.txt`, some startup
migrations may need adjusting, and the Admin backup button only works on SQLite.

## Deploying

Any host that can run a Python web app and keep one file on persistent storage will work. Run
the app with Gunicorn (included in `requirements.txt`, Linux and macOS only):

```bash
gunicorn app:app
```

Gunicorn listens on `0.0.0.0:$PORT` when the `PORT` environment variable is set, as it is on most
hosting platforms. Otherwise it listens on `127.0.0.1:8000`; add `--bind` to choose another address.

Gunicorn starts one worker by default. Keep it at one: the failed-login throttle is kept in memory
per worker, so more workers would allow more attempts.

On every server deployment:
- Set a unique `SECRET_KEY`, and do not set `FLASK_DEBUG`
- Serve the site over HTTPS
- Keep the database on storage that survives restarts and redeploys
- Run `flask create-admin` once, on the server, after the first deploy

### Option A: Render

1. Push the code to your own GitHub or GitLab repository.
2. In Render, create a **Web Service** from that repository, runtime **Python**:
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `gunicorn app:app`
   - **Instance type**: a paid instance type, because persistent disks are not available on the free type
3. Under **Environment**, add `SECRET_KEY` (a long random value). Render uses its current default
   Python unless you pin one with a `PYTHON_VERSION` variable (e.g. `3.13.4`).
4. Under **Disks**, add a persistent disk mounted at exactly **`/var/data`**. 1 GB is plenty.
   REMS stores `physdb.db` there.
   > Without the disk, REMS falls back to `/tmp/physdb.db` and **all data is lost on every deploy
   > or restart**. The log warns about this at startup.
5. Deploy. When the service is live, open its **Shell** tab and run `flask create-admin`.
6. Log in at your `onrender.com` URL, or add a custom domain in Render.

Render handles HTTPS. REMS turns on secure cookies and proxy handling itself, so you set no other
variables. Before deploying a change that alters the database, download a backup from the Admin page.

### Option B: Your Own Linux Server

The [self-hosting guide](docs/self-hosting.md) covers a full install on Ubuntu or another Linux
server, with or without internet access: Gunicorn under systemd, NGINX with HTTPS, scheduled
backups, health checks, and restore. If your IT department has to provision the server,
[docs/server-request-template.md](docs/server-request-template.md) is a starting point for the request.

## Using REMS

### Loading Your Data
Import in this order, so equipment can refer to people and facilities that already exist:

1. **Facilities**: **Admin → Facilities**, then add them one at a time or use **Import CSV**
2. **Personnel**: **Personnel → Import Personnel**
3. **Equipment**: **Equipment → Import Data**. Unknown manufacturers, departments, facilities, and contacts are created as needed
4. **Compliance tests** and **scheduled tests**: **Compliance → Import Tests**, and the import at the bottom of the compliance dashboard

Every list view has a CSV export. See [CSV Formats](#csv-formats) for the columns.

### Day-to-Day
- **Add or edit equipment** from the Equipment list. Click a unit to see its details, where most fields can be edited in place
- **Record a test** with **Add Test** on the unit's detail page, the equipment list, or the compliance dashboard. Acceptance and Annual tests restart the due-date clock
- **Schedule a test** with **Schedule Test** in the same places. Each entry is a single planned date
- **Check what is due** on the home page and compliance dashboard: overdue units, units due within 90 days, and upcoming scheduled tests
- **Plan replacements** on the Capital Planning page and its bubble chart

### Recovering a Locked-Out Account
If no admin can log in, run this on the server from the app directory:

```bash
python scripts/reset_password.py <username>
```

## CSV Formats

General rules for every import:
- Up to 500 rows per file
- Each row is saved on its own; problem rows are reported by row number and the rest still import
- Dates: `YYYY-MM-DD`, or `M/D/YYYY` or `M/D/YY` as Excel re-saves them
- Booleans: `TRUE`/`FALSE`, `1`/`0`, or `YES`/`Y` (any case)
- Excel's UTF-8 BOM is handled

### Equipment
Column names match the equipment export, so to edit in bulk you export from the Equipment List (filters apply), edit the file, and import it.

- Rows whose `eq_id` exists update that record; a blank `eq_id` creates new equipment (`equipment_class` required)
- Only the columns present in the file change; a blank cell clears that field
- Every cell is read as text, so values like room `101` or serial `00123` are kept exactly
- Unrecognized column names are reported and ignored
- Export-only calculated columns (`eq_statefacreg`, `eq_eeoldate`, `eq_capecst`, `eq_capcat`) are ignored on import

| Field | Description |
|---|---|
| `eq_id` | Equipment ID (blank for new equipment) |
| `equipment_class` | Equipment class (CT, MRI, X-ray, etc.). **Required** for new equipment |
| `equipment_subclass` | Subclass, matched within the class |
| `manufacturer`, `department` | Lookup names (created if new) |
| `facility` | Facility name; `facility_full` and `facility_address` are used only when the import creates the facility |
| `contact_id`, `contact_person`, `contact_email` | Contact, matched by ID then name; a new person needs a valid email. Same pattern for `supervisor*` and `physician*` |
| `eq_mod`, `eq_rm`, `eq_phone`, `eq_assetid`, `eq_sn`, `eq_statefac`, `eq_statereg`, `eq_manid`, `eq_acrsite`, `eq_acrunit`, `eq_notes` | Text fields |
| `eq_mandt`, `eq_rfrbdt`, `eq_instdt`, `eq_eoldate`, `eq_retdate` | Manufacture, refurbish, install, end-of-life, and retirement dates |
| `eq_retired`, `eq_planned`, `eq_physcov` | TRUE/FALSE (blank: not retired, not planned, physics covered) |
| `eq_auditfreq` | Comma-separated: Quarterly, Semiannual, Annual - ACR, Annual - TJC, Annual - ME |
| `eq_radcap`, `eq_capfund` | Radiology owned / replacement funded: 1, 0, or blank |
| `eq_capcst`, `eq_capyr`, `eq_captype`, `eq_capnote` | Capital cost (thousands), year, Replacement/Upgrade, notes |

### Personnel
Required: `name`, `email`

Imports create or update **contact records only**. Login access (username, password, login
required) is set per person in the Personnel pages, never by CSV.

| Field | Description |
|---|---|
| `id` | Personnel ID (for updating existing records) |
| `name` | Full name |
| `email` | Email address |
| `phone` | Phone number |
| `roles` | Comma-separated: `contact`, `supervisor`, `physician`, `physicist`, `physics_assistant`, `qa_technologist`. An unknown role rejects the row. |
| `contact`, `supervisor`, … `qa_technologist` | One TRUE/FALSE column per role, as the export writes them; used when `roles` is blank |

Rows without an `id` match an existing person by email (ignoring case).

### Compliance Tests
Required: `eq_id`, `test_type`, `test_date`

| Field | Description |
|---|---|
| `test_id` | Test ID (for updating existing records) |
| `eq_id` | Equipment ID |
| `test_type` | `Acceptance`, `Annual`, `Audit`, `QC Review`, `Shielding Design`, `Submission`, `Retire`, or `Other` (capitals don't matter) |
| `test_date`, `report_date`, `submission_date` | Dates |
| `performed_by_id`, `reviewed_by_id` | Personnel IDs |
| `notes` | Notes |

### Scheduled Tests
Required: `eq_id`, `scheduled_date`, `scheduling_date`

| Field | Description |
|---|---|
| `schedule_id` | Schedule ID (for updating existing records) |
| `eq_id` | Equipment ID |
| `scheduled_date` | Date the test is planned for |
| `scheduling_date` | Date it was scheduled |
| `notes` | Notes |

The export also includes `created_by`, `created_at`, `modified_by`, and `updated_at`, which are ignored on import.

### Facilities
Required: `name`

| Field | Description |
|---|---|
| `id` | Facility ID (for updating existing records) |
| `name` | Short facility name shown throughout the app |
| `facility_full` | Full facility name shown on equipment details (if the column is left out, existing values are kept) |
| `address` | Address |
| `is_active` | TRUE/FALSE |

## Backup and Restore

Admins can download the whole database from **Admin Dashboard → Database Export**:

| Format | Use it for | Notes |
|---|---|---|
| `.sqlite3` backup | Restoring the application | Complete and restorable. Contains user accounts and password hashes, so store it securely. |
| `.xlsx` workbook | Analysis in Excel | One worksheet per table, each a named Excel Table. Opens natively with no drivers or add-ins. Password hashes are excluded. Not restorable. |

The backup uses SQLite's `VACUUM INTO`, which writes a consistent, compact copy. Do not copy
`physdb.db` with `cp` while the app is running: a copy taken in the middle of a write can be
inconsistent. For scheduled backups from the command line, use SQLite's own backup command:

```bash
sqlite3 instance/physdb.db ".backup physdb_backup_$(date +%Y%m%d).db"
```

The workbook is a snapshot; download it again to refresh. To combine tables in Excel, use
**Data → Get Data → From File → From Workbook**, select the sheets, then Merge Queries on the ID
columns (e.g. `equipment.class_id` → `equipment_classes.id`).

**To restore**:
1. Stop the app.
2. Delete any `physdb.db-wal` and `physdb.db-shm` files next to the database. A leftover WAL file paired with a restored database can corrupt it.
3. Replace `physdb.db` with the backup file, renamed to `physdb.db`.
4. Start the app.

On Render, the database is `/var/data/physdb.db`; use the service's Shell or SSH access to do
steps 2 and 3, then restart the service. The
[self-hosting guide](docs/self-hosting.md#restoring-from-a-backup) has the full procedure for a Linux server.

## Security

- Username and password login with no default credentials; passwords must be at least 12 characters
- Failed logins throttled per client IP (10 per 15 minutes); login, failure, and logout events are logged with username and IP
- Admins can require a password change at next login; until the user picks a new password, every other page is blocked
- Role-based permissions checked on every route that changes data. Only admins can grant admin rights, set usernames or passwords, change active status, or edit/delete admin accounts; nobody can demote, deactivate, or delete their own account
- Deactivating someone or turning off their login access ends any session they have open
- CSRF protection on every POST (forms send `csrf_token`; in-page requests send the `X-CSRFToken` header)
- Session cookie is HttpOnly, SameSite=Lax, and Secure over HTTPS; logout requires POST
- XSS protection through Jinja autoescaping, plus `escapeHtml()` (static/js/main.js) for HTML built in JavaScript
- SQL injection prevention through the SQLAlchemy ORM
- Login redirects only go to pages within REMS
- Spreadsheet formula injection prevention: CSV exports prefix formula-like text with `'` (removed again on import); the Excel workbook writes all text literally
- Database error details go to the server log, not the page
- Personnel imports never create login accounts
- The app refuses to start without a `SECRET_KEY`

## Logs

REMS logs to standard output. Under systemd, read it with `journalctl -u rems`. On Render, use the
service's **Logs** tab. Running `python app.py` locally prints it to the terminal.

## Troubleshooting

| Problem | Check |
|---|---|
| `RuntimeError: SECRET_KEY environment variable is not set` | `.env` is missing, not in the app directory, or has no `SECRET_KEY` |
| Data disappears after a deploy (Render) | No persistent disk, or it is not mounted at `/var/data`; the startup log warns about this |
| Login succeeds but returns to the login page | `SESSION_COOKIE_SECURE=1` on a plain-HTTP site; serve over HTTPS or unset it |
| Import rows rejected | The import summary names each row and field; compare the columns with [CSV Formats](#csv-formats) or start from an export |
| `sqlite3.OperationalError: unable to open database file` | The account running the app cannot write to the database directory |

## Development

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

Tests cover: authentication and login throttling, open redirect rejection, role and personnel-permission enforcement, CSRF, output escaping, `must_change_password` enforcement, CSV import/export round trips, shared equipment filters, startup migrations, and date arithmetic. See `tests/test_app.py`.

The data model is drawn in [DATABASE_DIAGRAM.md](DATABASE_DIAGRAM.md). Release notes are in
[CHANGELOG.md](CHANGELOG.md).

## License

Copyright (c) 2026 Nick Bevins. All rights reserved.
