#!/bin/bash

# MServerController Installation Script for Debian 13+
# This script installs and configures MServerController with Nginx

set -e

echo "=========================================="
echo "MServerController Installation Script"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (use sudo)"
    exit 1
fi

# Check Debian version
if [ -f /etc/debian_version ]; then
    DEBIAN_VERSION=$(cat /etc/debian_version | cut -d. -f1)
    if [ "$DEBIAN_VERSION" -lt 13 ]; then
        echo "Warning: This script is designed for Debian 13 or newer."
        echo "Current version: $(cat /etc/debian_version)"
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
else
    echo "Error: This system does not appear to be Debian."
    exit 1
fi

# Update system
echo "Updating system packages..."
apt-get update
apt-get upgrade -y

# Install required packages
echo "Installing required packages..."
apt-get install -y curl wget git nginx openjdk-17-jre-headless

# Install Node.js (LTS version)
echo "Installing Node.js..."
curl -fsSL https://deb.nodesource.com/setup_lts.x | bash -
apt-get install -y nodejs

# Verify installations
echo ""
echo "Verifying installations..."
echo "Node.js version: $(node --version)"
echo "npm version: $(npm --version)"
echo "Java version: $(java -version 2>&1 | head -n 1)"
echo "Nginx version: $(nginx -v 2>&1)"
echo ""

# Set installation directory
INSTALL_DIR="/opt/mservercontroller"

# Clone or copy repository
echo "Setting up MServerController..."
if [ -d "$INSTALL_DIR" ]; then
    echo "Directory $INSTALL_DIR already exists."
    read -p "Remove and reinstall? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$INSTALL_DIR"
    else
        echo "Installation cancelled."
        exit 1
    fi
fi

# Check if we're running from the repository
if [ -f "$(dirname "$0")/package.json" ]; then
    echo "Copying files from current directory..."
    mkdir -p "$INSTALL_DIR"
    cp -r "$(dirname "$0")"/* "$INSTALL_DIR/"
else
    echo "Cloning from GitHub..."
    git clone https://github.com/TwiStarSystems/MServerController.git "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# Install Node.js dependencies
echo "Installing Node.js dependencies..."
npm install --production

# Create necessary directories
echo "Creating directories..."
mkdir -p servers backups uploads

# Set permissions
echo "Setting permissions..."
chown -R www-data:www-data "$INSTALL_DIR"
chmod -R 755 "$INSTALL_DIR"

# Configure Nginx
echo "Configuring Nginx..."
cp nginx.conf /etc/nginx/sites-available/mservercontroller
ln -sf /etc/nginx/sites-available/mservercontroller /etc/nginx/sites-enabled/mservercontroller

# Remove default Nginx site if it exists
rm -f /etc/nginx/sites-enabled/default

# Test Nginx configuration
nginx -t

# Create systemd service
echo "Creating systemd service..."
cat > /etc/systemd/system/mservercontroller.service <<EOF
[Unit]
Description=MServerController - Minecraft Server Manager
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/node server.js
Restart=always
RestartSec=10
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=mservercontroller
Environment=NODE_ENV=production
Environment=PORT=3000

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
systemctl daemon-reload

# Enable and start services
echo "Enabling and starting services..."
systemctl enable mservercontroller
systemctl start mservercontroller
systemctl reload nginx

# Check service status
sleep 2
if systemctl is-active --quiet mservercontroller; then
    echo ""
    echo "=========================================="
    echo "Installation Complete!"
    echo "=========================================="
    echo ""
    echo "MServerController is now running."
    echo ""
    echo "Access the web interface at:"
    echo "  http://$(hostname -I | awk '{print $1}')"
    echo "  or"
    echo "  http://localhost"
    echo ""
    echo "Service management commands:"
    echo "  Start:   sudo systemctl start mservercontroller"
    echo "  Stop:    sudo systemctl stop mservercontroller"
    echo "  Restart: sudo systemctl restart mservercontroller"
    echo "  Status:  sudo systemctl status mservercontroller"
    echo ""
    echo "Nginx management commands:"
    echo "  Reload:  sudo systemctl reload nginx"
    echo "  Restart: sudo systemctl restart nginx"
    echo ""
    echo "Logs:"
    echo "  App logs:   sudo journalctl -u mservercontroller -f"
    echo "  Nginx logs: sudo tail -f /var/log/nginx/access.log"
    echo ""
else
    echo ""
    echo "=========================================="
    echo "Installation completed with warnings"
    echo "=========================================="
    echo ""
    echo "The service did not start properly. Check logs with:"
    echo "  sudo journalctl -u mservercontroller -xe"
    echo ""
    exit 1
fi
