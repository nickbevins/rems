# REMS - Radiology Equipment Management System

## Overview
REMS is a Flask-based web application designed for comprehensive tracking and management of radiology equipment inventory, compliance testing, and personnel records in healthcare facilities.

## Core Functionality

### Equipment Management
- **Inventory Tracking**: Complete equipment lifecycle from installation to retirement
- **Asset Information**: Serial numbers, asset IDs, manufacture dates, end-of-life tracking
- **Location Management**: Department, room, and facility assignments
- **Technical Details**: ACR site/unit codes, ME facility registrations, audit frequencies

### Compliance Testing
- **Test Scheduling**: Automated compliance test scheduling based on equipment requirements
- **Test Records**: Complete testing history with performed by, reviewed by, and results tracking
- **Compliance Status**: Real-time dashboard showing equipment compliance status
- **Test Types**: Support for various compliance test types (ACR, TJC, ME)

### Personnel Management
- **Contact Database**: Centralized personnel records with roles and contact information
- **Equipment Assignments**: Link equipment to primary contacts, supervisors, and physicians
- **Role-Based Access**: Different permission levels (Admin, Physics Staff, Technician, Viewer)

### Data Management
- **CSV Import/Export**: Bulk data operations with backward compatibility
- **Advanced Search**: Multi-field filtering and search capabilities
- **Data Validation**: Form validation and data integrity checks
- **Audit Trail**: Creation and modification tracking

## Technical Architecture

### Database Design
- **Relational Structure**: Normalized database with proper foreign key relationships
- **Lookup Tables**: Separate tables for equipment classes, manufacturers, departments, facilities, personnel
- **Legacy Migration**: Migrated from flat text fields to relational structure while maintaining compatibility

### Key Models
- **Equipment**: Main inventory tracking with relational foreign keys
- **ComplianceTest**: Testing records linked to equipment
- **Personnel**: Staff and contact information
- **Facility/Department/Manufacturer**: Lookup tables for data consistency

### Security Features
- **User Authentication**: Flask-Login with username/password; no default credentials — admin created via `flask create-admin`
- **CSRF Protection**: Form security with Flask-WTF
- **Input Validation**: Comprehensive form validation; safe date parsing with `strptime('%Y-%m-%d')`
- **Role-Based Access Control**: Route-level decorators (`manage_equipment_required`, `manage_compliance_required`, `manage_personnel_required`)
- **Forced Password Change**: `enforce_password_change` before_request hook; all routes blocked until password updated
- **Open Redirect Prevention**: Login `next` parameter validated against host
- **Security Audit Logging**: Login success, failure, and logout events logged with username and IP
- **No Credential Storage in App DB**: `eq_servlogin`/`eq_servpwd` dropped via `check_and_migrate_db()` on startup
- **Mandatory SECRET_KEY**: `RuntimeError` at startup if not set — no insecure fallback
- **CSV Import Limits**: 500-row maximum per upload
- **No Credential Creation via Bulk Import**: Personnel CSV import creates contact records only; login access is granted individually through the UI
- **Loopback-Only Dev Server**: `app.run` binds `127.0.0.1`; `FLASK_ENV` replaced with `FLASK_DEBUG`

## User Interface

### Dashboard Features
- **Equipment List**: Sortable, filterable equipment inventory with pagination
- **Equipment Details**: Comprehensive equipment information with contact details
- **Compliance History**: Complete testing history with sortable records
- **Search & Filter**: Advanced filtering by class, manufacturer, department, facility

### Form Handling
- **Equipment Forms**: Multi-section forms with validation and auto-population
- **Contact Integration**: Automatic address population based on facility selection
- **Bulk Operations**: CSV-based bulk editing and import functionality

## Data Import/Export

### CSV Compatibility
- **Dual Format Support**: Handles both new descriptive column names and legacy formats
- **Automatic Relational Mapping**: Converts CSV text to proper database relationships
- **Smart Data Creation**: Automatically creates lookup table entries for new values
- **Round-trip Compatibility**: Export and re-import data seamlessly

### Migration Support
- **Legacy Field Cleanup**: Tools to migrate from old flat structure to relational design
- **Data Validation**: Verification scripts to ensure migration completeness
- **Backup Procedures**: Automated backup creation before destructive operations

## Deployment

### Production Features
- **Systemd Integration**: Automatic startup and failure recovery
- **Database**: SQLite for all environments; no separate database server required
- **Static File Handling**: Optimized for CDN deployment
- **Environment Configuration**: Environment variable-based configuration

### Monitoring & Maintenance
- **Health Checks**: Application monitoring endpoints
- **Automated Backups**: Regular database backup procedures
- **Log Management**: Comprehensive logging for troubleshooting

## Current Status
- **Database**: Fully migrated to relational structure; `check_and_migrate_db()` runs on every startup to apply incremental changes
- **Import/Export**: Personnel CSV import creates contact records only (no login credentials); equipment/compliance/facility import unchanged
- **UI/UX**: Modern Bootstrap-based responsive interface; service credential fields removed from equipment form and detail views
- **Security**: Hardened per internal security triage (2025-05); all addressable PDF findings resolved through v1.2.0 — see README for full feature list
- **Code Quality**: Duplicate `eq_mefacreg` logic extracted to `_generate_mefacreg()`; `MockPagination` promoted to module-level class; redundant in-function imports removed
- **Testing**: Integration test scaffold in `tests/` covering auth, roles, CSV limits, and date arithmetic

The application provides a complete solution for radiology equipment management with robust data handling, compliance tracking, and user-friendly interfaces suitable for healthcare environments.