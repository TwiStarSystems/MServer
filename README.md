# MServerController

A Web-Based Multi-Server Minecraft Manager

MServerController is a modern, user-friendly web application for creating, running, and managing **multiple Minecraft servers** simultaneously. Built with Python and Flask, it provides a clean interface for server administration with real-time monitoring, file management, and automated backups.

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0+-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## Features

### 🎮 Multi-Server Support
- Manage unlimited Minecraft servers from a single dashboard
- Start, stop, and monitor multiple servers simultaneously
- Each server has isolated configuration, files, and backups
- Real-time status indicators for all servers

### 🖥️ Real-Time Terminal
- Live server console output via WebSocket (Socket.IO)
- Execute commands on any running server
- Color-coded output for easy reading
- Persistent output buffer for recent history

### 📁 File Explorer
- Browse server files and directories
- Create, edit, and delete files
- Upload files to any server
- Download files and directories
- Syntax-highlighted text editor

### 💾 Backup System
- One-click backup creation per server
- Automatic ZIP compression
- Download backups to your local machine
- **Restore backups** with a single click
- Manage and delete old backups
- Backups organized by server

### 🆕 Easy Server Creation
- **Create Fresh Server** with automatic JAR download:
  - Vanilla (Official Minecraft Server)
  - Paper (High-performance Spigot fork)
  - Purpur (Paper fork with extra features)
  - BungeeCord (Proxy server)
  - Forge (Mod loader)
  - NeoForge (Modern Forge fork)
- **Upload Custom JAR** - Use your own server JAR file
- **Import Existing Server** - Import from ZIP file
- Automatic version selection with latest builds

### ⚙️ Server Configuration
- Configure server executable path
- Set Java memory allocation per server
- Customize JVM arguments
- Easy-to-use web interface

## Requirements

- **Operating System**: Debian 13+ (recommended), Ubuntu 22.04+, or any modern Linux
- **Web Server**: Nginx (for production)
- **Runtime**: Python 3.10+
- **Java**: OpenJDK 17+ (for running Minecraft servers)

## Installation

### Automated Installation (Recommended)

1. Clone the repository:
```bash
git clone https://github.com/TwiStarSystems/MServerController.git
cd MServerController
```

2. Run the installation script as root:
```bash
sudo ./install.sh
```

This will show an interactive menu with options:
- **Fresh Install** - Complete new installation
- **Update** - Update existing installation (preserves your data)
- **Quick Update** - Update files only (fast, ideal for dev testing)
- **Development Mode** - Run locally without installing
- **Status** - Show installation status
- **Uninstall** - Remove MServerController

You can also use command-line arguments:
```bash
sudo ./install.sh install        # Fresh installation
sudo ./install.sh update         # Update existing installation
sudo ./install.sh quick-update   # Quick file update (dev testing)
sudo ./install.sh status         # Check status
sudo ./install.sh uninstall      # Remove completely
./install.sh dev                 # Development mode (no sudo needed)
```

The script will:
- Install all required dependencies (Python, Nginx, Java)
- Create a Python virtual environment
- Set up the application in `/opt/mservercontroller`
- Configure Nginx as a reverse proxy
- Create and enable a systemd service
- Start the application automatically

3. Access the web interface:
```
http://your-server-ip
```

### Manual Installation

If you prefer to install manually:

1. **Install system dependencies**:
```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv nginx openjdk-17-jre-headless
```

2. **Clone and setup**:
```bash
git clone https://github.com/TwiStarSystems/MServerController.git
cd MServerController
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

3. **Configure Nginx** (optional, for production):
```bash
sudo cp nginx.conf /etc/nginx/sites-available/mservercontroller
sudo ln -s /etc/nginx/sites-available/mservercontroller /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

4. **Start the application**:
```bash
source venv/bin/activate
python server.py
```

### Development Mode

For local development:
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run with debug mode (optional)
python server.py
```

The application will be available at `http://localhost:3000`

## Usage

### Getting Started

1. **Access the web interface** at `http://your-server-ip`

2. **Add a server** by clicking the "Add" button in the sidebar:
   - Enter a name for your server
   - Specify the server directory (or leave empty to create a new one)
   - Configure the JAR file name and Java arguments
   - Click "Save"

3. **Start your server** by selecting it and clicking "Start"

### Managing Multiple Servers

#### Sidebar
- View all configured servers at a glance
- Green indicator = Running, Red = Stopped
- Click any server to manage it

#### Terminal View
- Real-time console output
- Send commands while server is running
- Start/Stop buttons for quick control

#### File Explorer
- Browse and edit server files
- Upload plugins, worlds, configurations
- Download any file

