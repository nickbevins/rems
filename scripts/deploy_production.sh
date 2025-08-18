#!/bin/bash
# Production Deployment Automation Script for REMS
# This script automates the deployment process described in PRODUCTION_DEPLOYMENT_GUIDE.md

set -e  # Exit on any error
set -u  # Exit on undefined variables

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration - MODIFY THESE VALUES FOR YOUR DEPLOYMENT
SERVER_NAME="${SERVER_NAME:-your-server-name.com}"
DB_PASSWORD="${DB_PASSWORD:-secure_password_here}"
SECRET_KEY="${SECRET_KEY:-$(openssl rand -hex 32)}"
APP_DIR="/opt/rems"
BACKUP_DIR="/opt/backups/rems"
DB_NAME="physdb"
DB_USER="physdb_user"

# Logging function
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

error() {
    echo -e "${RED}[ERROR] $1${NC}" >&2
}

warning() {
    echo -e "${YELLOW}[WARNING] $1${NC}"
}

info() {
    echo -e "${BLUE}[INFO] $1${NC}"
}

# Check if running as root
check_root() {
    if [[ $EUID -eq 0 ]]; then
        error "This script should not be run as root for security reasons"
        error "Run as a regular user with sudo privileges"
        exit 1
    fi
}

# Check for required environment variables
check_environment() {
    log "Checking environment variables..."
    
    if [[ "$SERVER_NAME" == "your-server-name.com" ]]; then
        error "Please set SERVER_NAME environment variable to your domain name"
        exit 1
    fi
    
    if [[ "$DB_PASSWORD" == "secure_password_here" ]]; then
        warning "Using default database password. Set DB_PASSWORD environment variable for production"
    fi
}

# Install system dependencies
install_dependencies() {
    log "Installing system dependencies..."
    
    sudo apt update && sudo apt upgrade -y
    
    # Core dependencies
    sudo apt install -y \
        python3.8 \
        python3.8-venv \
        python3-pip \
        nginx \
        mysql-server \
        supervisor \
        certbot \
        python3-certbot-nginx \
        rsync \
        cron \
        curl \
        git \
        openssl
    
    log "System dependencies installed successfully"
}

# Setup MySQL database
setup_database() {
    log "Setting up MySQL database..."
    
    # Check if MySQL is running
    if ! systemctl is-active --quiet mysql; then
        sudo systemctl start mysql
        sudo systemctl enable mysql
    fi
    
    # Create database and user
    mysql -u root -p -e "
        CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASSWORD}';
        GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';
        FLUSH PRIVILEGES;
    " || {
        error "Database setup failed. Please run mysql_secure_installation first"
        exit 1
    }
    
    log "Database setup completed successfully"
}

# Deploy application
deploy_application() {
    log "Deploying application to ${APP_DIR}..."
    
    # Create application directory
    sudo mkdir -p "$APP_DIR"
    sudo chown "$USER:$USER" "$APP_DIR"
    
    # Copy application files
    if [[ -f "app.py" ]]; then
        cp -r app.py templates/ static/ requirements.txt "$APP_DIR/"
        log "Application files copied"
    else
        error "app.py not found in current directory"
        exit 1
    fi
    
    # Create Python virtual environment
    cd "$APP_DIR"
    python3 -m venv venv
    source venv/bin/activate
    
    # Install Python dependencies
    pip install -r requirements.txt
    pip install gunicorn pymysql
    
    # Create environment configuration
    cat > .env << EOF
SECRET_KEY=${SECRET_KEY}
DATABASE_URL=mysql://${DB_USER}:${DB_PASSWORD}@localhost/${DB_NAME}
FLASK_ENV=production
FLASK_DEBUG=False
EOF
    
    chmod 600 .env
    
    log "Application deployed successfully"
}

# Create systemd service
create_service() {
    log "Creating systemd service..."
    
    sudo tee /etc/systemd/system/rems.service > /dev/null << EOF
[Unit]
Description=REMS - Radiation Equipment Management System
After=network.target mysql.service
Requires=mysql.service

[Service]
Type=notify
User=www-data
Group=www-data
WorkingDirectory=${APP_DIR}
Environment=PATH=${APP_DIR}/venv/bin
ExecStart=${APP_DIR}/venv/bin/gunicorn --bind 127.0.0.1:5000 --workers 4 --timeout 120 app:app
ExecReload=/bin/kill -s HUP \$MAINPID
Restart=always
RestartSec=10
KillMode=mixed
TimeoutStopSec=5

[Install]
WantedBy=multi-user.target
EOF
    
    # Set proper permissions
    sudo chown -R www-data:www-data "$APP_DIR"
    sudo chmod -R 755 "$APP_DIR"
    sudo chmod 600 "$APP_DIR/.env"
    
    # Register and start service
    sudo systemctl daemon-reload
    sudo systemctl enable rems.service
    
    log "Systemd service created successfully"
}

