# Production Deployment Automation Script for REMS (Windows)
# This script automates the deployment process for Windows Server environments

param(
    [Parameter(Mandatory=$true)]
    [string]$ServerName,
    
    [Parameter(Mandatory=$false)]
    [string]$DatabasePassword = "secure_password_here",
    
    [Parameter(Mandatory=$false)]
    [string]$AppDir = "C:\opt\rems",
    
    [Parameter(Mandatory=$false)]
    [string]$BackupDir = "C:\opt\backups\rems"
)

# Requires elevation
if (-NOT ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Error "This script requires Administrator privileges. Please run as Administrator."
    exit 1
}

# Configuration
$DB_NAME = "physdb"
$DB_USER = "physdb_user"
$SECRET_KEY = [System.Web.Security.Membership]::GeneratePassword(32, 0)

# Logging functions
function Write-Log {
    param([string]$Message)
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message" -ForegroundColor Green
}

function Write-Error-Log {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Write-Warning-Log {
    param([string]$Message)
    Write-Host "[WARNING] $Message" -ForegroundColor Yellow
}

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Blue
}

# Check prerequisites
function Test-Prerequisites {
    Write-Log "Checking prerequisites..."
    
    # Check if Python is installed
    try {
        $pythonVersion = python --version 2>&1
        Write-Info "Python version: $pythonVersion"
    } catch {
        Write-Error-Log "Python 3.8+ is required but not found. Please install Python from python.org"
        exit 1
    }
    
    # Check if MySQL is available
    try {
        $mysqlVersion = mysql --version 2>&1
        Write-Info "MySQL version: $mysqlVersion"
    } catch {
        Write-Error-Log "MySQL is required but not found. Please install MySQL Server 8.0+"
        exit 1
    }
}

# Install Windows dependencies
function Install-Dependencies {
    Write-Log "Installing Windows dependencies..."
    
    # Install Chocolatey if not present
    if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
        Write-Log "Installing Chocolatey package manager..."
        Set-ExecutionPolicy Bypass -Scope Process -Force
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
        iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))
    }
    
    # Install NSSM for service management
    choco install nssm -y
    
    # Install IIS if not already installed
    Enable-WindowsOptionalFeature -Online -FeatureName IIS-WebServerRole, IIS-WebServer, IIS-CommonHttpFeatures, IIS-HttpRedirect, IIS-WebServerManagementTools -All
    
    Write-Log "Dependencies installed successfully"
}

# Setup MySQL database
function Setup-Database {
    Write-Log "Setting up MySQL database..."
    
    # Start MySQL service
    Start-Service MySQL80
    Set-Service MySQL80 -StartupType Automatic
    
    # Create database and user
    $sqlCommands = @"
CREATE DATABASE IF NOT EXISTS $DB_NAME CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DatabasePassword';
GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$DB_USER'@'localhost';
FLUSH PRIVILEGES;
"@
    
    $sqlCommands | mysql -u root -p
    
    Write-Log "Database setup completed successfully"
}

# Deploy application
function Deploy-Application {
    Write-Log "Deploying application to $AppDir..."
    
    # Create application directory
    New-Item -ItemType Directory -Force -Path $AppDir
    
    # Copy application files
    if (Test-Path "app.py") {
        Copy-Item -Path "app.py", "templates", "static", "requirements.txt" -Destination $AppDir -Recurse -Force
        Write-Log "Application files copied"
    } else {
        Write-Error-Log "app.py not found in current directory"
        exit 1
    }
    
    # Create Python virtual environment
    Set-Location $AppDir
    python -m venv venv
    & "$AppDir\venv\Scripts\Activate.ps1"
    
    # Install Python dependencies
    pip install -r requirements.txt
    pip install gunicorn pymysql waitress
    
    # Create environment configuration
    $envContent = @"
SECRET_KEY=$SECRET_KEY
DATABASE_URL=mysql://$DB_USER`:$DatabasePassword@localhost/$DB_NAME
FLASK_ENV=production
FLASK_DEBUG=False
"@
    
    $envContent | Out-File -FilePath "$AppDir\.env" -Encoding UTF8
    
    # Set proper permissions
    icacls $AppDir /grant "IIS_IUSRS:(OI)(CI)F" /T
    icacls "$AppDir\.env" /grant "IIS_IUSRS:R"
    
    Write-Log "Application deployed successfully"
}

