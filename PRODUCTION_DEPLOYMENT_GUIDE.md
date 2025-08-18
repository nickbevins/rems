# Production Installation Guide for REMS

## Overview
This guide provides step-by-step instructions for deploying the Radiation Equipment Management System (REMS) in a production environment with automatic startup, failure recovery, and automated backup capabilities.

## Pre-Installation Requirements

**Server Setup:**
- Ubuntu Server 20.04/22.04 LTS or Windows Server 2019/2022
- Minimum 16GB RAM, 4+ CPU cores
- 500GB SSD storage with RAID 1
- Static IP address configured
- Firewall configured (ports 80, 443, 22/3389)

## Step 1: System Dependencies Installation

### Ubuntu/Linux Installation
```bash
# Update system packages to latest versions
sudo apt update && sudo apt upgrade -y

# Install core dependencies:
# - python3.8: Runtime environment for the Flask application
# - python3.8-venv: Virtual environment support for dependency isolation
# - nginx: Web server for reverse proxy and SSL termination
# - mysql-server: Database server for persistent storage
# - supervisor: Process control system (alternative to systemd)
# - certbot: SSL certificate management via Let's Encrypt
sudo apt install -y python3.8 python3.8-venv python3-pip nginx mysql-server
sudo apt install -y supervisor certbot python3-certbot-nginx

# Install backup and scheduling utilities
sudo apt install -y rsync cron
```

### Windows Installation
- Install Python 3.8+ from python.org
- Install MySQL Server 8.0+
- Install IIS or NGINX for Windows
- Install NSSM (Non-Sucking Service Manager) for service management

## Step 2: Database Setup

```bash
# Secure MySQL installation - sets root password and removes test databases
sudo mysql_secure_installation

# Create application database and dedicated user
sudo mysql -u root -p
```

```sql
-- Create database with UTF-8 support for international characters
CREATE DATABASE physdb CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Create dedicated database user with limited privileges
CREATE USER 'physdb_user'@'localhost' IDENTIFIED BY 'secure_password_here';

-- Grant only necessary privileges to the application user
GRANT ALL PRIVILEGES ON physdb.* TO 'physdb_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

**Explanation:** We create a dedicated database user instead of using root for security. The UTF-8 character set ensures proper handling of international characters in equipment names and locations.

## Step 3: Application Deployment

```bash
# Create application directory in standard location
sudo mkdir -p /opt/rems
sudo chown $USER:$USER /opt/rems
cd /opt/rems

# Copy application files here (app.py, templates/, static/, requirements.txt)
# This can be done via git clone, scp, or file transfer

# Create isolated Python environment to avoid conflicts
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
pip install gunicorn  # Production WSGI server (more robust than Flask dev server)

# Create production environment configuration
cat > .env << EOF
SECRET_KEY=your_very_secure_secret_key_here
DATABASE_URL=mysql://physdb_user:secure_password_here@localhost/physdb
FLASK_ENV=production
FLASK_DEBUG=False
EOF

# Initialize database schema (run once, then stop)
python app.py
```

**Explanation:** The virtual environment isolates Python dependencies, preventing conflicts with system packages. Gunicorn is a production-grade WSGI server that handles multiple concurrent requests efficiently.

## Step 4: Auto-Start Service Configuration

### Linux (Systemd Service)

```bash
# Create systemd service file for automatic startup and management
sudo tee /etc/systemd/system/rems.service << EOF
[Unit]
Description=REMS - Radiation Equipment Management System
After=network.target mysql.service  # Start after network and database
Requires=mysql.service               # Require database to be running

[Service]
Type=notify
User=www-data                        # Run as web server user for security
Group=www-data
WorkingDirectory=/opt/rems
Environment=PATH=/opt/rems/venv/bin
ExecStart=/opt/rems/venv/bin/gunicorn --bind 127.0.0.1:5000 --workers 4 --timeout 120 app:app
ExecReload=/bin/kill -s HUP \$MAINPID
Restart=always                       # Automatically restart on failure
RestartSec=10                        # Wait 10 seconds before restart
KillMode=mixed
TimeoutStopSec=5

