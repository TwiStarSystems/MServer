#!/bin/bash

# MServerController Installation Script for Debian 13+
# This script installs, updates, and configures MServerController with Nginx (Python version)

set -e

# Configuration
INSTALL_DIR="/opt/mservercontroller"
REPO_URL="https://github.com/TwiStarSystems/MServerController.git"
SERVICE_NAME="mservercontroller"
DEPLOYMENT_CONFIG="$INSTALL_DIR/deployment.conf"
SSL_DIR="$INSTALL_DIR/ssl"
ENCRYPTION_KEY_FILE="$INSTALL_DIR/encryption.key"

# Deployment mode variables
DEPLOYMENT_MODE=""
CONTROLLER_URL=""
NODE_ID=""
USE_SSL="false"
USE_ENCRYPTION="false"
ENCRYPTION_KEY=""

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

# Check Debian version
check_debian() {
    if [ -f /etc/debian_version ]; then
        DEBIAN_VERSION=$(cat /etc/debian_version | cut -d. -f1)
        if [ "$DEBIAN_VERSION" -lt 13 ]; then
            print_warning "This script is designed for Debian 13 or newer."
            echo "Current version: $(cat /etc/debian_version)"
            read -p "Continue anyway? (y/n) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
    else
        print_warning "This system does not appear to be Debian."
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

# Prompt for deployment mode
prompt_deployment_mode() {
    print_header "Deployment Configuration"
    
    echo "Select deployment mode:"
    echo ""
    echo "  1) Master Node    - Full controller with Web UI (default)"
    echo "  2) Slave Node     - Headless worker node managed by Master"
    echo ""
    read -p "Enter your choice [1-2] (default: 1): " mode_choice
    
    mode_choice=${mode_choice:-1}
    
    case $mode_choice in
        1)
            DEPLOYMENT_MODE="master"
            print_success "Deployment mode: Master Node (Central Controller)"
            
            # Prompt for SSL/TLS
            echo ""
            read -p "Enable SSL/TLS encryption (HTTPS)? (y/n) (default: n): " use_ssl_choice
            use_ssl_choice=${use_ssl_choice:-n}
            if [[ $use_ssl_choice =~ ^[Yy]$ ]]; then
                USE_SSL="true"
                print_info "SSL/TLS will be enabled with self-signed certificate"
            else
                USE_SSL="false"
            fi
            
            # Prompt for payload encryption
            echo ""
            read -p "Enable payload encryption for Master-Slave communication? (y/n) (default: n): " use_enc_choice
            use_enc_choice=${use_enc_choice:-n}
            if [[ $use_enc_choice =~ ^[Yy]$ ]]; then
                USE_ENCRYPTION="true"
                print_info "Payload encryption will be enabled"
            else
                USE_ENCRYPTION="false"
            fi
            ;;
        2)
            DEPLOYMENT_MODE="slave"
            print_success "Deployment mode: Slave Node (Client Worker)"
            
            # Prompt for controller URL
            echo ""
            echo "Enter the Master Node controller URL:"
            echo "Example: https://192.168.1.100:3000 (with SSL) or http://192.168.1.100:3000 (without SSL)"
            read -p "Controller URL: " CONTROLLER_URL
            
            if [ -z "$CONTROLLER_URL" ]; then
                print_error "Controller URL is required for Slave nodes"
                exit 1
            fi
            
            # Check if using HTTPS
            if [[ $CONTROLLER_URL == https://* ]]; then
                USE_SSL="true"
                echo ""
                read -p "Verify SSL certificate? (y/n) (default: y): " verify_ssl_choice
                verify_ssl_choice=${verify_ssl_choice:-y}
                if [[ ! $verify_ssl_choice =~ ^[Yy]$ ]]; then
                    print_warning "SSL verification will be disabled (insecure)"
                fi
            else
                USE_SSL="false"
            fi
            
            # Prompt for payload encryption
            echo ""
            read -p "Enable payload encryption (if Master has it enabled)? (y/n) (default: n): " use_enc_choice
            use_enc_choice=${use_enc_choice:-n}
            if [[ $use_enc_choice =~ ^[Yy]$ ]]; then
                USE_ENCRYPTION="true"
                echo "Enter the encryption key (copy from Master node's $ENCRYPTION_KEY_FILE):"
                read -p "Encryption Key: " ENCRYPTION_KEY
                if [ -z "$ENCRYPTION_KEY" ]; then
                    print_error "Encryption key is required when encryption is enabled"
                    exit 1
                fi
            else
                USE_ENCRYPTION="false"
            fi
            
            # Prompt for node ID
            echo ""
            echo "Enter a unique Node ID for this Slave:"
            echo "Example: worker-01, production-node-1, etc."
            read -p "Node ID: " NODE_ID
            
            if [ -z "$NODE_ID" ]; then
                # Generate a default node ID
                NODE_ID="slave-$(hostname)-$(date +%s | tail -c 5)"
                print_warning "No Node ID provided, using: $NODE_ID"
            fi
            
            # Validate controller connectivity
            print_info "Validating connection to Master Node..."
            if curl -s --connect-timeout 5 "$CONTROLLER_URL/api/health" >/dev/null 2>&1; then
                print_success "Master Node is reachable"
            else
                print_warning "Cannot reach Master Node at $CONTROLLER_URL"
                read -p "Continue anyway? (y/n) " -n 1 -r
                echo
                if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                    exit 1
                fi
            fi
            ;;
        *)
            print_error "Invalid option"
            exit 1
            ;;
    esac
    
    echo ""
}

