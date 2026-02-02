#!/bin/bash

# MServerController Installation Script for Debian/Ubuntu
# This script installs, updates, and configures MServerController (Python version)

set -e

# Configuration
INSTALL_DIR="/opt/mservercontroller"
REPO_URL="https://github.com/TwiStarSystems/MServerController.git"
SERVICE_NAME="mservercontroller"
SSL_DIR="$INSTALL_DIR/ssl"

# SSL configuration
USE_SSL="false"
USE_NGINX="false"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
print_header() {
    echo ""
    echo -e "${BLUE}==========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}==========================================${NC}"
    echo ""
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${BLUE}→ $1${NC}"
}

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then 
        print_error "Please run as root (use sudo)"
        exit 1
    fi
}

# Check Linux distribution
check_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO="$ID"
        VERSION_ID="${VERSION_ID:-unknown}"
        
        case "$DISTRO" in
            debian)
                DEBIAN_VERSION=$(echo "$VERSION_ID" | cut -d. -f1)
                if [ "$DEBIAN_VERSION" != "unknown" ] && [ "$DEBIAN_VERSION" -lt 11 ]; then
                    print_warning "This script is designed for Debian 11 or newer."
                    echo "Current version: $VERSION_ID"
                    read -p "Continue anyway? (y/n) " -n 1 -r
                    echo
                    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                        exit 1
                    fi
                fi
                ;;
            ubuntu)
                print_info "Detected Ubuntu $VERSION_ID"
                ;;
            *)
                print_warning "This system ($DISTRO) may not be fully supported."
                read -p "Continue anyway? (y/n) " -n 1 -r
                echo
                if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                    exit 1
                fi
                ;;
        esac
    else
        print_warning "Cannot detect Linux distribution."
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

# Generate secure random key using Python
generate_secret_key() {
    python3 -c "import secrets; print(secrets.token_hex(32))"
}

# Prompt for environment configuration
prompt_env_config() {
    print_header "Environment Configuration"
    
    # Flask environment
    echo "Flask Environment:"
    echo "  1) Production (recommended for deployment)"
    echo "  2) Development (for testing only)"
    echo ""
    read -p "Select environment [1-2] (default: 1): " flask_choice
    flask_choice=${flask_choice:-1}
    
    if [ "$flask_choice" = "2" ]; then
        FLASK_ENV="development"
        print_info "Development mode selected"
        print_warning "Development mode allows all CORS origins and disables some security features"
    else
        FLASK_ENV="production"
        print_info "Production mode selected"
    fi
    echo ""
    
    # Secret key
    print_info "Generating secure secret key..."
    SECRET_KEY=$(generate_secret_key)
    print_success "Secret key generated"
    echo ""
    
    # ALLOWED_ORIGINS (required for production)
    if [ "$FLASK_ENV" = "production" ]; then
        echo "CORS Configuration (ALLOWED_ORIGINS):"
        echo "This controls which domains can access your API."
        echo ""
        echo "The following will be automatically included:"
        echo "  - http://localhost:3000 and https://localhost (for local testing)"
        echo "  - http://<server-ip>:3000 and https://<server-ip> (for IP access)"
        echo ""
        echo "You can add additional domains (comma-separated):"
        echo "Examples:"
        echo "  - https://example.com"
        echo "  - https://example.com,https://www.example.com"
        echo ""
        
        # Get server IP
        local server_ip=$(hostname -I | awk '{print $1}')
        local hostname=$(hostname)
        
        read -p "Enter additional allowed origins (comma-separated) [press Enter to skip]: " user_origins
        
        # Build ALLOWED_ORIGINS list with localhost and server IP always included
        ALLOWED_ORIGINS="http://localhost:3000,https://localhost,http://$server_ip:3000,https://$server_ip"
        
        # Add user-provided origins if any
        if [ -n "$user_origins" ]; then
            ALLOWED_ORIGINS="$ALLOWED_ORIGINS,$user_origins"
        fi
        
        print_info "ALLOWED_ORIGINS configured:"
        echo "  Localhost: http://localhost:3000, https://localhost"
        echo "  Server IP: http://$server_ip:3000, https://$server_ip"
        if [ -n "$user_origins" ]; then
            echo "  Custom: $user_origins"
        fi
    else
        ALLOWED_ORIGINS=""
        print_info "Development mode: CORS allows all origins"
    fi
    echo ""
    
    # Port configuration
    read -p "Enter server port [default: 3000]: " user_port
    SERVER_PORT=${user_port:-3000}
    print_info "Server port set to: $SERVER_PORT"
    echo ""
    
    # Optional configurations
    echo "Optional Configuration (press Enter to skip):"
    echo ""
    
    read -p "Session cookie domain (for subdomain support): " session_domain
    SESSION_COOKIE_DOMAIN="$session_domain"
    
    read -p "Session lifetime in seconds [default: 604800 = 7 days]: " session_lifetime
    PERMANENT_SESSION_LIFETIME=${session_lifetime:-604800}
    echo ""
    
    print_success "Environment configuration complete"
    echo ""
}

