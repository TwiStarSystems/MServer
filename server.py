#!/usr/bin/env python3
"""
MServerController - A web-based Minecraft server controller and manager
Python/Flask implementation with multi-server support and RBAC
"""

import os
import json
import shutil
import zipfile
import subprocess
import threading
import uuid
import time
import requests
import hashlib
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory, send_file, session, redirect, url_for
from flask_socketio import SocketIO, emit
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# Initialize Flask app
app = Flask(__name__, static_folder='public', static_url_path='')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
socketio = SocketIO(app, cors_allowed_origins="*", manage_session=False)

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
USERS_PATH = BASE_DIR / 'users.json'
JAR_URLS_PATH = BASE_DIR / 'configs' / 'jarurls.conf'

# Ensure directories exist
for directory in [SERVERS_DIR, BACKUPS_DIR, UPLOADS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)


# ==================== User Management & RBAC ====================

class UserManager:
    """Manages users, authentication, and role-based access control"""
    
    ROLES = {
        'public': 0,   # Can only see server status
        'user': 1,     # Can manage own servers
        'admin': 2     # Full access
    }
    
    def __init__(self):
        self.users = self._load_users()
        self.lock = threading.Lock()
        self._ensure_admin_exists()
    
    def _load_users(self):
        """Load users from file"""
        if USERS_PATH.exists():
            with open(USERS_PATH, 'r') as f:
                return json.load(f)
        return {'users': {}}
    
    def _save_users(self):
        """Save users to file"""
        with open(USERS_PATH, 'w') as f:
            json.dump(self.users, f, indent=2)
    
    def _ensure_admin_exists(self):
        """Create default admin if no users exist"""
        if not self.users.get('users'):
            self.users['users'] = {}
            # Create default admin account
            admin_id = str(uuid.uuid4())[:8]
            self.users['users'][admin_id] = {
                'username': 'admin',
                'password': generate_password_hash('admin'),
                'role': 'admin',
                'approved': True,
                'created': datetime.now().isoformat(),
                'lastLogin': None
            }
            self._save_users()
            print("Default admin created - Username: admin, Password: admin")
            print("WARNING: Change the default password immediately!")
    
    def authenticate(self, username, password):
        """Authenticate a user and return user data if successful"""
        for user_id, user in self.users.get('users', {}).items():
            if user['username'].lower() == username.lower():
                if check_password_hash(user['password'], password):
                    if not user.get('approved', False) and user['role'] != 'admin':
                        return None, "Account pending approval"
                    # Update last login
                    user['lastLogin'] = datetime.now().isoformat()
                    self._save_users()
                    return user_id, user
                return None, "Invalid password"
        return None, "User not found"
    
    def register(self, username, password):
        """Register a new user (pending approval)"""
        with self.lock:
            # Check if username exists
            for user in self.users.get('users', {}).values():
                if user['username'].lower() == username.lower():
                    return None, "Username already exists"
            
            # Validate username
            if len(username) < 3 or len(username) > 32:
                return None, "Username must be 3-32 characters"
            if not username.replace('_', '').replace('-', '').isalnum():
                return None, "Username can only contain letters, numbers, underscores, and hyphens"
            
            # Validate password
            if len(password) < 6:
                return None, "Password must be at least 6 characters"
            
            user_id = str(uuid.uuid4())[:8]
            self.users['users'][user_id] = {
                'username': username,
                'password': generate_password_hash(password),
                'role': 'user',
                'approved': False,  # Requires admin approval
                'created': datetime.now().isoformat(),
                'lastLogin': None
            }
            self._save_users()
            return user_id, "Registration successful. Please wait for admin approval."
    
    def get_user(self, user_id):
        """Get user by ID"""
        return self.users.get('users', {}).get(user_id)
    
    def get_user_by_username(self, username):
        """Get user by username"""
        for user_id, user in self.users.get('users', {}).items():
            if user['username'].lower() == username.lower():
                return user_id, user
        return None, None
    
    def get_all_users(self):
        """Get all users (for admin panel)"""
        users = []
        for user_id, user in self.users.get('users', {}).items():
            users.append({
                'id': user_id,
                'username': user['username'],
                'role': user['role'],
                'approved': user.get('approved', False),
                'created': user.get('created'),
                'lastLogin': user.get('lastLogin')
            })
        return users
    
    def approve_user(self, user_id):
        """Approve a pending user"""
        with self.lock:
            if user_id in self.users.get('users', {}):
                self.users['users'][user_id]['approved'] = True
                self._save_users()
                return True
        return False
    
    def update_user_role(self, user_id, role):
        """Update user role"""
        if role not in self.ROLES:
            return False
        with self.lock:
            if user_id in self.users.get('users', {}):
                self.users['users'][user_id]['role'] = role
                self._save_users()
                return True
        return False
    
    def delete_user(self, user_id):
        """Delete a user"""
        with self.lock:
            if user_id in self.users.get('users', {}):
                del self.users['users'][user_id]
                self._save_users()
                return True
        return False
    
    def change_password(self, user_id, old_password, new_password):
        """Change user password"""
        with self.lock:
            user = self.users.get('users', {}).get(user_id)
            if not user:
                return False, "User not found"
            
            if not check_password_hash(user['password'], old_password):
                return False, "Current password is incorrect"
            
            if len(new_password) < 6:
                return False, "New password must be at least 6 characters"
            
            self.users['users'][user_id]['password'] = generate_password_hash(new_password)
            self._save_users()
            return True, "Password changed successfully"
    
    def reset_password(self, user_id, new_password):
        """Admin reset user password"""
        with self.lock:
            if user_id not in self.users.get('users', {}):
                return False
            if len(new_password) < 6:
                return False
            self.users['users'][user_id]['password'] = generate_password_hash(new_password)
            self._save_users()
            return True
    
    def get_role_level(self, role):
        """Get numeric role level"""
        return self.ROLES.get(role, 0)


