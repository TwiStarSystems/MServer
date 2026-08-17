# MServer

A Web-Based Multi-Server Minecraft Manager

MServer is a modern, feature-rich web application for creating, running, and managing **multiple Minecraft servers** simultaneously. Built with Python/Flask and Socket.IO, it provides a responsive dark-themed interface with real-time monitoring, role-based access control, automated backups, task scheduling, and a full public REST API.

![Version](https://img.shields.io/badge/Version-4.0.0-purple.svg)
![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0+-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## Features

### 🎮 Multi-Server Management
- Create, start, stop, kill, and monitor unlimited Minecraft servers from a single dashboard
- Per-server isolated configuration, files, backups, and scheduled tasks
- Real-time status indicators (Running, Stopped, Starting, Stopping, Unresponsive)
- Server import from ZIP archive, custom JAR upload, or world-only import
- Managed server mode with automatic JAR update tracking
- Server approval workflow (optional admin gating for new servers)
- Bedrock Edition support alongside Java Edition
- First-run setup wizard for initial admin account creation

### 🖥️ Real-Time Terminal & Logs
- Live server console output via WebSocket (Socket.IO)
- Execute commands on any running server in real time
- Persistent output buffer for recent history
- Dedicated logs tab with separate log viewer
- Terminal input with command history

### 📁 File Explorer
- Browse, create, edit, rename, and delete server files and directories
- Upload and download files
- Built-in syntax-highlighted text editor
- Breadcrumb navigation with path display

### 🧩 Mod & Plugin Manager
- Dedicated tab for managing server mods and plugins
- Upload, enable, disable, and remove JAR files
- Separate sections for plugins (Bukkit/Spigot/Paper) and mods (Forge/NeoForge/Fabric)
- Drag-and-drop multi-file upload support

### 📋 NBT Editor
- Read and write Minecraft NBT binary files directly from the web UI
- Add, edit, and delete NBT tags
- Supports all NBT tag types (compound, list, string, int, etc.)
- GZip and uncompressed format support

### ⚙️ Server Properties Editor
- Visual editor for `server.properties` with categorized fields
- Input validation and type-appropriate controls
- Apply changes without manually editing config files

### 🎨 Resource Pack Hosting
- Upload resource packs per server
- Automatic SHA-1 hash computation for `server.properties` integration
- Built-in resource pack URL generation
- Automatic `server.properties` updates with resource pack settings

### 💾 Backup System
- One-click backup creation per server with ZIP compression
- Download, restore, and delete backups
- **Automated backup scheduling** with cron expressions
- Configurable backup retention (max count and auto-cleanup)
- SMTP email notifications for backup success/failure
- **External backup storage** (S3-compatible or FTP) with automatic upload
- Backups organized by server

### ⏰ Task Scheduler
- Schedule server actions: start, stop, reboot, and custom commands
- Cron-based scheduling (specific times, intervals, days of week)
- Run-limited tasks (execute N times then auto-disable)
- Per-server task management with enable/disable toggle

### 💬 Server Messaging
- Schedule automated in-game messages (announcements, MOTD, reminders)
- Cron-based and event-triggered delivery (on backup, start, stop, crash)
- Full text formatting (color, bold, italic, underlined, strikethrough, obfuscated)
- Target specific players or broadcast to all
- Per-server message management with enable/disable toggle

### 🔄 Background Job Queue
- Long-running operations (backups, restores, JAR swaps, deletions) run asynchronously
- Real-time progress reporting via WebSocket push notifications
- Per-server concurrency control (no overlapping jobs on the same server)
- Job history with status tracking (queued, running, completed, failed, cancelled)
- Cancel running jobs from the UI
- Downloadable job artifacts (e.g. backup files)

### 👥 User Management & RBAC
- Role-based access control with three tiers: **Admin** (full access), **User** (manage own servers), **Public** (view-only status)
- User registration with optional admin approval workflow
- Per-server access control (users see only their owned/assigned servers)
- Admin user management panel (create, edit, delete, approve users)
- Account lockout after failed login attempts with automatic anti-lockout emergency admin
- Username, display name, and email profile management

### 🔐 Security
- Multi-Factor Authentication (MFA/2FA) with TOTP (Google Authenticator, Authy, etc.)
- Hashed recovery codes for MFA account recovery
- CSRF protection on all state-changing endpoints
- Rate limiting per IP (login, uploads, backups, API)
- Session-based authentication with secure cookie settings
- Password hashing with Werkzeug
- Path traversal protection on all file operations
- Configurable MFA enforcement for admins or all users
- SSL/TLS support with certificate arguments

### 🌐 Public API (v1)
- RESTful API with API key authentication
- Key management with permissions (read, write, admin, console)
- Per-key rate limiting and expiration
- API usage statistics and request tracking
- Endpoints for server listing, status, start/stop, and command execution
- Auto-generated API documentation endpoint

### 📊 System Monitoring
- Real-time CPU, RAM, and disk usage charts (admin dashboard)
- Historical stats with 7-day retention
- Per-server resource monitoring
- Live stats broadcast via WebSocket every 10 seconds

### 🔧 Admin Settings Panel
- **Branding**: Custom site title, favicon upload, and footer text
- **App Settings**: Toggle registration, require approval, server approval workflow
- **MFA Settings**: Require MFA for admins or all users
- **SMTP Configuration**: Email notifications with test email support
- **Email Templates**: Customizable notification templates with reset-to-default
- **Webhook Notifications**: Outbound webhooks for server events
- **External Backup Storage**: Configure S3-compatible or FTP destinations
- **JAR Bucket Manager**: Download server JARs from official APIs (Paper, Purpur, Folia, Forge, NeoForge, Fabric, Vanilla, Spigot, BungeeCord)
- **Tools Manager**: Upload and execute custom Python scripts (admin only)
- **User Management**: Full CRUD with role assignment and password reset
- **API Key Management**: Create, revoke, and manage public API keys

### 🆕 Server Type Support
- **Java Edition**: Vanilla, Paper, Purpur, Folia, Spigot, BungeeCord
- **Modded**: Forge, NeoForge, Fabric
- **Bedrock Edition**: Bedrock Dedicated Server
- Automatic version detection and JAR download from official APIs
- Local JAR library with bucket management

### 🔄 Version Management
- Version file tracking with automatic update checks
- Remote version comparison against Git repository
- In-app version display

### 📱 Responsive Design
- Dark-themed modern UI
- Sidebar server list with collapsible navigation
- Tabbed interface per server (Terminal, Logs, Files, Mods, Properties, Resource Pack, Players, Backups, Tasks, Messages)
- Profile modal with password change and MFA setup
- Mobile-friendly responsive layout
- First-run setup page with guided onboarding

### 👤 Player Management
- View and manage operator (ops) list with permission levels
- Whitelist management (add/remove players)
- Ban list management with reasons
- Player data viewer (inventory, stats from NBT)
- Mojang UUID lookup integration

## Requirements

- **Operating System**: Debian 13+ (recommended), Ubuntu 22.04+, or any modern Linux
- **Web Server**: Nginx (for production)
- **Runtime**: Python 3.10+
- **Java**: OpenJDK 17+ (for running Minecraft servers)

## Installation

### Automated Installation (Recommended)

1. Clone the repository:
```bash
git clone https://github.com/TwiStarSystems/MServer.git
cd MServer
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
- **Uninstall** - Remove MServer

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
- Set up the application in `/opt/mserver`
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
git clone https://github.com/TwiStarSystems/MServer.git
cd MServer
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

3. **Configure Nginx** (optional, for production):
```bash
sudo cp nginx.conf /etc/nginx/sites-available/mserver
sudo ln -s /etc/nginx/sites-available/mserver /etc/nginx/sites-enabled/
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

2. **Complete first-run setup** — on a fresh install you'll be guided to create the initial admin account

3. **Add a server** by clicking the "Add" button in the sidebar:
   - Enter a name for your server
   - Specify the server directory (or leave empty to create a new one)
   - Configure the JAR file name and Java arguments
   - Click "Save"

4. **Start your server** by selecting it and clicking "Start"

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
| `FLASK_ENV` | Set to `development` for debug mode and looser cookies | (unset) |

### Server Configuration

Each server stores its configuration in `config.json`:
```json
{
  "servers": {
    "abc12345": {
      "name": "Survival Server",
      "serverPath": "/opt/mserver/servers/abc12345",
      "executable": "server.jar",
      "javaArgs": "-Xmx4G -Xms2G",
      "autoStart": false,
      "created": "2025-01-14T10:00:00"
    }
  }
}
```

### External Backup Storage (Optional)

Configure via the Admin Settings panel to automatically upload backups to:
- **S3-compatible storage** (AWS S3, MinIO, Backblaze B2, etc.)
- **FTP/SFTP server**

Requires `boto3` for S3 support (not installed by default):
```bash
pip install boto3>=1.34.0
```

## Service Management

If installed via the installation script, MServer runs as a systemd service:

```bash
# Start the service
sudo systemctl start mserver

# Stop the service
sudo systemctl stop mserver

# Restart the service
sudo systemctl restart mserver

# Check service status
sudo systemctl status mserver

# View logs
sudo journalctl -u mserver -f
```

## Updating

### Update from Git Repository

To update an existing installation:

```bash
cd MServer
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

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/login` | Login with username/password |
| POST | `/api/auth/logout` | Logout current session |
| POST | `/api/auth/register` | Register new account |
| GET | `/api/auth/me` | Get current user info |
| POST | `/api/auth/password` | Change password |
| PUT | `/api/auth/profile/username` | Update username |
| PUT | `/api/auth/profile/name` | Update display name |
| PUT | `/api/auth/profile/email` | Update email |

### MFA
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/mfa/setup` | Begin MFA setup (returns QR code) |
| POST | `/api/auth/mfa/verify` | Verify MFA code to complete setup |
| POST | `/api/auth/mfa/disable` | Disable MFA |
| POST | `/api/auth/mfa/verify-login` | Verify MFA during login |

### Server Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/servers` | List all servers |
| POST | `/api/servers` | Create new server |
| POST | `/api/servers/import` | Import server from ZIP |
| GET | `/api/servers/<id>` | Get server details |
| PUT | `/api/servers/<id>` | Update server config |
| DELETE | `/api/servers/<id>` | Delete server |
| POST | `/api/servers/<id>/start` | Start server |
| POST | `/api/servers/<id>/stop` | Stop server gracefully |
| POST | `/api/servers/<id>/kill` | Force kill server process |
| POST | `/api/servers/<id>/command` | Send console command |
| GET | `/api/servers/<id>/output` | Get console output buffer |
| POST | `/api/servers/<id>/upload-jar` | Upload custom JAR file |
| POST | `/api/servers/<id>/download-jar` | Download JAR for server |
| GET | `/api/servers/<id>/eula` | Check EULA status |
| POST | `/api/servers/<id>/eula/accept` | Accept EULA |

### File Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/servers/<id>/files` | List files in directory |
| GET | `/api/servers/<id>/files/read` | Read file content |
| POST | `/api/servers/<id>/files/write` | Write file content |
| POST | `/api/servers/<id>/files/create` | Create file or folder |
| POST | `/api/servers/<id>/files/upload` | Upload file |
| GET | `/api/servers/<id>/files/download` | Download file |
| DELETE | `/api/servers/<id>/files/delete` | Delete file or folder |
| GET | `/api/servers/<id>/logs` | Get server log content |

### Mods & Plugins
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/servers/<id>/mods` | List mods and plugins |
| POST | `/api/servers/<id>/mods/upload` | Upload mod/plugin JAR |
| POST | `/api/servers/<id>/mods/<type>/<file>/enable` | Enable a mod |
| POST | `/api/servers/<id>/mods/<type>/<file>/disable` | Disable a mod |
| DELETE | `/api/servers/<id>/mods/<type>/<file>` | Delete a mod |

### NBT Editor
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/servers/<id>/nbt/read` | Read NBT file |
| POST | `/api/servers/<id>/nbt/write` | Write NBT file |
| POST | `/api/servers/<id>/nbt/update` | Update NBT tag |
| POST | `/api/servers/<id>/nbt/add` | Add NBT tag |
| POST | `/api/servers/<id>/nbt/delete` | Delete NBT tag |

### Player Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/servers/<id>/players/ops` | List operators |
| POST | `/api/servers/<id>/players/ops` | Add operator |
| PUT | `/api/servers/<id>/players/ops/<uuid>` | Update op level |
| DELETE | `/api/servers/<id>/players/ops/<uuid>` | Remove operator |
| GET | `/api/servers/<id>/players/whitelist` | List whitelist |
| POST | `/api/servers/<id>/players/whitelist` | Add to whitelist |
| DELETE | `/api/servers/<id>/players/whitelist/<uuid>` | Remove from whitelist |
| GET | `/api/servers/<id>/players/banned` | List bans |
| POST | `/api/servers/<id>/players/banned` | Ban player |
| DELETE | `/api/servers/<id>/players/banned/<uuid>` | Unban player |
| GET | `/api/servers/<id>/players/playerdata` | List player data files |

### Backups
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/servers/<id>/backups` | List backups |
| POST | `/api/servers/<id>/backups/create` | Create backup |
| GET | `/api/servers/<id>/backups/download` | Download backup |
| POST | `/api/servers/<id>/backups/restore` | Restore backup |
| DELETE | `/api/servers/<id>/backups/delete` | Delete backup |
| GET | `/api/servers/<id>/backups/schedule` | Get backup schedule |
| POST | `/api/servers/<id>/backups/schedule` | Set backup schedule |
| DELETE | `/api/servers/<id>/backups/schedule` | Remove backup schedule |

### Task Scheduler
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/servers/<id>/tasks` | List tasks |
| POST | `/api/servers/<id>/tasks` | Create task |
| GET | `/api/servers/<id>/tasks/<tid>` | Get task details |
| PUT | `/api/servers/<id>/tasks/<tid>` | Update task |
| DELETE | `/api/servers/<id>/tasks/<tid>` | Delete task |

### Server Messages
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/servers/<id>/messages` | List scheduled messages |
| POST | `/api/servers/<id>/messages` | Create scheduled message |
| PUT | `/api/servers/<id>/messages/<mid>` | Update message |
| DELETE | `/api/servers/<id>/messages/<mid>` | Delete message |
| POST | `/api/servers/<id>/messages/test` | Test-send a message now |

### Background Jobs
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/jobs` | List all jobs (with status filter) |
| GET | `/api/jobs/<id>` | Get job details and progress |
| POST | `/api/jobs/<id>/cancel` | Cancel a running job |
| DELETE | `/api/jobs/<id>` | Delete a completed job |
| GET | `/api/jobs/<id>/download` | Download job artifact |

### Admin
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/users` | List all users |
| POST | `/api/admin/users` | Create user |
| GET | `/api/admin/users/<id>` | Get user details |
| DELETE | `/api/admin/users/<id>` | Delete user |
| POST | `/api/admin/users/<id>/approve` | Approve user |
| PUT | `/api/admin/users/<id>/role` | Change role |
| POST | `/api/admin/users/<id>/password` | Reset password |
| DELETE | `/api/admin/users/<id>/mfa` | Reset user MFA |
| POST | `/api/admin/users/<id>/enable` | Enable account |

### Settings (Admin)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/settings/smtp` | Get SMTP configuration |
| PUT | `/api/settings/smtp` | Update SMTP configuration |
| POST | `/api/settings/smtp/test` | Send test email |
| GET | `/api/settings/webhook` | Get webhook configuration |
| PUT | `/api/settings/webhook` | Update webhook configuration |
| POST | `/api/settings/webhook/test` | Send test webhook |
| GET | `/api/settings/email-templates` | List email templates |
| PUT | `/api/settings/email-template/<name>` | Update email template |
| POST | `/api/settings/email-template/<name>/reset` | Reset template to default |

### Public API (v1) — API Key Auth
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/status` | Service status |
| GET | `/api/v1/servers` | List servers |
| GET | `/api/v1/servers/<id>` | Server details |
| GET | `/api/v1/servers/<id>/status` | Server status |
| POST | `/api/v1/servers/<id>/command` | Send command |
| POST | `/api/v1/servers/<id>/start` | Start server |
| POST | `/api/v1/servers/<id>/stop` | Stop server |
| POST | `/api/v1/servers/<id>/restart` | Restart server |
| GET | `/api/v1/docs` | API documentation |

## Security Considerations

- **Authentication**: Session-based with secure HTTP-only cookies and configurable SameSite policy
- **CSRF Protection**: All state-changing requests require a valid CSRF token
- **Password Policy**: Minimum 12 characters with uppercase, lowercase, and digit requirements for registration
- **MFA/2FA**: Optional TOTP-based multi-factor authentication with hashed recovery codes
- **Rate Limiting**: Configurable per-endpoint limits (login, uploads, backups, API)
- **Path Traversal Protection**: All file operations validated against server directories
- **Reverse Proxy**: Designed to run behind Nginx with ProxyFix for correct IP detection
- **API Keys**: Hashed storage with SHA-256, per-key permissions and expiration
- **Account Lockout**: Automatic disable after repeated failed login attempts
- **Anti-Lockout**: Emergency admin account auto-created when all admins are locked out
- **SSL/TLS**: Native support via `--ssl-cert` and `--ssl-key` arguments
- Set `SECRET_KEY` environment variable in production to persist sessions across restarts

## Troubleshooting

### Service won't start
```bash
# Check logs
sudo journalctl -u mserver -xe

# Verify Python is installed
python3 --version

# Check if port 3000 is available
sudo netstat -tlnp | grep 3000

# Test manually
cd /opt/mserver
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
MServer/
├── server.py                 # Main Python/Flask backend (API, WebSocket, managers)
├── db.py                     # SQLite database layer (schema, connections, queries)
├── api_manager.py            # Public API v1 blueprint (key auth endpoints)
├── requirements.txt          # Python dependencies
├── version                   # Application version file
├── nginx.conf                # Nginx reverse proxy configuration
├── install.sh                # Interactive installation script
├── git-release.sh            # Git release/versioning helper
├── msc.db                    # SQLite database (users, servers, jobs, stats — generated)
├── config.json               # Server configurations (generated)
├── configs/
│   └── jarurls.conf          # JAR download URL configuration
├── public/                   # Frontend files
│   ├── index.html            # Main dashboard page
│   ├── login.html            # Login/registration page
│   ├── setup.html            # First-run setup wizard
│   ├── settings.html         # Admin settings panel
│   ├── public.html           # Public server status page
│   ├── app.js                # Dashboard frontend logic
│   ├── setup.js              # First-run setup logic
│   ├── settings.js           # Settings panel logic
│   ├── login.js              # Login/registration logic
│   ├── public.js             # Public page logic
│   ├── utils.js              # Shared utility functions
│   ├── styles.css            # Application styles
│   ├── favicons/             # Uploaded favicon files
│   └── resourcepacks/        # Hosted resource packs
├── docs/                     # Documentation
├── servers/                  # Minecraft server files (per-server subdirectories)
├── serverexecutables/        # Downloaded server JARs (by type)
├── backups/                  # Server backups (per-server subdirectories)
├── tools/                    # Admin-uploaded Python tools
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

MServer is open source under a permissive, MIT-style license: you may use, copy,
modify, distribute, sublicense, and sell it, provided the copyright and permission
notice are retained. See [LICENSE](LICENSE) for the full text.

## Support

For issues, questions, or suggestions, please open an issue on GitHub:
https://github.com/TwiStarSystems/MServer/issues