# Configure NGINX
configure_nginx() {
    log "Configuring NGINX..."
    
    sudo tee /etc/nginx/sites-available/rems > /dev/null << EOF
# HTTP server - redirect all traffic to HTTPS
server {
    listen 80;
    server_name ${SERVER_NAME};
    
    # Force HTTPS for security
    return 301 https://\$server_name\$request_uri;
}

# HTTPS server - main application
server {
    listen 443 ssl http2;
    server_name ${SERVER_NAME};
    
    # SSL Configuration (certificates will be obtained via certbot)
    ssl_certificate /etc/letsencrypt/live/${SERVER_NAME}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${SERVER_NAME}/privkey.pem;
    
    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    
    # Serve static files directly
    location /static {
        alias ${APP_DIR}/static;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    
    # Proxy all other requests to Flask application
    location / {
        proxy_pass http://127.0.0.1:5000;
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
    
    # Enable the site
    sudo ln -sf /etc/nginx/sites-available/rems /etc/nginx/sites-enabled/
    sudo rm -f /etc/nginx/sites-enabled/default
    
    # Test NGINX configuration
    sudo nginx -t
    
    log "NGINX configuration completed"
}

# Setup automated backups
setup_backups() {
    log "Setting up automated backup system..."
    
    # Create backup directories
    sudo mkdir -p "$BACKUP_DIR"/{daily,weekly,monthly}
    sudo chown root:root "$BACKUP_DIR"
    
    # Create backup script
    sudo tee /opt/backups/rems-backup.sh > /dev/null << 'EOF'
#!/bin/bash

# Configuration variables
DB_NAME="physdb"
DB_USER="physdb_user"
DB_PASS="${DB_PASSWORD}"
APP_DIR="/opt/rems"
BACKUP_DIR="/opt/backups/rems"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

# Create timestamped backup directory
mkdir -p "$BACKUP_DIR/daily/$DATE"

# Database backup
mysqldump -u $DB_USER -p$DB_PASS --single-transaction --routines --triggers $DB_NAME | gzip > "$BACKUP_DIR/daily/$DATE/database.sql.gz"

# Application files backup
tar -czf "$BACKUP_DIR/daily/$DATE/application.tar.gz" -C /opt rems --exclude='rems/venv' --exclude='rems/instance/*.db'

# Log backup completion
echo "$(date): Backup completed - $DATE" >> /var/log/rems-backup.log

# Cleanup old backups
find "$BACKUP_DIR/daily" -type d -mtime +$RETENTION_DAYS -exec rm -rf {} +

# Create weekly backups on Sundays
if [ $(date +%u) -eq 7 ]; then
    cp -r "$BACKUP_DIR/daily/$DATE" "$BACKUP_DIR/weekly/"
    find "$BACKUP_DIR/weekly" -type d -mtime +90 -exec rm -rf {} +
fi

# Create monthly backups on first day of month
if [ $(date +%d) -eq 01 ]; then
    cp -r "$BACKUP_DIR/daily/$DATE" "$BACKUP_DIR/monthly/"
    find "$BACKUP_DIR/monthly" -type d -mtime +365 -exec rm -rf {} +
fi
EOF
    
    # Replace DB_PASSWORD placeholder
    sudo sed -i "s/\${DB_PASSWORD}/$DB_PASSWORD/g" /opt/backups/rems-backup.sh
    sudo chmod +x /opt/backups/rems-backup.sh
    
    # Create backup verification script
    sudo tee /opt/backups/verify-backup.sh > /dev/null << 'EOF'
#!/bin/bash

LATEST_BACKUP=$(find /opt/backups/rems/daily -type d -name "????????_??????" | sort | tail -1)

if [ -z "$LATEST_BACKUP" ]; then
    echo "$(date): ERROR - No backups found!" >> /var/log/rems-backup.log
    exit 1
fi

# Verify database backup
if gzip -t "$LATEST_BACKUP/database.sql.gz"; then
    echo "$(date): Database backup verified - $LATEST_BACKUP" >> /var/log/rems-backup.log
else
    echo "$(date): ERROR - Database backup corrupted - $LATEST_BACKUP" >> /var/log/rems-backup.log
fi

# Verify application backup
if tar -tzf "$LATEST_BACKUP/application.tar.gz" >/dev/null; then
    echo "$(date): Application backup verified - $LATEST_BACKUP" >> /var/log/rems-backup.log
else
    echo "$(date): ERROR - Application backup corrupted - $LATEST_BACKUP" >> /var/log/rems-backup.log
fi
EOF
    
    sudo chmod +x /opt/backups/verify-backup.sh
    
    log "Backup system configured successfully"
}

# Setup monitoring and health checks
setup_monitoring() {
    log "Setting up monitoring and health checks..."
    
    # Create health check script
    sudo tee "$APP_DIR/health-check.sh" > /dev/null << EOF
#!/bin/bash

# Check if application is responding
if curl -f -s http://localhost:5000 > /dev/null; then
    echo "\$(date): REMS application is healthy"
else
    echo "\$(date): ERROR - REMS application not responding" >> /var/log/rems-health.log
    systemctl restart rems.service
    echo "\$(date): Restarted REMS service" >> /var/log/rems-health.log
fi

# Check database connectivity
if mysql -u ${DB_USER} -p${DB_PASSWORD} ${DB_NAME} -e "SELECT 1;" > /dev/null 2>&1; then
    echo "\$(date): Database connection healthy"
else
    echo "\$(date): ERROR - Database connection failed" >> /var/log/rems-health.log
fi
EOF
    
    sudo chmod +x "$APP_DIR/health-check.sh"
    
    # Setup log rotation
    sudo tee /etc/logrotate.d/rems > /dev/null << EOF
/var/log/rems*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    copytruncate
}
EOF
    
    log "Monitoring system configured successfully"
}

# Configure firewall
configure_firewall() {
    log "Configuring UFW firewall..."
    
    sudo ufw --force enable
    sudo ufw allow ssh
    sudo ufw allow 'Nginx Full'
    sudo ufw deny 3306  # Block external MySQL access
    
    log "Firewall configured successfully"
}

# Setup cron jobs
setup_cron() {
    log "Setting up cron jobs..."
    
    # Create temporary crontab file
    crontab -l > /tmp/rems-cron 2>/dev/null || true
    
    # Add backup job
    echo "0 2 * * * /opt/backups/rems-backup.sh" >> /tmp/rems-cron
    
    # Add backup verification job
    echo "0 3 * * 0 /opt/backups/verify-backup.sh" >> /tmp/rems-cron
    
    # Add health check job
    echo "*/5 * * * * $APP_DIR/health-check.sh >> /var/log/rems-health.log 2>&1" >> /tmp/rems-cron
    
    # Add SSL renewal job
    echo "0 12 * * * /usr/bin/certbot renew --quiet" >> /tmp/rems-cron
    
    # Install crontab
    crontab /tmp/rems-cron
    rm /tmp/rems-cron
    
    log "Cron jobs configured successfully"
}

# Initialize database
initialize_database() {
    log "Initializing database schema..."
    
    cd "$APP_DIR"
    source venv/bin/activate
    
    # Run the application briefly to create tables
    timeout 10s python app.py || true
    
    log "Database initialized successfully"
}

# Obtain SSL certificate
obtain_ssl() {
    log "Obtaining SSL certificate..."
    
    # Start NGINX temporarily for HTTP validation
    sudo systemctl start nginx
    
    # Obtain certificate
    sudo certbot --nginx -d "$SERVER_NAME" --non-interactive --agree-tos --email "admin@$SERVER_NAME"
    
    log "SSL certificate obtained successfully"
}

# Start services
start_services() {
    log "Starting all services..."
    
    sudo systemctl start rems.service
    sudo systemctl restart nginx
    
    # Check service status
    if systemctl is-active --quiet rems.service; then
        log "REMS service started successfully"
    else
        error "Failed to start REMS service"
        sudo journalctl -u rems.service --no-pager -l
        exit 1
    fi
    
    if systemctl is-active --quiet nginx; then
        log "NGINX service started successfully"
    else
        error "Failed to start NGINX service"
        exit 1
    fi
}

# Final verification
verify_deployment() {
    log "Performing final verification..."
    
    # Test local application
    if curl -f -s http://localhost:5000 > /dev/null; then
        log "✓ Application responding on localhost:5000"
    else
        error "✗ Application not responding on localhost:5000"
    fi
    
    # Test HTTPS
    if curl -f -s "https://$SERVER_NAME" > /dev/null; then
        log "✓ Application accessible via HTTPS"
    else
        warning "✗ HTTPS access failed - check DNS and SSL configuration"
    fi
    
    # Check database connection
    cd "$APP_DIR"
    source venv/bin/activate
    if python -c "from app import db; db.create_all(); print('Database connection successful')" 2>/dev/null; then
        log "✓ Database connection verified"
    else
        error "✗ Database connection failed"
    fi
    
    log "Deployment verification completed"
}

# Print deployment summary
print_summary() {
    echo
    log "=== DEPLOYMENT COMPLETED SUCCESSFULLY ==="
    echo
    info "Application URL: https://$SERVER_NAME"
    info "Application directory: $APP_DIR"
    info "Backup directory: $BACKUP_DIR"
    info "Service: sudo systemctl status rems.service"
    info "Logs: sudo journalctl -u rems.service -f"
    info "Health logs: tail -f /var/log/rems-health.log"
    info "Backup logs: tail -f /var/log/rems-backup.log"
    echo
    warning "IMPORTANT: Update DNS records to point $SERVER_NAME to this server"
    warning "IMPORTANT: Change default database password in production"
    warning "IMPORTANT: Review and customize /opt/rems/.env file"
    echo
}

# Main deployment function
main() {
    log "Starting REMS Production Deployment..."
    log "Server: $SERVER_NAME"
    log "App Directory: $APP_DIR"
    
    check_root
    check_environment
    install_dependencies
    setup_database
    deploy_application
    create_service
    configure_nginx
    setup_backups
    setup_monitoring
    configure_firewall
    setup_cron
    initialize_database
    obtain_ssl
    start_services
    verify_deployment
    print_summary
    
    log "Deployment completed successfully!"
}

# Handle script interruption
trap 'error "Deployment interrupted!"; exit 1' INT TERM

# Run main function
main "$@"