# Initialize user manager
user_manager = UserManager()


# ==================== Authentication Decorators ====================

def get_current_user():
    """Get the currently logged in user from session"""
    user_id = session.get('user_id')
    if user_id:
        user = user_manager.get_user(user_id)
        if user and user.get('approved', False):
            return user_id, user
    return None, None

def login_required(f):
    """Decorator to require login for a route"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id, user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required', 'code': 'AUTH_REQUIRED'}), 401
        return f(*args, **kwargs)
    return decorated_function

def role_required(min_role):
    """Decorator to require a minimum role level"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_id, user = get_current_user()
            if not user:
                return jsonify({'error': 'Authentication required', 'code': 'AUTH_REQUIRED'}), 401
            
            user_role_level = user_manager.get_role_level(user.get('role', 'public'))
            required_level = user_manager.get_role_level(min_role)
            
            if user_role_level < required_level:
                return jsonify({'error': 'Insufficient permissions', 'code': 'FORBIDDEN'}), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def admin_required(f):
    """Decorator to require admin role"""
    return role_required('admin')(f)

def can_access_server(server_id):
    """Check if current user can access a specific server"""
    user_id, user = get_current_user()
    if not user:
        return False
    
    # Admins can access all servers
    if user.get('role') == 'admin':
        return True
    
    # Users can only access their own servers
    server_config = server_manager.get_server_config(server_id)
    if server_config and server_config.get('owner') == user_id:
        return True
    
    return False

def server_access_required(f):
    """Decorator to require access to a specific server"""
    @wraps(f)
    def decorated_function(server_id, *args, **kwargs):
        user_id, user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required', 'code': 'AUTH_REQUIRED'}), 401
        
        if not can_access_server(server_id):
            return jsonify({'error': 'Access denied to this server', 'code': 'FORBIDDEN'}), 403
        
        return f(server_id, *args, **kwargs)
    return decorated_function