# Create Windows service
function Create-Service {
    Write-Log "Creating Windows service..."
    
    # Create service startup script
    $startupScript = @"
@echo off
cd /d $AppDir
call venv\Scripts\activate.bat
waitress-serve --host=127.0.0.1 --port=5000 app:app
"@
    
    $startupScript | Out-File -FilePath "$AppDir\start_service.bat" -Encoding ASCII
    
    # Install service with NSSM
    nssm install REMS "$AppDir\start_service.bat"
    nssm set REMS AppDirectory $AppDir
    nssm set REMS Start SERVICE_AUTO_START
    nssm set REMS Description "REMS - Radiation Equipment Management System"
    
    Write-Log "Windows service created successfully"
}

# Configure IIS as reverse proxy
function Configure-IIS {
    Write-Log "Configuring IIS reverse proxy..."
    
    # Install URL Rewrite module (required for reverse proxy)
    $urlRewriteUrl = "https://download.microsoft.com/download/1/2/8/128E2E22-C1A9-44A4-BE2A-5859ED1D4592/rewrite_amd64_en-US.msi"
    $urlRewritePath = "$env:TEMP\urlrewrite.msi"
    
    Invoke-WebRequest -Uri $urlRewriteUrl -OutFile $urlRewritePath
    Start-Process msiexec.exe -Wait -ArgumentList "/i $urlRewritePath /quiet"
    Remove-Item $urlRewritePath
    
    # Install Application Request Routing (ARR)
    $arrUrl = "https://download.microsoft.com/download/E/9/8/E9849D6A-020E-47E4-9FD0-A023E99B54EB/requestRouter_amd64.msi"
    $arrPath = "$env:TEMP\arr.msi"
    
    Invoke-WebRequest -Uri $arrUrl -OutFile $arrPath
    Start-Process msiexec.exe -Wait -ArgumentList "/i $arrPath /quiet"
    Remove-Item $arrPath
    
    # Create IIS site configuration
    $webConfig = @"
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
    <system.web>
        <compilation targetFramework="4.0" />
    </system.web>
    <system.webServer>
        <rewrite>
            <rules>
                <rule name="ReverseProxyInboundRule1" stopProcessing="true">
                    <match url="(.*)" />
                    <action type="Rewrite" url="http://127.0.0.1:5000/{R:1}" />
                </rule>
            </rules>
        </rewrite>
    </system.webServer>
</configuration>
"@
    
    # Create site directory
    $siteDir = "C:\inetpub\wwwroot\rems"
    New-Item -ItemType Directory -Force -Path $siteDir
    $webConfig | Out-File -FilePath "$siteDir\web.config" -Encoding UTF8
    
    # Import WebAdministration module
    Import-Module WebAdministration
    
    # Create IIS site
    New-WebSite -Name "REMS" -Port 80 -PhysicalPath $siteDir -Force
    
    Write-Log "IIS configuration completed"
}

# Setup automated backups
function Setup-Backups {
    Write-Log "Setting up automated backup system..."
    
    # Create backup directories
    New-Item -ItemType Directory -Force -Path "$BackupDir\daily"
    New-Item -ItemType Directory -Force -Path "$BackupDir\weekly"
    New-Item -ItemType Directory -Force -Path "$BackupDir\monthly"
    
    # Create backup script
    $backupScript = @"
# REMS Backup Script for Windows
`$DB_NAME = "$DB_NAME"
`$DB_USER = "$DB_USER" 
`$DB_PASS = "$DatabasePassword"
`$APP_DIR = "$AppDir"
`$BACKUP_DIR = "$BackupDir"
`$DATE = Get-Date -Format "yyyyMMdd_HHmmss"
`$RETENTION_DAYS = 30

# Create timestamped backup directory
`$BackupPath = "`$BACKUP_DIR\daily\`$DATE"
New-Item -ItemType Directory -Force -Path `$BackupPath

# Database backup
mysqldump -u `$DB_USER -p`$DB_PASS --single-transaction --routines --triggers `$DB_NAME | gzip > "`$BackupPath\database.sql.gz"

# Application files backup
Compress-Archive -Path `$APP_DIR -DestinationPath "`$BackupPath\application.zip" -CompressionLevel Optimal

# Log backup completion
Add-Content -Path "C:\logs\rems-backup.log" -Value "`$(Get-Date): Backup completed - `$DATE"

# Cleanup old backups
Get-ChildItem "`$BACKUP_DIR\daily" | Where-Object { `$_.CreationTime -lt (Get-Date).AddDays(-`$RETENTION_DAYS) } | Remove-Item -Recurse -Force