# Generate encryption key
generate_encryption_key() {
    # Only generate encryption key for MASTER nodes
    if [ "$DEPLOYMENT_MODE" != "master" ]; then
        print_info "Skipping encryption key generation (Slave node receives key from Master)"
        return 0
    fi
    
    if [ "$USE_ENCRYPTION" = "true" ]; then
        print_info "Generating encryption key..."
        
        # Generate a Fernet-compatible key using Python from virtual environment
        ENCRYPTION_KEY=$("$INSTALL_DIR/venv/bin/python3" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
        
        # Save to file
        echo "$ENCRYPTION_KEY" > "$ENCRYPTION_KEY_FILE"
        chmod 600 "$ENCRYPTION_KEY_FILE"
        
        print_success "Encryption key generated and saved to $ENCRYPTION_KEY_FILE"
        echo ""
        print_warning "IMPORTANT: Copy this encryption key to your Slave nodes!"
        echo "Encryption Key: $ENCRYPTION_KEY"
        echo ""
        read -p "Press Enter to continue..."
    fi
}

# Generate SSL certificates
generate_ssl_certs() {
    if [ "$USE_SSL" = "true" ] && [ "$DEPLOYMENT_MODE" = "master" ]; then
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

# Save deployment configuration
save_deployment_config() {
    print_info "Saving deployment configuration..."
    
    cat > "$DEPLOYMENT_CONFIG" <<EOF
# MServerController Deployment Configuration
# This file is automatically generated during installation

DEPLOYMENT_MODE=$DEPLOYMENT_MODE
CONTROLLER_URL=$CONTROLLER_URL
NODE_ID=$NODE_ID
USE_SSL=$USE_SSL
USE_ENCRYPTION=$USE_ENCRYPTION
EOF
    
    # Add encryption key reference for slave nodes
    if [ "$DEPLOYMENT_MODE" = "slave" ] && [ "$USE_ENCRYPTION" = "true" ]; then
        echo "ENCRYPTION_KEY=$ENCRYPTION_KEY" >> "$DEPLOYMENT_CONFIG"
        # Also save to encryption.key file for systemd service
        echo "$ENCRYPTION_KEY" > "$ENCRYPTION_KEY_FILE"
        chmod 600 "$ENCRYPTION_KEY_FILE"
    elif [ "$DEPLOYMENT_MODE" = "master" ] && [ "$USE_ENCRYPTION" = "true" ]; then
        echo "ENCRYPTION_KEY_FILE=$ENCRYPTION_KEY_FILE" >> "$DEPLOYMENT_CONFIG"
    fi
    
    chmod 600 "$DEPLOYMENT_CONFIG"
    print_success "Configuration saved to $DEPLOYMENT_CONFIG"
}

# Load deployment configuration
load_deployment_config() {
    if [ -f "$DEPLOYMENT_CONFIG" ]; then
        source "$DEPLOYMENT_CONFIG"
        return 0
    fi
    return 1
}

# Install system dependencies
install_dependencies() {
    print_info "Updating system packages..."
    apt-get update
    apt-get upgrade -y

    print_info "Installing required packages..."
    
    # Base packages for all nodes
    apt-get install -y curl wget git openjdk-21-jre-headless python3 python3-pip python3-venv
    
    # Install Nginx only for Master nodes
    if [ "$DEPLOYMENT_MODE" = "master" ]; then
        apt-get install -y nginx
    fi

    echo ""
    print_success "Dependencies installed"
    echo "  Python version: $(python3 --version)"
    echo "  pip version: $(pip3 --version)"
    echo "  Java version: $(java -version 2>&1 | head -n 1)"
    
    if [ "$DEPLOYMENT_MODE" = "master" ]; then
        echo "  Nginx version: $(nginx -v 2>&1)"
    fi
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
    if [ "$DEPLOYMENT_MODE" != "master" ]; then
        print_info "Skipping Nginx configuration (Slave node)"
        return 0
    fi
    
    print_info "Skipping Nginx configuration (app listens directly on HTTP/HTTPS ports)"
    # Disable nginx if it's running
    if systemctl is-active --quiet nginx 2>/dev/null; then
        systemctl stop nginx 2>/dev/null || true
        systemctl disable nginx 2>/dev/null || true
        print_success "Nginx disabled"
    fi
    return 0
}

# Create systemd service
create_service() {
    print_info "Creating systemd service..."
    
    # Determine ExecStart command based on deployment mode
    local exec_start
    local description
    local service_port="3000"  # Default port
    local encryption_env=""
    
    if [ "$DEPLOYMENT_MODE" = "slave" ]; then
        description="MServerController - Minecraft Server Manager (Slave Node)"
        exec_start="$INSTALL_DIR/venv/bin/python server.py --mode client --controller $CONTROLLER_URL --node-id $NODE_ID"
        
        # Add SSL verification flag if disabled
        if [ "$USE_SSL" = "true" ] && [[ ! $verify_ssl_choice =~ ^[Yy]$ ]]; then
            exec_start="$exec_start --no-verify-ssl"
        fi
        
        # Set encryption environment variable if enabled
        if [ "$USE_ENCRYPTION" = "true" ]; then
            encryption_env="Environment=ENCRYPTION_KEY=$ENCRYPTION_KEY"
        fi
        
        # Create service file
        cat > /etc/systemd/system/mservercontroller.service <<EOF
[Unit]
Description=$description
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
Environment=PORT=3000
$encryption_env

[Install]
WantedBy=multi-user.target
EOF
    else
        description="MServerController - Minecraft Server Manager (Master Node)"
        
        # Determine port based on SSL
        if [ "$USE_SSL" = "true" ]; then
            service_port="443"
            exec_start="$INSTALL_DIR/venv/bin/python server.py --mode central --port 443 --ssl-cert $SSL_DIR/cert.pem --ssl-key $SSL_DIR/key.pem"
        else
            service_port="3000"
            exec_start="$INSTALL_DIR/venv/bin/python server.py --mode central --port 3000"
        fi
        
        # Create service file with encryption key in environment if enabled
        if [ "$USE_ENCRYPTION" = "true" ]; then
            cat > /etc/systemd/system/mservercontroller.service <<EOF
[Unit]
Description=$description
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
Environment=ENCRYPTION_KEY=$(cat $ENCRYPTION_KEY_FILE)

[Install]
WantedBy=multi-user.target
EOF
        else
            cat > /etc/systemd/system/mservercontroller.service <<EOF
[Unit]
Description=$description
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
        fi
    fi

    systemctl daemon-reload
    print_success "Systemd service created for $DEPLOYMENT_MODE mode"
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
    
    if [ "$DEPLOYMENT_MODE" = "master" ]; then
        echo "Deployment Mode: Master Node (Central Controller)"
        echo ""
        
        # Show configuration
        echo "Configuration:"
        if [ "$USE_SSL" = "true" ]; then
            echo "  Transport Security: HTTPS (SSL/TLS Enabled) on port 443"
        else
            echo "  Transport Security: HTTP on port 3000"
        fi
        
        if [ "$USE_ENCRYPTION" = "true" ]; then
            echo "  Payload Encryption: Enabled (Fernet)"
        else
            echo "  Payload Encryption: Disabled"
        fi
        echo ""
        
        # Show access URL
        if [ "$USE_SSL" = "true" ]; then
            echo "Access the web interface at:"
            echo "  https://$(hostname -I | awk '{print $1}'):443"
            echo "  or"
            echo "  https://$(hostname -I | awk '{print $1}')"
            echo "  or"
            echo "  https://localhost"
            echo ""
            print_warning "Using self-signed certificate - browsers will show security warning"
            echo "Accept the certificate warning to proceed."
        else
            echo "Access the web interface at:"
            echo "  http://$(hostname -I | awk '{print $1}'):3000"
            echo "  or"
            echo "  http://localhost:3000"
        fi
        echo ""
    else
        echo "Deployment Mode: Slave Node (Client Worker)"
        echo "Controller: $CONTROLLER_URL"
        echo "Node ID: $NODE_ID"
        echo ""
        echo "This node will register with the Master controller."
        echo "Check the Master's web UI to verify connection."
        echo ""
    fi
    
    echo "Service management commands:"
    echo "  Start:   sudo systemctl start mservercontroller"
    echo "  Stop:    sudo systemctl stop mservercontroller"
    echo "  Restart: sudo systemctl restart mservercontroller"
    echo "  Status:  sudo systemctl status mservercontroller"
    echo ""
    echo "Logs:"
    echo "  App logs:   sudo journalctl -u mservercontroller -f"
    
    if [ "$DEPLOYMENT_MODE" = "master" ]; then
        echo "  Nginx logs: sudo tail -f /var/log/nginx/access.log"
    fi
    
    echo ""
}

# Fresh installation
do_install() {
    print_header "Fresh Installation"
    
    check_debian
    
    # Prompt for deployment mode
    prompt_deployment_mode
    
    install_dependencies
    
    # Handle existing installation
    if [ -d "$INSTALL_DIR" ]; then
        print_warning "Directory $INSTALL_DIR already exists."
        read -p "Remove and reinstall? This will DELETE all data! (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            # Stop service if running
            systemctl stop mservercontroller 2>/dev/null || true
            rm -rf "$INSTALL_DIR"
        else
            print_error "Installation cancelled."
            exit 1
        fi
    fi
    
    # Copy or clone files
    if [ -f "$(dirname "$0")/server.py" ]; then
        print_info "Copying files from current directory..."
        mkdir -p "$INSTALL_DIR"
        cp -r "$(dirname "$0")"/* "$INSTALL_DIR/"
        
        # Copy tools folder if it exists
        if [ -d "$(dirname "$0")/tools" ]; then
            print_info "Copying tools folder..."
            cp -r "$(dirname "$0")/tools" "$INSTALL_DIR/"
            print_success "Tools folder copied"
        fi
    else
        print_info "Cloning from GitHub..."
        git clone "$REPO_URL" "$INSTALL_DIR"
    fi
    
    cd "$INSTALL_DIR"
    
    setup_python_env
    create_directories
    generate_ssl_certs
    generate_encryption_key
    save_deployment_config
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

# Update existing installation (preserves all configs and encryption keys)
do_update() {
    print_header "Update Installation"
    
    # Check if installation exists
    if [ ! -d "$INSTALL_DIR" ]; then
        print_error "No existing installation found at $INSTALL_DIR"
        echo "Please run a fresh installation first."
        exit 1
    fi
    
    # Load existing deployment configuration
    if load_deployment_config; then
        print_success "Loaded deployment configuration: $DEPLOYMENT_MODE mode"
        if [ "$DEPLOYMENT_MODE" = "slave" ]; then
            echo "  Controller: $CONTROLLER_URL"
            echo "  Node ID: $NODE_ID"
        fi
        if [ "$USE_ENCRYPTION" = "true" ]; then
            echo "  Encryption: Enabled"
        fi
    else
        print_warning "No deployment configuration found, assuming Master mode"
        DEPLOYMENT_MODE="master"
    fi
    
    # Display what will be preserved
    print_info "Files and data to be PRESERVED during update:"
    echo "  • config.json (server configurations)"
    echo "  • users.json (user accounts)"
    echo "  • settings.json (app settings)"
    echo "  • stats.json (performance metrics)"
    echo "  • clients.json (registered nodes)"
    echo "  • commands.json (command queue)"
    echo "  • backup_schedules.json (backup schedules)"
    echo "  • task_schedules.json (task schedules)"
    echo "  • encryption.key (encryption key - CRITICAL)"
    echo "  • deployment.conf (deployment configuration)"
    echo "  • servers/* (all game server data)"
    echo "  • backups/* (all backups)"
    echo "  • ssl/* (SSL certificates if Master)"
    echo ""
    
    # Stop the service
    print_info "Stopping MServerController service..."
    systemctl stop mservercontroller 2>/dev/null || true
    sleep 1
    
    # List of critical files to preserve
    local preserve_files=(
        "config.json"
        "users.json"
        "settings.json"
        "stats.json"
        "clients.json"
        "commands.json"
        "backup_schedules.json"
        "task_schedules.json"
        "encryption.key"
        "deployment.conf"
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
    
    # Also backup SSL directory for Master nodes
    if [ "$DEPLOYMENT_MODE" = "master" ] && [ -d "$INSTALL_DIR/ssl" ]; then
        cp -r "$INSTALL_DIR/ssl" "$backup_dir/"
        print_success "  Backed up: ssl/ (certificates)"
    fi
    
    # Update application files
    if [ -f "$(dirname "$0")/server.py" ]; then
        print_info "Updating application files from current directory..."
        
        # Copy core application files
        cp "$(dirname "$0")/server.py" "$INSTALL_DIR/"
        cp "$(dirname "$0")/server_client.py" "$INSTALL_DIR/"
        cp "$(dirname "$0")/server_core.py" "$INSTALL_DIR/" 2>/dev/null || true
        cp "$(dirname "$0")/system_info.py" "$INSTALL_DIR/" 2>/dev/null || true
        cp "$(dirname "$0")/requirements.txt" "$INSTALL_DIR/"
        cp "$(dirname "$0")/nginx.conf" "$INSTALL_DIR/"
        
        # Update frontend files
        if [ -d "$(dirname "$0")/public" ]; then
            rm -rf "$INSTALL_DIR/public"
            cp -r "$(dirname "$0")/public" "$INSTALL_DIR/"
            print_success "  Updated: public/ (frontend files)"
        fi
        
        # Update configs directory
        if [ -d "$(dirname "$0")/configs" ]; then
            rm -rf "$INSTALL_DIR/configs"
            cp -r "$(dirname "$0")/configs" "$INSTALL_DIR/"
            print_success "  Updated: configs/ (templates)"
        fi
        
        # Update documentation
        if [ -d "$(dirname "$0")/docs" ]; then
            rm -rf "$INSTALL_DIR/docs"
            cp -r "$(dirname "$0")/docs" "$INSTALL_DIR/"
            print_success "  Updated: docs/ (documentation)"
        fi
        
        # Merge tools (don't overwrite user tools)
        if [ -d "$(dirname "$0")/tools" ]; then
            mkdir -p "$INSTALL_DIR/tools"
            cp "$(dirname "$0")/tools"/*.py "$INSTALL_DIR/tools/" 2>/dev/null || true
            print_success "  Updated: tools/ (scripts)"
        fi
        
        print_success "Application files updated from local source"
    else
        print_info "Updating from GitHub..."
        cd "$INSTALL_DIR"
        git stash 2>/dev/null || true
        git pull origin main
        print_success "Application files updated from GitHub"
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
    if [ -d "$backup_dir/ssl" ] && [ "$DEPLOYMENT_MODE" = "master" ]; then
        rm -rf "$INSTALL_DIR/ssl"
        cp -r "$backup_dir/ssl" "$INSTALL_DIR/"
        print_success "  Restored: ssl/ (certificates)"
    fi
    
    rm -rf "$backup_dir"
    
    
    cd "$INSTALL_DIR"
    
    # Update Python virtual environment
    print_info "Updating Python virtual environment..."
    setup_python_env
    
    # Ensure all required directories exist
    create_directories
    
    # Fix permissions
    set_permissions
    
    # Update Nginx configuration (for Master nodes)
    configure_nginx
    
    # Update systemd service (regenerate based on current deployment mode)
    print_info "Updating systemd service for $DEPLOYMENT_MODE mode..."
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
        if [ "$USE_ENCRYPTION" = "true" ]; then
            echo "  ✓ Encryption key preserved"
        fi
        echo "  ✓ Service restarted ($DEPLOYMENT_MODE mode)"
        echo ""
        show_completion "Update"
    else
        print_error "Update completed with warnings"
        echo "Service failed to restart. Check logs with:"
        echo "  sudo journalctl -u mservercontroller -xe"
        exit 1
    fi
}

# Quick update (files only, no dependency reinstall - preserves configs and encryption)
do_quick_update() {
    print_header "Quick Update (Files Only - Fast Development Mode)"
    
    # Check if installation exists
    if [ ! -d "$INSTALL_DIR" ]; then
        print_error "No existing installation found at $INSTALL_DIR"
        echo "Please run a fresh installation first."
        exit 1
    fi
    
    # Load existing deployment configuration
    if load_deployment_config; then
        print_success "Loaded deployment configuration: $DEPLOYMENT_MODE mode"
        if [ "$DEPLOYMENT_MODE" = "slave" ]; then
            echo "  Controller: $CONTROLLER_URL"
            echo "  Node ID: $NODE_ID"
        fi
    else
        print_warning "No deployment configuration found, assuming Master mode"
        DEPLOYMENT_MODE="master"
    fi
    
    print_info "This quick update will:"
    echo "  • Update application files ONLY"
    echo "  • NOT reinstall Python dependencies"
    echo "  • PRESERVE all configurations"
    echo "  • PRESERVE encryption keys"
    echo "  • PRESERVE user data and logs"
    echo ""
    
    # Stop the service
    print_info "Stopping MServerController service..."
    systemctl stop mservercontroller 2>/dev/null || true
    sleep 1
    
    # Update only application files (no backups needed - quick update)
    if [ -f "$(dirname "$0")/server.py" ]; then
        print_info "Updating application files..."
        
        # Core application files
        cp "$(dirname "$0")/server.py" "$INSTALL_DIR/"
        cp "$(dirname "$0")/server_client.py" "$INSTALL_DIR/"
        cp "$(dirname "$0")/server_core.py" "$INSTALL_DIR/" 2>/dev/null || true
        cp "$(dirname "$0")/system_info.py" "$INSTALL_DIR/" 2>/dev/null || true
        
        # Frontend files
        if [ -d "$(dirname "$0")/public" ]; then
            rm -rf "$INSTALL_DIR/public"
            cp -r "$(dirname "$0")/public" "$INSTALL_DIR/"
            print_success "  Updated: public/"
        fi
        
        # Config templates
        if [ -d "$(dirname "$0")/configs" ]; then
            rm -rf "$INSTALL_DIR/configs"
            cp -r "$(dirname "$0")/configs" "$INSTALL_DIR/"
            print_success "  Updated: configs/"
        fi
        
        # Documentation
        if [ -d "$(dirname "$0")/docs" ]; then
            rm -rf "$INSTALL_DIR/docs"
            cp -r "$(dirname "$0")/docs" "$INSTALL_DIR/"
            print_success "  Updated: docs/"
        fi
        
        # Tools
        if [ -d "$(dirname "$0")/tools" ]; then
            mkdir -p "$INSTALL_DIR/tools"
            cp "$(dirname "$0")/tools"/*.py "$INSTALL_DIR/tools/" 2>/dev/null || true
            print_success "  Updated: tools/"
        fi
        
        print_success "Application files updated"
    else
        print_info "Updating from GitHub (files only)..."
        cd "$INSTALL_DIR"
        git stash 2>/dev/null || true
        git pull origin main
        print_success "Application files updated from GitHub"
    fi
    
    # Fix permissions
    set_permissions
    
    # Restart services quickly without dependency reinstall
    if restart_services; then
        echo ""
        print_success "Quick update complete!"
        echo ""
        echo "Summary:"
        echo "  ✓ Application files updated"
        echo "  ✓ All configurations preserved"
        echo "  ✓ All user data preserved"
        if [ "$USE_ENCRYPTION" = "true" ]; then
            echo "  ✓ Encryption key preserved"
        fi
        echo "  ✓ Service restarted ($DEPLOYMENT_MODE mode)"
        echo ""
        echo "Note: Python dependencies were NOT updated in quick mode."
        echo "Run 'sudo $0 update' for a full update with dependency refresh."
        echo ""
    else
        print_error "Quick update completed with warnings"
        echo "Check logs with: sudo journalctl -u mservercontroller -xe"
        exit 1
    fi
}

# Dev mode - run locally without installing
do_dev() {
    print_header "Development Mode"
    
    SCRIPT_DIR="$(dirname "$0")"
    
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
    
    # Check if dependencies need to be installed
    if ! pip show flask >/dev/null 2>&1; then
        print_info "Installing Python dependencies..."
        pip install --upgrade pip
        pip install -r requirements.txt
    fi
    
    # Create data directories if they don't exist
    mkdir -p servers backups uploads
    
    echo ""
    print_success "Development environment ready!"
    echo ""
    echo "Starting MServerController in development mode..."
    echo "Press Ctrl+C to stop"
    echo ""
    echo "=========================================="
    
    # Run the server
    python server.py
}

# Uninstall
do_uninstall() {
    print_header "Uninstall MServerController"
    
    echo "This will remove:"
    echo "  - The application at $INSTALL_DIR"
    echo "  - The systemd service"
    echo "  - The Nginx configuration"
    echo ""
    print_warning "All server data, backups, and configurations will be DELETED!"
    echo ""
    read -p "Are you sure you want to uninstall? (y/n) " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Uninstall cancelled."
        exit 0
    fi
    
    print_info "Stopping services..."
    systemctl stop mservercontroller 2>/dev/null || true
    systemctl disable mservercontroller 2>/dev/null || true
    
    print_info "Removing systemd service..."
    rm -f /etc/systemd/system/mservercontroller.service
    systemctl daemon-reload
    
    print_info "Removing Nginx configuration..."
    rm -f /etc/nginx/sites-enabled/mservercontroller
    rm -f /etc/nginx/sites-available/mservercontroller
    systemctl reload nginx 2>/dev/null || true
    
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
        
        # Load and display deployment configuration
        if load_deployment_config; then
            echo ""
            echo "Deployment Configuration:"
            echo "  Mode: $DEPLOYMENT_MODE"
            if [ "$DEPLOYMENT_MODE" = "slave" ]; then
                echo "  Controller: $CONTROLLER_URL"
                echo "  Node ID: $NODE_ID"
            fi
        fi
    else
        print_warning "No installation found at $INSTALL_DIR"
    fi
    
    echo ""
    
    # Check service status
    echo "Service Status:"
    if systemctl is-active --quiet mservercontroller; then
        print_success "MServerController service is running"
    else
        print_warning "MServerController service is not running"
    fi
    
    if systemctl is-enabled --quiet mservercontroller 2>/dev/null; then
        print_success "Service is enabled (starts on boot)"
    else
        print_warning "Service is not enabled"
    fi
    
    echo ""
    
    # Check Nginx
    echo "Nginx Status:"
    if systemctl is-active --quiet nginx; then
        print_success "Nginx is running"
    else
        print_warning "Nginx is not running"
    fi
    
    echo ""
    
    # Show config info if exists
    if [ -f "$INSTALL_DIR/config.json" ]; then
        SERVER_COUNT=$(grep -o '"[a-f0-9]\{8\}"' "$INSTALL_DIR/config.json" 2>/dev/null | wc -l || echo "0")
        echo "Configured servers: $SERVER_COUNT"
    fi
    
    # Show disk usage
    if [ -d "$INSTALL_DIR" ]; then
        echo ""
        echo "Disk Usage:"
        du -sh "$INSTALL_DIR" 2>/dev/null || true
        du -sh "$INSTALL_DIR/servers" 2>/dev/null || true
        du -sh "$INSTALL_DIR/backups" 2>/dev/null || true
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
    echo "  quick-update  Quick update (files only, faster for dev testing)"
    echo "  dev           Run in development mode (no installation)"
    echo "  status        Show installation status"
    echo "  uninstall     Remove MServerController completely"
    echo "  help          Show this help message"
    echo ""
    echo "Examples:"
    echo "  sudo $0 install        # Fresh installation"
    echo "  sudo $0 update         # Update to latest version"
    echo "  sudo $0 quick-update   # Quick file update for testing"
    echo "  $0 dev                 # Run locally for development"
    echo ""
}

# Interactive menu
show_menu() {
    print_header "MServerController Installation Script"
    
    # Check if already installed
    if [ -d "$INSTALL_DIR" ]; then
        echo "Existing installation detected at $INSTALL_DIR"
        
        # Show current deployment mode if available
        if load_deployment_config; then
            echo "Current mode: $DEPLOYMENT_MODE"
            if [ "$DEPLOYMENT_MODE" = "slave" ]; then
                echo "Connected to: $CONTROLLER_URL"
            fi
        fi
        echo ""
    fi
    
    echo "Please select an option:"
    echo ""
    echo "  1) Fresh Install      - Complete new installation (Master or Slave)"
    echo "  2) Update             - Update existing installation (preserves data)"
    echo "  3) Quick Update       - Update files only (fast, for dev testing)"
    echo "  4) Development Mode   - Run locally without installing"
    echo "  5) Status             - Show installation status"
    echo "  6) Uninstall          - Remove MServerController"
    echo "  7) Exit"
    echo ""
    read -p "Enter your choice [1-7]: " choice
    
    case $choice in
        1) check_root; do_install ;;
        2) check_root; do_update ;;
        3) check_root; do_quick_update ;;
        4) do_dev ;;
        5) do_status ;;
        6) check_root; do_uninstall ;;
        7) echo "Goodbye!"; exit 0 ;;
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
        quick-update|quickupdate|quick)
            check_root
            do_quick_update
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
