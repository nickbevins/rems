# Production Installation Guide for REMS

## Overview
This guide provides step-by-step instructions for deploying the Radiation Equipment Management System (REMS) in a production environment with automatic startup, failure recovery, and automated backup capabilities.

The examples here are written for an on-premise Linux VM, which is the primary planned deployment target, but the same principles apply to any Linux-based environment — including cloud VMs (AWS EC2, Azure VM, etc.) or bare-metal servers. Windows Server deployment notes are included where relevant.

## Pre-Installation Requirements

**Recommended Server Specs:**
- Ubuntu Server 22.04 LTS (or any Linux distro), Windows Server 2019/2022, or cloud VM
- 2-4 vCPUs, 4-8GB RAM (the application is lightweight; scale to your environment)
- 50GB storage minimum (OS + app + backups; expand as needed)
- Static IP or stable DNS hostname
- Firewall: ports 80 and 443 open inbound; port 22 (SSH) for admin access

## Step 1: System Dependencies Installation

### Ubuntu/Linux Installation
```bash
# Update system packages to latest versions
sudo apt update && sudo apt upgrade -y

# Install core dependencies:
# - python3.11: Runtime environment for the Flask application
# - python3.11-venv: Virtual environment support for dependency isolation
# - nginx: Web server for reverse proxy and SSL termination
# - certbot: SSL certificate management via Let's Encrypt
sudo apt install -y python3.11 python3.11-venv python3-pip nginx
sudo apt install -y supervisor certbot python3-certbot-nginx

# Install backup and scheduling utilities
sudo apt install -y rsync cron sqlite3
```

### Windows Installation
- Install Python 3.11 from python.org
- Install IIS or NGINX for Windows
- Install NSSM (Non-Sucking Service Manager) for service management

## Step 2: Application Deployment

```bash
# Create application directory in standard location
sudo mkdir -p /opt/rems
sudo chown $USER:$USER /opt/rems
cd /opt/rems

# Copy application files here (app.py, templates/, static/, requirements.txt)
# This can be done via git clone, scp, or file transfer

# Create isolated Python environment to avoid conflicts
python3.11 -m venv venv
source venv/bin/activate

# Install all Python dependencies (including gunicorn)
pip install -r requirements.txt

# Create production environment configuration
cat > .env << EOF
SECRET_KEY=your_very_secure_secret_key_here
FLASK_ENV=production
EOF
```

**Note:** No separate database installation or initialization is required. The application uses SQLite, which is file-based and requires no server process. The database file (`instance/physdb.db`) is created automatically the first time Gunicorn starts.

**Important:** After first login, immediately change the default admin credentials (username: `admin`, password: `password123`).

**Explanation:** The virtual environment isolates Python dependencies, preventing conflicts with system packages. Gunicorn is included in `requirements.txt` and is the production-grade WSGI server that handles concurrent requests efficiently.

## Step 3: Auto-Start Service Configuration

### Linux (Systemd Service)

```bash
# Create systemd service file for automatic startup and management
sudo tee /etc/systemd/system/rems.service << EOF
[Unit]
Description=REMS - Radiation Equipment Management System
After=network.target

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

# Ensure www-data can write to the instance directory for the database file
sudo chown -R www-data:www-data /opt/rems/instance

# Register and start the service
sudo systemctl daemon-reload
sudo systemctl enable rems.service  # Enable auto-start at boot
sudo systemctl start rems.service   # Start service now
sudo systemctl status rems.service  # Check service status
```

### Windows Service (using NSSM)

```cmd
# Install application as Windows service using NSSM
nssm install REMS "C:\opt\rems\venv\Scripts\gunicorn.exe"
nssm set REMS AppParameters "--bind 127.0.0.1:5000 --workers 4 --timeout 120 app:app"
nssm set REMS AppDirectory "C:\opt\rems"
nssm set REMS Start SERVICE_AUTO_START  # Auto-start with Windows
nssm start REMS
```

**Explanation:** Systemd manages the application lifecycle, automatically restarting it if it crashes and starting it at boot time. The service runs as `www-data` user for security isolation. No database service dependency is needed since SQLite is file-based.

## Step 4: Web Server Configuration (NGINX)

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

    # SSL Configuration (certificate from your internal CA - see Step 8)
    ssl_certificate /etc/ssl/rems/rems.crt;
    ssl_certificate_key /etc/ssl/rems/rems.key;

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

```

**Explanation:** NGINX acts as a reverse proxy, handling SSL termination, static file serving, and security headers. This architecture improves performance and security compared to serving directly from Flask.

## Step 5: Automated Backup System

### Database Backup Script

The database is a single SQLite file at `/opt/rems/instance/physdb.db`. Backups are simple file copies using SQLite's built-in hot-backup command, which ensures a consistent snapshot even while the application is running.

```bash
# Create backup directory structure
sudo mkdir -p /opt/backups/rems/{daily,weekly,monthly}
sudo chown root:root /opt/backups/rems

# Create comprehensive backup script
sudo tee /opt/backups/rems-backup.sh << 'EOF'
#!/bin/bash

# Configuration variables
APP_DIR="/opt/rems"
DB_FILE="$APP_DIR/instance/physdb.db"
BACKUP_DIR="/opt/backups/rems"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

# Create timestamped backup directory
mkdir -p "$BACKUP_DIR/daily/$DATE"

# Database backup using SQLite's .backup command for a consistent hot backup
# This is safe to run while the application is live
sqlite3 "$DB_FILE" ".backup '$BACKUP_DIR/daily/$DATE/physdb.db'"
gzip "$BACKUP_DIR/daily/$DATE/physdb.db"

