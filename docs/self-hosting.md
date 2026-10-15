# Self-Hosting REMS on Linux

This guide installs REMS on a Linux server you manage: an on-premises VM, a cloud VM (AWS, Azure,
DigitalOcean, etc.), or bare metal. When you finish, the app starts at boot, restarts if it fails,
is served over HTTPS, and backs itself up every night.

The commands are written for **Ubuntu Server 22.04 or 24.04**. Other distributions work the same
way with their own package manager. For a quicker hosted setup, see
[Deploying on Render](../README.md#option-a-render) in the README.

```
browser ──HTTPS──▶ NGINX (:443) ──▶ Gunicorn (127.0.0.1:5000) ──▶ instance/physdb.db (SQLite)
```

NGINX handles HTTPS and serves static files. Gunicorn runs the Flask app. The database is a single
SQLite file, so there is no database server to install.

> **Windows servers:** Gunicorn does not run on Windows. Run REMS in a Linux VM or WSL instead.

## Requirements

- **Server**: 1-2 vCPUs, 1-2 GB RAM, and 20 GB disk is plenty for a group of a few dozen users. Most of the disk goes to the OS and backups.
- **Hostname**: a DNS name users will type, e.g. `rems.example.org` (public) or `rems.yourdomain.local` (internal).
- **Firewall**: inbound 80 and 443 for users, 22 for SSH.
- **Internet**: needed during installation for `apt` and `pip`. REMS itself needs no internet at runtime. Its CSS, JavaScript, and icons are bundled. For a server with no internet access, see [Offline installation](#offline-installation).

The examples use `/opt/rems` for the app and `rems.example.org` for the hostname. Replace them with your own.

## Step 1: Install System Packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git nginx sqlite3 curl

# Python 3.11 or newer. Ubuntu 24.04 ships 3.12:
sudo apt install -y python3 python3-venv
# Ubuntu 22.04 ships 3.10, so install 3.11 alongside it:
# sudo apt install -y python3.11 python3.11-venv
```

In the commands below, use `python3.11` instead of `python3` if you are on Ubuntu 22.04.

## Step 2: Install the Application

Run REMS as its own unprivileged system user, so a problem in the app cannot touch the rest of the server.

```bash
sudo useradd --system --home-dir /opt/rems --shell /usr/sbin/nologin rems
sudo git clone <repository-url> /opt/rems
cd /opt/rems

sudo python3 -m venv venv
sudo venv/bin/pip install -r requirements.txt
```

`requirements.txt` includes Gunicorn. `requirements-dev.txt` is only for running the test suite,
so the server doesn't need it.

### Configure

Generate a secret key, then write `.env`:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"

sudo tee /opt/rems/.env > /dev/null << 'EOF'
SECRET_KEY=paste-the-generated-value-here
# NGINX serves HTTPS and forwards requests to Gunicorn:
# send the session cookie only over HTTPS
SESSION_COOKIE_SECURE=1
# trust one proxy hop (NGINX) for the client IP and scheme
TRUSTED_PROXY_COUNT=1
EOF
```

Do **not** set `FLASK_DEBUG` on a server. The [README](../README.md#configuration) describes every setting.

### Set ownership and permissions

```bash
sudo mkdir -p /opt/rems/instance
sudo chown -R rems:rems /opt/rems
sudo chmod 600 /opt/rems/.env         # only the rems user can read the secret key
sudo chmod 700 /opt/rems/instance     # holds the database
```

The rest of `/opt/rems` stays world-readable, so NGINX (running as `www-data`) can serve `static/`.

### Create the database and first admin

```bash
cd /opt/rems
sudo -u rems venv/bin/flask create-admin
```

This creates `instance/physdb.db` and prompts for the admin's name, email, username, and password.
There are no default credentials. Run it as the `rems` user so the new database file belongs to
`rems`.

## Step 3: Run Gunicorn as a Service

systemd starts REMS at boot and restarts it if it fails.

```bash
sudo tee /etc/systemd/system/rems.service > /dev/null << 'EOF'
[Unit]
Description=REMS - Radiation Equipment Management System
After=network.target

[Service]
User=rems
Group=rems
WorkingDirectory=/opt/rems
ExecStart=/opt/rems/venv/bin/gunicorn app:app --bind 127.0.0.1:5000 --timeout 120
ExecReload=/bin/kill -s HUP $MAINPID
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now rems
sudo systemctl status rems
curl -I http://127.0.0.1:5000/login      # expect HTTP/1.1 200 OK
```

Gunicorn listens only on `127.0.0.1`, so users can reach it only through NGINX. It runs one worker
by default. Leave it that way: the failed-login throttle is kept in memory per worker, so adding
workers with `--workers` would multiply the number of attempts allowed.

Application logs go to the systemd journal: `sudo journalctl -u rems -f`.

## Step 4: Get an HTTPS Certificate

Pick the option that matches your network.

### Option A: Internal network (organization's certificate authority)

If REMS is reachable only inside your network, Let's Encrypt cannot validate it. Ask your IT or
security team for:

> *"An SSL server certificate for an internal web application, hostname `rems.yourdomain.local`."*

They will give you a certificate file (`.crt` or `.pem`, ideally including the intermediate chain)
and a private key (`.key`). Install them:

```bash
sudo mkdir -p /etc/ssl/rems
sudo cp your-cert.crt /etc/ssl/rems/rems.crt
sudo cp your-cert.key /etc/ssl/rems/rems.key
sudo chmod 600 /etc/ssl/rems/rems.key
```

Domain-joined Windows computers already trust certificates from the organization's CA, so users see
no browser warnings. These certificates usually last 1-2 years. Set a reminder to request a
renewal, then repeat the copy and run `sudo systemctl reload nginx`.

### Option B: Public server (Let's Encrypt)

If the hostname resolves publicly and port 80 is reachable from the internet:

```bash
sudo apt install -y certbot
sudo certbot certonly --standalone -d rems.example.org \
    --pre-hook "systemctl stop nginx" --post-hook "systemctl start nginx"
```

The certificate is saved under `/etc/letsencrypt/live/rems.example.org/`. Certbot installs a timer
that renews it automatically, reusing the same hooks. Check renewal with
`sudo certbot renew --dry-run`.

## Step 5: Configure NGINX

Set the certificate paths to match the option you chose in Step 4:

| | `ssl_certificate` | `ssl_certificate_key` |
|---|---|---|
| Option A | `/etc/ssl/rems/rems.crt` | `/etc/ssl/rems/rems.key` |
| Option B | `/etc/letsencrypt/live/rems.example.org/fullchain.pem` | `/etc/letsencrypt/live/rems.example.org/privkey.pem` |

```bash
sudo tee /etc/nginx/sites-available/rems > /dev/null << 'EOF'
server {
    listen 80;
    server_name rems.example.org;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name rems.example.org;

    ssl_certificate     /etc/ssl/rems/rems.crt;
    ssl_certificate_key /etc/ssl/rems/rems.key;

    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;

    # Allow CSV uploads larger than NGINX's 1 MB default
    client_max_body_size 10m;

    # REMS links static files as /static/file?v=<modified time>, so a long cache
    # is safe: an updated file gets a new URL.
    location /static {
        alias /opt/rems/static;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/rems /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

## Step 6: Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

Allow SSH **before** enabling the firewall, or you can lock yourself out of a remote server.

## Step 7: Nightly Backups

The script takes a consistent snapshot with SQLite's backup command, which is safe while the app is
running. It also copies `.env`: without the original `SECRET_KEY`, a restored server still works,
but everyone is logged out. It keeps 30 daily, 13 weekly, and 12 monthly copies.

```bash
sudo mkdir -p /var/backups/rems/{daily,weekly,monthly}
sudo chmod 700 /var/backups/rems

sudo tee /usr/local/bin/rems-backup > /dev/null << 'EOF'
#!/bin/bash
set -euo pipefail

APP_DIR=/opt/rems
BACKUP_DIR=/var/backups/rems
STAMP=$(date +%Y%m%d_%H%M%S)
DEST="$BACKUP_DIR/daily/$STAMP"

mkdir -p "$DEST"
sqlite3 "$APP_DIR/instance/physdb.db" ".backup '$DEST/physdb.db'"
sqlite3 "$DEST/physdb.db" "PRAGMA integrity_check;" | grep -qx ok
gzip "$DEST/physdb.db"
cp "$APP_DIR/.env" "$DEST/env"

[ "$(date +%u)" = 7 ]  && cp -r "$DEST" "$BACKUP_DIR/weekly/"
[ "$(date +%d)" = 01 ] && cp -r "$DEST" "$BACKUP_DIR/monthly/"

find "$BACKUP_DIR/daily"   -mindepth 1 -maxdepth 1 -type d -mtime +30  -exec rm -rf {} +
find "$BACKUP_DIR/weekly"  -mindepth 1 -maxdepth 1 -type d -mtime +91  -exec rm -rf {} +
find "$BACKUP_DIR/monthly" -mindepth 1 -maxdepth 1 -type d -mtime +365 -exec rm -rf {} +

echo "$(date): backup OK $STAMP"
EOF
sudo chmod 700 /usr/local/bin/rems-backup

# Run it once now to check it works
sudo /usr/local/bin/rems-backup
```

Schedule it nightly at 2 AM. A file in `/etc/cron.d` leaves root's existing crontab untouched:

```bash
echo '0 2 * * * root /usr/local/bin/rems-backup >> /var/log/rems-backup.log 2>&1' \
    | sudo tee /etc/cron.d/rems-backup
```

Because the script exits on any error, a failed backup or integrity check leaves an error in
`/var/log/rems-backup.log` with no `backup OK` line.

**Keep a copy off the server.** A backup on the same disk does not protect against losing the
server. Point `BACKUP_DIR` at a network share, or copy `/var/backups/rems` elsewhere with `rsync`.
The backups contain password hashes and the secret key, so store them securely.

Admins can also download a backup at any time from **Admin Dashboard → Database Export**. That's
useful before an upgrade, but it does not replace scheduled backups.

## Step 8: Health Check (Optional)

systemd already restarts REMS if it crashes. This check also catches the rarer case where the app
is running but has stopped answering:

```bash
sudo tee /usr/local/bin/rems-health > /dev/null << 'EOF'
#!/bin/bash
if ! curl -fsS -o /dev/null --max-time 10 http://127.0.0.1:5000/login; then
    echo "$(date): REMS not responding, restarting"
    systemctl restart rems
fi
EOF
sudo chmod 755 /usr/local/bin/rems-health

echo '*/5 * * * * root /usr/local/bin/rems-health >> /var/log/rems-health.log 2>&1' \
    | sudo tee /etc/cron.d/rems-health
```

Rotate the two log files:

```bash
sudo tee /etc/logrotate.d/rems > /dev/null << 'EOF'
/var/log/rems-backup.log /var/log/rems-health.log {
    monthly
    rotate 12
    compress
    missingok
    notifempty
}
EOF
```

## Step 9: Check Everything

```bash
sudo systemctl status rems nginx
curl -I https://rems.example.org/login      # expect 200
sudo journalctl -u rems -n 50               # application log
ls -l /var/backups/rems/daily               # today's backup is there
```

Then open `https://rems.example.org` in a browser and log in with the admin account from Step 2.

## Upgrading

```bash
sudo /usr/local/bin/rems-backup             # backup first
cd /opt/rems
sudo -u rems git pull                       # or copy in the new files
sudo venv/bin/pip install -r requirements.txt
sudo chown -R rems:rems /opt/rems
sudo systemctl restart rems
```

Schema changes are applied automatically when the app starts, so there's no migration step. Check
`sudo journalctl -u rems -n 50` for `Migration:` lines and errors.

## Restoring from a Backup

```bash
# 1. Stop the app so nothing writes to the database
sudo systemctl stop rems

# 2. Keep the current database in case you need to undo the restore
sudo mv /opt/rems/instance/physdb.db /opt/rems/instance/physdb.db.pre-restore

# 3. Remove the write-ahead log files
sudo rm -f /opt/rems/instance/physdb.db-wal /opt/rems/instance/physdb.db-shm

# 4. Put the backup in place and check it
#    (for a .sqlite3 file downloaded from the Admin page, copy it here instead)
sudo sh -c 'gunzip -c /var/backups/rems/daily/<STAMP>/physdb.db.gz > /opt/rems/instance/physdb.db'
sudo sqlite3 /opt/rems/instance/physdb.db "PRAGMA integrity_check;"     # expect: ok

# 5. Fix ownership and start
sudo chown rems:rems /opt/rems/instance/physdb.db
sudo chmod 600 /opt/rems/instance/physdb.db
sudo systemctl start rems
```

> **Do not skip step 3.** A `-wal` file left over from the old database, sitting next to a restored
> `physdb.db`, can corrupt it. SQLite tries to replay a write-ahead log that belongs to a different
> database.

**Rebuilding on a new server:** follow Steps 1-6, but skip `flask create-admin` (the restored
database already has its accounts). Restore `.env` from the backup's `env` file, then restore the
database as above.

**Test your backups** now and then by restoring one to a scratch location:

```bash
gunzip -c /var/backups/rems/daily/<STAMP>/physdb.db.gz > /tmp/rems-test.db
sqlite3 /tmp/rems-test.db "PRAGMA integrity_check; SELECT COUNT(*) FROM equipment; SELECT COUNT(*) FROM compliance_tests;"
rm /tmp/rems-test.db
```

## Offline Installation

For a server with no internet access, download everything on a connected machine that runs the
**same Ubuntu release and CPU architecture**, so the packages and Python wheels match.

On the connected machine:

```bash
# System packages and their dependencies (use python3.11 / python3.11-venv on 22.04)
mkdir debs && cd debs
apt-get download $(apt-cache depends --recurse --no-recommends --no-suggests --no-conflicts \
    --no-breaks --no-replaces --no-enhances nginx sqlite3 curl python3 python3-venv \
    | grep '^\w' | sort -u)
cd ..

# The application and its Python packages
git clone <repository-url> rems
pip download -r rems/requirements.txt -d python-packages
```

Copy `debs/`, `rems/`, and `python-packages/` to the server by whatever transfer method you're
allowed to use. Then:

```bash
sudo dpkg -i debs/*.deb
sudo cp -r rems /opt/rems
sudo useradd --system --home-dir /opt/rems --shell /usr/sbin/nologin rems
cd /opt/rems
sudo python3 -m venv venv
sudo venv/bin/pip install --no-index --find-links=/path/to/python-packages -r requirements.txt
```

Continue from [Configure](#configure) in Step 2. For HTTPS, use Option A, since Let's Encrypt needs
internet access.