# Create .env file
create_env_file() {
    print_info "Creating .env file..."
    
    cat > "$INSTALL_DIR/.env" <<EOF
# Environment Configuration for MServerController
# Generated by installer on $(date)

# ==================== REQUIRED FOR PRODUCTION ====================

# Secret key for session encryption (GENERATED AUTOMATICALLY)
SECRET_KEY=$SECRET_KEY

# Flask environment (development or production)
FLASK_ENV=$FLASK_ENV

EOF

    # Add ALLOWED_ORIGINS if in production
    if [ "$FLASK_ENV" = "production" ] && [ -n "$ALLOWED_ORIGINS" ]; then
        cat >> "$INSTALL_DIR/.env" <<EOF
# Allowed CORS origins for SocketIO (comma-separated, required in production)
ALLOWED_ORIGINS=$ALLOWED_ORIGINS

EOF
    fi

    cat >> "$INSTALL_DIR/.env" <<EOF
# ==================== OPTIONAL CONFIGURATION ====================

# Port to run the server on
PORT=$SERVER_PORT

EOF

    # Add optional configurations if provided
    if [ -n "$SESSION_COOKIE_DOMAIN" ]; then
        cat >> "$INSTALL_DIR/.env" <<EOF
# Session cookie domain (for subdomain support)
SESSION_COOKIE_DOMAIN=$SESSION_COOKIE_DOMAIN

EOF
    fi

    cat >> "$INSTALL_DIR/.env" <<EOF
# Session lifetime in seconds (default: 604800 = 7 days)
PERMANENT_SESSION_LIFETIME=$PERMANENT_SESSION_LIFETIME

EOF

    cat >> "$INSTALL_DIR/.env" <<EOF
# ==================== SECURITY NOTES ====================

# 1. This file contains sensitive information - keep it secure
# 2. Never commit this file to version control
# 3. In production, always use FLASK_ENV=production
# 4. Set ALLOWED_ORIGINS to your actual domain(s) in production
# 5. Use HTTPS in production (SESSION_COOKIE_SECURE is auto-enabled)
EOF

    # Set proper permissions on .env file
    chmod 600 "$INSTALL_DIR/.env"
    chown www-data:www-data "$INSTALL_DIR/.env"
    
    print_success ".env file created"
    echo "  Location: $INSTALL_DIR/.env"
    echo "  Permissions: 600 (owner read/write only)"
    echo ""
}

# Prompt for SSL configuration
prompt_ssl_config() {
    print_header "SSL/TLS Configuration"
    
    echo "Would you like to enable SSL/TLS encryption (HTTPS)?"
    echo ""
    echo "Options:"
    echo "  1) HTTP only (port 3000) - No encryption, app serves directly"
    echo "  2) HTTPS direct (port 443) - App handles SSL with self-signed certificate"
    echo "  3) HTTPS with Nginx (port 443) - Nginx handles SSL as reverse proxy"
    echo ""
    read -p "Select option [1-3] (default: 1): " ssl_choice
    ssl_choice=${ssl_choice:-1}
    
    case $ssl_choice in
        1)
            USE_SSL="false"
            USE_NGINX="false"
            print_info "HTTP mode selected - app will serve directly on port 3000"
            ;;
        2)
            USE_SSL="true"
            USE_NGINX="false"
            print_info "HTTPS direct mode - app will handle SSL on port 443"
            ;;
        3)
            USE_SSL="true"
            USE_NGINX="true"
            print_info "HTTPS with Nginx - Nginx will handle SSL as reverse proxy"
            ;;
        *)
            print_warning "Invalid choice, defaulting to HTTP only"
            USE_SSL="false"
            USE_NGINX="false"
            ;;
    esac
    echo ""
}