# ==================== JAR/Version Manager ====================

class JarVersionManager:
    """Manager for Minecraft server JAR files and versions"""
    
    SERVER_TYPES = {
        'vanilla': {'name': 'Vanilla', 'description': 'Official Minecraft server', 'modded': False},
        'paper': {'name': 'Paper', 'description': 'High-performance Spigot fork', 'modded': False},
        'purpur': {'name': 'Purpur', 'description': 'Paper fork with extra features', 'modded': False},
        'bungeecord': {'name': 'BungeeCord', 'description': 'Proxy server for multi-server networks', 'modded': True},
        'forge': {'name': 'Forge', 'description': 'Mod loader for Minecraft mods', 'modded': True},
        'neoforge': {'name': 'NeoForge', 'description': 'Modern Forge fork with improved features', 'modded': True}
    }
    
    def __init__(self):
        self.jar_urls = self._load_jar_urls()
    
    def _load_jar_urls(self):
        """Load JAR URLs from config file"""
        urls = {}
        if JAR_URLS_PATH.exists():
            with open(JAR_URLS_PATH, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, url = line.split('=', 1)
                        if ':' in key:
                            server_type, version = key.split(':', 1)
                            if server_type not in urls:
                                urls[server_type] = {}
                            urls[server_type][version] = url
        return urls
    
    def get_server_types(self):
        """Get list of available server types"""
        return [
            {
                'id': type_id,
                'name': info['name'],
                'description': info['description'],
                'modded': info['modded']
            }
            for type_id, info in self.SERVER_TYPES.items()
        ]
    
    def get_versions(self, server_type):
        """Get available versions for a server type"""
        versions = []
        if server_type in self.jar_urls:
            for version in self.jar_urls[server_type].keys():
                versions.append(version)
        return sorted(versions, key=lambda v: [int(x) if x.isdigit() else x for x in v.replace('-', '.').split('.')], reverse=True)
    
    def _get_paper_download_url(self, version):
        """Get Paper download URL from API"""
        try:
            # Get latest build for version
            api_url = f"https://api.papermc.io/v2/projects/paper/versions/{version}"
            response = requests.get(api_url, timeout=10)
            if response.status_code != 200:
                return None
            
            data = response.json()
            builds = data.get('builds', [])
            if not builds:
                return None
            
            latest_build = max(builds)
            
            # Get download URL for latest build
            build_url = f"https://api.papermc.io/v2/projects/paper/versions/{version}/builds/{latest_build}"
            build_response = requests.get(build_url, timeout=10)
            if build_response.status_code != 200:
                return None
            
            build_data = build_response.json()
            downloads = build_data.get('downloads', {})
            application = downloads.get('application', {})
            jar_name = application.get('name')
            
            if jar_name:
                return f"https://api.papermc.io/v2/projects/paper/versions/{version}/builds/{latest_build}/downloads/{jar_name}"
            return None
        except Exception as e:
            print(f"Error fetching Paper URL: {e}")
            return None
    
    def _get_purpur_download_url(self, version):
        """Get Purpur download URL from API"""
        try:
            # Get latest build for version
            api_url = f"https://api.purpurmc.org/v2/purpur/{version}"
            response = requests.get(api_url, timeout=10)
            if response.status_code != 200:
                return None
            
            data = response.json()
            builds = data.get('builds', {})
            latest = builds.get('latest')
            
            if latest:
                return f"https://api.purpurmc.org/v2/purpur/{version}/{latest}/download"
            return None
        except Exception as e:
            print(f"Error fetching Purpur URL: {e}")
            return None
    
    def get_download_url(self, server_type, version):
        """Get download URL for a specific server type and version"""
        if server_type not in self.jar_urls:
            return None
        
        if version not in self.jar_urls[server_type]:
            return None
        
        url = self.jar_urls[server_type][version]
        
        # Handle API-based downloads
        if url == 'API':
            if server_type == 'paper':
                return self._get_paper_download_url(version)
            elif server_type == 'purpur':
                return self._get_purpur_download_url(version)
        
        return url
    
    def download_jar(self, server_type, version, dest_path, progress_callback=None):
        """Download a server JAR file"""
        url = self.get_download_url(server_type, version)
        if not url:
            return False, "Download URL not found"
        
        try:
            response = requests.get(url, stream=True, timeout=300)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            dest_path = Path(dest_path)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(dest_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size:
                            progress_callback(downloaded, total_size)
            
            return True, str(dest_path)
        except requests.RequestException as e:
            return False, f"Download failed: {str(e)}"
        except Exception as e:
            return False, f"Error: {str(e)}"


# Initialize JAR manager
jar_manager = JarVersionManager()

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
    
    def create_server(self, name, server_path='', executable='server.jar', java_args='-Xmx2G -Xms1G', 
                      server_type=None, version=None, owner=None):
        """Create a new server configuration"""
        server_id = str(uuid.uuid4())[:8]
        
        if 'servers' not in self.config:
            self.config['servers'] = {}
        
        # Create server directory
        server_dir = Path(server_path) if server_path else SERVERS_DIR / server_id
        server_dir.mkdir(parents=True, exist_ok=True)
        
        self.config['servers'][server_id] = {
            'name': name,
            'serverPath': str(server_dir),
            'executable': executable,
            'javaArgs': java_args,
            'serverType': server_type,
            'version': version,
            'owner': owner,
            'autoStart': False,
            'created': datetime.now().isoformat()
        }
        
        self._save_config()
        return server_id
    
    def import_server_from_zip(self, name, zip_path, java_args='-Xmx2G -Xms1G', owner=None):
        """Import a server from a ZIP file"""
        server_id = str(uuid.uuid4())[:8]
        server_dir = SERVERS_DIR / server_id
        
        try:
            # Create server directory
            server_dir.mkdir(parents=True, exist_ok=True)
            
            # Extract ZIP file
            with zipfile.ZipFile(zip_path, 'r') as zipf:
                zipf.extractall(server_dir)
            
            # Find server JAR file
            executable = 'server.jar'
            for item in server_dir.iterdir():
                if item.suffix == '.jar' and item.is_file():
                    # Prioritize common server jar names
                    if item.name in ['server.jar', 'paper.jar', 'purpur.jar', 'spigot.jar', 'forge.jar']:
                        executable = item.name
                        break
                    elif 'server' in item.name.lower() or 'paper' in item.name.lower():
                        executable = item.name
            
            # Check if files are in a subdirectory (common with some ZIPs)
            subdirs = [d for d in server_dir.iterdir() if d.is_dir()]
            if len(subdirs) == 1 and not any(server_dir.glob('*.jar')):
                # Move files from subdirectory to server_dir
                subdir = subdirs[0]
                for item in subdir.iterdir():
                    shutil.move(str(item), str(server_dir / item.name))
                subdir.rmdir()
                
                # Re-check for JAR
                for item in server_dir.iterdir():
                    if item.suffix == '.jar' and item.is_file():
                        if item.name in ['server.jar', 'paper.jar', 'purpur.jar', 'spigot.jar', 'forge.jar']:
                            executable = item.name
                            break
                        elif 'server' in item.name.lower() or 'paper' in item.name.lower():
                            executable = item.name
            
            if 'servers' not in self.config:
                self.config['servers'] = {}
            
            self.config['servers'][server_id] = {
                'name': name,
                'serverPath': str(server_dir),
                'executable': executable,
                'javaArgs': java_args,
                'serverType': 'imported',
                'owner': owner,
                'autoStart': False,
                'created': datetime.now().isoformat()
            }
            
            self._save_config()
            return True, server_id
        except Exception as e:
            # Clean up on failure
            if server_dir.exists():
                shutil.rmtree(server_dir)
            return False, str(e)
    
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


# ==================== Static Files & Page Routes ====================

@app.route('/')
def index():
    """Serve main page - redirects to login if not authenticated"""
    user_id, user = get_current_user()
    if not user:
        return redirect('/login.html')
    return send_from_directory('public', 'index.html')

@app.route('/login.html')
def login_page():
    """Serve login page"""
    return send_from_directory('public', 'login.html')

@app.route('/public.html')
def public_page():
    """Serve public status page (no auth required)"""
    return send_from_directory('public', 'public.html')

@app.route('/<path:path>')
def static_files(path):
    """Serve static files"""
    # Allow certain files without auth (CSS, JS, and public pages)
    public_files = ['styles.css', 'app.js', 'login.js', 'public.js']
    if path in public_files or path.startswith('assets/'):
        return send_from_directory('public', path)
    
    # Check auth for other files
    user_id, user = get_current_user()
    if not user:
        return redirect('/login.html')
    
    return send_from_directory('public', path)


# ==================== Authentication API ====================

@app.route('/api/auth/login', methods=['POST'])
@limiter.limit("10 per minute")
def api_login():
    """Authenticate user"""
    data = request.get_json()
    username = data.get('username', '')
    password = data.get('password', '')
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    user_id, result = user_manager.authenticate(username, password)
    
    if user_id is None:
        return jsonify({'error': result}), 401
    
    # Set session
    session.permanent = True
    session['user_id'] = user_id
    session['username'] = result['username']
    session['role'] = result['role']
    
    return jsonify({
        'success': True,
        'user': {
            'id': user_id,
            'username': result['username'],
            'role': result['role']
        }
    })

@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    """Log out user"""
    session.clear()
    return jsonify({'success': True})

@app.route('/api/auth/register', methods=['POST'])
@limiter.limit("5 per hour")
def api_register():
    """Register new user"""
    data = request.get_json()
    username = data.get('username', '')
    password = data.get('password', '')
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    user_id, message = user_manager.register(username, password)
    
    if user_id is None:
        return jsonify({'error': message}), 400
    
    return jsonify({'success': True, 'message': message})

@app.route('/api/auth/me', methods=['GET'])
def api_current_user():
    """Get current logged in user"""
    user_id, user = get_current_user()
    
    if not user:
        return jsonify({'authenticated': False})
    
    return jsonify({
        'authenticated': True,
        'user': {
            'id': user_id,
            'username': user['username'],
            'role': user['role']
        }
    })

@app.route('/api/auth/password', methods=['POST'])
@login_required
def api_change_password():
    """Change current user's password"""
    user_id = session.get('user_id')
    data = request.get_json()
    
    old_password = data.get('oldPassword', '')
    new_password = data.get('newPassword', '')
    
    success, message = user_manager.change_password(user_id, old_password, new_password)
    
    if not success:
        return jsonify({'error': message}), 400
    
    return jsonify({'success': True, 'message': message})


# ==================== Admin API ====================

@app.route('/api/admin/users', methods=['GET'])
@admin_required
def api_get_users():
    """Get all users (admin only)"""
    return jsonify({'users': user_manager.get_all_users()})

@app.route('/api/admin/users/<user_id>/approve', methods=['POST'])
@admin_required
def api_approve_user(user_id):
    """Approve a pending user"""
    if user_manager.approve_user(user_id):
        return jsonify({'success': True})
    return jsonify({'error': 'User not found'}), 404

@app.route('/api/admin/users/<user_id>/role', methods=['PUT'])
@admin_required
def api_update_user_role(user_id):
    """Update user role"""
    data = request.get_json()
    role = data.get('role')
    
    if not role:
        return jsonify({'error': 'Role required'}), 400
    
    # Prevent changing own role (for safety)
    if user_id == session.get('user_id'):
        return jsonify({'error': 'Cannot change your own role'}), 400
    
    if user_manager.update_user_role(user_id, role):
        return jsonify({'success': True})
    return jsonify({'error': 'Invalid role or user not found'}), 400

@app.route('/api/admin/users/<user_id>/password', methods=['POST'])
@admin_required
def api_reset_user_password(user_id):
    """Reset user password (admin only)"""
    data = request.get_json()
    new_password = data.get('password', '')
    
    if len(new_password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    
    if user_manager.reset_password(user_id, new_password):
        return jsonify({'success': True})
    return jsonify({'error': 'User not found'}), 404

@app.route('/api/admin/users/<user_id>', methods=['DELETE'])
@admin_required
def api_delete_user(user_id):
    """Delete a user"""
    # Prevent deleting self
    if user_id == session.get('user_id'):
        return jsonify({'error': 'Cannot delete your own account'}), 400
    
    if user_manager.delete_user(user_id):
        return jsonify({'success': True})
    return jsonify({'error': 'User not found'}), 404


# ==================== Public API (No Auth Required) ====================

@app.route('/api/public/servers', methods=['GET'])
def api_public_servers():
    """Get server status for public view (limited info)"""
    servers = server_manager.get_servers_list()
    # Return only public info (name and running status)
    public_servers = [
        {
            'name': s['name'],
            'running': s['running']
        }
        for s in servers
    ]
    return jsonify({'servers': public_servers})


# ==================== JAR/Version API ====================

@app.route('/api/server-types', methods=['GET'])
@login_required
def get_server_types():
    """Get list of available server types"""
    return jsonify({'types': jar_manager.get_server_types()})

@app.route('/api/server-types/<server_type>/versions', methods=['GET'])
@login_required
def get_server_versions(server_type):
    """Get available versions for a server type"""
    versions = jar_manager.get_versions(server_type)
    return jsonify({'versions': versions})


# ==================== Server Management API ====================

@app.route('/api/servers', methods=['GET'])
@login_required
def get_servers():
    """Get list of servers accessible to the current user"""
    user_id, user = get_current_user()
    all_servers = server_manager.get_servers_list()
    
    # Admins see all servers
    if user.get('role') == 'admin':
        return jsonify({'servers': all_servers})
    
    # Users see only their own servers
    user_servers = [s for s in all_servers if s.get('owner') == user_id]
    return jsonify({'servers': user_servers})

@app.route('/api/servers', methods=['POST'])
@login_required
def create_server():
    """Create a new server"""
    user_id, user = get_current_user()
    
    data = request.get_json()
    name = data.get('name', 'New Server')
    server_path = data.get('serverPath', '')
    executable = data.get('executable', 'server.jar')
    java_args = data.get('javaArgs', '-Xmx2G -Xms1G')
    server_type = data.get('serverType')
    version = data.get('version')
    download_jar = data.get('downloadJar', False)
    
    # Create the server configuration with owner
    server_id = server_manager.create_server(
        name=name,
        server_path=server_path,
        executable=executable,
        java_args=java_args,
        server_type=server_type,
        version=version,
        owner=user_id
    )
    
    # Download JAR if requested
    if download_jar and server_type and version:
        server_config = server_manager.get_server_config(server_id)
        server_dir = Path(server_config['serverPath'])
        jar_path = server_dir / executable
        
        success, result = jar_manager.download_jar(server_type, version, jar_path)
        if not success:
            return jsonify({
                'success': True, 
                'serverId': server_id,
                'warning': f'Server created but JAR download failed: {result}'
            })
        
        # Create eula.txt for convenience
        eula_path = server_dir / 'eula.txt'
        eula_path.write_text('# By setting this to TRUE, you agree to the Minecraft EULA\neula=false\n')
    
    return jsonify({'success': True, 'serverId': server_id})

@app.route('/api/servers/import', methods=['POST'])
@login_required
@limiter.limit("5 per 15 minutes")
def import_server():
    """Import a server from a ZIP file"""
    user_id, user = get_current_user()
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if not file.filename.endswith('.zip'):
        return jsonify({'error': 'File must be a ZIP archive'}), 400
    
    name = request.form.get('name', 'Imported Server')
    java_args = request.form.get('javaArgs', '-Xmx2G -Xms1G')
    
    # Save uploaded file temporarily
    filename = secure_filename(file.filename)
    temp_path = UPLOADS_DIR / filename
    
    try:
        file.save(str(temp_path))
        
        success, result = server_manager.import_server_from_zip(name, temp_path, java_args, owner=user_id)
        
        if success:
            return jsonify({'success': True, 'serverId': result})
        else:
            return jsonify({'error': result}), 400
    finally:
        # Clean up temp file
        if temp_path.exists():
            temp_path.unlink()

@app.route('/api/servers/<server_id>/upload-jar', methods=['POST'])
@server_access_required
@limiter.limit("10 per 15 minutes")
def upload_custom_jar(server_id):
    """Upload a custom JAR file for a server"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if not file.filename.endswith('.jar'):
        return jsonify({'error': 'File must be a JAR file'}), 400
    
    server_config = server_manager.get_server_config(server_id)
    if not server_config:
        return jsonify({'error': 'Server not found'}), 404
    
    server_path = Path(server_config['serverPath'])
    filename = secure_filename(file.filename)
    jar_path = server_path / filename
    
    try:
        file.save(str(jar_path))
        
        # Update server config to use this JAR
        server_manager.update_server(server_id, executable=filename, serverType='custom')
        
        return jsonify({'success': True, 'executable': filename})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/download-jar', methods=['POST'])
@server_access_required
@limiter.limit("5 per 15 minutes")
def download_server_jar(server_id):
    """Download a specific server JAR for an existing server"""
    data = request.get_json()
    server_type = data.get('serverType')
    version = data.get('version')
    executable = data.get('executable', 'server.jar')
    
    if not server_type or not version:
        return jsonify({'error': 'Server type and version required'}), 400
    
    server_config = server_manager.get_server_config(server_id)
    if not server_config:
        return jsonify({'error': 'Server not found'}), 404
    
    server_path = Path(server_config['serverPath'])
    jar_path = server_path / executable
    
    success, result = jar_manager.download_jar(server_type, version, jar_path)
    
    if success:
        server_manager.update_server(server_id, executable=executable, serverType=server_type, version=version)
        return jsonify({'success': True, 'path': result})
    else:
        return jsonify({'error': result}), 400

@app.route('/api/servers/<server_id>', methods=['GET'])
@server_access_required
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
@server_access_required
def update_server(server_id):
    """Update a server's configuration"""
    data = request.get_json()
    
    # Don't allow updating certain fields
    data.pop('id', None)
    data.pop('created', None)
    data.pop('owner', None)  # Can't change owner
    
    if server_manager.update_server(server_id, **data):
        return jsonify({'success': True})
    return jsonify({'error': 'Server not found'}), 404

@app.route('/api/servers/<server_id>', methods=['DELETE'])
@server_access_required
def delete_server(server_id):
    """Delete a server configuration"""
    if server_manager.delete_server(server_id):
        return jsonify({'success': True})
    return jsonify({'error': 'Server not found'}), 404

@app.route('/api/servers/<server_id>/start', methods=['POST'])
@server_access_required
def start_server(server_id):
    """Start a server"""
    success, message = server_manager.start_server(server_id)
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 400

@app.route('/api/servers/<server_id>/stop', methods=['POST'])
@server_access_required
def stop_server(server_id):
    """Stop a server"""
    success, message = server_manager.stop_server(server_id)
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 400

@app.route('/api/servers/<server_id>/command', methods=['POST'])
@server_access_required
def send_command(server_id):
    """Send a command to a server"""
    data = request.get_json()
    command = data.get('command', '')
    
    success, message = server_manager.send_command(server_id, command)
    if success:
        return jsonify({'success': True})
    return jsonify({'error': message}), 400

@app.route('/api/servers/<server_id>/output', methods=['GET'])
@server_access_required
def get_server_output(server_id):
    """Get recent output from a server"""
    instance = server_manager.servers.get(server_id)
    if not instance:
        return jsonify({'output': []})
    
    lines = request.args.get('lines', 100, type=int)
    return jsonify({'output': instance.get_recent_output(lines)})


# ==================== File Explorer API ====================

@app.route('/api/servers/<server_id>/files', methods=['GET'])
@server_access_required
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
@server_access_required
def read_server_file(server_id):
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
@server_access_required
def write_server_file(server_id):
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
@server_access_required
def create_server_file(server_id):
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
@server_access_required
def delete_server_file(server_id):
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
@server_access_required
def download_server_file(server_id):
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
@server_access_required
def upload_server_file(server_id):
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
@server_access_required
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
@server_access_required
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
@server_access_required
def download_backup(server_id):
    """Download a backup"""
    backup_name = request.args.get('name', '')
    backup_path = BACKUPS_DIR / server_id / backup_name
    
    if not backup_path.exists():
        return jsonify({'error': 'Backup not found'}), 404
    
    return send_file(backup_path, as_attachment=True)

@app.route('/api/servers/<server_id>/backups/delete', methods=['DELETE'])
@server_access_required
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
@server_access_required
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
    # Check if user is authenticated
    if 'user_id' not in session:
        return False  # Reject connection
    print(f'Client connected to WebSocket (user: {session.get("username", "unknown")})')

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    print('Client disconnected from WebSocket')

@socketio.on('command')
def handle_command(data):
    """Handle command from client"""
    # Verify user is authenticated
    if 'user_id' not in session:
        emit('message', {'type': 'error', 'data': 'Not authenticated\n'})
        return
    
    server_id = data.get('serverId')
    command = data.get('command', '')
    
    if server_id:
        # Check if user has access to this server
        user = user_manager.get_user(session['user_id'])
        if not user:
            emit('message', {'type': 'error', 'data': 'User not found\n'})
            return
        
        server_config = server_manager.get_server_config(server_id)
        if not server_config:
            emit('message', {'type': 'error', 'data': 'Server not found\n'})
            return
        
        # Check access: admin can access all, users can only access owned servers
        if user.get('role') != 'admin' and server_config.get('owner') != session['user_id']:
            emit('message', {'type': 'error', 'data': 'Access denied\n'})
            return
        
        success, message = server_manager.send_command(server_id, command)
        if not success:
            emit('message', {'type': 'error', 'data': f'{message}\n', 'serverId': server_id})

@socketio.on('subscribe')
def handle_subscribe(data):
    """Subscribe to a server's output"""
    # Verify user is authenticated
    if 'user_id' not in session:
        return
    
    server_id = data.get('serverId')
    if server_id:
        # Check if user has access to this server
        user = user_manager.get_user(session['user_id'])
        if not user:
            return
        
        server_config = server_manager.get_server_config(server_id)
        if not server_config:
            return
        
        # Check access
        if user.get('role') != 'admin' and server_config.get('owner') != session['user_id']:
            return
        
        instance = server_manager.servers.get(server_id)
        if instance:
            # Send recent output to the client
            for line in instance.get_recent_output():
                emit('message', {'type': 'output', 'data': line, 'serverId': server_id})


if __name__ == '__main__':
    print(f'MServerController running on http://localhost:{PORT}')
    print('⚠️  WARNING: Default admin credentials are admin/admin - change immediately!')
    socketio.run(app, host='0.0.0.0', port=PORT, debug=False, allow_unsafe_werkzeug=True)