#### Backups
- Create backups of any server
- Restore previous states
- Download backups for external storage

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PORT` | HTTP port for the application | `3000` |
| `SECRET_KEY` | Flask secret key for sessions | Auto-generated |

### Server Configuration

Each server stores its configuration in `config.json`:
```json
{
  "servers": {
    "abc12345": {
      "name": "Survival Server",
      "serverPath": "/opt/mservercontroller/servers/abc12345",
      "executable": "server.jar",
      "javaArgs": "-Xmx4G -Xms2G",
      "autoStart": false,
      "created": "2025-01-14T10:00:00"
    }
  }
}
```

## Service Management

If installed via the installation script, MServerController runs as a systemd service:

```bash
# Start the service
sudo systemctl start mservercontroller

# Stop the service
sudo systemctl stop mservercontroller

# Restart the service
sudo systemctl restart mservercontroller

# Check service status
sudo systemctl status mservercontroller

# View logs
sudo journalctl -u mservercontroller -f
```

## Updating

### Update from Git Repository

To update an existing installation:

```bash
cd MServerController
git pull origin main
sudo ./install.sh update
```

The update process:
- Stops the service
- Backs up your configuration
- Updates application files
- Reinstalls Python dependencies
- Restores your configuration
- Restarts the service

All your servers, backups, and settings are preserved.

### Quick Update (Development)

For rapid development testing, use quick update:

```bash
sudo ./install.sh quick-update
```

This only copies the application files (server.py, public/) without reinstalling dependencies, making it much faster for iterative development.

## API Reference

### Server Types & Versions
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/server-types` | List available server types |
| GET | `/api/server-types/<type>/versions` | List versions for a server type |

### Server Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/servers` | List all servers |
| POST | `/api/servers` | Create new server (with optional JAR download) |
| POST | `/api/servers/import` | Import server from ZIP file |
| GET | `/api/servers/<id>` | Get server details |
| PUT | `/api/servers/<id>` | Update server config |
| DELETE | `/api/servers/<id>` | Delete server config |
| POST | `/api/servers/<id>/start` | Start server |
| POST | `/api/servers/<id>/stop` | Stop server |
| POST | `/api/servers/<id>/upload-jar` | Upload custom JAR file |
| POST | `/api/servers/<id>/download-jar` | Download JAR for existing server |

### File Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/servers/<id>/files` | List files |
| GET | `/api/servers/<id>/files/read` | Read file content |
| POST | `/api/servers/<id>/files/write` | Write file content |
| POST | `/api/servers/<id>/files/upload` | Upload file |
| GET | `/api/servers/<id>/files/download` | Download file |
| DELETE | `/api/servers/<id>/files/delete` | Delete file |

### Backup Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/servers/<id>/backups` | List backups |
| POST | `/api/servers/<id>/backups/create` | Create backup |
| GET | `/api/servers/<id>/backups/download` | Download backup |
| POST | `/api/servers/<id>/backups/restore` | Restore backup |
| DELETE | `/api/servers/<id>/backups/delete` | Delete backup |

## Security Considerations

- The application runs on localhost by default and should be accessed through Nginx
- File operations are restricted to configured server directories
- Path traversal attacks are prevented with security checks
- Rate limiting is enabled on all API endpoints:
  - General API: 100 requests per 15 minutes per IP
  - Upload endpoint: 10 requests per 15 minutes per IP
  - Backup creation: 5 requests per 15 minutes per IP
- Consider setting up SSL/TLS certificates for production use
- Implement firewall rules to restrict access to the web interface

## Troubleshooting

### Service won't start
```bash
# Check logs
sudo journalctl -u mservercontroller -xe

# Verify Python is installed
python3 --version

# Check if port 3000 is available
sudo netstat -tlnp | grep 3000

# Test manually
cd /opt/mservercontroller
source venv/bin/activate
python server.py
```

### Nginx errors
```bash
# Test Nginx configuration
sudo nginx -t

# Check Nginx logs
sudo tail -f /var/log/nginx/error.log
```

### Minecraft server won't start
- Verify Java is installed: `java -version`
- Check that the server JAR path is correct
- Ensure the server directory has proper permissions
- Review the terminal output for error messages
- Accept the EULA if required (`eula.txt`)

## Directory Structure

```
MServerController/
├── server.py                 # Main Python/Flask server
├── server_core.py            # Core utilities
├── requirements.txt          # Python dependencies
├── nginx.conf                # Nginx configuration
├── install.sh                # Installation script
├── config.json               # Server configurations (generated)
├── public/                   # Frontend files
│   ├── index.html            # Main HTML page
│   ├── styles.css            # Styles
│   └── app.js                # Frontend JavaScript
├── docs/                     # Documentation
│   └── DEVELOPMENT_GUIDE.md  # Development reference
├── venv/                     # Python virtual environment
├── servers/                  # Minecraft server files (per-server subdirectories)
├── backups/                  # Server backups (per-server subdirectories)
└── uploads/                  # Temporary upload directory
```

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

MIT License - see [LICENSE](LICENSE) file for details

## Support

For issues, questions, or suggestions, please open an issue on GitHub:
https://github.com/TwiStarSystems/MServerController/issues
