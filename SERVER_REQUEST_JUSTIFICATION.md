# Server Build Request — Radiation Equipment Management System (REMS)

## Application Overview

The Radiation Equipment Management System (REMS) is an internal web application for managing radiology imaging equipment inventory, compliance testing schedules, and departmental personnel records. It replaces manual tracking processes and provides a centralized, auditable record of equipment compliance status.

## User Base

- Approximately 5 internal users (medical physicists, physics assistants, administrative staff)
- Rarely more than 1-2 concurrent users
- Internal access only — not exposed to the internet

## Application Stack

| Component | Technology |
|---|---|
| Web framework | Python/Flask |
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
- No outbound internet access required after initial setup

## SSL Certificate

An SSL server certificate issued by the organizational CA will be required for the internal hostname. This should be requested separately from IT/security.

## Backup Strategy

Automated daily backups of the SQLite database file are handled by a cron job on the server. If a network backup share is available, backups can be directed there for additional redundancy.

## Support Level

Low-criticality internal departmental tool. Business-hours support level is appropriate. Downtime outside of business hours is acceptable.
