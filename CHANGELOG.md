# Changelog

## v1.3.1
- **Personnel**: equipment and compliance test dropdowns list active people and lookup values only, plus whatever the record already has assigned (marked "(inactive)"), so saving never clears an existing assignment; turning off login access now ends an open session; login access requires a username and password; admins cannot turn off their own login access; personnel list and details show one status (Inactive, Login Enabled, Login Required (Not Configured), or Contact Only)
- **Messages**: only green success confirmations close on their own; help boxes on the import and admin pages, import summaries, and info, warning, and error messages stay until closed
- **Security**: minimum password length raised from 6 to 12; raw database error text no longer shown in the backup and import messages

## v1.3.0
- **Full Facility**: new `facilities.facility_full` for the formal facility name, set in admin, shown on the equipment details page, and exported/imported as `facility_full`
- **Security**: CSRF protection on every form; personnel permissions (only admins manage logins, admin rights, and admin accounts; the `admin` role is gone — `is_admin` is the only source of admin rights); XSS fixes on the equipment details inline editor and the capital bubble chart; formula-injection-safe exports; secure session cookie and proxy headers on Render; failed-login throttling; POST-only logout
- **Import**: bulk edit merged into the equipment import (update by `eq_id`, only listed columns change); cells read as text; per-row errors instead of failing the whole file; Excel BOM and `M/D/YYYY` dates handled; compliance test types validated; legacy column-name aliases removed
- **Bugs**: compliance dashboard/export crash when combining a filter with search; exports now match the page's filters (list or capital planning); inline retire sets the retirement date; capital category overlap check at open-ended boundaries; bad query parameters no longer cause errors
- **Cleanup**: the six admin lookup tables share one set of routes and two templates (`LOOKUP_TABLES` in app.py); all CSV imports share one row-by-row runner and all CSV exports one download helper; compliance export now includes `performed_by_id`/`reviewed_by_id` so it re-imports cleanly; one shared equipment filter query for the list, capital, compliance, and export pages; dashboard, compliance, list, and export pages use a fixed number of queries instead of several per row; startup migration drops unused columns (`eq_address`, `eq_eeoldate`, `eq_capcat`, `eq_capecst`) and renames old lowercase test types; unused `/api/equipment`, `/api/equipment/search`, and `/api/facility/<id>/address` routes removed

## v1.2.0
- Bulk personnel import no longer creates login credentials; contact records only — login access granted individually via UI
- `FLASK_ENV` deprecated; replaced with `FLASK_DEBUG`; local dev server binds `127.0.0.1` only
- Duplicate `eq_statefacreg` generation extracted to `_generate_statefacreg()` utility function
- `MockPagination` dynamic `type()` pattern replaced with a proper module-level class
- Redundant in-function `import re` statements removed (now top-level); missing `import logging` added
- Unused `today` variable removed from `get_last_tested_date()`

## v1.1.0
- Security hardening: removed default credentials, hardened SECRET_KEY handling, open redirect fix, audit logging, role enforcement, CSV row limits, safe date parsing
- Removed `eq_servlogin`/`eq_servpwd` from database and UI; automatic migration on startup via `check_and_migrate_db()`
- Integration test scaffold (`tests/`)

## v1.0.0
- Initial release
- Equipment database management
- Compliance testing system
- CSV import functionality
- Web-based interface
- Search and filtering capabilities