# Generate SSL certificates
generate_ssl_certs() {
    if [ "$USE_SSL" = "true" ]; then
        print_info "Generating self-signed SSL certificate..."
        
        mkdir -p "$SSL_DIR"
        
        # Get IP address for SAN
        local ip_addr=$(hostname -I | awk '{print $1}')
        local hostname=$(hostname)
        
        # Create OpenSSL config for SAN
        cat > "$SSL_DIR/openssl.cnf" <<EOF
[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
ST = State
L = City
O = MServerController
CN = $hostname

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = $hostname
DNS.2 = localhost
IP.1 = 127.0.0.1
IP.2 = $ip_addr
EOF
        
        # Generate self-signed certificate (valid for 365 days)
        openssl req -x509 -newkey rsa:4096 -nodes \
            -keyout "$SSL_DIR/key.pem" \
            -out "$SSL_DIR/cert.pem" \
            -days 365 \
            -config "$SSL_DIR/openssl.cnf" \
            2>/dev/null
        
        chmod 600 "$SSL_DIR/key.pem"
        chmod 644 "$SSL_DIR/cert.pem"
        rm -f "$SSL_DIR/openssl.cnf"
        
        print_success "SSL certificate generated"
        echo "  Certificate: $SSL_DIR/cert.pem"
        echo "  Private Key: $SSL_DIR/key.pem"
        echo "  Valid for: 365 days"
        echo "  Hostname: $hostname"
        echo "  IP Address: $ip_addr"
        echo ""
        print_warning "This is a self-signed certificate. For production, use a certificate from a trusted CA."
        echo ""
    fi
}

# Install system dependencies
install_dependencies() {
    print_info "Updating system packages..."
    apt-get update
    apt-get upgrade -y

    print_info "Installing required packages..."
    # Install Java - try different versions based on availability
    if apt-cache show openjdk-21-jre-headless >/dev/null 2>&1; then
        JAVA_PKG="openjdk-21-jre-headless"
    elif apt-cache show openjdk-17-jre-headless >/dev/null 2>&1; then
        JAVA_PKG="openjdk-17-jre-headless"
    else
        JAVA_PKG="default-jre-headless"
    fi
    
    apt-get install -y curl wget git "$JAVA_PKG" python3 python3-pip python3-venv openssl

    echo ""
    print_success "Dependencies installed"
    echo "  Python version: $(python3 --version)"
    echo "  pip version: $(pip3 --version 2>/dev/null || echo 'pip installed via venv')"
    echo "  Java version: $(java -version 2>&1 | head -n 1)"
}

# Setup Python virtual environment and install packages
setup_python_env() {
    print_info "Setting up Python virtual environment..."
    
    # Remove old venv if exists
    if [ -d "$INSTALL_DIR/venv" ]; then
        rm -rf "$INSTALL_DIR/venv"
    fi
    
    python3 -m venv "$INSTALL_DIR/venv"
    source "$INSTALL_DIR/venv/bin/activate"
    
    print_info "Installing Python dependencies..."
    pip install --upgrade pip
    pip install -r "$INSTALL_DIR/requirements.txt"
    
    deactivate
    print_success "Python environment configured"
}

# Create necessary directories
create_directories() {
    print_info "Creating directories..."
    mkdir -p "$INSTALL_DIR/servers"
    mkdir -p "$INSTALL_DIR/backups"
    mkdir -p "$INSTALL_DIR/uploads"
    print_success "Directories created"
}

# Set proper permissions
set_permissions() {
    print_info "Setting permissions..."
    chown -R www-data:www-data "$INSTALL_DIR"
    chmod -R 755 "$INSTALL_DIR"
    print_success "Permissions configured"
}

# Configure Nginx
configure_nginx() {
    if [ "$USE_NGINX" = "true" ]; then
        print_info "Installing and configuring Nginx..."
        
        # Install nginx if not present
        if ! command -v nginx &> /dev/null; then
            apt-get install -y nginx
        fi
        
        # Get IP address and hostname for nginx config
        local ip_addr=$(hostname -I | awk '{print $1}')
        local hostname=$(hostname)
        
        # Create nginx configuration for HTTPS reverse proxy
        cat > /etc/nginx/sites-available/mservercontroller <<EOF
# MServerController - Nginx HTTPS Reverse Proxy Configuration
# SSL termination at Nginx, proxying to Flask app on localhost:3000

server {
    listen 80;
    server_name $hostname $ip_addr localhost;
    
    # Redirect all HTTP traffic to HTTPS
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name $hostname $ip_addr localhost;
    
    # SSL Certificate paths
    ssl_certificate $SSL_DIR/cert.pem;
    ssl_certificate_key $SSL_DIR/key.pem;
    
    # SSL Security Settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    
    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    
    # Increase max body size for file uploads
    client_max_body_size 500M;
    
    # Proxy to MServerController app
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_cache_bypass \$http_upgrade;
        proxy_read_timeout 86400;
    }
    
    # WebSocket support for console/real-time features
    location /socket.io {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }
}
EOF
        
        # Enable the site
        rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
        ln -sf /etc/nginx/sites-available/mservercontroller /etc/nginx/sites-enabled/
        
        # Test nginx configuration
        if nginx -t 2>/dev/null; then
            print_success "Nginx configuration is valid"
        else
            print_error "Nginx configuration test failed"
            nginx -t
            return 1
        fi
        
        # Enable and start nginx
        systemctl enable nginx
        systemctl restart nginx
        
        print_success "Nginx configured as HTTPS reverse proxy"
    else
        # App serves directly, disable nginx if present
        if systemctl is-active --quiet nginx 2>/dev/null; then
            print_info "Disabling Nginx (app serves directly)..."
            systemctl stop nginx 2>/dev/null || true
            systemctl disable nginx 2>/dev/null || true
            print_success "Nginx disabled"
        fi
    fi
    return 0
}

