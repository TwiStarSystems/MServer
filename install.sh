#!/bin/bash

# MServer Installation Script for Debian/Ubuntu
# This script installs, updates, and configures MServer (Python version)

set -e

# Configuration
INSTALL_DIR="/opt/mserver"
REPO_URL="https://github.com/TwiStarSystems/MServer.git"
SERVICE_NAME="mserver"

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
    
    # Flask environment is always production (this installer only deploys prod).
    FLASK_ENV="production"

    # Secret key
    print_info "Generating secure secret key..."
    SECRET_KEY=$(generate_secret_key)
    print_success "Secret key generated"
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

    # Secure cookies. MServer always runs as plain HTTP and sits behind
    # an external reverse proxy that terminates TLS, so enforce the Secure cookie
    # flag (the proxy must forward X-Forwarded-Proto=https). Override in .env if
    # you ever expose the app over plain HTTP directly.
    SESSION_COOKIE_SECURE="true"

    # CORS origins
    read -p "Allowed WebSocket/CORS origins (comma-separated, e.g. https://panel.example.com) [default: *]: " cors_input
    CORS_ORIGINS="${cors_input:-*}"
    if [ "$CORS_ORIGINS" != "*" ]; then
        # Auto-prepend https:// to each entry if no scheme is provided
        # (the panel is served over HTTPS by the reverse proxy).
        _fixed_origins=""
        IFS=',' read -ra _parts <<< "$CORS_ORIGINS"
        for _part in "${_parts[@]}"; do
            _part="$(echo "$_part" | xargs)"  # trim whitespace
            if [ -n "$_part" ] && [[ ! "$_part" =~ ^https?:// ]]; then
                _part="https://$_part"
            fi
            if [ -n "$_fixed_origins" ]; then
                _fixed_origins="$_fixed_origins,$_part"
            else
                _fixed_origins="$_part"
            fi
        done
        CORS_ORIGINS="$_fixed_origins"
        print_info "CORS origins: $CORS_ORIGINS"
    else
        print_info "CORS set to wildcard (*). Restrict this in .env for production."
    fi
    echo ""

    print_success "Environment configuration complete"
    echo ""
}

# Create .env file
create_env_file() {
    print_info "Creating .env file..."
    
    cat > "$INSTALL_DIR/.env" <<EOF
# Environment Configuration for MServer
# Generated by installer on $(date)

# ==================== REQUIRED FOR PRODUCTION ====================

# Secret key for session encryption (GENERATED AUTOMATICALLY)
SECRET_KEY=$SECRET_KEY

# Flask environment (development or production)
FLASK_ENV=$FLASK_ENV

EOF

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

# Secure-cookie flag. Defaults to true: the app runs HTTP behind a reverse proxy
# that terminates TLS and forwards X-Forwarded-Proto=https. Set to false only if
# you expose the panel over plain HTTP directly (not recommended).
SESSION_COOKIE_SECURE=$SESSION_COOKIE_SECURE

# Comma-separated allowed WebSocket/CORS origins (use * to allow all)
# Example: CORS_ORIGINS=https://panel.example.com,https://example.com
CORS_ORIGINS=$CORS_ORIGINS

EOF

    cat >> "$INSTALL_DIR/.env" <<EOF
# ==================== SECURITY NOTES ====================

# 1. This file contains sensitive information - keep it secure
# 2. Never commit this file to version control
# 3. In production, always use FLASK_ENV=production
# 4. Keep SESSION_COOKIE_SECURE=true when a TLS-terminating proxy is in front
# 5. Restrict CORS_ORIGINS to your domain for production deployments
EOF

    # Set proper permissions on .env file
    chmod 600 "$INSTALL_DIR/.env"
    chown www-data:www-data "$INSTALL_DIR/.env"
    
    print_success ".env file created"
    echo "  Location: $INSTALL_DIR/.env"
    echo "  Permissions: 600 (owner read/write only)"
    echo ""
}



# Install the newest available Java JRE (21+)
# Tries standard apt packages first (25 → 21), then falls back to Eclipse
# Temurin (Adoptium) — the official OpenJDK distribution for newer versions.
install_java() {
    JAVA_PKG=""

    print_info "Searching for latest Java in system repositories..."
    for version in 25 24 23 22 21; do
        if apt-cache show "openjdk-${version}-jre-headless" >/dev/null 2>&1; then
            JAVA_PKG="openjdk-${version}-jre-headless"
            break
        fi
    done

    if [ -n "$JAVA_PKG" ]; then
        print_info "Installing $JAVA_PKG from system packages..."
        apt-get install -y "$JAVA_PKG"
    else
        print_info "Java 21+ not found in system repos. Adding Eclipse Temurin (Adoptium) repository..."
        apt-get install -y wget apt-transport-https gnupg

        # Import Adoptium GPG key
        wget -qO /tmp/adoptium.gpg "https://packages.adoptium.net/artifactory/api/gpg/key/public"
        gpg --batch --dearmor -o /etc/apt/trusted.gpg.d/adoptium.gpg /tmp/adoptium.gpg
        rm -f /tmp/adoptium.gpg

        # Add Adoptium apt repository for the current distro codename
        DISTRO_CODENAME=$(awk -F= '/^VERSION_CODENAME/{print$2}' /etc/os-release)
        echo "deb https://packages.adoptium.net/artifactory/deb ${DISTRO_CODENAME} main" \
            | tee /etc/apt/sources.list.d/adoptium.list
        apt-get update

        # Try Temurin JRE packages newest first
        for version in 25 24 23 22 21; do
            if apt-cache show "temurin-${version}-jre" >/dev/null 2>&1; then
                JAVA_PKG="temurin-${version}-jre"
                break
            fi
        done

        if [ -n "$JAVA_PKG" ]; then
            print_info "Installing $JAVA_PKG from Eclipse Temurin..."
            apt-get install -y "$JAVA_PKG"
        else
            print_warning "Could not find Java 21+ via Temurin. Installing system default Java."
            apt-get install -y default-jre-headless
        fi
    fi

    # If multiple Java versions are installed, make the newest the system default
    if command -v update-java-alternatives >/dev/null 2>&1; then
        update-java-alternatives --set "$(update-java-alternatives --list | sort -t' ' -k3 -rV | head -1 | awk '{print $1}')" 2>/dev/null || true
    fi
}

# Install system dependencies
install_dependencies() {
    print_info "Updating system packages..."
    apt-get update
    apt-get upgrade -y

    print_info "Installing required packages..."
    # Core runtime tools
    apt-get install -y curl wget git unzip

    # Python runtime + build tools needed to compile C extensions
    # (cryptography, Pillow/qrcode, eventlet all require headers at build time)
    apt-get install -y \
        python3 python3-pip python3-venv python3-dev \
        build-essential libffi-dev \
        libjpeg-dev libpng-dev zlib1g-dev

    install_java

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
    mkdir -p "$INSTALL_DIR/tools"
    mkdir -p "$INSTALL_DIR/configs"
    mkdir -p "$INSTALL_DIR/public/resourcepacks"
    mkdir -p "$INSTALL_DIR/serverexecutables"/{vanilla,paper,purpur,spigot,fabric,folia,forge,neoforge,bedrock}
    print_success "Directories created"
}

# Set proper permissions
set_permissions() {
    print_info "Setting permissions..."
    chown -R www-data:www-data "$INSTALL_DIR"
    chmod -R 755 "$INSTALL_DIR"
    # Secure sensitive files
    if [ -f "$INSTALL_DIR/.env" ]; then
        chmod 600 "$INSTALL_DIR/.env"
    fi
    print_success "Permissions configured"
}

# Create systemd service
create_service() {
    print_info "Creating systemd service..."
    
    local exec_start="$INSTALL_DIR/venv/bin/python server.py --port ${SERVER_PORT:-3000}"
    local service_port="${SERVER_PORT:-3000}"
    
    cat > /etc/systemd/system/mserver.service <<EOF
[Unit]
Description=MServer - Minecraft Server Manager
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
SyslogIdentifier=mserver
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
    systemctl enable mserver
    systemctl start mserver
    
    sleep 2
    if systemctl is-active --quiet mserver; then
        print_success "MServer service is running"
        return 0
    else
        print_error "Service failed to start"
        return 1
    fi
}

# Restart services (for updates)
restart_services() {
    print_info "Restarting services..."
    
    if systemctl is-active --quiet mserver; then
        systemctl restart mserver
    else
        systemctl start mserver
    fi
    
    sleep 2
    if systemctl is-active --quiet mserver; then
        print_success "MServer service is running"
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
    echo "MServer is now running."
    echo ""
    
    # MServer serves plain HTTP; put it behind your reverse proxy for TLS.
    echo "Configuration:"
    echo "  Transport: HTTP on port ${SERVER_PORT:-3000} (place your reverse proxy in front for HTTPS)"
    echo ""
    echo "Access the web interface (direct / behind your proxy) at:"
    echo "  http://$(hostname -I | awk '{print $1}'):${SERVER_PORT:-3000}"
    echo "  or"
    echo "  http://localhost:${SERVER_PORT:-3000}"
    echo ""

    echo "First-run setup:"
    echo "  Open the web interface in a browser — you'll be prompted to create"
    echo "  the administrator account. No default password is created."
    echo ""

    echo "Service management commands:"
    echo "  Start:   sudo systemctl start mserver"
    echo "  Stop:    sudo systemctl stop mserver"
    echo "  Restart: sudo systemctl restart mserver"
    echo "  Status:  sudo systemctl status mserver"
    echo ""
    echo "Logs:"
    echo "  App logs: sudo journalctl -u mserver -f"
    echo ""
}

# Fresh installation
do_install() {
    print_header "Fresh Installation"
    
    check_distro
    
    # Prompt for environment configuration first
    prompt_env_config

    install_dependencies
    
    # Handle existing installation
    if [ -d "$INSTALL_DIR" ]; then
        print_warning "Directory $INSTALL_DIR already exists."
        read -p "Remove and reinstall? This will DELETE all data! (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            # Stop service if running
            systemctl stop mserver 2>/dev/null || true
            systemctl disable mserver 2>/dev/null || true
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
        cp "$SCRIPT_DIR/api_manager.py" "$INSTALL_DIR/"
        cp "$SCRIPT_DIR/db.py" "$INSTALL_DIR/"
        cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
        cp "$SCRIPT_DIR/version" "$INSTALL_DIR/" 2>/dev/null || true
        
        # Copy directories
        if [ -d "$SCRIPT_DIR/public" ]; then
            cp -r "$SCRIPT_DIR/public" "$INSTALL_DIR/"
            print_success "Copied: public/"
        fi
        
        if [ -d "$SCRIPT_DIR/configs" ]; then
            cp -r "$SCRIPT_DIR/configs" "$INSTALL_DIR/"
            print_success "Copied: configs/"
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
    set_permissions
    create_service
    
    if start_services; then
        show_completion "Installation"
    else
        print_error "Installation completed with warnings"
        echo "Check logs with: sudo journalctl -u mserver -xe"
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
    
    # Display what will be preserved
    print_info "Files and data to be PRESERVED during update:"
    echo "  • msc.db (SQLite database — users, servers, schedules, tasks, stats, API keys)"
    echo "  • settings.json (app settings)"
    echo "  • servers/* (all game server data)"
    echo "  • backups/* (all backups)"
    echo "  • uploads/* (uploaded files)"
    echo ""
    
    read -p "Continue with update? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Update cancelled."
        exit 0
    fi
    
    # Stop the service
    print_info "Stopping MServer service..."
    systemctl stop mserver 2>/dev/null || true
    sleep 2
    
    # List of critical files to preserve
    local preserve_files=(
        "msc.db"
        "settings.json"
        ".env"
    )
    
    # Create temporary backup directory
    local backup_dir="/tmp/mserver_update_backup_$$"
    mkdir -p "$backup_dir"
    print_info "Creating temporary backup of critical files..."
    
    for file in "${preserve_files[@]}"; do
        if [ -f "$INSTALL_DIR/$file" ]; then
            cp "$INSTALL_DIR/$file" "$backup_dir/"
            print_success "  Backed up: $file"
        fi
    done
    
    # Determine source directory (where install.sh is located)
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    print_info "Source directory: $SCRIPT_DIR"
    
    # Update application files
    if [ -f "$SCRIPT_DIR/server.py" ]; then
        print_info "Updating application files from source directory..."
        
        # Copy core application files
        cp -f "$SCRIPT_DIR/server.py" "$INSTALL_DIR/"
        print_success "  Updated: server.py"
        
        cp -f "$SCRIPT_DIR/api_manager.py" "$INSTALL_DIR/"
        print_success "  Updated: api_manager.py"
        
        cp -f "$SCRIPT_DIR/db.py" "$INSTALL_DIR/"
        print_success "  Updated: db.py"
        
        cp -f "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
        print_success "  Updated: requirements.txt"
        
        # Update version file
        if [ -f "$SCRIPT_DIR/version" ]; then
            cp -f "$SCRIPT_DIR/version" "$INSTALL_DIR/"
            print_success "  Updated: version"
        fi
        
        # Update frontend files (THIS IS CRITICAL FOR YOUR CHANGES)
        if [ -d "$SCRIPT_DIR/public" ]; then
            print_info "Removing old frontend files..."
            rm -rf "$INSTALL_DIR/public"
            print_info "Copying new frontend files..."
            cp -rf "$SCRIPT_DIR/public" "$INSTALL_DIR/"
            # Verify the copy succeeded and show file count
            if [ -d "$INSTALL_DIR/public" ]; then
                local file_count=$(find "$INSTALL_DIR/public" -type f | wc -l)
                print_success "  Updated: public/ (frontend files) - $file_count files copied"
                # Verify critical files
                [ -f "$INSTALL_DIR/public/app.js" ] && print_success "    ✓ app.js updated" || print_warning "    ⚠ app.js not found!"
                [ -f "$INSTALL_DIR/public/settings.js" ] && print_success "    ✓ settings.js updated" || print_warning "    ⚠ settings.js not found!"
            else
                print_error "  Failed to copy public/ directory!"
            fi
        else
            print_warning "  Source public/ directory not found at $SCRIPT_DIR/public"
        fi
        
        # Update configs directory (templates only)
        if [ -d "$SCRIPT_DIR/configs" ]; then
            rm -rf "$INSTALL_DIR/configs"
            cp -r "$SCRIPT_DIR/configs" "$INSTALL_DIR/"
            print_success "  Updated: configs/ (templates)"
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
        print_warning "IMPORTANT: Clear your browser cache!"
        echo "  To see the updated frontend changes:"
        echo "  1. Press Ctrl+Shift+R (or Cmd+Shift+R on Mac) to hard refresh"
        echo "  2. Or clear browser cache completely"
        echo "  3. Or use Incognito/Private browsing mode"
        echo ""
        echo "  Updated timestamp: $(date)"
        echo ""
        show_completion "Update"
    else
        print_error "Update completed with warnings"
        echo "Service failed to restart. Check logs with:"
        echo "  sudo journalctl -u mserver -xe"
        exit 1
    fi
}

# Uninstall
do_uninstall() {
    print_header "Uninstall MServer"
    
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
    systemctl stop mserver 2>/dev/null || true
    systemctl disable mserver 2>/dev/null || true
    
    print_info "Removing systemd service..."
    rm -f /etc/systemd/system/mserver.service
    systemctl daemon-reload
    
    print_info "Removing application files..."
    rm -rf "$INSTALL_DIR"
    
    echo ""
    print_success "MServer has been uninstalled"
    echo ""
}

# Show status
do_status() {
    print_header "MServer Status"
    
    # Check if installed
    if [ -d "$INSTALL_DIR" ]; then
        print_success "Installation found at $INSTALL_DIR"
        
        # Show version if available
        if [ -f "$INSTALL_DIR/version" ]; then
            echo "  Version: $(cat \"$INSTALL_DIR/version\")"
        fi
        
        echo "  Mode: HTTP (TLS handled by your external reverse proxy)"
    else
        print_warning "No installation found at $INSTALL_DIR"
        return
    fi
    
    echo ""
    
    # Check service status
    echo "Service Status:"
    if systemctl is-active --quiet mserver 2>/dev/null; then
        print_success "MServer service is running"
    else
        print_warning "MServer service is not running"
    fi
    
    if systemctl is-enabled --quiet mserver 2>/dev/null; then
        print_success "Service is enabled (starts on boot)"
    else
        print_warning "Service is not enabled"
    fi
    
    echo ""
    
    # Show config info if database exists
    if [ -f "$INSTALL_DIR/msc.db" ]; then
        SERVER_COUNT=$(python3 -c "import sqlite3; c=sqlite3.connect('$INSTALL_DIR/msc.db'); print(c.execute('SELECT COUNT(*) FROM servers').fetchone()[0])" 2>/dev/null || echo "0")
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
    echo "MServer Installation Script"
    echo ""
    echo "Usage: $0 [OPTION]"
    echo ""
    echo "Options:"
    echo "  install       Fresh installation (default if no option given)"
    echo "  update        Update existing installation (preserves data)"
    echo "  status        Show installation status"
    echo "  uninstall     Remove MServer completely"
    echo "  help          Show this help message"
    echo ""
    echo "Examples:"
    echo "  sudo $0 install        # Fresh installation"
    echo "  sudo $0 update         # Update to latest version"
    echo "  $0 status              # Check installation status"
    echo ""
}

# Interactive menu
show_menu() {
    print_header "MServer Installation Script"
    
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
    echo "  3) Status             - Show installation status"
    echo "  4) Uninstall          - Remove MServer"
    echo "  5) Exit"
    echo ""
    read -p "Enter your choice [1-5]: " choice

    case $choice in
        1) check_root; do_install ;;
        2) check_root; do_update ;;
        3) do_status ;;
        4) check_root; do_uninstall ;;
        5) echo "Goodbye!"; exit 0 ;;
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