# Weekly backups on Sundays
if ((Get-Date).DayOfWeek -eq "Sunday") {
    Copy-Item -Path `$BackupPath -Destination "`$BACKUP_DIR\weekly" -Recurse
    Get-ChildItem "`$BACKUP_DIR\weekly" | Where-Object { `$_.CreationTime -lt (Get-Date).AddDays(-90) } | Remove-Item -Recurse -Force
}

# Monthly backups on first day of month
if ((Get-Date).Day -eq 1) {
    Copy-Item -Path `$BackupPath -Destination "`$BACKUP_DIR\monthly" -Recurse
    Get-ChildItem "`$BACKUP_DIR\monthly" | Where-Object { `$_.CreationTime -lt (Get-Date).AddDays(-365) } | Remove-Item -Recurse -Force
}
"@
    
    $backupScript | Out-File -FilePath "$BackupDir\rems-backup.ps1" -Encoding UTF8
    
    # Create scheduled task for daily backups
    $action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-File `"$BackupDir\rems-backup.ps1`""
    $trigger = New-ScheduledTaskTrigger -Daily -At "2:00AM"
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount
    
    Register-ScheduledTask -TaskName "REMS Daily Backup" -Action $action -Trigger $trigger -Principal $principal -Force
    
    Write-Log "Backup system configured successfully"
}

# Setup monitoring
function Setup-Monitoring {
    Write-Log "Setting up monitoring and health checks..."
    
    # Create logs directory
    New-Item -ItemType Directory -Force -Path "C:\logs"
    
    # Create health check script
    $healthScript = @"
# REMS Health Check Script
try {
    `$response = Invoke-WebRequest -Uri "http://localhost:5000" -UseBasicParsing -TimeoutSec 10
    if (`$response.StatusCode -eq 200) {
        Add-Content -Path "C:\logs\rems-health.log" -Value "`$(Get-Date): REMS application is healthy"
    } else {
        Add-Content -Path "C:\logs\rems-health.log" -Value "`$(Get-Date): WARNING - REMS returned status `$(`$response.StatusCode)"
    }
} catch {
    Add-Content -Path "C:\logs\rems-health.log" -Value "`$(Get-Date): ERROR - REMS application not responding"
    # Restart service
    Restart-Service REMS
    Add-Content -Path "C:\logs\rems-health.log" -Value "`$(Get-Date): Restarted REMS service"
}

# Check database connectivity
try {
    mysql -u $DB_USER -p$DatabasePassword $DB_NAME -e "SELECT 1;" 2>`$null
    if (`$LASTEXITCODE -eq 0) {
        Add-Content -Path "C:\logs\rems-health.log" -Value "`$(Get-Date): Database connection healthy"
    } else {
        Add-Content -Path "C:\logs\rems-health.log" -Value "`$(Get-Date): ERROR - Database connection failed"
    }
} catch {
    Add-Content -Path "C:\logs\rems-health.log" -Value "`$(Get-Date): ERROR - Database connection failed"
}
"@
    
    $healthScript | Out-File -FilePath "$AppDir\health-check.ps1" -Encoding UTF8
    
    # Create scheduled task for health checks (every 5 minutes)
    $healthAction = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-File `"$AppDir\health-check.ps1`""
    $healthTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 365)
    
    Register-ScheduledTask -TaskName "REMS Health Check" -Action $healthAction -Trigger $healthTrigger -Force
    
    Write-Log "Monitoring system configured successfully"
}