# Create systemd service
create_service() {
    print_info "Creating systemd service..."
    
    local exec_start
    local service_port="3000"
    
    # Determine port and SSL based on configuration
    if [ "$USE_NGINX" = "true" ]; then
        # With nginx: app runs HTTP on 3000, nginx handles SSL on 443
        service_port="3000"
        exec_start="$INSTALL_DIR/venv/bin/python server.py --port 3000"
    elif [ "$USE_SSL" = "true" ]; then
        # Direct SSL: app handles SSL on 443
        service_port="443"
        exec_start="$INSTALL_DIR/venv/bin/python server.py --port 443 --ssl-cert $SSL_DIR/cert.pem --ssl-key $SSL_DIR/key.pem"
    else
        # HTTP only: app serves on 3000
        service_port="3000"
        exec_start="$INSTALL_DIR/venv/bin/python server.py --port 3000"
    fi
    
    cat > /etc/systemd/system/mservercontroller.service <<EOF
[Unit]
Description=MServerController - Minecraft Server Manager
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=$INSTALL_DIR
ExecStart=$exec_start
Restart=always
RestartSec=10
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=mservercontroller
Environment=PORT=$service_port

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    print_success "Systemd service created"
}

# Start services
start_services() {
    print_info "Starting services..."
    systemctl enable mservercontroller
    systemctl start mservercontroller
    
    sleep 2
    if systemctl is-active --quiet mservercontroller; then
        print_success "MServerController service is running"
        return 0
    else
        print_error "Service failed to start"
        return 1
    fi
}

# Restart services (for updates)
restart_services() {
    print_info "Restarting services..."
    
    if systemctl is-active --quiet mservercontroller; then
        systemctl restart mservercontroller
    else
        systemctl start mservercontroller
    fi
    
    sleep 2
    if systemctl is-active --quiet mservercontroller; then
        print_success "MServerController service is running"
        return 0
    else
        print_error "Service failed to start"
        return 1
    fi
}

# Show completion message
show_completion() {
    local action="$1"
    echo ""
    print_header "${action} Complete!"
    echo "MServerController is now running."
    echo ""
    
    # Show configuration
    echo "Configuration:"
    if [ "$USE_NGINX" = "true" ]; then
        echo "  Transport Security: HTTPS via Nginx reverse proxy"
        echo "  Nginx: SSL termination on port 443"
        echo "  App: HTTP on port 3000 (internal)"
    elif [ "$USE_SSL" = "true" ]; then
        echo "  Transport Security: HTTPS (direct SSL) on port 443"
    else
        echo "  Transport Security: HTTP on port 3000"
    fi
    echo ""
    
    # Show access URL
    if [ "$USE_SSL" = "true" ]; then
        echo "Access the web interface at:"
        echo "  https://$(hostname -I | awk '{print $1}')"
        echo "  or"
        echo "  https://localhost"
        echo ""
        print_warning "Using self-signed certificate - browsers will show security warning"
        echo "Accept the certificate warning to proceed."
        if [ "$USE_NGINX" = "true" ]; then
            echo ""
            echo "Nginx commands:"
            echo "  Reload: sudo systemctl reload nginx"
            echo "  Status: sudo systemctl status nginx"
            echo "  Logs:   sudo tail -f /var/log/nginx/error.log"
        fi
    else
        echo "Access the web interface at:"
        echo "  http://$(hostname -I | awk '{print $1}'):3000"
        echo "  or"
        echo "  http://localhost:3000"
    fi
    echo ""
    
    echo "Service management commands:"
    echo "  Start:   sudo systemctl start mservercontroller"
    echo "  Stop:    sudo systemctl stop mservercontroller"
    echo "  Restart: sudo systemctl restart mservercontroller"
    echo "  Status:  sudo systemctl status mservercontroller"
    echo ""
    echo "Logs:"
    echo "  App logs: sudo journalctl -u mservercontroller -f"
    echo ""
}

