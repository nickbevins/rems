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
- **User Authentication**: Flask-Login with role-based permissions
- **CSRF Protection**: Form security with Flask-WTF
- **Input Validation**: Comprehensive form validation and sanitization

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
- **Database Flexibility**: SQLite for development, MySQL/PostgreSQL for production
- **Static File Handling**: Optimized for CDN deployment
- **Environment Configuration**: Environment variable-based configuration

### Monitoring & Maintenance
- **Health Checks**: Application monitoring endpoints
- **Automated Backups**: Regular database backup procedures
- **Log Management**: Comprehensive logging for troubleshooting

## Current Status
- **Database**: Fully migrated to relational structure
- **Import/Export**: Updated for new CSV format with backward compatibility
- **UI/UX**: Modern Bootstrap-based responsive interface
- **Testing**: All legacy field references removed and verified

The application provides a complete solution for radiology equipment management with robust data handling, compliance tracking, and user-friendly interfaces suitable for healthcare environments.