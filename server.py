#!/usr/bin/env python3
"""
MServerController - A web-based Minecraft server controller and manager
Python/Flask implementation with multi-server support
"""

import os
import json
import shutil
import zipfile
import subprocess
import threading
import uuid
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_socketio import SocketIO, emit
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename

# Initialize Flask app
app = Flask(__name__, static_folder='public', static_url_path='')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'mservercontroller-secret-key')
socketio = SocketIO(app, cors_allowed_origins="*")

# Rate limiting
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["100 per 15 minutes"],
    storage_uri="memory://"
)

# Configuration
PORT = int(os.environ.get('PORT', 3000))
BASE_DIR = Path(__file__).parent.absolute()
SERVERS_DIR = BASE_DIR / 'servers'
BACKUPS_DIR = BASE_DIR / 'backups'
UPLOADS_DIR = BASE_DIR / 'uploads'
CONFIG_PATH = BASE_DIR / 'config.json'

# Ensure directories exist
for directory in [SERVERS_DIR, BACKUPS_DIR, UPLOADS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# Multi-server state management
class ServerManager:
    """Manages multiple Minecraft server instances"""
    
    def __init__(self):
        self.servers = {}  # server_id -> ServerInstance
        self.config = self._load_config()
        self.lock = threading.Lock()
    
    def _load_config(self):
        """Load configuration from file"""
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
        return {'servers': {}}
    
    def _save_config(self):
        """Save configuration to file"""
        with open(CONFIG_PATH, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def get_servers_list(self):
        """Get list of all configured servers with their status"""
        servers = []
        for server_id, server_config in self.config.get('servers', {}).items():
            instance = self.servers.get(server_id)
            is_running = instance is not None and instance.is_running()
            servers.append({
                'id': server_id,
                'name': server_config.get('name', 'Unnamed Server'),
                'serverPath': server_config.get('serverPath', ''),
                'executable': server_config.get('executable', 'server.jar'),
                'javaArgs': server_config.get('javaArgs', '-Xmx2G -Xms1G'),
                'autoStart': server_config.get('autoStart', False),
                'running': is_running
            })
        return servers
    
    def get_server_config(self, server_id):
        """Get configuration for a specific server"""
        return self.config.get('servers', {}).get(server_id)
    
    def create_server(self, name, server_path, executable='server.jar', java_args='-Xmx2G -Xms1G'):
        """Create a new server configuration"""
        server_id = str(uuid.uuid4())[:8]
        
        if 'servers' not in self.config:
            self.config['servers'] = {}
        
        self.config['servers'][server_id] = {
            'name': name,
            'serverPath': server_path,
            'executable': executable,
            'javaArgs': java_args,
            'autoStart': False,
            'created': datetime.now().isoformat()
        }
        
        # Create server directory if it doesn't exist
        server_dir = Path(server_path) if server_path else SERVERS_DIR / server_id
        server_dir.mkdir(parents=True, exist_ok=True)
        
        if not server_path:
            self.config['servers'][server_id]['serverPath'] = str(server_dir)
        
        self._save_config()
        return server_id
    
    def update_server(self, server_id, **kwargs):
        """Update server configuration"""
        if server_id not in self.config.get('servers', {}):
            return False
        
        self.config['servers'][server_id].update(kwargs)
        self._save_config()
        return True
    
    def delete_server(self, server_id):
        """Delete a server configuration (does not delete files)"""
        if server_id in self.servers:
            self.stop_server(server_id)
        
        if server_id in self.config.get('servers', {}):
            del self.config['servers'][server_id]
            self._save_config()
            return True
        return False
    
    def start_server(self, server_id):
        """Start a Minecraft server"""
        with self.lock:
            if server_id in self.servers and self.servers[server_id].is_running():
                return False, "Server is already running"
            
            server_config = self.get_server_config(server_id)
            if not server_config:
                return False, "Server configuration not found"
            
            server_path = Path(server_config.get('serverPath', ''))
            executable = server_config.get('executable', 'server.jar')
            java_args = server_config.get('javaArgs', '-Xmx2G -Xms1G')
            
            if not server_path.exists():
                return False, "Server path does not exist"
            
            executable_path = server_path / executable
            if not executable_path.exists():
                return False, f"Server executable '{executable}' not found"
            
            try:
                instance = ServerInstance(server_id, server_path, executable, java_args)
                instance.start()
                self.servers[server_id] = instance
                return True, "Server started"
            except Exception as e:
                return False, str(e)
    
    def stop_server(self, server_id):
        """Stop a Minecraft server"""
        with self.lock:
            if server_id not in self.servers:
                return False, "Server is not running"
            
            instance = self.servers[server_id]
            if not instance.is_running():
                del self.servers[server_id]
                return False, "Server is not running"
            
            instance.stop()
            return True, "Server stopping..."
    
    def send_command(self, server_id, command):
        """Send a command to a running server"""
        if server_id not in self.servers:
            return False, "Server is not running"
        
        instance = self.servers[server_id]
        if not instance.is_running():
            return False, "Server is not running"
        
        instance.send_command(command)
        return True, "Command sent"
    
    def get_server_path(self, server_id):
        """Get the path for a specific server"""
        server_config = self.get_server_config(server_id)
        if server_config:
            return Path(server_config.get('serverPath', SERVERS_DIR))
        return SERVERS_DIR


class ServerInstance:
    """Represents a running Minecraft server instance"""
    
    def __init__(self, server_id, server_path, executable, java_args):
        self.server_id = server_id
        self.server_path = Path(server_path)
        self.executable = executable
        self.java_args = java_args
        self.process = None
        self.output_buffer = []
        self.max_buffer_size = 1000
    
    def start(self):
        """Start the server process"""
        args = ['java'] + self.java_args.split() + ['-jar', self.executable, 'nogui']
        
        self.process = subprocess.Popen(
            args,
            cwd=str(self.server_path),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        
        # Start output reader threads
        threading.Thread(target=self._read_output, args=('stdout',), daemon=True).start()
        threading.Thread(target=self._read_output, args=('stderr',), daemon=True).start()
        threading.Thread(target=self._monitor_process, daemon=True).start()
    
    def _read_output(self, stream_type):
        """Read output from the process and broadcast to clients"""
        stream = self.process.stdout if stream_type == 'stdout' else self.process.stderr
        try:
            for line in iter(stream.readline, ''):
                if line:
                    msg_type = 'output' if stream_type == 'stdout' else 'error'
                    self._broadcast({'type': msg_type, 'data': line, 'serverId': self.server_id})
                    self._add_to_buffer(line)
                if self.process.poll() is not None:
                    break
        except Exception as e:
            self._broadcast({'type': 'error', 'data': f'Stream error: {str(e)}\n', 'serverId': self.server_id})
    
    def _monitor_process(self):
        """Monitor the process and notify when it exits"""
        if self.process:
            self.process.wait()
            code = self.process.returncode
            self._broadcast({'type': 'info', 'data': f'Server stopped with code {code}\n', 'serverId': self.server_id})
            self._broadcast({'type': 'status', 'serverId': self.server_id, 'running': False})
    
    def _broadcast(self, data):
        """Broadcast message to all clients"""
        socketio.emit('message', data, namespace='/')
    
    def _add_to_buffer(self, line):
        """Add line to output buffer"""
        self.output_buffer.append(line)
        if len(self.output_buffer) > self.max_buffer_size:
            self.output_buffer.pop(0)
    
    def is_running(self):
        """Check if the server is running"""
        return self.process is not None and self.process.poll() is None
    
    def send_command(self, command):
        """Send a command to the server"""
        if self.is_running():
            self.process.stdin.write(command + '\n')
            self.process.stdin.flush()
    
    def stop(self):
        """Stop the server gracefully"""
        if self.is_running():
            self.send_command('stop')
            
            def force_kill():
                time.sleep(15)
                if self.is_running():
                    self.process.kill()
            
            threading.Thread(target=force_kill, daemon=True).start()
    
    def get_recent_output(self, lines=100):
        """Get recent output from the buffer"""
        return self.output_buffer[-lines:]


# Initialize server manager
server_manager = ServerManager()


def is_safe_path(base_path, requested_path):
    """Check if the requested path is within the base path (prevent directory traversal)"""
    try:
        base = Path(base_path).resolve()
        full = (base / requested_path).resolve()
        return str(full).startswith(str(base))
    except Exception:
        return False


# Serve static files
@app.route('/')
def index():
    return send_from_directory('public', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('public', path)


# ==================== Server Management API ====================

@app.route('/api/servers', methods=['GET'])
def get_servers():
    """Get list of all servers"""
    return jsonify({'servers': server_manager.get_servers_list()})

@app.route('/api/servers', methods=['POST'])
def create_server():
    """Create a new server"""
    data = request.get_json()
    name = data.get('name', 'New Server')
    server_path = data.get('serverPath', '')
    executable = data.get('executable', 'server.jar')
    java_args = data.get('javaArgs', '-Xmx2G -Xms1G')
    
    server_id = server_manager.create_server(name, server_path, executable, java_args)
    return jsonify({'success': True, 'serverId': server_id})

@app.route('/api/servers/<server_id>', methods=['GET'])
def get_server(server_id):
    """Get a specific server's configuration"""
    config = server_manager.get_server_config(server_id)
    if not config:
        return jsonify({'error': 'Server not found'}), 404
    
    instance = server_manager.servers.get(server_id)
    is_running = instance is not None and instance.is_running()
    
    return jsonify({
        'id': server_id,
        'running': is_running,
        **config
    })

@app.route('/api/servers/<server_id>', methods=['PUT'])
def update_server(server_id):
    """Update a server's configuration"""
    data = request.get_json()
    
    # Don't allow updating certain fields
    data.pop('id', None)
    data.pop('created', None)
    
    if server_manager.update_server(server_id, **data):
        return jsonify({'success': True})
    return jsonify({'error': 'Server not found'}), 404

@app.route('/api/servers/<server_id>', methods=['DELETE'])
def delete_server(server_id):
    """Delete a server configuration"""
    if server_manager.delete_server(server_id):
        return jsonify({'success': True})
    return jsonify({'error': 'Server not found'}), 404

@app.route('/api/servers/<server_id>/start', methods=['POST'])
def start_server(server_id):
    """Start a server"""
    success, message = server_manager.start_server(server_id)
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 400

@app.route('/api/servers/<server_id>/stop', methods=['POST'])
def stop_server(server_id):
    """Stop a server"""
    success, message = server_manager.stop_server(server_id)
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 400

@app.route('/api/servers/<server_id>/command', methods=['POST'])
def send_command(server_id):
    """Send a command to a server"""
    data = request.get_json()
    command = data.get('command', '')
    
    success, message = server_manager.send_command(server_id, command)
    if success:
        return jsonify({'success': True})
    return jsonify({'error': message}), 400

@app.route('/api/servers/<server_id>/output', methods=['GET'])
def get_server_output(server_id):
    """Get recent output from a server"""
    instance = server_manager.servers.get(server_id)
    if not instance:
        return jsonify({'output': []})
    
    lines = request.args.get('lines', 100, type=int)
    return jsonify({'output': instance.get_recent_output(lines)})


# ==================== File Explorer API ====================

@app.route('/api/servers/<server_id>/files', methods=['GET'])
def list_files(server_id):
    """List files in a server's directory"""
    requested_path = request.args.get('path', '')
    server_path = server_manager.get_server_path(server_id)
    
    if not is_safe_path(server_path, requested_path):
        return jsonify({'error': 'Access denied'}), 403
    
    full_path = server_path / requested_path
    
    if not full_path.exists():
        return jsonify({'error': 'Path not found'}), 404
    
    if full_path.is_file():
        return jsonify({'isFile': True, 'path': requested_path})
    
    files = []
    try:
        for item in full_path.iterdir():
            stat = item.stat()
            files.append({
                'name': item.name,
                'isDirectory': item.is_dir(),
                'size': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
    except PermissionError:
        return jsonify({'error': 'Permission denied'}), 403
    
    return jsonify({'files': files, 'currentPath': requested_path})

@app.route('/api/servers/<server_id>/files/read', methods=['GET'])
def read_file(server_id):
    """Read file content"""
    requested_path = request.args.get('path', '')
    server_path = server_manager.get_server_path(server_id)
    
    if not is_safe_path(server_path, requested_path):
        return jsonify({'error': 'Access denied'}), 403
    
    full_path = server_path / requested_path
    
    if not full_path.exists():
        return jsonify({'error': 'File not found'}), 404
    
    try:
        content = full_path.read_text(encoding='utf-8')
        return jsonify({'content': content})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/files/write', methods=['POST'])
def write_file(server_id):
    """Write file content"""
    data = request.get_json()
    file_path = data.get('path', '')
    content = data.get('content', '')
    server_path = server_manager.get_server_path(server_id)
    
    if not is_safe_path(server_path, file_path):
        return jsonify({'error': 'Access denied'}), 403
    
    full_path = server_path / file_path
    
    try:
        full_path.write_text(content, encoding='utf-8')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/files/create', methods=['POST'])
def create_file(server_id):
    """Create file or directory"""
    data = request.get_json()
    file_path = data.get('path', '')
    file_type = data.get('type', 'file')
    server_path = server_manager.get_server_path(server_id)
    
    if not is_safe_path(server_path, file_path):
        return jsonify({'error': 'Access denied'}), 403
    
    full_path = server_path / file_path
    
    try:
        if file_type == 'directory':
            full_path.mkdir(parents=True, exist_ok=True)
        else:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.touch()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/files/delete', methods=['DELETE'])
def delete_file(server_id):
    """Delete file or directory"""
    data = request.get_json()
    file_path = data.get('path', '')
    server_path = server_manager.get_server_path(server_id)
    
    if not is_safe_path(server_path, file_path):
        return jsonify({'error': 'Access denied'}), 403
    
    full_path = server_path / file_path
    
    if not full_path.exists():
        return jsonify({'error': 'File not found'}), 404
    
    try:
        if full_path.is_dir():
            shutil.rmtree(full_path)
        else:
            full_path.unlink()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/files/download', methods=['GET'])
def download_file(server_id):
    """Download a file"""
    requested_path = request.args.get('path', '')
    server_path = server_manager.get_server_path(server_id)
    
    if not is_safe_path(server_path, requested_path):
        return jsonify({'error': 'Access denied'}), 403
    
    full_path = server_path / requested_path
    
    if not full_path.exists():
        return jsonify({'error': 'File not found'}), 404
    
    return send_file(full_path, as_attachment=True)

@app.route('/api/servers/<server_id>/files/upload', methods=['POST'])
@limiter.limit("10 per 15 minutes")
def upload_file(server_id):
    """Upload a file"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    target_path = request.form.get('path', '')
    server_path = server_manager.get_server_path(server_id)
    
    if not is_safe_path(server_path, target_path):
        return jsonify({'error': 'Access denied'}), 403
    
    filename = secure_filename(file.filename)
    dest_dir = server_path / target_path
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename
    
    try:
        file.save(str(dest_path))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== Backup API ====================

@app.route('/api/servers/<server_id>/backups', methods=['GET'])
def list_backups(server_id):
    """List backups for a server"""
    backup_dir = BACKUPS_DIR / server_id
    
    if not backup_dir.exists():
        return jsonify({'backups': []})
    
    backups = []
    for item in backup_dir.iterdir():
        if item.suffix == '.zip':
            stat = item.stat()
            backups.append({
                'name': item.name,
                'size': stat.st_size,
                'created': datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
    
    backups.sort(key=lambda x: x['created'], reverse=True)
    return jsonify({'backups': backups})

@app.route('/api/servers/<server_id>/backups/create', methods=['POST'])
@limiter.limit("5 per 15 minutes")
def create_backup(server_id):
    """Create a backup for a server"""
    server_path = server_manager.get_server_path(server_id)
    
    if not server_path.exists():
        return jsonify({'error': 'Server path not found'}), 400
    
    # Create backup directory for this server
    backup_dir = BACKUPS_DIR / server_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y-%m-%dT%H-%M-%S')
    backup_name = f'backup-{timestamp}.zip'
    backup_path = backup_dir / backup_name
    
    try:
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(server_path):
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(server_path)
                    zipf.write(file_path, arcname)
        
        size = backup_path.stat().st_size
        return jsonify({'success': True, 'backup': backup_name, 'size': size})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/backups/download', methods=['GET'])
def download_backup(server_id):
    """Download a backup"""
    backup_name = request.args.get('name', '')
    backup_path = BACKUPS_DIR / server_id / backup_name
    
    if not backup_path.exists():
        return jsonify({'error': 'Backup not found'}), 404
    
    return send_file(backup_path, as_attachment=True)

@app.route('/api/servers/<server_id>/backups/delete', methods=['DELETE'])
def delete_backup(server_id):
    """Delete a backup"""
    data = request.get_json()
    backup_name = data.get('name', '')
    backup_path = BACKUPS_DIR / server_id / backup_name
    
    if not backup_path.exists():
        return jsonify({'error': 'Backup not found'}), 404
    
    try:
        backup_path.unlink()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/backups/restore', methods=['POST'])
def restore_backup(server_id):
    """Restore a backup"""
    data = request.get_json()
    backup_name = data.get('name', '')
    backup_path = BACKUPS_DIR / server_id / backup_name
    
    if not backup_path.exists():
        return jsonify({'error': 'Backup not found'}), 404
    
    # Check if server is running
    instance = server_manager.servers.get(server_id)
    if instance and instance.is_running():
        return jsonify({'error': 'Stop the server before restoring a backup'}), 400
    
    server_path = server_manager.get_server_path(server_id)
    
    try:
        # Clear server directory (except the backup)
        for item in server_path.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        
        # Extract backup
        with zipfile.ZipFile(backup_path, 'r') as zipf:
            zipf.extractall(server_path)
        
        return jsonify({'success': True, 'message': 'Backup restored successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== WebSocket Events ====================

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    print('Client connected to WebSocket')

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    print('Client disconnected from WebSocket')

@socketio.on('command')
def handle_command(data):
    """Handle command from client"""
    server_id = data.get('serverId')
    command = data.get('command', '')
    
    if server_id:
        success, message = server_manager.send_command(server_id, command)
        if not success:
            emit('message', {'type': 'error', 'data': f'{message}\n', 'serverId': server_id})

@socketio.on('subscribe')
def handle_subscribe(data):
    """Subscribe to a server's output"""
    server_id = data.get('serverId')
    if server_id:
        instance = server_manager.servers.get(server_id)
        if instance:
            # Send recent output to the client
            for line in instance.get_recent_output():
                emit('message', {'type': 'output', 'data': line, 'serverId': server_id})


if __name__ == '__main__':
    print(f'MServerController running on http://localhost:{PORT}')
    socketio.run(app, host='0.0.0.0', port=PORT, debug=False, allow_unsafe_werkzeug=True)