# Fresh installation
do_install() {
    print_header "Fresh Installation"
    
    check_distro
    
    # Prompt for environment configuration first
    prompt_env_config
    
    # Prompt for SSL configuration
    prompt_ssl_config
    
    install_dependencies
    
    # Handle existing installation
    if [ -d "$INSTALL_DIR" ]; then
        print_warning "Directory $INSTALL_DIR already exists."
        read -p "Remove and reinstall? This will DELETE all data! (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            # Stop service if running
            systemctl stop mservercontroller 2>/dev/null || true
            systemctl disable mservercontroller 2>/dev/null || true
            rm -rf "$INSTALL_DIR"
        else
            print_error "Installation cancelled."
            exit 1
        fi
    fi
    
    # Determine source directory (where install.sh is located)
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    
    # Copy or clone files
    if [ -f "$SCRIPT_DIR/server.py" ]; then
        print_info "Copying files from source directory..."
        mkdir -p "$INSTALL_DIR"
        
        # Copy all application files
        cp "$SCRIPT_DIR/server.py" "$INSTALL_DIR/"
        cp "$SCRIPT_DIR/server_core.py" "$INSTALL_DIR/" 2>/dev/null || true
        cp "$SCRIPT_DIR/api_manager.py" "$INSTALL_DIR/" 2>/dev/null || true
        cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
        cp "$SCRIPT_DIR/version" "$INSTALL_DIR/" 2>/dev/null || true
        cp "$SCRIPT_DIR/users.json" "$INSTALL_DIR/" 2>/dev/null || true
        
        # Copy directories
        if [ -d "$SCRIPT_DIR/public" ]; then
            cp -r "$SCRIPT_DIR/public" "$INSTALL_DIR/"
            print_success "Copied: public/"
        fi
        
        if [ -d "$SCRIPT_DIR/configs" ]; then
            cp -r "$SCRIPT_DIR/configs" "$INSTALL_DIR/"
            print_success "Copied: configs/"
        fi
        
        if [ -d "$SCRIPT_DIR/docs" ]; then
            cp -r "$SCRIPT_DIR/docs" "$INSTALL_DIR/"
            print_success "Copied: docs/"
        fi
        
        if [ -d "$SCRIPT_DIR/tools" ]; then
            cp -r "$SCRIPT_DIR/tools" "$INSTALL_DIR/"
            print_success "Copied: tools/"
        fi
        
        if [ -d "$SCRIPT_DIR/serverexecutables" ]; then
            cp -r "$SCRIPT_DIR/serverexecutables" "$INSTALL_DIR/"
            print_success "Copied: serverexecutables/"
        fi
        
        print_success "Application files copied"
    else
        print_info "Cloning from GitHub..."
        git clone "$REPO_URL" "$INSTALL_DIR"
        print_success "Repository cloned"
    fi
    
    cd "$INSTALL_DIR"
    
    # Create .env file with user configuration
    create_env_file
    
    setup_python_env
    create_directories
    generate_ssl_certs
    set_permissions
    configure_nginx
    create_service
    
    if start_services; then
        show_completion "Installation"
    else
        print_error "Installation completed with warnings"
        echo "Check logs with: sudo journalctl -u mservercontroller -xe"
        exit 1
    fi
}