# Configure Windows Firewall
function Configure-Firewall {
    Write-Log "Configuring Windows Firewall..."
    
    # Allow HTTP and HTTPS
    New-NetFirewallRule -DisplayName "REMS HTTP" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow
    New-NetFirewallRule -DisplayName "REMS HTTPS" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow
    
    # Block external MySQL access
    New-NetFirewallRule -DisplayName "Block MySQL External" -Direction Inbound -Protocol TCP -LocalPort 3306 -Action Block
    
    Write-Log "Firewall configured successfully"
}

# Initialize database
function Initialize-Database {
    Write-Log "Initializing database schema..."
    
    Set-Location $AppDir
    & "$AppDir\venv\Scripts\Activate.ps1"
    
    # Run the application briefly to create tables
    $job = Start-Job -ScriptBlock { python app.py }
    Start-Sleep -Seconds 10
    Stop-Job $job
    Remove-Job $job
    
    Write-Log "Database initialized successfully"
}

# Start services
function Start-Services {
    Write-Log "Starting all services..."
    
    # Start REMS service
    Start-Service REMS
    Set-Service REMS -StartupType Automatic
    
    # Start IIS
    Start-Service W3SVC
    Set-Service W3SVC -StartupType Automatic
    
    # Verify services
    if ((Get-Service REMS).Status -eq "Running") {
        Write-Log "REMS service started successfully"
    } else {
        Write-Error-Log "Failed to start REMS service"
        exit 1
    }
    
    if ((Get-Service W3SVC).Status -eq "Running") {
        Write-Log "IIS service started successfully"  
    } else {
        Write-Error-Log "Failed to start IIS service"
        exit 1
    }
}

# Final verification
function Test-Deployment {
    Write-Log "Performing final verification..."
    
    Start-Sleep -Seconds 5
    
    # Test local application
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:5000" -UseBasicParsing -TimeoutSec 10
        Write-Log "✓ Application responding on localhost:5000"
    } catch {
        Write-Error-Log "✗ Application not responding on localhost:5000"
    }
    
    # Test through IIS
    try {
        $response = Invoke-WebRequest -Uri "http://localhost" -UseBasicParsing -TimeoutSec 10
        Write-Log "✓ Application accessible via IIS"
    } catch {
        Write-Warning-Log "✗ IIS proxy failed - check configuration"
    }
    
    Write-Log "Deployment verification completed"
}

# Print deployment summary
function Show-Summary {
    Write-Host ""
    Write-Log "=== DEPLOYMENT COMPLETED SUCCESSFULLY ==="
    Write-Host ""
    Write-Info "Application URL: http://$ServerName"
    Write-Info "Application directory: $AppDir"
    Write-Info "Backup directory: $BackupDir"
    Write-Info "Service: Get-Service REMS"
    Write-Info "Health logs: Get-Content C:\logs\rems-health.log -Tail 10"
    Write-Info "Backup logs: Get-Content C:\logs\rems-backup.log -Tail 10"
    Write-Host ""
    Write-Warning-Log "IMPORTANT: Configure DNS records to point $ServerName to this server"
    Write-Warning-Log "IMPORTANT: Install SSL certificate for HTTPS"
    Write-Warning-Log "IMPORTANT: Review and customize $AppDir\.env file"
    Write-Host ""
}

# Main deployment function
function Main {
    Write-Log "Starting REMS Production Deployment for Windows..."
    Write-Log "Server: $ServerName"
    Write-Log "App Directory: $AppDir"
    
    Test-Prerequisites
    Install-Dependencies
    Setup-Database
    Deploy-Application
    Create-Service
    Configure-IIS
    Setup-Backups
    Setup-Monitoring
    Configure-Firewall
    Initialize-Database
    Start-Services
    Test-Deployment
    Show-Summary
    
    Write-Log "Deployment completed successfully!"
}

# Error handling
trap {
    Write-Error-Log "Deployment failed: $($_.Exception.Message)"
    exit 1
}

# Run main function
Main