[Install]
WantedBy=multi-user.target          # Start at boot time
EOF

# Register and start the service
sudo systemctl daemon-reload
sudo systemctl enable rems.service  # Enable auto-start at boot
sudo systemctl start rems.service   # Start service now
sudo systemctl status rems.service  # Check service status
```

### Windows Service (using NSSM)

```cmd
# Install application as Windows service using NSSM
nssm install REMS "C:\opt\rems\venv\Scripts\python.exe"
nssm set REMS Application "C:\opt\rems\venv\Scripts\gunicorn.exe"
nssm set REMS AppParameters "--bind 127.0.0.1:5000 --workers 4 app:app"
nssm set REMS AppDirectory "C:\opt\rems"
nssm set REMS Start SERVICE_AUTO_START  # Auto-start with Windows
nssm start REMS
```

**Explanation:** Systemd manages the application lifecycle, automatically restarting it if it crashes and starting it at boot time. The service runs as `www-data` user for security isolation.

## Step 5: Web Server Configuration (NGINX)

```bash
# Create NGINX reverse proxy configuration
sudo tee /etc/nginx/sites-available/rems << EOF
# HTTP server - redirect all traffic to HTTPS
server {
    listen 80;
    server_name your-server-name.com;
    
    # Force HTTPS for security
    return 301 https://\$server_name\$request_uri;
}