# Update existing installation (preserves all configs and data)
do_update() {
    print_header "Update Installation"
    
    # Check if installation exists
    if [ ! -d "$INSTALL_DIR" ]; then
        print_error "No existing installation found at $INSTALL_DIR"
        echo "Please run a fresh installation first."
        exit 1
    fi
    
    # Check if SSL was previously enabled
    if [ -d "$INSTALL_DIR/ssl" ] && [ -f "$INSTALL_DIR/ssl/cert.pem" ]; then
        USE_SSL="true"
        print_info "SSL configuration detected and will be preserved"
    fi
    
    # Display what will be preserved
    print_info "Files and data to be PRESERVED during update:"
    echo "  • config.json (server configurations)"
    echo "  • users.json (user accounts)"
    echo "  • settings.json (app settings)"
    echo "  • stats.json (performance metrics)"
    echo "  • servers/* (all game server data)"
    echo "  • backups/* (all backups)"
    echo "  • uploads/* (uploaded files)"
    echo "  • ssl/* (SSL certificates if present)"
    echo ""
    
    read -p "Continue with update? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Update cancelled."
        exit 0
    fi
    
    # Stop the service
    print_info "Stopping MServerController service..."
    systemctl stop mservercontroller 2>/dev/null || true
    sleep 2
    
    # List of critical files to preserve
    local preserve_files=(
        "config.json"
        "users.json"
        "settings.json"
        "stats.json"
        "schedules.json"
        "tasks.json"
        ".env"
    )
    
    # Create temporary backup directory
    local backup_dir="/tmp/mservercontroller_update_backup_$$"
    mkdir -p "$backup_dir"
    print_info "Creating temporary backup of critical files..."
    
    for file in "${preserve_files[@]}"; do
        if [ -f "$INSTALL_DIR/$file" ]; then
            cp "$INSTALL_DIR/$file" "$backup_dir/"
            print_success "  Backed up: $file"
        fi
    done
    
    # Also backup SSL directory if it exists
    if [ -d "$INSTALL_DIR/ssl" ]; then
        cp -r "$INSTALL_DIR/ssl" "$backup_dir/"
        print_success "  Backed up: ssl/ (certificates)"
    fi
    
    # Determine source directory (where install.sh is located)
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    
    # Update application files
    if [ -f "$SCRIPT_DIR/server.py" ]; then
        print_info "Updating application files from source directory..."
        
        # Copy core application files
        cp "$SCRIPT_DIR/server.py" "$INSTALL_DIR/"
        cp "$SCRIPT_DIR/server_core.py" "$INSTALL_DIR/" 2>/dev/null || true
        cp "$SCRIPT_DIR/api_manager.py" "$INSTALL_DIR/" 2>/dev/null || true
        cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
        
        # Update version file
        if [ -f "$SCRIPT_DIR/version" ]; then
            cp "$SCRIPT_DIR/version" "$INSTALL_DIR/"
            print_success "  Updated: version"
        fi
        
        # Update frontend files
        if [ -d "$SCRIPT_DIR/public" ]; then
            rm -rf "$INSTALL_DIR/public"
            cp -r "$SCRIPT_DIR/public" "$INSTALL_DIR/"
            print_success "  Updated: public/ (frontend files)"
        fi
        
        # Update configs directory (templates only)
        if [ -d "$SCRIPT_DIR/configs" ]; then
            rm -rf "$INSTALL_DIR/configs"
            cp -r "$SCRIPT_DIR/configs" "$INSTALL_DIR/"
            print_success "  Updated: configs/ (templates)"
        fi
        
        # Update documentation
        if [ -d "$SCRIPT_DIR/docs" ]; then
            rm -rf "$INSTALL_DIR/docs"
            cp -r "$SCRIPT_DIR/docs" "$INSTALL_DIR/"
            print_success "  Updated: docs/ (documentation)"
        fi
        
        # Update tools
        if [ -d "$SCRIPT_DIR/tools" ]; then
            mkdir -p "$INSTALL_DIR/tools"
            cp "$SCRIPT_DIR/tools"/*.py "$INSTALL_DIR/tools/" 2>/dev/null || true
            print_success "  Updated: tools/ (scripts)"
        fi
        
        # Update serverexecutables (new jar files etc)
        if [ -d "$SCRIPT_DIR/serverexecutables" ]; then
            # Merge, don't replace - preserve any custom executables
            cp -r "$SCRIPT_DIR/serverexecutables"/* "$INSTALL_DIR/serverexecutables/" 2>/dev/null || true
            print_success "  Updated: serverexecutables/"
        fi
        
        print_success "Application files updated from local source"
    else
        print_info "Updating from GitHub..."
        cd "$INSTALL_DIR"
        
        # Stash any local changes
        git stash 2>/dev/null || true
        
        # Pull latest changes
        if git pull origin main; then
            print_success "Application files updated from GitHub"
        else
            print_warning "Git pull had issues, trying reset..."
            git fetch origin main
            git reset --hard origin/main
            print_success "Application files updated from GitHub (hard reset)"
        fi
    fi
    
    # Restore all critical files from backup
    print_info "Restoring critical files and data..."
    for file in "${preserve_files[@]}"; do
        if [ -f "$backup_dir/$file" ]; then
            cp "$backup_dir/$file" "$INSTALL_DIR/"
            print_success "  Restored: $file"
        fi
    done
    
    # Restore SSL certificates if present
    if [ -d "$backup_dir/ssl" ]; then
        rm -rf "$INSTALL_DIR/ssl"
        cp -r "$backup_dir/ssl" "$INSTALL_DIR/"
        print_success "  Restored: ssl/ (certificates)"
    fi
    
    # Cleanup temporary backup
    rm -rf "$backup_dir"
    
    cd "$INSTALL_DIR"
    
    # Check if .env file exists, if not prompt for configuration
    if [ ! -f "$INSTALL_DIR/.env" ]; then
        print_warning ".env file not found - environment configuration required"
        echo "The application now requires environment variables to be configured."
        echo ""
        prompt_env_config
        create_env_file
    fi
    
    # Update Python virtual environment
    print_info "Updating Python virtual environment..."
    setup_python_env
    
    # Ensure all required directories exist
    create_directories
    
    # Fix permissions
    set_permissions
    
    # Update systemd service (in case of changes)
    print_info "Updating systemd service..."
    create_service
    
    # Restart services with new code
    if restart_services; then
        echo ""
        print_success "Update completed successfully!"
        echo ""
        echo "Summary:"
        echo "  ✓ Application files updated"
        echo "  ✓ Python dependencies updated"
        echo "  ✓ All configurations preserved"
        echo "  ✓ All user data preserved"
        echo "  ✓ Service restarted"
        echo ""
        show_completion "Update"
    else
        print_error "Update completed with warnings"
        echo "Service failed to restart. Check logs with:"
        echo "  sudo journalctl -u mservercontroller -xe"
        exit 1
    fi
}

# Dev mode - run locally without installing
do_dev() {
    print_header "Development Mode"
    
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    
    if [ ! -f "$SCRIPT_DIR/server.py" ]; then
        print_error "server.py not found in current directory"
        exit 1
    fi
    
    cd "$SCRIPT_DIR"
    
    # Create venv if it doesn't exist
    if [ ! -d "venv" ]; then
        print_info "Creating virtual environment..."
        python3 -m venv venv
    fi
    
    source venv/bin/activate
    
    # Check if dependencies need to be installed or updated
    print_info "Checking Python dependencies..."
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
    
    # Create data directories if they don't exist
    mkdir -p servers backups uploads serverexecutables
    
    # Check if .env file exists, if not create a development one
    if [ ! -f ".env" ]; then
        print_warning ".env file not found - creating development configuration..."
        
        # Generate a development secret key
        local dev_secret=$(python3 -c "import secrets; print(secrets.token_hex(32))")
        
        cat > .env <<EOF
# Development Environment Configuration
# Auto-generated by installer

# Flask environment
FLASK_ENV=development

# Secret key for session encryption
SECRET_KEY=$dev_secret

# Port (default for development)
PORT=3000

# Development mode allows all CORS origins
# No need to set ALLOWED_ORIGINS
EOF
        print_success ".env file created for development"
        echo "  FLASK_ENV=development"
        echo "  PORT=3000"
        echo ""
    fi
    
    echo ""
    print_success "Development environment ready!"
    echo ""
    echo "Starting MServerController in development mode..."
    echo "Access at: http://localhost:3000"
    echo "Press Ctrl+C to stop"
    echo ""
    echo "=========================================="
    
    # Run the server
    python server.py --port 3000
}

# Uninstall
do_uninstall() {
    print_header "Uninstall MServerController"
    
    # Check if installation exists
    if [ ! -d "$INSTALL_DIR" ]; then
        print_warning "No installation found at $INSTALL_DIR"
        echo "Nothing to uninstall."
        exit 0
    fi
    
    echo "This will remove:"
    echo "  - The application at $INSTALL_DIR"
    echo "  - The systemd service"
    echo ""
    print_warning "All server data, backups, and configurations will be DELETED!"
    echo ""
    read -p "Are you sure you want to uninstall? (y/n) " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Uninstall cancelled."
        exit 0
    fi
    
    # Double-check for servers data
    if [ -d "$INSTALL_DIR/servers" ] && [ "$(ls -A "$INSTALL_DIR/servers" 2>/dev/null)" ]; then
        echo ""
        print_warning "Server data detected in $INSTALL_DIR/servers"
        read -p "This will DELETE all server worlds and data! Type 'DELETE' to confirm: " confirm
        if [ "$confirm" != "DELETE" ]; then
            echo "Uninstall cancelled."
            exit 0
        fi
    fi
    
    print_info "Stopping services..."
    systemctl stop mservercontroller 2>/dev/null || true
    systemctl disable mservercontroller 2>/dev/null || true
    
    # Clean up nginx configuration if it exists
    if [ -f "/etc/nginx/sites-enabled/mservercontroller" ]; then
        print_info "Removing Nginx configuration..."
        rm -f /etc/nginx/sites-enabled/mservercontroller
        rm -f /etc/nginx/sites-available/mservercontroller
        systemctl reload nginx 2>/dev/null || true
    fi
    
    print_info "Removing systemd service..."
    rm -f /etc/systemd/system/mservercontroller.service
    systemctl daemon-reload
    
    print_info "Removing application files..."
    rm -rf "$INSTALL_DIR"
    
    echo ""
    print_success "MServerController has been uninstalled"
    echo ""
}

# Show status
do_status() {
    print_header "MServerController Status"
    
    # Check if installed
    if [ -d "$INSTALL_DIR" ]; then
        print_success "Installation found at $INSTALL_DIR"
        
        # Show version if available
        if [ -f "$INSTALL_DIR/version" ]; then
            echo "  Version: $(cat \"$INSTALL_DIR/version\")"
        fi
        
        # Check for SSL and Nginx
        if [ -d "$INSTALL_DIR/ssl" ] && [ -f "$INSTALL_DIR/ssl/cert.pem" ]; then
            if [ -f "/etc/nginx/sites-enabled/mservercontroller" ]; then
                echo "  Mode: HTTPS via Nginx reverse proxy"
            else
                echo "  Mode: HTTPS direct (app handles SSL)"
            fi
        else
            echo "  Mode: HTTP (no encryption)"
        fi
    else
        print_warning "No installation found at $INSTALL_DIR"
        return
    fi
    
    echo ""
    
    # Check service status
    echo "Service Status:"
    if systemctl is-active --quiet mservercontroller 2>/dev/null; then
        print_success "MServerController service is running"
    else
        print_warning "MServerController service is not running"
    fi
    
    if systemctl is-enabled --quiet mservercontroller 2>/dev/null; then
        print_success "Service is enabled (starts on boot)"
    else
        print_warning "Service is not enabled"
    fi
    
    # Check nginx status if site is configured
    if [ -f "/etc/nginx/sites-enabled/mservercontroller" ]; then
        echo ""
        echo "Nginx Status:"
        if systemctl is-active --quiet nginx 2>/dev/null; then
            print_success "Nginx is running"
        else
            print_warning "Nginx is not running"
        fi
    fi
    
    echo ""
    
    # Show config info if exists
    if [ -f "$INSTALL_DIR/config.json" ]; then
        SERVER_COUNT=$(grep -c '"name"' "$INSTALL_DIR/config.json" 2>/dev/null || echo "0")
        echo "Configured servers: $SERVER_COUNT"
    fi
    
    # Show disk usage
    if [ -d "$INSTALL_DIR" ]; then
        echo ""
        echo "Disk Usage:"
        du -sh "$INSTALL_DIR" 2>/dev/null || true
        if [ -d "$INSTALL_DIR/servers" ]; then
            du -sh "$INSTALL_DIR/servers" 2>/dev/null || true
        fi
        if [ -d "$INSTALL_DIR/backups" ]; then
            du -sh "$INSTALL_DIR/backups" 2>/dev/null || true
        fi
    fi
    
    echo ""
}

# Show help/usage
show_usage() {
    echo "MServerController Installation Script"
    echo ""
    echo "Usage: $0 [OPTION]"
    echo ""
    echo "Options:"
    echo "  install       Fresh installation (default if no option given)"
    echo "  update        Update existing installation (preserves data)"
    echo "  dev           Run in development mode (no installation)"
    echo "  status        Show installation status"
    echo "  uninstall     Remove MServerController completely"
    echo "  help          Show this help message"
    echo ""
    echo "Examples:"
    echo "  sudo $0 install        # Fresh installation"
    echo "  sudo $0 update         # Update to latest version"
    echo "  $0 dev                 # Run locally for development"
    echo "  $0 status              # Check installation status"
    echo ""
}

# Interactive menu
show_menu() {
    print_header "MServerController Installation Script"
    
    # Check if already installed
    if [ -d "$INSTALL_DIR" ]; then
        print_info "Existing installation detected at $INSTALL_DIR"
        if [ -f "$INSTALL_DIR/version" ]; then
            echo "  Version: $(cat "$INSTALL_DIR/version")"
        fi
        echo ""
    fi
    
    echo "Please select an option:"
    echo ""
    echo "  1) Fresh Install      - Complete new installation"
    echo "  2) Update             - Update existing installation (preserves data)"
    echo "  3) Development Mode   - Run locally without installing"
    echo "  4) Status             - Show installation status"
    echo "  5) Uninstall          - Remove MServerController"
    echo "  6) Exit"
    echo ""
    read -p "Enter your choice [1-6]: " choice
    
    case $choice in
        1) check_root; do_install ;;
        2) check_root; do_update ;;
        3) do_dev ;;
        4) do_status ;;
        5) check_root; do_uninstall ;;
        6) echo "Goodbye!"; exit 0 ;;
        *) print_error "Invalid option"; exit 1 ;;
    esac
}

# Main entry point
main() {
    case "${1:-}" in
        install)
            check_root
            do_install
            ;;
        update)
            check_root
            do_update
            ;;
        dev|development)
            do_dev
            ;;
        status)
            do_status
            ;;
        uninstall|remove)
            check_root
            do_uninstall
            ;;
        help|-h|--help)
            show_usage
            ;;
        "")
            # No argument - show interactive menu
            show_menu
            ;;
        *)
            print_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
}

# Run main
main "$@"
