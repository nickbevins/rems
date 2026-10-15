# Server Build Request — Radiation Equipment Management System (REMS)

> **Template.** Use this as a starting point when your IT department has to provision a server for
> REMS. Edit the user count, hostname, and support level to fit your organization, and delete this
> note. The install itself is covered in the [self-hosting guide](self-hosting.md).

## Application Overview

The Radiation Equipment Management System (REMS) is an internal web application for managing radiology imaging equipment inventory, compliance testing schedules, and departmental personnel records. It replaces manual tracking processes and provides a centralized, auditable record of equipment compliance status.

### What it does

- **Equipment inventory**: the full lifecycle from planning and installation to retirement, including serial and asset numbers, location (facility, department, room), ACR site/unit codes, state facility registrations, and capital planning.
- **Compliance testing**: test history with who performed and reviewed each test, scheduled tests, and a dashboard of overdue and upcoming tests. Due dates follow each machine's audit frequencies (Quarterly, Semiannual, Annual - ACR, Annual - TJC, Annual - ME).
- **Personnel**: a contact list with roles (contact, supervisor, physician, physicist, physics assistant, QA technologist), linked to equipment as contact, supervisor, and physician.
- **Data management**: CSV import and export for equipment, personnel, compliance tests, scheduled tests, and facilities; a restorable database backup and an Excel workbook export for admins.

### Security

- Username/password sign-in with no default credentials; the first admin is created with `flask create-admin`
- Repeated failed sign-ins are throttled; sign-ins, failures, and sign-outs are logged with username and IP address
- Permission checks on every route that changes data (equipment, compliance, personnel)
- Admins can require users to change their password before doing anything else
- CSRF protection on every form and in-page request
- Sign-in redirects are checked so they cannot send users to another site
- The app refuses to start without a `SECRET_KEY`
- CSV imports are capped at 500 rows, and personnel imports never create sign-in accounts
- Equipment service credentials are not stored in the application database

## User Base

- Approximately [N] internal users (medical physicists, physics assistants, administrative staff)
- Rarely more than a few concurrent users
- Internal access only — not exposed to the internet

## Application Stack

| Component | Technology |
|---|---|
| Web framework | Python 3.11+ / Flask |
| WSGI server | Gunicorn |
| Reverse proxy | NGINX |
| Database | SQLite (file-based, no separate database server required) |
| OS | Ubuntu Server 22.04 LTS or 24.04 LTS |

## Requested Resources

| Resource | Request | Justification |
|---|---|---|
| vCPUs | 2 | Lightweight application; Gunicorn handles low-concurrency workload comfortably on 2 cores |
| Sockets | 1 | Single-socket VM sufficient for workload |
| Memory (vRAM) | 4 GB | Flask/Gunicorn memory footprint is minimal; 4GB provides ample headroom |
| Storage | 50 GB (single OS drive) | OS (~15GB), application (~1GB), database and backups (~10GB), headroom (~24GB) |

No separate Apps or Data drive is required. The application uses a file-based SQLite database that resides on the OS drive alongside the application. If a network backup share is available, backup scripts can be directed there instead.

## Network Requirements

- Static internal IP address or stable internal DNS hostname (e.g. `rems.domain.local`)
- Inbound ports: **80** (HTTP, redirects to HTTPS), **443** (HTTPS)
- Admin access: **port 22** (SSH)
- **Outbound internet access**:
  - **Initial setup only**: Required for OS package installation (`apt update`, `apt upgrade`, `apt install`) and Python package installation (`pip install`)
  - **Runtime**: **No outbound internet access required** — application functions entirely offline once deployed
  - **Air-gapped deployment**: Fully supported with pre-downloaded packages and offline installation procedures (see the [self-hosting guide](self-hosting.md))

## SSL Certificate

An SSL server certificate issued by the organizational CA will be required for the internal hostname.

## Backup Strategy

Automated daily backups of the SQLite database file are handled by a cron job on the server. If a network backup share is available, backups can be directed there for additional redundancy. Admins can also download an on-demand backup from the Admin page.

## Support Level

Low-criticality internal departmental tool. Business-hours support level is appropriate. Downtime outside of business hours is acceptable.
