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
- Python 3.8 or higher
- pip package manager
- SQLite (default) or MySQL/PostgreSQL database

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
   cp .env.example .env
   # Edit .env file with your configuration
   ```

5. **Initialize Database**
   ```bash
   python app.py
   # This will create the database tables automatically
   ```

6. **Access the Application**
   - Navigate to `http://localhost:5000`
   - Default admin login: `admin` / `password123`
   - Change the admin password immediately after first login

## Production Deployment (Render.com)

### Requirements
- Render.com account with paid tier ($7+ for persistent storage)
- GitHub repository with your code

### Setup Steps
1. **Create Render Web Service**
   - Connect your GitHub repository
   - Set build command: `pip install -r requirements.txt`
   - Set start command: `gunicorn app:app`

2. **Add Persistent Disk**
   - In Render dashboard, go to your service
   - Add disk with mount path: `/var/data`
   - Size: 1GB minimum (can expand later)

3. **Environment Variables**
   - Set `RENDER=true`
   - Set `SECRET_KEY` to a secure random string
   - Optionally set `DATABASE_URL` for PostgreSQL

4. **Deploy and Import Data**
   - Deploy the service
   - Use CSV import features to load your data
   - Data will persist across future deployments

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
- `SECRET_KEY`: Flask secret key for session security
- `DATABASE_URL`: Database connection string
- `FLASK_ENV`: Development/production environment
- `ITEMS_PER_PAGE`: Number of items displayed per page

### Database Options
- **SQLite** (default): Simple file-based database
- **MySQL**: For multi-user production environments
- **PostgreSQL**: Enterprise-grade database option

## Security Features
- CSRF protection on all forms
- Input validation and sanitization
- Secure session management
- SQL injection prevention
- XSS protection

## Maintenance

### Database Backup
```bash
# SQLite
cp physdb.db physdb_backup_$(date +%Y%m%d).db

# MySQL
mysqldump -u username -p physdb > physdb_backup_$(date +%Y%m%d).sql
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

### CSV Import Format
The CSV file should contain the following columns:
- `eq_class`: Equipment class (CT, MRI, X-ray, etc.)
- `eq_subclass`: Equipment subclass
- `eq_manu`: Manufacturer name
- `eq_mod`: Model number
- `eq_dept`: Department
- `eq_rm`: Room number
- `eq_fac`: Facility name
- `eq_address`: Facility address
- Contact fields for personnel
- Asset tracking fields
- Date fields (YYYY-MM-DD format)
- Technical specifications
- Compliance requirements

### Date Format
All dates should be in YYYY-MM-DD format:
- `eq_instdt`: Installation date
- `eq_eoldate`: End of life date
- `eq_mandt`: Manufacture date

### Boolean Fields
Use TRUE/FALSE for boolean values:
- `eq_retired`: Equipment retirement status

## License

This project is developed for internal use in healthcare organizations for managing radiology equipment compliance and maintenance.

## Version History

### v1.0.0
- Initial release
- Equipment database management
- Compliance testing system
- CSV import functionality
- Web-based interface
- Search and filtering capabilities

---

For technical support or questions about this system, please contact your system administrator.