# HTTPS server - main application
server {
    listen 443 ssl http2;
    server_name your-server-name.com;
    
    # SSL Configuration (certificates obtained via certbot)
    ssl_certificate /etc/letsencrypt/live/your-server-name.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-server-name.com/privkey.pem;
    
    # Security headers to prevent common attacks
    add_header X-Frame-Options DENY;                    # Prevent clickjacking
    add_header X-Content-Type-Options nosniff;          # Prevent MIME sniffing
    add_header X-XSS-Protection "1; mode=block";        # XSS protection
    
    # Serve static files directly (CSS, JS, images) for better performance
    location /static {
        alias /opt/rems/static;
        expires 1y;                                      # Cache static files for 1 year
        add_header Cache-Control "public, immutable";
    }
    
    # Proxy all other requests to Flask application
    location / {
        proxy_pass http://127.0.0.1:5000;               # Forward to Gunicorn
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
EOF

# Enable the site configuration
sudo ln -s /etc/nginx/sites-available/rems /etc/nginx/sites-enabled/
sudo nginx -t                               # Test configuration syntax
sudo systemctl restart nginx

# Obtain SSL certificate from Let's Encrypt (free)
sudo certbot --nginx -d your-server-name.com
```

**Explanation:** NGINX acts as a reverse proxy, handling SSL termination, static file serving, and security headers. This architecture improves performance and security compared to serving directly from Flask.

## Step 6: Automated Backup System

### Database Backup Script

```bash
# Create backup directory structure
sudo mkdir -p /opt/backups/rems/{daily,weekly,monthly}
sudo chown root:root /opt/backups/rems

# Create comprehensive backup script
sudo tee /opt/backups/rems-backup.sh << 'EOF'
#!/bin/bash

# Configuration variables
DB_NAME="physdb"
DB_USER="physdb_user"
DB_PASS="secure_password_here"
APP_DIR="/opt/rems"
BACKUP_DIR="/opt/backups/rems"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

# Create timestamped backup directory
mkdir -p "$BACKUP_DIR/daily/$DATE"

# Database backup with consistency guarantees
# --single-transaction ensures consistent backup of InnoDB tables
# --routines includes stored procedures and functions
# --triggers includes database triggers
mysqldump -u $DB_USER -p$DB_PASS --single-transaction --routines --triggers $DB_NAME | gzip > "$BACKUP_DIR/daily/$DATE/database.sql.gz"

# Application files backup (excluding virtual environment and SQLite files)
tar -czf "$BACKUP_DIR/daily/$DATE/application.tar.gz" -C /opt rems --exclude='rems/venv' --exclude='rems/instance/*.db'

# Log backup completion for monitoring
echo "$(date): Backup completed - $DATE" >> /var/log/rems-backup.log

# Cleanup old daily backups (keep specified number of days)
find "$BACKUP_DIR/daily" -type d -mtime +$RETENTION_DAYS -exec rm -rf {} +

# Create weekly backups on Sundays
if [ $(date +%u) -eq 7 ]; then
    cp -r "$BACKUP_DIR/daily/$DATE" "$BACKUP_DIR/weekly/"
    find "$BACKUP_DIR/weekly" -type d -mtime +90 -exec rm -rf {} +  # Keep 3 months
fi

# Create monthly backups on first day of month
if [ $(date +%d) -eq 01 ]; then
    cp -r "$BACKUP_DIR/daily/$DATE" "$BACKUP_DIR/monthly/"
    find "$BACKUP_DIR/monthly" -type d -mtime +365 -exec rm -rf {} +  # Keep 1 year
fi
EOF

chmod +x /opt/backups/rems-backup.sh
```

### Backup Scheduling and Verification

```bash
# Add backup jobs to root crontab
sudo crontab -e

# Add these cron job entries:
# Daily backup at 2 AM (low usage time)
0 2 * * * /opt/backups/rems-backup.sh

# Weekly backup verification on Sundays at 3 AM
0 3 * * 0 /opt/backups/verify-backup.sh

# Monthly log rotation to prevent log files from growing too large
0 0 1 * * logrotate /etc/logrotate.d/rems-backup
```

### Backup Verification Script

```bash
# Create backup integrity verification script
sudo tee /opt/backups/verify-backup.sh << 'EOF'
#!/bin/bash

# Find the most recent backup directory
LATEST_BACKUP=$(find /opt/backups/rems/daily -type d -name "????????_??????" | sort | tail -1)

if [ -z "$LATEST_BACKUP" ]; then
    echo "$(date): ERROR - No backups found!" >> /var/log/rems-backup.log
    exit 1
fi

# Verify database backup integrity
if gzip -t "$LATEST_BACKUP/database.sql.gz"; then
    echo "$(date): Database backup verified - $LATEST_BACKUP" >> /var/log/rems-backup.log
else
    echo "$(date): ERROR - Database backup corrupted - $LATEST_BACKUP" >> /var/log/rems-backup.log
fi

# Verify application backup integrity
if tar -tzf "$LATEST_BACKUP/application.tar.gz" >/dev/null; then
    echo "$(date): Application backup verified - $LATEST_BACKUP" >> /var/log/rems-backup.log
else
    echo "$(date): ERROR - Application backup corrupted - $LATEST_BACKUP" >> /var/log/rems-backup.log
fi
EOF

chmod +x /opt/backups/verify-backup.sh
```

**Explanation:** The backup system creates daily, weekly, and monthly backups with different retention periods. Verification ensures backup integrity without false confidence in corrupted backups.

## Step 7: Production Security Hardening

```bash
# Set proper file permissions for security
sudo chown -R www-data:www-data /opt/rems    # Web server user owns files
sudo chmod -R 755 /opt/rems                 # Read/execute for group, no write
sudo chmod 600 /opt/rems/.env               # Only owner can read environment file

# Configure UFW firewall
sudo ufw enable
sudo ufw allow ssh                          # Allow SSH access
sudo ufw allow 'Nginx Full'                # Allow HTTP/HTTPS
sudo ufw deny 3306                          # Block external MySQL access

# Set up log rotation to prevent disk space issues
sudo tee /etc/logrotate.d/rems << EOF
/var/log/rems*.log {
    daily
    missingok                               # Don't error if log file missing
    rotate 30                               # Keep 30 days of logs
    compress                                # Compress old logs
    delaycompress                           # Don't compress most recent
    notifempty                              # Don't rotate empty files
    copytruncate                            # Truncate original file after copy
}
EOF
```

**Explanation:** Security hardening follows the principle of least privilege, limiting file permissions and network access to only what's necessary for operation.

## Step 8: Monitoring and Health Checks

```bash
# Create application health monitoring script
sudo tee /opt/rems/health-check.sh << 'EOF'
#!/bin/bash

# Check if application is responding to HTTP requests
if curl -f -s http://localhost:5000 > /dev/null; then
    echo "$(date): REMS application is healthy"
else
    echo "$(date): ERROR - REMS application not responding" >> /var/log/rems-health.log
    # Attempt automatic recovery
    systemctl restart rems.service
    echo "$(date): Restarted REMS service" >> /var/log/rems-health.log
fi

# Check database connectivity
if mysql -u physdb_user -psecure_password_here physdb -e "SELECT 1;" > /dev/null 2>&1; then
    echo "$(date): Database connection healthy"
else
    echo "$(date): ERROR - Database connection failed" >> /var/log/rems-health.log
fi
EOF

chmod +x /opt/rems/health-check.sh

# Schedule health checks every 5 minutes
echo "*/5 * * * * /opt/rems/health-check.sh >> /var/log/rems-health.log 2>&1" | sudo crontab -
```

**Explanation:** Health checks provide early detection of issues and automatic recovery for common problems like application crashes or database connection issues.

## Step 9: SSL Certificate Auto-Renewal

```bash
# Test certificate renewal process (dry run)
sudo certbot renew --dry-run

# Schedule automatic certificate renewal (runs twice daily)
# Let's Encrypt certificates expire every 90 days
echo "0 12 * * * /usr/bin/certbot renew --quiet" | sudo crontab -
```

**Explanation:** SSL certificates from Let's Encrypt expire every 90 days. Automatic renewal ensures continuous secure access without manual intervention.

## Step 10: Final Verification

```bash
# Verify all critical services are running
sudo systemctl status rems.service          # Application service
sudo systemctl status nginx                 # Web server
sudo systemctl status mysql                 # Database server

# Test external application access
curl -I https://your-server-name.com        # Should return 200 OK

# Monitor real-time logs for issues
sudo journalctl -u rems.service -f          # Application logs
tail -f /var/log/rems-backup.log           # Backup logs
tail -f /var/log/rems-health.log           # Health check logs
```

## Disaster Recovery Process

### Complete System Restoration

```bash
# Stop application to prevent data corruption during restore
sudo systemctl stop rems.service

# Restore database from backup
gunzip < /opt/backups/rems/daily/YYYYMMDD_HHMMSS/database.sql.gz | mysql -u physdb_user -p physdb

# Restore application files
cd /opt && tar -xzf /opt/backups/rems/daily/YYYYMMDD_HHMMSS/application.tar.gz

# Recreate virtual environment and reinstall dependencies
cd /opt/rems
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn

# Restart all services
sudo systemctl start rems.service
sudo systemctl restart nginx
```

### Backup Testing Procedure

```bash
# Monthly backup restoration test (recommended)
# 1. Create test database
mysql -u root -p -e "CREATE DATABASE physdb_test;"

# 2. Restore latest backup to test database
gunzip < /opt/backups/rems/daily/$(ls -1 /opt/backups/rems/daily | tail -1)/database.sql.gz | mysql -u root -p physdb_test

# 3. Verify data integrity
mysql -u root -p physdb_test -e "SELECT COUNT(*) FROM equipment; SELECT COUNT(*) FROM compliance_tests;"

# 4. Clean up test database
mysql -u root -p -e "DROP DATABASE physdb_test;"
```

## System Architecture Summary

**Service Dependencies:**
1. **MySQL Database** - Persistent data storage
2. **REMS Application** - Flask/Gunicorn service (depends on MySQL)
3. **NGINX Web Server** - Reverse proxy and SSL termination
4. **Cron Jobs** - Automated backups and health checks
5. **Certbot** - SSL certificate management

**Automatic Recovery Features:**
- Service restart on application failure (systemd)
- Health monitoring with automatic recovery (cron)
- SSL certificate auto-renewal (certbot + cron)
- Daily backup verification with corruption detection
- Log rotation to prevent disk space issues

**Security Features:**
- Firewall configuration blocking unnecessary ports
- SSL/TLS encryption for all web traffic
- Secure file permissions and user isolation
- Security headers preventing common web attacks
- Database user with minimal required privileges

This production deployment provides enterprise-level reliability, security, and maintainability for the REMS application.