# Application files backup (excluding virtual environment and database file)
tar -czf "$BACKUP_DIR/daily/$DATE/application.tar.gz" -C /opt rems \
    --exclude='rems/venv' \
    --exclude='rems/instance/*.db'

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
if gzip -t "$LATEST_BACKUP/physdb.db.gz"; then
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

**Explanation:** The backup system creates daily, weekly, and monthly backups with different retention periods. SQLite's `.backup` command produces a consistent snapshot without needing to stop the application. Verification ensures backup integrity.

## Step 6: Production Security Hardening

```bash
# Set proper file permissions for security
sudo chown -R www-data:www-data /opt/rems    # Web server user owns files
sudo chmod -R 755 /opt/rems                 # Read/execute for group, no write
sudo chmod 600 /opt/rems/.env               # Only owner can read environment file

# Configure UFW firewall
sudo ufw enable
sudo ufw allow ssh                          # Allow SSH access
sudo ufw allow 'Nginx Full'                # Allow HTTP/HTTPS

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

## Step 7: Monitoring and Health Checks

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

# Check database file is accessible and not corrupt
DB_FILE="/opt/rems/instance/physdb.db"
if sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM equipment;" > /dev/null 2>&1; then
    echo "$(date): Database is healthy"
else
    echo "$(date): ERROR - Database check failed" >> /var/log/rems-health.log
fi
EOF

chmod +x /opt/rems/health-check.sh

# Schedule health checks every 5 minutes
echo "*/5 * * * * /opt/rems/health-check.sh >> /var/log/rems-health.log 2>&1" | sudo crontab -
```

**Explanation:** Health checks provide early detection of issues and automatic recovery for common problems like application crashes. The database check verifies the SQLite file is readable and not corrupt.

## Step 8: SSL Certificate

Choose the appropriate option for your deployment:

### Option A: Internal Network (AD Certificate Services)

If REMS is on an internal network not reachable from the internet, use a certificate issued by your organization's Active Directory Certificate Services (AD CS). Let's Encrypt cannot be used in this case as it requires public internet access to validate your domain.

### Option B: Internet-Accessible Server (Let's Encrypt)

If your server is publicly reachable, you can use a free Let's Encrypt certificate:

```bash
sudo certbot --nginx -d your-server-name.com

# Schedule automatic renewal (certificates expire every 90 days)
echo "0 12 * * * /usr/bin/certbot renew --quiet" | sudo crontab -
```

---

### Option A Detail: Internal CA / AD CS

### Requesting a Certificate from IT

Ask your IT/security team for:
> *"An SSL server certificate for an internal web application, hostname `rems.yourdomain.local` (or whatever internal hostname you choose)."*

They will provide you with:
- A certificate file (`.crt` or `.pem`)
- A private key file (`.key`)

### Installing the Certificate

```bash
# Create directory for certificate files
sudo mkdir -p /etc/ssl/rems
sudo chmod 700 /etc/ssl/rems

# Copy the files provided by IT to the server
# (replace with actual filenames IT provides)
sudo cp your-cert.crt /etc/ssl/rems/rems.crt
sudo cp your-cert.key /etc/ssl/rems/rems.key
sudo chmod 600 /etc/ssl/rems/rems.key

# Restart NGINX to apply
sudo systemctl restart nginx
```

### Certificate Renewal

AD CS certificates typically have 1-2 year validity. Set a calendar reminder to request a renewal before expiry. IT will provide updated certificate files — repeat the install steps above and restart NGINX.

**Note:** Domain-joined Windows machines will automatically trust certificates issued by your organization's CA, so users will see no browser warnings.

## Step 9: Final Verification

```bash
# Verify all critical services are running
sudo systemctl status rems.service          # Application service
sudo systemctl status nginx                 # Web server

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
# Stop application to prevent interference during restore
sudo systemctl stop rems.service

# Restore database from backup
gunzip -c /opt/backups/rems/daily/YYYYMMDD_HHMMSS/physdb.db.gz > /opt/rems/instance/physdb.db
sudo chown www-data:www-data /opt/rems/instance/physdb.db

# Restore application files (if needed)
cd /opt && tar -xzf /opt/backups/rems/daily/YYYYMMDD_HHMMSS/application.tar.gz

# Recreate virtual environment and reinstall dependencies
cd /opt/rems
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Restart all services
sudo systemctl start rems.service
sudo systemctl restart nginx
```

### Backup Testing Procedure

```bash
# Monthly backup restoration test (recommended)
# 1. Decompress the latest backup to a temp location
gunzip -c /opt/backups/rems/daily/$(ls -1 /opt/backups/rems/daily | tail -1)/physdb.db.gz > /tmp/physdb_test.db

# 2. Verify data integrity
sqlite3 /tmp/physdb_test.db "SELECT COUNT(*) FROM equipment; SELECT COUNT(*) FROM compliance_tests;"

# 3. Clean up
rm /tmp/physdb_test.db
```

### Schema Upgrades

The application automatically applies any required schema changes on startup via `check_and_migrate_db()`. No manual SQL migrations are needed when upgrading to a newer version — simply deploy the updated code and restart the service.

## System Architecture Summary

**Service Dependencies:**
1. **REMS Application** - Flask/Gunicorn service (SQLite database is embedded, no separate service needed)
2. **NGINX Web Server** - Reverse proxy and SSL termination
3. **Cron Jobs** - Automated backups and health checks
4. **Certbot** - SSL certificate management

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

This production deployment provides reliable, low-maintenance hosting for the REMS application suitable for small-team use.
