# MServerController
A Web-Based Minecraft Server Manager

MServerController is a modern, user-friendly web application for creating, running, and managing Minecraft servers. Built with Node.js and Express, it provides a clean interface for server administration with real-time monitoring, file management, and automated backups.

## Features

### 🖥️ Terminal View
- Real-time server console output via WebSocket
- Live command execution
- Color-coded output for easy reading
- Command history and input

### 📁 File Explorer
- Browse server files and directories
- Create, edit, and delete files
- Upload files to the server
- Download files and directories
- Syntax-highlighted text editor

### 💾 Backup System
- One-click backup creation
- Automatic ZIP compression
- Download backups to your local machine
- Manage and delete old backups
- Full server state preservation

### ⚙️ Server Configuration
- Configure server executable path
- Set Java memory allocation
- Customize JVM arguments
- Change server directory
- Easy-to-use web interface

## Requirements

- **Operating System**: Debian 13 or newer
- **Web Server**: Nginx
- **Runtime**: Node.js LTS (18+)
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

The script will:
- Install all required dependencies (Node.js, Nginx, Java)
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

1. **Install dependencies**:
```bash
sudo apt-get update
sudo apt-get install -y nodejs npm nginx openjdk-17-jre-headless
```

2. **Clone and setup**:
```bash
git clone https://github.com/TwiStarSystems/MServerController.git
cd MServerController
npm install
```

3. **Configure Nginx**:
```bash
sudo cp nginx.conf /etc/nginx/sites-available/mservercontroller
sudo ln -s /etc/nginx/sites-available/mservercontroller /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

4. **Start the application**:
```bash
node server.js
```

## Usage

### Initial Setup

1. **Access the web interface** at `http://your-server-ip`

2. **Configure your server** in the Configuration tab:
   - Set the server directory path (where your Minecraft server files are)
   - Specify the server JAR file name (e.g., `server.jar`)
   - Configure Java memory settings (e.g., `-Xmx2G -Xms1G`)
   - Click "Save Configuration"

3. **Start your server** from the Terminal tab

### Managing Your Server

#### Terminal View
- Click the "Start Server" button to launch your Minecraft server
- Watch real-time console output
- Execute commands by typing in the input field and pressing Enter
- Click "Stop Server" to gracefully shut down

#### File Explorer
- Browse your server files
- Click on a file to edit its contents
- Use the action buttons to:
  - **New File**: Create a new file
  - **New Folder**: Create a new directory
  - **Upload**: Upload files from your computer
  - **Download**: Download individual files
  - **Delete**: Remove files or folders

#### Backups
- Click "Create Backup" to create a ZIP archive of your entire server
- Download backups to your local machine
- Delete old backups to save space
- Backups are stored in the `backups/` directory

## Configuration

### Environment Variables

You can customize the application using environment variables:

- `PORT`: HTTP port (default: 3000)
- `NODE_ENV`: Environment mode (production/development)

### Config File

The application stores its configuration in `config.json`:
```json
{
  "serverPath": "/path/to/minecraft/server",
  "executable": "server.jar",
  "javaArgs": "-Xmx2G -Xms1G"
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

## Security Considerations

- The application runs on localhost by default and should be accessed through Nginx
- File operations are restricted to the configured server directory
- Path traversal attacks are prevented
- Consider setting up SSL/TLS certificates for production use
- Implement firewall rules to restrict access to the web interface
- Change default ports if needed
- Regular backups are recommended

## Troubleshooting

### Service won't start
```bash
# Check logs
sudo journalctl -u mservercontroller -xe

# Verify Node.js is installed
node --version

# Check if port 3000 is available
sudo netstat -tlnp | grep 3000
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
- Check that the server JAR path is correct in Configuration
- Ensure the server directory has proper permissions
- Review the terminal output for error messages

## Directory Structure

```
MServerController/
├── server.js           # Main Node.js server
├── package.json        # Node.js dependencies
├── nginx.conf          # Nginx configuration
├── install.sh          # Installation script
├── public/             # Frontend files
│   ├── index.html      # Main HTML page
│   ├── styles.css      # Styles
│   └── app.js          # Frontend JavaScript
├── servers/            # Minecraft server files (default)
├── backups/            # Server backups
└── uploads/            # Temporary upload directory
```

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## License

MIT License - see LICENSE file for details

## Support

For issues, questions, or suggestions, please open an issue on GitHub:
https://github.com/TwiStarSystems/MServerController/issues
