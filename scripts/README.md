# REMS Deployment Scripts

This directory contains automated deployment scripts for the REMS (Radiation Equipment Management System) application.

## Scripts Overview

### Production Deployment
- `deploy_production.sh` - Linux/Ubuntu automated production deployment
- `deploy_production.ps1` - Windows Server automated production deployment

### Utility Scripts
- `populate_personnel.py` - Populate personnel/contact data
- `create_admin.py` - Create administrative users
- `set_default_passwords.py` - Reset user passwords
- `get_personnel_ids.py` - Extract personnel information

## Linux Production Deployment

### Prerequisites
- Ubuntu Server 20.04/22.04 LTS
- User with sudo privileges (not root)
- Domain name pointing to server
- Minimum 16GB RAM, 4+ CPU cores, 500GB storage

### Usage
```bash
# Set required environment variables
export SERVER_NAME="your-domain.com"
export DB_PASSWORD="your_secure_database_password"

# Make script executable
chmod +x deploy_production.sh

# Run deployment (will prompt for MySQL root password)
./deploy_production.sh
```

### What it does
1. Installs system dependencies (Python, NGINX, MySQL, etc.)
2. Sets up MySQL database with dedicated user
3. Deploys application to `/opt/rems`
4. Creates systemd service for auto-startup
5. Configures NGINX reverse proxy with security headers
6. Sets up automated daily/weekly/monthly backups
7. Configures health monitoring with automatic recovery
8. Sets up UFW firewall rules
9. Obtains SSL certificate via Let's Encrypt
10. Performs verification tests

## Windows Production Deployment

### Prerequisites
- Windows Server 2019/2022
- Administrator privileges
- MySQL Server 8.0+ installed
- Python 3.8+ installed
- Domain name pointing to server

### Usage
```powershell
# Run PowerShell as Administrator
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Run deployment script
.\deploy_production.ps1 -ServerName "your-domain.com" -DatabasePassword "your_secure_password"
```

### What it does
1. Installs Windows dependencies (Chocolatey, NSSM, IIS modules)
2. Sets up MySQL database with dedicated user
3. Deploys application to `C:\opt\rems`
4. Creates Windows service for auto-startup
5. Configures IIS as reverse proxy
6. Sets up automated backups via scheduled tasks
7. Configures health monitoring via scheduled tasks
8. Sets up Windows Firewall rules
9. Performs verification tests

## Post-Deployment Steps

### Both Platforms
1. **Update DNS**: Point your domain to the server's IP address
2. **Review Configuration**: Check and customize the `.env` file in the application directory
3. **Test Application**: Access your application via the configured domain
4. **Monitor Logs**: Check health and backup logs regularly

### Linux Additional Steps
```bash
# Monitor service status
sudo systemctl status rems.service

# View application logs
sudo journalctl -u rems.service -f

# View health check logs
tail -f /var/log/rems-health.log

# View backup logs
tail -f /var/log/rems-backup.log

# Manual backup
sudo /opt/backups/rems-backup.sh

# Manual health check
sudo /opt/rems/health-check.sh
```

### Windows Additional Steps
```powershell
# Check service status
Get-Service REMS

# View health check logs
Get-Content C:\logs\rems-health.log -Tail 10

# View backup logs  
Get-Content C:\logs\rems-backup.log -Tail 10

# Manual backup
& "C:\opt\backups\rems\rems-backup.ps1"

# Manual health check
& "C:\opt\rems\health-check.ps1"
```

## Directory Structure After Deployment

### Linux
```
/opt/rems/                  # Application directory
├── app.py                  # Main application
├── templates/              # HTML templates
├── static/                 # CSS/JS files
├── venv/                   # Python virtual environment
├── .env                    # Environment configuration
└── health-check.sh         # Health monitoring script

/opt/backups/rems/          # Backup directory
├── daily/                  # Daily backups (30 days)
├── weekly/                 # Weekly backups (3 months)
├── monthly/                # Monthly backups (1 year)
├── rems-backup.sh          # Backup script
└── verify-backup.sh        # Backup verification script
```

### Windows
```
C:\opt\rems\                # Application directory
├── app.py                  # Main application
├── templates\              # HTML templates
├── static\                 # CSS/JS files
├── venv\                   # Python virtual environment
├── .env                    # Environment configuration
├── start_service.bat       # Service startup script
└── health-check.ps1        # Health monitoring script

C:\opt\backups\rems\        # Backup directory
├── daily\                  # Daily backups (30 days)
├── weekly\                 # Weekly backups (3 months)
├── monthly\                # Monthly backups (1 year)
└── rems-backup.ps1         # Backup script
```

## Security Features

Both deployment scripts implement:
- Database user with minimal required privileges
- Firewall configuration blocking unnecessary ports
- SSL/TLS encryption for web traffic (Linux only, manual setup required for Windows)
- Security headers preventing common web attacks
- File permissions following principle of least privilege
- Service isolation using dedicated users

## Backup and Recovery

### Automated Backups
- **Daily**: 2 AM, retained for 30 days
- **Weekly**: Sundays, retained for 3 months  
- **Monthly**: First day of month, retained for 1 year

### Manual Recovery
```bash
# Linux - Restore from backup
sudo systemctl stop rems.service
gunzip < /opt/backups/rems/daily/YYYYMMDD_HHMMSS/database.sql.gz | mysql -u physdb_user -p physdb
cd /opt && sudo tar -xzf /opt/backups/rems/daily/YYYYMMDD_HHMMSS/application.tar.gz
sudo systemctl start rems.service

# Windows - Restore from backup  
Stop-Service REMS
# Restore database from backup
mysql -u physdb_user -p physdb < backup_file.sql
# Restore application files from backup zip
Expand-Archive -Path backup_file.zip -DestinationPath C:\opt\rems -Force
Start-Service REMS
```

## Troubleshooting

### Common Issues
1. **Service won't start**: Check logs for database connection issues
2. **Application not accessible**: Verify firewall rules and DNS configuration
3. **SSL certificate issues**: Ensure domain points to server before running certbot
4. **Database connection failed**: Check MySQL service status and credentials

### Getting Help
- Check application logs for detailed error messages
- Verify all prerequisites are met
- Ensure environment variables are set correctly
- Test database connectivity manually

## Maintenance

### Regular Tasks
- Monitor disk space for log and backup files
- Review security updates for system packages
- Test backup restoration procedures monthly
- Monitor application performance and resource usage

### Updates
To update the application:
1. Stop the service
2. Create a backup
3. Update application files
4. Restart the service
5. Verify functionality

The deployment scripts provide a robust, production-ready environment with automated monitoring, backups, and recovery capabilities.