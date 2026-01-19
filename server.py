#!/usr/bin/env python3
"""
MServerController - A web-based Minecraft server controller and manager
Python/Flask implementation with multi-server support and RBAC
"""

import os
import io
import gzip
import json
import shutil
import zipfile
import subprocess
import threading
import uuid
import time
import struct
import requests
import hashlib
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

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
SETTINGS_PATH = BASE_DIR / 'settings.json'
SCHEDULES_PATH = BASE_DIR / 'schedules.json'
STATS_PATH = BASE_DIR / 'stats.json'
JAR_URLS_PATH = BASE_DIR / 'configs' / 'jarurls.conf'
API_URLS_PATH = BASE_DIR / 'configs' / 'apiurls.json'
TOOLS_DIR = BASE_DIR / 'tools'

# Ensure directories exist
for directory in [SERVERS_DIR, BACKUPS_DIR, UPLOADS_DIR, TOOLS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)


# ==================== Settings Manager ====================

class SettingsManager:
    """Manages application settings including branding"""
    
    DEFAULT_SETTINGS = {
        'branding': {
            'siteTitle': 'MServerController',
            'siteIcon': '',
            'footerAddition': ''
        },
        'app': {
            'enableRegistration': True,
            'requireApproval': True,
            'requireServerApproval': False
        }
    }
    
    def __init__(self):
        self.settings = self._load_settings()
    
    def _load_settings(self):
        """Load settings from file"""
        if SETTINGS_PATH.exists():
            try:
                with open(SETTINGS_PATH, 'r') as f:
                    settings = json.load(f)
                    # Merge with defaults to ensure all keys exist
                    for key, value in self.DEFAULT_SETTINGS.items():
                        if key not in settings:
                            settings[key] = value
                        elif isinstance(value, dict):
                            for k, v in value.items():
                                if k not in settings[key]:
                                    settings[key][k] = v
                    return settings
            except Exception:
                pass
        return self.DEFAULT_SETTINGS.copy()
    
    def _save_settings(self):
        """Save settings to file"""
        with open(SETTINGS_PATH, 'w') as f:
            json.dump(self.settings, f, indent=2)
    
    def get_settings(self):
        """Get all settings"""
        return self.settings
    
    def get_branding(self):
        """Get branding settings"""
        return self.settings.get('branding', self.DEFAULT_SETTINGS['branding'])
    
    def update_branding(self, branding_data):
        """Update branding settings"""
        if 'branding' not in self.settings:
            self.settings['branding'] = {}
        
        for key in ['siteTitle', 'siteIcon', 'footerAddition']:
            if key in branding_data:
                self.settings['branding'][key] = branding_data[key]
        
        self._save_settings()
        return self.settings['branding']
    
    def get_app_settings(self):
        """Get app settings"""
        return self.settings.get('app', self.DEFAULT_SETTINGS['app'])
    
    def update_app_settings(self, app_data):
        """Update app settings"""
        if 'app' not in self.settings:
            self.settings['app'] = {}
        
        for key in ['enableRegistration', 'requireApproval', 'requireServerApproval']:
            if key in app_data:
                self.settings['app'][key] = app_data[key]
        
        self._save_settings()
        return self.settings['app']


# ==================== System Stats Manager ====================

class StatsManager:
    """Manages system statistics collection and storage"""
    
    RETENTION_DAYS = 7
    
    def __init__(self):
        self.stats = self._load_stats()
        self._start_collection()
    
    def _load_stats(self):
        """Load stats from file"""
        if STATS_PATH.exists():
            try:
                with open(STATS_PATH, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {'history': []}
    
    def _save_stats(self):
        """Save stats to file"""
        try:
            with open(STATS_PATH, 'w') as f:
                json.dump(self.stats, f)
        except Exception as e:
            print(f"Failed to save stats: {e}")
    
    def _cleanup_old_stats(self):
        """Remove stats older than retention period"""
        cutoff = datetime.now() - timedelta(days=self.RETENTION_DAYS)
        cutoff_ts = cutoff.isoformat()
        self.stats['history'] = [
            s for s in self.stats['history']
            if s.get('timestamp', '') > cutoff_ts
        ]
    
    def _get_system_stats(self):
        """Get current system statistics"""
        stats = {
            'timestamp': datetime.now().isoformat(),
            'cpu': 0,
            'memory': {'used': 0, 'total': 0, 'percent': 0},
            'disk': {'used': 0, 'total': 0, 'percent': 0}
        }
        
        try:
            # Try to use psutil if available
            import psutil
            stats['cpu'] = psutil.cpu_percent(interval=1)
            
            mem = psutil.virtual_memory()
            stats['memory'] = {
                'used': mem.used,
                'total': mem.total,
                'percent': mem.percent
            }
            
            disk = psutil.disk_usage('/')
            stats['disk'] = {
                'used': disk.used,
                'total': disk.total,
                'percent': disk.percent
            }
        except ImportError:
            # Fallback to reading from /proc on Linux
            try:
                # CPU usage from /proc/stat
                with open('/proc/stat', 'r') as f:
                    cpu_line = f.readline()
                    cpu_times = list(map(int, cpu_line.split()[1:8]))
                    idle = cpu_times[3]
                    total = sum(cpu_times)
                    # Store for next calculation
                    if hasattr(self, '_last_cpu'):
                        idle_delta = idle - self._last_cpu[0]
                        total_delta = total - self._last_cpu[1]
                        if total_delta > 0:
                            stats['cpu'] = round(100 * (1 - idle_delta / total_delta), 1)
                    self._last_cpu = (idle, total)
                
                # Memory from /proc/meminfo
                with open('/proc/meminfo', 'r') as f:
                    meminfo = {}
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 2:
                            key = parts[0].rstrip(':')
                            value = int(parts[1]) * 1024  # Convert KB to bytes
                            meminfo[key] = value
                    
                    total = meminfo.get('MemTotal', 0)
                    available = meminfo.get('MemAvailable', meminfo.get('MemFree', 0))
                    used = total - available
                    stats['memory'] = {
                        'used': used,
                        'total': total,
                        'percent': round(100 * used / total, 1) if total > 0 else 0
                    }
                
                # Disk usage
                statvfs = os.statvfs('/')
                total = statvfs.f_blocks * statvfs.f_frsize
                free = statvfs.f_bavail * statvfs.f_frsize
                used = total - free
                stats['disk'] = {
                    'used': used,
                    'total': total,
                    'percent': round(100 * used / total, 1) if total > 0 else 0
                }
            except Exception as e:
                print(f"Failed to get system stats: {e}")
        
        return stats
    
    def _collect_stats(self):
        """Background thread to collect stats every 10 seconds"""
        while True:
            try:
                stats = self._get_system_stats()
                self.stats['history'].append(stats)
                self._cleanup_old_stats()
                self._save_stats()
                
                # Emit to connected clients
                socketio.emit('stats_update', stats)
            except Exception as e:
                print(f"Stats collection error: {e}")
            
            time.sleep(10)
    
    def _start_collection(self):
        """Start the stats collection thread"""
        thread = threading.Thread(target=self._collect_stats, daemon=True)
        thread.start()
    
    def get_current_stats(self):
        """Get the most recent stats"""
        return self._get_system_stats()
    
    def get_history(self, hours=24):
        """Get stats history for the specified number of hours"""
        cutoff = datetime.now() - timedelta(hours=hours)
        cutoff_ts = cutoff.isoformat()
        return [
            s for s in self.stats['history']
            if s.get('timestamp', '') > cutoff_ts
        ]


# ==================== Backup Scheduler ====================

class BackupScheduler:
    """Manages scheduled automated backups for servers"""
    
    def __init__(self):
        self.schedules = self._load_schedules()
        self.scheduler = BackgroundScheduler()
        self.scheduler.start()
        self._restore_schedules()
    
    def _load_schedules(self):
        """Load schedules from file"""
        if SCHEDULES_PATH.exists():
            try:
                with open(SCHEDULES_PATH, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {'schedules': {}}
    
    def _save_schedules(self):
        """Save schedules to file"""
        with open(SCHEDULES_PATH, 'w') as f:
            json.dump(self.schedules, f, indent=2)
    
    def _restore_schedules(self):
        """Restore all schedules from saved config on startup"""
        for server_id, schedule in self.schedules.get('schedules', {}).items():
            if schedule.get('enabled', False):
                self._add_job(server_id, schedule)
    
    def _add_job(self, server_id, schedule):
        """Add a scheduled backup job"""
        job_id = f"backup_{server_id}"
        
        # Remove existing job if any
        try:
            self.scheduler.remove_job(job_id)
        except:
            pass
        
        # Create cron trigger based on schedule type
        schedule_type = schedule.get('type', 'daily')
        hour = schedule.get('hour', 3)
        minute = schedule.get('minute', 0)
        
        if schedule_type == 'hourly':
            trigger = CronTrigger(minute=minute)
        elif schedule_type == 'daily':
            trigger = CronTrigger(hour=hour, minute=minute)
        elif schedule_type == 'weekly':
            day_of_week = schedule.get('dayOfWeek', 0)  # 0 = Monday
            trigger = CronTrigger(day_of_week=day_of_week, hour=hour, minute=minute)
        elif schedule_type == 'custom':
            # Custom cron expression
            cron_expr = schedule.get('cron', '0 3 * * *')
            parts = cron_expr.split()
            if len(parts) == 5:
                trigger = CronTrigger(
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4]
                )
            else:
                trigger = CronTrigger(hour=3, minute=0)
        else:
            trigger = CronTrigger(hour=hour, minute=minute)
        
        self.scheduler.add_job(
            self._execute_backup,
            trigger,
            args=[server_id],
            id=job_id,
            replace_existing=True,
            max_instances=1
        )
    
    def _execute_backup(self, server_id):
        """Execute a scheduled backup for a server"""
        print(f"[Scheduler] Starting scheduled backup for server: {server_id}")
        
        try:
            # Get server config
            server_config = server_manager.get_server_config(server_id)
            if not server_config:
                print(f"[Scheduler] Server {server_id} not found")
                return
            
            server_path = Path(server_config.get('serverPath', SERVERS_DIR))
            if not server_path.exists():
                print(f"[Scheduler] Server path not found for {server_id}")
                return
            
            # Check if server is running and stop it if configured to do so
            schedule = self.schedules['schedules'].get(server_id, {})
            was_running = False
            instance = server_manager.servers.get(server_id)
            
            if instance and instance.is_running():
                if schedule.get('stopServer', True):
                    print(f"[Scheduler] Stopping server {server_id} for backup")
                    was_running = True
                    
                    # Send warning to players
                    server_manager.send_command(server_id, "say [Backup] Server will restart in 30 seconds for scheduled backup!")
                    time.sleep(10)
                    server_manager.send_command(server_id, "say [Backup] Server restarting in 20 seconds...")
                    time.sleep(10)
                    server_manager.send_command(server_id, "say [Backup] Server restarting in 10 seconds...")
                    time.sleep(10)
                    
                    # Stop the server gracefully
                    server_manager.stop_server(server_id)
                    
                    # Wait for server to stop (max 60 seconds)
                    for _ in range(60):
                        if server_id not in server_manager.servers or not server_manager.servers[server_id].is_running():
                            break
                        time.sleep(1)
                    
                    # Force kill if still running
                    if server_id in server_manager.servers and server_manager.servers[server_id].is_running():
                        server_manager.kill_server(server_id)
                        time.sleep(2)
                else:
                    print(f"[Scheduler] Server {server_id} is running, backup may be inconsistent (stopServer=False)")
            
            # Create backup directory for this server
            backup_dir = BACKUPS_DIR / server_id
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y-%m-%dT%H-%M-%S')
            backup_name = f'scheduled-backup-{timestamp}.zip'
            backup_path = backup_dir / backup_name
            
            # Create the backup
            print(f"[Scheduler] Creating backup: {backup_name}")
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(server_path):
                    for file in files:
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(server_path)
                        zipf.write(file_path, arcname)
            
            size = backup_path.stat().st_size
            print(f"[Scheduler] Backup created: {backup_name} ({size} bytes)")
            
            # Update last backup time
            self.schedules['schedules'][server_id]['lastBackup'] = datetime.now().isoformat()
            self._save_schedules()
            
            # Clean up old backups if retention is set
            max_backups = schedule.get('maxBackups', 0)
            if max_backups > 0:
                self._cleanup_old_backups(server_id, max_backups)
            
            # Restart server if it was running
            if was_running and schedule.get('restartAfter', True):
                print(f"[Scheduler] Restarting server {server_id}")
                server_manager.start_server(server_id)
            
            # Emit notification to connected clients
            socketio.emit('backup_completed', {
                'serverId': server_id,
                'backup': backup_name,
                'size': size,
                'scheduled': True
            })
            
            print(f"[Scheduler] Scheduled backup completed for server: {server_id}")
            
        except Exception as e:
            print(f"[Scheduler] Backup failed for server {server_id}: {e}")
            socketio.emit('backup_failed', {
                'serverId': server_id,
                'error': str(e),
                'scheduled': True
            })
    
    def _cleanup_old_backups(self, server_id, max_backups):
        """Remove old scheduled backups exceeding the maximum count"""
        backup_dir = BACKUPS_DIR / server_id
        if not backup_dir.exists():
            return
        
        # Get all scheduled backups sorted by date
        backups = []
        for item in backup_dir.iterdir():
            if item.name.startswith('scheduled-backup-') and item.suffix == '.zip':
                backups.append((item, item.stat().st_mtime))
        
        backups.sort(key=lambda x: x[1], reverse=True)
        
        # Remove backups exceeding max count
        for backup_file, _ in backups[max_backups:]:
            try:
                backup_file.unlink()
                print(f"[Scheduler] Removed old backup: {backup_file.name}")
            except Exception as e:
                print(f"[Scheduler] Failed to remove old backup {backup_file.name}: {e}")
    
    def set_schedule(self, server_id, schedule_config):
        """Set or update a backup schedule for a server"""
        if 'schedules' not in self.schedules:
            self.schedules['schedules'] = {}
        
        self.schedules['schedules'][server_id] = {
            'enabled': schedule_config.get('enabled', True),
            'type': schedule_config.get('type', 'daily'),
            'hour': schedule_config.get('hour', 3),
            'minute': schedule_config.get('minute', 0),
            'dayOfWeek': schedule_config.get('dayOfWeek', 0),
            'cron': schedule_config.get('cron', ''),
            'stopServer': schedule_config.get('stopServer', True),
            'restartAfter': schedule_config.get('restartAfter', True),
            'maxBackups': schedule_config.get('maxBackups', 7),
            'lastBackup': self.schedules.get('schedules', {}).get(server_id, {}).get('lastBackup'),
            'createdAt': datetime.now().isoformat()
        }
        
        self._save_schedules()
        
        if schedule_config.get('enabled', True):
            self._add_job(server_id, self.schedules['schedules'][server_id])
        else:
            # Remove job if disabled
            try:
                self.scheduler.remove_job(f"backup_{server_id}")
            except:
                pass
        
        return self.schedules['schedules'][server_id]
    
    def get_schedule(self, server_id):
        """Get the backup schedule for a server"""
        schedule = self.schedules.get('schedules', {}).get(server_id)
        if schedule:
            # Add next run time if job exists
            try:
                job = self.scheduler.get_job(f"backup_{server_id}")
                if job and job.next_run_time:
                    schedule['nextRun'] = job.next_run_time.isoformat()
            except:
                pass
        return schedule
    
    def delete_schedule(self, server_id):
        """Delete a backup schedule for a server"""
        if server_id in self.schedules.get('schedules', {}):
            del self.schedules['schedules'][server_id]
            self._save_schedules()
            
            try:
                self.scheduler.remove_job(f"backup_{server_id}")
            except:
                pass
            
            return True
        return False
    
    def get_all_schedules(self):
        """Get all backup schedules"""
        schedules = {}
        for server_id, schedule in self.schedules.get('schedules', {}).items():
            schedules[server_id] = schedule.copy()
            try:
                job = self.scheduler.get_job(f"backup_{server_id}")
                if job and job.next_run_time:
                    schedules[server_id]['nextRun'] = job.next_run_time.isoformat()
            except:
                pass
        return schedules


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
            
            # Check if approval is required
            require_approval = settings_manager.get_app_settings().get('requireApproval', True)
            
            user_id = str(uuid.uuid4())[:8]
            self.users['users'][user_id] = {
                'username': username,
                'password': generate_password_hash(password),
                'role': 'user',
                'approved': not require_approval,  # Auto-approve if not required
                'created': datetime.now().isoformat(),
                'lastLogin': None
            }
            self._save_users()
            
            if require_approval:
                return user_id, "Registration successful. Please wait for admin approval."
            return user_id, "Registration successful. You can now log in."
    
    def create_user(self, username, password, role='user'):
        """Create a user directly (admin function, auto-approved)"""
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
            
            # Validate role
            if role not in self.ROLES:
                return None, "Invalid role"
            
            user_id = str(uuid.uuid4())[:8]
            self.users['users'][user_id] = {
                'username': username,
                'password': generate_password_hash(password),
                'role': role,
                'approved': True,  # Admin-created users are auto-approved
                'created': datetime.now().isoformat(),
                'lastLogin': None
            }
            self._save_users()
            return user_id, "User created successfully"
    
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


# Initialize managers (settings_manager must be first as UserManager uses it)
settings_manager = SettingsManager()
user_manager = UserManager()
stats_manager = StatsManager()


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
    
    # Server type metadata - now categorized as 'unmodded' or 'modded'
    SERVER_TYPE_INFO = {
        'vanilla': {'name': 'Vanilla', 'description': 'Official Minecraft Java Edition server', 'category': 'unmodded'},
        'bedrock': {'name': 'Bedrock', 'description': 'Official Minecraft Bedrock Edition server (not yet supported)', 'category': 'unmodded'},
        'paper': {'name': 'Paper', 'description': 'High-performance Spigot fork', 'category': 'modded'},
        'folia': {'name': 'Folia', 'description': 'Paper fork for multi-threaded regions', 'category': 'modded'},
        'purpur': {'name': 'Purpur', 'description': 'Paper fork with extra features', 'category': 'modded'},
        'spigot': {'name': 'Spigot', 'description': 'Bukkit-compatible server with plugins', 'category': 'modded'},
        'forge': {'name': 'Forge', 'description': 'Mod loader for Minecraft mods (installer)', 'category': 'modded'},
        'neoforge': {'name': 'NeoForge', 'description': 'Modern Forge fork (installer)', 'category': 'modded'}
    }
    
    # Server executables directory
    EXECUTABLES_DIR = BASE_DIR / 'serverexecutables'
    
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
    
    def _scan_local_jars(self):
        """
        Scan serverexecutables directory for available JAR files.
        Returns dict: {server_type: [{version, filename, path, size}]}
        """
        local_jars = {}
        
        if not self.EXECUTABLES_DIR.exists():
            return local_jars
        
        for type_dir in self.EXECUTABLES_DIR.iterdir():
            if not type_dir.is_dir():
                continue
            
            server_type = type_dir.name.lower()
            local_jars[server_type] = []
            
            for jar_file in type_dir.iterdir():
                if not jar_file.is_file():
                    continue
                if jar_file.suffix not in ['.jar', '.zip']:
                    continue
                if jar_file.name.startswith('.'):
                    continue
                
                # Parse version from filename
                version = self._extract_version(jar_file.name, server_type)
                if version:
                    local_jars[server_type].append({
                        'version': version,
                        'filename': jar_file.name,
                        'path': str(jar_file),
                        'size': jar_file.stat().st_size
                    })
        
        return local_jars
    
    def _extract_version(self, filename, server_type):
        """
        Extract version from JAR filename.
        Handles patterns like:
          - vanilla-1.21.4.jar -> 1.21.4
          - paper-1.21.4-232.jar -> 1.21.4 (build 232)
          - forge-1.21.3-53.0.26-installer.jar -> 1.21.3-53.0.26
          - neoforge-21.4.156-installer.jar -> 21.4.156
        """
        import re
        
        # Remove extension
        name = filename.replace('.jar', '').replace('.zip', '')
        
        # Remove -installer suffix
        name = name.replace('-installer', '')
        
        # Pattern for different server types
        patterns = {
            'vanilla': r'vanilla-([\d.]+)',
            'paper': r'paper-([\d.]+)(?:-\d+)?',
            'folia': r'folia-([\d.]+)(?:-\d+)?',
            'purpur': r'purpur-([\d.]+)(?:-\d+)?',
            'forge': r'forge-([\d.]+-[\d.]+)',
            'neoforge': r'neoforge-([\d.]+(?:-beta)?)',
        }
        
        # Try specific pattern first
        if server_type in patterns:
            match = re.search(patterns[server_type], name, re.IGNORECASE)
            if match:
                return match.group(1)
        
        # Generic fallback: type-VERSION or just VERSION
        generic = re.search(rf'{server_type}-([\d.-]+)', name, re.IGNORECASE)
        if generic:
            return generic.group(1)
        
        # Very generic: just find version-like string
        version_match = re.search(r'(\d+\.\d+(?:\.\d+)?(?:-[\d.]+)?)', name)
        if version_match:
            return version_match.group(1)
        
        return None
    
    def get_server_types(self):
        """
        Get list of server types that have local JAR files available.
        Only returns types with at least one downloaded JAR.
        """
        local_jars = self._scan_local_jars()
        
        available_types = []
        for server_type, jars in local_jars.items():
            if not jars:
                continue
            
            # Get metadata or create default
            info = self.SERVER_TYPE_INFO.get(server_type, {
                'name': server_type.title(),
                'description': f'{server_type.title()} server',
                'category': 'modded'
            })
            
            available_types.append({
                'id': server_type,
                'name': info['name'],
                'description': info['description'],
                'category': info['category'],
                'jarCount': len(jars)
            })
        
        # Sort by name
        available_types.sort(key=lambda x: x['name'])
        return available_types
    
    def get_server_engines(self, category=None):
        """
        Get list of server engines filtered by category.
        category: 'modded', 'unmodded', or None for all
        Only returns engines with at least one downloaded JAR.
        """
        local_jars = self._scan_local_jars()
        
        available_engines = []
        for server_type, jars in local_jars.items():
            if not jars:
                continue
            
            # Get metadata or create default
            info = self.SERVER_TYPE_INFO.get(server_type, {
                'name': server_type.title(),
                'description': f'{server_type.title()} server',
                'category': 'modded'
            })
            
            # Filter by category if specified
            if category and info['category'] != category:
                continue
            
            available_engines.append({
                'id': server_type,
                'name': info['name'],
                'description': info['description'],
                'category': info['category'],
                'jarCount': len(jars)
            })
        
        # Sort by name
        available_engines.sort(key=lambda x: x['name'])
        return available_engines
    
    def get_versions(self, server_type):
        """
        Get available local versions for a server type.
        Returns list of version strings, sorted newest first.
        """
        local_jars = self._scan_local_jars()
        
        if server_type not in local_jars:
            return []
        
        versions = [jar['version'] for jar in local_jars[server_type]]
        
        # Sort versions (newest first)
        def version_key(v):
            # Handle versions like "1.21.4", "21.4.156", "1.21.3-53.0.26"
            parts = []
            for p in v.replace('-', '.').split('.'):
                try:
                    parts.append(int(p))
                except ValueError:
                    parts.append(p)
            return parts
        
        return sorted(set(versions), key=version_key, reverse=True)
    
    def get_local_jar_info(self, server_type, version):
        """
        Get info about a specific local JAR file.
        Returns: {filename, path, size} or None if not found
        """
        local_jars = self._scan_local_jars()
        
        if server_type not in local_jars:
            return None
        
        for jar in local_jars[server_type]:
            if jar['version'] == version:
                return jar
        
        return None
    
    def copy_jar_to_server(self, server_type, version, dest_path):
        """
        Copy a local JAR file to the server directory.
        Returns: (success: bool, message: str)
        """
        jar_info = self.get_local_jar_info(server_type, version)
        
        if not jar_info:
            return False, f'JAR file not found for {server_type} version {version}'
        
        source_path = Path(jar_info['path'])
        dest_path = Path(dest_path)
        
        if not source_path.exists():
            return False, f'Source JAR file not found: {source_path}'
        
        try:
            # Ensure destination directory exists
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy the JAR file
            shutil.copy2(source_path, dest_path)
            
            return True, str(dest_path)
        except Exception as e:
            return False, f'Failed to copy JAR: {str(e)}'
    
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


# ==================== NBT Parser/Editor ====================

class NBTEditor:
    """
    Pure Python NBT (Named Binary Tag) parser and editor for Minecraft .dat files.
    Supports both compressed (gzip) and uncompressed NBT files.
    """
    
    # Tag type constants
    TAG_END = 0
    TAG_BYTE = 1
    TAG_SHORT = 2
    TAG_INT = 3
    TAG_LONG = 4
    TAG_FLOAT = 5
    TAG_DOUBLE = 6
    TAG_BYTE_ARRAY = 7
    TAG_STRING = 8
    TAG_LIST = 9
    TAG_COMPOUND = 10
    TAG_INT_ARRAY = 11
    TAG_LONG_ARRAY = 12
    
    TAG_NAMES = {
        0: 'End', 1: 'Byte', 2: 'Short', 3: 'Int', 4: 'Long',
        5: 'Float', 6: 'Double', 7: 'ByteArray', 8: 'String',
        9: 'List', 10: 'Compound', 11: 'IntArray', 12: 'LongArray'
    }
    
    def __init__(self):
        self.compression = None  # 'gzip' or None
    
    def read_file(self, filepath):
        """Read and parse an NBT file, returns tree structure"""
        filepath = Path(filepath)
        
        with open(filepath, 'rb') as f:
            data = f.read()
        
        # Try gzip first
        try:
            decompressed = gzip.decompress(data)
            self.compression = 'gzip'
            data = decompressed
        except:
            self.compression = None
        
        reader = io.BytesIO(data)
        return self._read_named_tag(reader)
    
    def write_file(self, filepath, nbt_data):
        """Write NBT data back to file"""
        filepath = Path(filepath)
        
        writer = io.BytesIO()
        self._write_named_tag(writer, nbt_data)
        
        data = writer.getvalue()
        
        if self.compression == 'gzip':
            data = gzip.compress(data)
        
        with open(filepath, 'wb') as f:
            f.write(data)
    
    def _read_named_tag(self, reader):
        """Read a named tag from the stream"""
        tag_type = struct.unpack('>B', reader.read(1))[0]
        
        if tag_type == self.TAG_END:
            return None
        
        name_length = struct.unpack('>H', reader.read(2))[0]
        name = reader.read(name_length).decode('utf-8')
        
        value = self._read_tag_payload(reader, tag_type)
        
        return {
            'type': tag_type,
            'typeName': self.TAG_NAMES.get(tag_type, 'Unknown'),
            'name': name,
            'value': value
        }
    
    def _read_tag_payload(self, reader, tag_type):
        """Read tag payload based on type"""
        if tag_type == self.TAG_BYTE:
            return struct.unpack('>b', reader.read(1))[0]
        
        elif tag_type == self.TAG_SHORT:
            return struct.unpack('>h', reader.read(2))[0]
        
        elif tag_type == self.TAG_INT:
            return struct.unpack('>i', reader.read(4))[0]
        
        elif tag_type == self.TAG_LONG:
            return struct.unpack('>q', reader.read(8))[0]
        
        elif tag_type == self.TAG_FLOAT:
            return struct.unpack('>f', reader.read(4))[0]
        
        elif tag_type == self.TAG_DOUBLE:
            return struct.unpack('>d', reader.read(8))[0]
        
        elif tag_type == self.TAG_BYTE_ARRAY:
            length = struct.unpack('>i', reader.read(4))[0]
            return list(struct.unpack(f'>{length}b', reader.read(length)))
        
        elif tag_type == self.TAG_STRING:
            length = struct.unpack('>H', reader.read(2))[0]
            return reader.read(length).decode('utf-8')
        
        elif tag_type == self.TAG_LIST:
            list_type = struct.unpack('>B', reader.read(1))[0]
            length = struct.unpack('>i', reader.read(4))[0]
            items = []
            for _ in range(length):
                items.append({
                    'type': list_type,
                    'typeName': self.TAG_NAMES.get(list_type, 'Unknown'),
                    'value': self._read_tag_payload(reader, list_type)
                })
            return {'listType': list_type, 'items': items}
        
        elif tag_type == self.TAG_COMPOUND:
            children = []
            while True:
                child = self._read_named_tag(reader)
                if child is None:
                    break
                children.append(child)
            return children
        
        elif tag_type == self.TAG_INT_ARRAY:
            length = struct.unpack('>i', reader.read(4))[0]
            return list(struct.unpack(f'>{length}i', reader.read(length * 4)))
        
        elif tag_type == self.TAG_LONG_ARRAY:
            length = struct.unpack('>i', reader.read(4))[0]
            return list(struct.unpack(f'>{length}q', reader.read(length * 8)))
        
        return None
    
    def _write_named_tag(self, writer, tag):
        """Write a named tag to the stream"""
        tag_type = tag['type']
        name = tag['name']
        
        writer.write(struct.pack('>B', tag_type))
        name_bytes = name.encode('utf-8')
        writer.write(struct.pack('>H', len(name_bytes)))
        writer.write(name_bytes)
        
        self._write_tag_payload(writer, tag_type, tag['value'])
    
    def _write_tag_payload(self, writer, tag_type, value):
        """Write tag payload based on type"""
        if tag_type == self.TAG_BYTE:
            writer.write(struct.pack('>b', int(value)))
        
        elif tag_type == self.TAG_SHORT:
            writer.write(struct.pack('>h', int(value)))
        
        elif tag_type == self.TAG_INT:
            writer.write(struct.pack('>i', int(value)))
        
        elif tag_type == self.TAG_LONG:
            writer.write(struct.pack('>q', int(value)))
        
        elif tag_type == self.TAG_FLOAT:
            writer.write(struct.pack('>f', float(value)))
        
        elif tag_type == self.TAG_DOUBLE:
            writer.write(struct.pack('>d', float(value)))
        
        elif tag_type == self.TAG_BYTE_ARRAY:
            writer.write(struct.pack('>i', len(value)))
            writer.write(struct.pack(f'>{len(value)}b', *value))
        
        elif tag_type == self.TAG_STRING:
            value_bytes = value.encode('utf-8')
            writer.write(struct.pack('>H', len(value_bytes)))
            writer.write(value_bytes)
        
        elif tag_type == self.TAG_LIST:
            list_type = value['listType']
            items = value['items']
            writer.write(struct.pack('>B', list_type))
            writer.write(struct.pack('>i', len(items)))
            for item in items:
                self._write_tag_payload(writer, list_type, item['value'])
        
        elif tag_type == self.TAG_COMPOUND:
            for child in value:
                self._write_named_tag(writer, child)
            writer.write(struct.pack('>B', self.TAG_END))
        
        elif tag_type == self.TAG_INT_ARRAY:
            writer.write(struct.pack('>i', len(value)))
            writer.write(struct.pack(f'>{len(value)}i', *value))
        
        elif tag_type == self.TAG_LONG_ARRAY:
            writer.write(struct.pack('>i', len(value)))
            writer.write(struct.pack(f'>{len(value)}q', *value))
    
    def to_json(self, nbt_data):
        """Convert NBT data to JSON-serializable format"""
        return json.dumps(nbt_data, indent=2)
    
    def update_value(self, nbt_data, path, new_value):
        """
        Update a value at a specific path in the NBT tree.
        Path is a list of keys/indices like ['Data', 'Player', 'Pos', 0]
        """
        if not path:
            return nbt_data
        
        current = nbt_data
        for i, key in enumerate(path[:-1]):
            if current['type'] == self.TAG_COMPOUND:
                for child in current['value']:
                    if child['name'] == key:
                        current = child
                        break
            elif current['type'] == self.TAG_LIST:
                current = current['value']['items'][int(key)]
        
        # Set the final value
        final_key = path[-1]
        if current['type'] == self.TAG_COMPOUND:
            for child in current['value']:
                if child['name'] == final_key:
                    child['value'] = new_value
                    break
        elif current['type'] == self.TAG_LIST:
            current['value']['items'][int(final_key)]['value'] = new_value
        else:
            current['value'] = new_value
        
        return nbt_data
    
    def add_tag(self, nbt_data, parent_path, new_tag):
        """Add a new tag to a compound or list"""
        current = nbt_data
        for key in parent_path:
            if current['type'] == self.TAG_COMPOUND:
                for child in current['value']:
                    if child['name'] == key:
                        current = child
                        break
            elif current['type'] == self.TAG_LIST:
                current = current['value']['items'][int(key)]
        
        if current['type'] == self.TAG_COMPOUND:
            current['value'].append(new_tag)
        elif current['type'] == self.TAG_LIST:
            current['value']['items'].append(new_tag)
        
        return nbt_data
    
    def delete_tag(self, nbt_data, path):
        """Delete a tag at the specified path"""
        if not path:
            return nbt_data
        
        current = nbt_data
        for key in path[:-1]:
            if current['type'] == self.TAG_COMPOUND:
                for child in current['value']:
                    if child['name'] == key:
                        current = child
                        break
            elif current['type'] == self.TAG_LIST:
                current = current['value']['items'][int(key)]
        
        final_key = path[-1]
        if current['type'] == self.TAG_COMPOUND:
            current['value'] = [c for c in current['value'] if c['name'] != final_key]
        elif current['type'] == self.TAG_LIST:
            del current['value']['items'][int(final_key)]
        
        return nbt_data


# Initialize NBT editor
nbt_editor = NBTEditor()


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
    
    def get_servers_list(self, include_pending=False):
        """Get list of all configured servers with their status"""
        servers = []
        for server_id, server_config in self.config.get('servers', {}).items():
            is_approved = server_config.get('approved', True)  # Default to approved for legacy servers
            
            # Skip pending servers unless explicitly requested
            if not include_pending and not is_approved:
                continue
                
            instance = self.servers.get(server_id)
            is_running = instance is not None and instance.is_running()
            servers.append({
                'id': server_id,
                'name': server_config.get('name', 'Unnamed Server'),
                'serverPath': server_config.get('serverPath', ''),
                'executable': server_config.get('executable', 'server.jar'),
                'javaArgs': server_config.get('javaArgs', '-Xmx2G -Xms1G'),
                'autoStart': server_config.get('autoStart', False),
                'serverType': server_config.get('serverType'),
                'version': server_config.get('version'),
                'owner': server_config.get('owner'),
                'created': server_config.get('created'),
                'approved': is_approved,
                'running': is_running
            })
        return servers
    
    def get_pending_servers(self):
        """Get list of servers pending approval"""
        servers = []
        for server_id, server_config in self.config.get('servers', {}).items():
            if not server_config.get('approved', True):  # Not approved
                servers.append({
                    'id': server_id,
                    'name': server_config.get('name', 'Unnamed Server'),
                    'type': server_config.get('serverType', 'Server'),
                    'owner': server_config.get('owner'),
                    'created': server_config.get('created')
                })
        return servers
    
    def approve_server(self, server_id):
        """Approve a pending server"""
        if server_id in self.config.get('servers', {}):
            self.config['servers'][server_id]['approved'] = True
            self._save_config()
            return True
        return False
    
    def reject_server(self, server_id):
        """Reject (delete) a pending server"""
        return self.delete_server(server_id)
    
    def get_server_config(self, server_id):
        """Get configuration for a specific server"""
        return self.config.get('servers', {}).get(server_id)
    
    def create_server(self, name, server_path='', executable='server.jar', java_args='-Xmx2G -Xms1G', 
                      server_type=None, version=None, owner=None, approved=True, category='unmodded'):
        """Create a new server configuration"""
        server_id = str(uuid.uuid4())[:8]
        
        if 'servers' not in self.config:
            self.config['servers'] = {}
        
        # Create server directory
        server_dir = Path(server_path) if server_path else SERVERS_DIR / server_id
        server_dir.mkdir(parents=True, exist_ok=True)
        
        # Determine if modded based on category
        is_modded = category == 'modded'
        
        # Create managed.conf file
        self._create_managed_conf(server_dir, server_id, name, modded=is_modded)
        
        self.config['servers'][server_id] = {
            'name': name,
            'serverPath': str(server_dir),
            'executable': executable,
            'javaArgs': java_args,
            'serverType': server_type,
            'version': version,
            'owner': owner,
            'autoStart': False,
            'approved': approved,
            'category': category,
            'created': datetime.now().isoformat()
        }
        
        self._save_config()
        return server_id
    
    def _create_managed_conf(self, server_dir, server_id, name, modded=False):
        """Create or update the managed.conf file for a server"""
        managed_conf_path = Path(server_dir) / 'managed.conf'
        config = {
            'ManagedBy': 'MServerController',
            'ServerId': server_id,
            'ServerName': name,
            'Modded': 'true' if modded else 'false',
            'CreatedAt': datetime.now().isoformat(),
            'EULAAccepted': 'false'
        }
        
        # If file exists, preserve existing settings
        if managed_conf_path.exists():
            existing = self._read_managed_conf(server_dir)
            config.update(existing)
            config['ServerId'] = server_id  # Always update these
            config['ServerName'] = name
            config['Modded'] = 'true' if modded else 'false'
        
        self._write_managed_conf(server_dir, config)
    
    def _read_managed_conf(self, server_dir):
        """Read the managed.conf file"""
        managed_conf_path = Path(server_dir) / 'managed.conf'
        config = {}
        if managed_conf_path.exists():
            try:
                with open(managed_conf_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if '=' in line and not line.startswith('#'):
                            key, value = line.split('=', 1)
                            config[key.strip()] = value.strip()
            except Exception:
                pass
        return config
    
    def _write_managed_conf(self, server_dir, config):
        """Write the managed.conf file"""
        managed_conf_path = Path(server_dir) / 'managed.conf'
        try:
            with open(managed_conf_path, 'w') as f:
                f.write("# MServerController Managed Server Configuration\n")
                f.write("# Do not edit this file manually unless you know what you're doing\n\n")
                for key, value in config.items():
                    f.write(f"{key}={value}\n")
        except Exception as e:
            print(f"Error writing managed.conf: {e}")
    
    def is_managed(self, server_id):
        """Check if a server has a managed.conf file"""
        server_config = self.get_server_config(server_id)
        if not server_config:
            return False
        
        server_dir = Path(server_config.get('serverPath', ''))
        managed_conf_path = server_dir / 'managed.conf'
        return managed_conf_path.exists()
    
    def enable_management(self, server_id):
        """Create managed.conf for an existing server that doesn't have one"""
        server_config = self.get_server_config(server_id)
        if not server_config:
            return False, "Server not found"
        
        server_dir = Path(server_config.get('serverPath', ''))
        if not server_dir.exists():
            return False, "Server directory not found"
        
        # Check if already managed
        managed_conf_path = server_dir / 'managed.conf'
        if managed_conf_path.exists():
            return True, "Server is already managed"
        
        # Create managed.conf
        name = server_config.get('name', 'Unknown Server')
        category = server_config.get('category', 'unmodded')
        is_modded = category == 'modded'
        self._create_managed_conf(server_dir, server_id, name, modded=is_modded)
        
        return True, "Management enabled"
    
    def check_eula_accepted(self, server_id):
        """Check if EULA has been accepted for a server"""
        server_config = self.get_server_config(server_id)
        if not server_config:
            return False
        
        server_dir = Path(server_config.get('serverPath', ''))
        managed_conf = self._read_managed_conf(server_dir)
        return managed_conf.get('EULAAccepted', 'false').lower() == 'true'
    
    def accept_eula(self, server_id):
        """Accept the EULA for a server"""
        server_config = self.get_server_config(server_id)
        if not server_config:
            return False, "Server not found"
        
        server_dir = Path(server_config.get('serverPath', ''))
        
        # Update managed.conf
        managed_conf = self._read_managed_conf(server_dir)
        managed_conf['EULAAccepted'] = 'true'
        managed_conf['EULAAcceptedAt'] = datetime.now().isoformat()
        self._write_managed_conf(server_dir, managed_conf)
        
        # Create/update eula.txt
        eula_path = server_dir / 'eula.txt'
        try:
            with open(eula_path, 'w') as f:
                f.write("# By setting this to TRUE, you agree to the Minecraft EULA\n")
                f.write("# https://aka.ms/MinecraftEULA\n")
                f.write("eula=true\n")
            return True, "EULA accepted"
        except Exception as e:
            return False, f"Failed to write eula.txt: {e}"
    
    def import_server_from_zip(self, name, zip_path, java_args='-Xmx2G -Xms1G', jar_name=None, owner=None, approved=True, category='unmodded'):
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
            # Use provided jar_name if specified and exists, otherwise auto-detect
            executable = 'server.jar'
            if jar_name:
                jar_path = server_dir / jar_name
                if jar_path.exists() and jar_path.suffix == '.jar':
                    executable = jar_name
            
            # If jar_name not provided or not found, auto-detect
            if not jar_name or executable == 'server.jar':
                for item in server_dir.iterdir():
                    if item.suffix == '.jar' and item.is_file():
                        # Prioritize common server jar names
                        if item.name in ['server.jar', 'paper.jar', 'purpur.jar', 'folia.jar', 'forge.jar', 'neoforge.jar']:
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
                
                # Re-check for JAR if we're auto-detecting
                if not jar_name or executable == 'server.jar':
                    for item in server_dir.iterdir():
                        if item.suffix == '.jar' and item.is_file():
                            if item.name in ['server.jar', 'paper.jar', 'purpur.jar', 'folia.jar', 'forge.jar', 'neoforge.jar']:
                                executable = item.name
                                break
                            elif 'server' in item.name.lower() or 'paper' in item.name.lower():
                                executable = item.name
                elif jar_name:
                    # Check if the specified jar_name exists after moving
                    jar_path = server_dir / jar_name
                    if jar_path.exists() and jar_path.suffix == '.jar':
                        executable = jar_name
            
            if 'servers' not in self.config:
                self.config['servers'] = {}
            
            # Determine if modded based on category
            is_modded = category == 'modded'
            
            # Create managed.conf file
            self._create_managed_conf(server_dir, server_id, name, modded=is_modded)
            
            self.config['servers'][server_id] = {
                'name': name,
                'serverPath': str(server_dir),
                'executable': executable,
                'javaArgs': java_args,
                'serverType': 'imported',
                'category': category,
                'owner': owner,
                'autoStart': False,
                'approved': approved,
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
        
        # If category was updated, also update managed.conf
        if 'category' in kwargs:
            server_config = self.config['servers'][server_id]
            server_dir = Path(server_config.get('serverPath', ''))
            managed_conf_path = server_dir / 'managed.conf'
            if managed_conf_path.exists():
                managed_config = self._read_managed_conf(server_dir)
                managed_config['Modded'] = 'true' if kwargs['category'] == 'modded' else 'false'
                self._write_managed_conf(server_dir, managed_config)
        
        return True
    
    def delete_server(self, server_id, delete_files=False):
        """Delete a server configuration
        
        Args:
            server_id: The server ID to delete
            delete_files: If True, also delete all server files. If False, only remove managed.conf
        """
        if server_id in self.servers:
            self.stop_server(server_id)
        
        server_config = self.config.get('servers', {}).get(server_id)
        if not server_config:
            return False
        
        server_path = Path(server_config.get('serverPath', ''))
        
        if delete_files:
            # Delete entire server directory
            if server_path.exists():
                try:
                    shutil.rmtree(server_path)
                except Exception as e:
                    print(f"Error deleting server files: {e}")
        else:
            # Only remove managed.conf to unmanage the server
            managed_conf = server_path / 'managed.conf'
            if managed_conf.exists():
                try:
                    managed_conf.unlink()
                except Exception as e:
                    print(f"Error removing managed.conf: {e}")
        
        # Remove from config
        del self.config['servers'][server_id]
        self._save_config()
        return True
    
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
        """Stop a Minecraft server gracefully"""
        with self.lock:
            if server_id not in self.servers:
                return False, "Server is not running"
            
            instance = self.servers[server_id]
            if not instance.is_running():
                del self.servers[server_id]
                return False, "Server is not running"
            
            instance.stop()
            return True, "Server stopping..."
    
    def kill_server(self, server_id):
        """Forcefully kill a Minecraft server process"""
        with self.lock:
            if server_id not in self.servers:
                return False, "Server is not running"
            
            instance = self.servers[server_id]
            if not instance.is_running():
                del self.servers[server_id]
                return False, "Server is not running"
            
            instance.kill()
            del self.servers[server_id]
            return True, "Server killed"
    
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
        # Clear the output buffer on start for fresh logs
        self.output_buffer = []
        
        args = ['java'] + self.java_args.split() + ['-jar', self.executable, 'nogui']
        
        # Set environment to reduce buffering
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'
        
        self.process = subprocess.Popen(
            args,
            cwd=str(self.server_path),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr into stdout for unified output
            text=False,  # Use binary mode for better control
            bufsize=0,  # Unbuffered
            env=env
        )
        
        # Start single unified output reader thread
        threading.Thread(target=self._read_output_unbuffered, daemon=True).start()
        threading.Thread(target=self._monitor_process, daemon=True).start()
    
    def _read_output_unbuffered(self):
        """Read output from the process in real-time and broadcast to clients"""
        try:
            buffer = b''
            while self.process.poll() is None:
                # Read available data (non-blocking style with small chunks)
                chunk = self.process.stdout.read(1)
                if chunk:
                    buffer += chunk
                    # Check for newline to send complete lines
                    if chunk == b'\n':
                        try:
                            line = buffer.decode('utf-8', errors='replace')
                        except:
                            line = buffer.decode('latin-1', errors='replace')
                        self._broadcast({'type': 'output', 'data': line, 'serverId': self.server_id})
                        self._add_to_buffer(line)
                        buffer = b''
            
            # Read any remaining output after process exits
            remaining = self.process.stdout.read()
            if remaining:
                try:
                    line = remaining.decode('utf-8', errors='replace')
                except:
                    line = remaining.decode('latin-1', errors='replace')
                if line:
                    self._broadcast({'type': 'output', 'data': line, 'serverId': self.server_id})
                    self._add_to_buffer(line)
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
            # Write as bytes since we're using binary mode
            self.process.stdin.write((command + '\n').encode('utf-8'))
            self.process.stdin.flush()
    
    def stop(self):
        """Stop the server gracefully by sending 'stop' command"""
        if self.is_running():
            self.send_command('stop')
            
            def force_kill():
                time.sleep(30)
                if self.is_running():
                    self.process.kill()
            
            threading.Thread(target=force_kill, daemon=True).start()
    
    def kill(self):
        """Forcefully kill the server process immediately"""
        if self.is_running():
            self.process.kill()
            self.process.wait()
    
    def get_recent_output(self, lines=100):
        """Get recent output from the buffer"""
        return self.output_buffer[-lines:]


# Initialize server manager
server_manager = ServerManager()

# Initialize backup scheduler
backup_scheduler = BackupScheduler()


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

@app.route('/settings.html')
@login_required
def settings_page():
    """Serve settings page (admin only)"""
    user_id, user = get_current_user()
    if user.get('role') != 'admin':
        return redirect('/')
    return send_from_directory('public', 'settings.html')

@app.route('/<path:path>')
def static_files(path):
    """Serve static files"""
    # Allow certain files without auth (CSS, JS, and public pages)
    public_files = ['styles.css', 'app.js', 'login.js', 'public.js', 'settings.js']
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
    # Check if registration is enabled
    if not settings_manager.get_app_settings().get('enableRegistration', True):
        return jsonify({'error': 'Registration is currently disabled'}), 403
    
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
        return jsonify({'error': 'Not authenticated'}), 401
    
    return jsonify({
        'id': user_id,
        'username': user['username'],
        'role': user['role']
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

@app.route('/api/admin/users', methods=['POST'])
@admin_required
def api_create_user():
    """Create a new user (admin only)"""
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    role = data.get('role', 'user')
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    if role not in ['admin', 'user', 'public']:
        return jsonify({'error': 'Invalid role'}), 400
    
    user_id, message = user_manager.create_user(username, password, role)
    
    if not user_id:
        return jsonify({'error': message}), 400
    
    return jsonify({'success': True, 'userId': user_id, 'message': message})

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


# ==================== Admin Server Approval API ====================

@app.route('/api/admin/servers/pending', methods=['GET'])
@admin_required
def api_get_pending_servers():
    """Get list of servers pending approval"""
    pending = server_manager.get_pending_servers()
    # Enrich with owner usernames
    for server in pending:
        owner_id = server.get('owner')
        if owner_id:
            user = user_manager.get_user_by_id(owner_id)
            server['owner'] = user.get('username', 'Unknown') if user else 'Unknown'
    return jsonify({'servers': pending})

@app.route('/api/admin/servers/<server_id>/approve', methods=['POST'])
@admin_required
def api_approve_server(server_id):
    """Approve a pending server"""
    if server_manager.approve_server(server_id):
        return jsonify({'success': True})
    return jsonify({'error': 'Server not found'}), 404

@app.route('/api/admin/servers/<server_id>/reject', methods=['DELETE'])
@admin_required
def api_reject_server(server_id):
    """Reject (delete) a pending server"""
    if server_manager.reject_server(server_id):
        return jsonify({'success': True})
    return jsonify({'error': 'Server not found'}), 404


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

@app.route('/api/server-engines', methods=['GET'])
@login_required
def get_server_engines():
    """Get list of available server engines, optionally filtered by category"""
    category = request.args.get('category')
    return jsonify({'engines': jar_manager.get_server_engines(category)})

@app.route('/api/server-engines/<engine>/versions', methods=['GET'])
@login_required
def get_engine_versions(engine):
    """Get available versions for a server engine"""
    versions = jar_manager.get_versions(engine)
    return jsonify({'versions': versions})

@app.route('/api/default-server-path', methods=['GET'])
@login_required
def get_default_server_path():
    """Get the default server installation path"""
    return jsonify({'path': str(SERVERS_DIR)})


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
    category = data.get('category', 'unmodded')
    server_engine = data.get('serverEngine')  # New: engine (paper, folia, etc.)
    server_type = data.get('serverType') or server_engine  # Backward compat
    version = data.get('version')
    download_jar = data.get('downloadJar', False)
    
    # Check if server approval is required (admins are always auto-approved)
    is_admin = user.get('role') == 'admin'
    require_approval = settings_manager.get_app_settings().get('requireServerApproval', False)
    approved = is_admin or not require_approval
    
    # Create the server configuration with owner
    server_id = server_manager.create_server(
        name=name,
        server_path=server_path,
        executable=executable,
        java_args=java_args,
        server_type=server_type,
        version=version,
        owner=user_id,
        approved=approved,
        category=category
    )
    
    # Copy JAR from serverexecutables if requested
    if download_jar and server_type and version:
        server_config = server_manager.get_server_config(server_id)
        server_dir = Path(server_config['serverPath'])
        jar_path = server_dir / executable
        
        # Copy the local JAR file to the server directory
        success, result = jar_manager.copy_jar_to_server(server_type, version, jar_path)
        if not success:
            return jsonify({
                'success': True, 
                'serverId': server_id,
                'warning': f'Server created but JAR copy failed: {result}'
            })
        
        # Create eula.txt for convenience
        eula_path = server_dir / 'eula.txt'
        eula_path.write_text('# By setting this to TRUE, you agree to the Minecraft EULA\neula=false\n')
    
    response = {'success': True, 'serverId': server_id}
    if not approved:
        response['pendingApproval'] = True
        response['message'] = 'Server created and pending admin approval'
    return jsonify(response)

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
    jar_name = request.form.get('jarName', 'server.jar')
    java_args = request.form.get('javaArgs', '-Xmx2G -Xms1G')
    category = request.form.get('category', 'unmodded')
    
    # Check if server approval is required (admins are always auto-approved)
    is_admin = user.get('role') == 'admin'
    require_approval = settings_manager.get_app_settings().get('requireServerApproval', False)
    approved = is_admin or not require_approval
    
    # Save uploaded file temporarily
    filename = secure_filename(file.filename)
    temp_path = UPLOADS_DIR / filename
    
    try:
        file.save(str(temp_path))
        
        success, result = server_manager.import_server_from_zip(
            name, temp_path, java_args, 
            jar_name=jar_name, 
            owner=user_id, 
            approved=approved,
            category=category
        )
        
        if success:
            response = {'success': True, 'serverId': result}
            if not approved:
                response['pendingApproval'] = True
                response['message'] = 'Server imported and pending admin approval'
            return jsonify(response)
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
    """Copy a server JAR from serverexecutables to an existing server"""
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
    
    # Copy from local serverexecutables directory
    success, result = jar_manager.copy_jar_to_server(server_type, version, jar_path)
    
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
    # Check if we should delete files too
    delete_files = request.args.get('deleteFiles', 'false').lower() == 'true'
    
    if server_manager.delete_server(server_id, delete_files=delete_files):
        return jsonify({'success': True})
    return jsonify({'error': 'Server not found'}), 404

@app.route('/api/servers/<server_id>/managed', methods=['GET'])
@server_access_required
def check_managed(server_id):
    """Check if a server has managed.conf"""
    is_managed = server_manager.is_managed(server_id)
    return jsonify({'managed': is_managed})

@app.route('/api/servers/<server_id>/managed/enable', methods=['POST'])
@server_access_required
def enable_management(server_id):
    """Create managed.conf for a server"""
    success, message = server_manager.enable_management(server_id)
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 400

@app.route('/api/servers/<server_id>/eula', methods=['GET'])
@server_access_required
def check_eula(server_id):
    """Check if EULA has been accepted for a server"""
    accepted = server_manager.check_eula_accepted(server_id)
    return jsonify({'accepted': accepted})

@app.route('/api/servers/<server_id>/eula/accept', methods=['POST'])
@server_access_required
def accept_eula(server_id):
    """Accept the EULA for a server"""
    success, message = server_manager.accept_eula(server_id)
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 400

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
    """Stop a server gracefully"""
    success, message = server_manager.stop_server(server_id)
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 400

@app.route('/api/servers/<server_id>/kill', methods=['POST'])
@server_access_required
def kill_server(server_id):
    """Forcefully kill a server process"""
    success, message = server_manager.kill_server(server_id)
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

# ==================== NBT File Endpoints ====================

@app.route('/api/servers/<server_id>/nbt/read', methods=['GET'])
@server_access_required
def read_nbt_file(server_id):
    """Read and parse an NBT file (.dat)"""
    requested_path = request.args.get('path', '')
    server_path = server_manager.get_server_path(server_id)
    
    if not is_safe_path(server_path, requested_path):
        return jsonify({'error': 'Access denied'}), 403
    
    full_path = server_path / requested_path
    
    if not full_path.exists():
        return jsonify({'error': 'File not found'}), 404
    
    try:
        nbt_data = nbt_editor.read_file(full_path)
        return jsonify({
            'success': True,
            'data': nbt_data,
            'compression': nbt_editor.compression
        })
    except Exception as e:
        return jsonify({'error': f'Failed to parse NBT file: {str(e)}'}), 500

@app.route('/api/servers/<server_id>/nbt/write', methods=['POST'])
@server_access_required
def write_nbt_file(server_id):
    """Write modified NBT data back to file"""
    data = request.get_json()
    file_path = data.get('path', '')
    nbt_data = data.get('data')
    compression = data.get('compression', 'gzip')
    server_path = server_manager.get_server_path(server_id)
    
    if not is_safe_path(server_path, file_path):
        return jsonify({'error': 'Access denied'}), 403
    
    full_path = server_path / file_path
    
    try:
        nbt_editor.compression = compression
        nbt_editor.write_file(full_path, nbt_data)
        return jsonify({'success': True, 'message': 'NBT file saved'})
    except Exception as e:
        return jsonify({'error': f'Failed to write NBT file: {str(e)}'}), 500

@app.route('/api/servers/<server_id>/nbt/update', methods=['POST'])
@server_access_required
def update_nbt_value(server_id):
    """Update a single value in an NBT file"""
    data = request.get_json()
    file_path = data.get('path', '')
    tag_path = data.get('tagPath', [])
    new_value = data.get('value')
    server_path = server_manager.get_server_path(server_id)
    
    if not is_safe_path(server_path, file_path):
        return jsonify({'error': 'Access denied'}), 403
    
    full_path = server_path / file_path
    
    try:
        nbt_data = nbt_editor.read_file(full_path)
        nbt_data = nbt_editor.update_value(nbt_data, tag_path, new_value)
        nbt_editor.write_file(full_path, nbt_data)
        return jsonify({'success': True, 'message': 'Value updated'})
    except Exception as e:
        return jsonify({'error': f'Failed to update NBT value: {str(e)}'}), 500

@app.route('/api/servers/<server_id>/nbt/add', methods=['POST'])
@server_access_required
def add_nbt_tag(server_id):
    """Add a new tag to an NBT file"""
    data = request.get_json()
    file_path = data.get('path', '')
    parent_path = data.get('parentPath', [])
    new_tag = data.get('tag')
    server_path = server_manager.get_server_path(server_id)
    
    if not is_safe_path(server_path, file_path):
        return jsonify({'error': 'Access denied'}), 403
    
    full_path = server_path / file_path
    
    try:
        nbt_data = nbt_editor.read_file(full_path)
        nbt_data = nbt_editor.add_tag(nbt_data, parent_path, new_tag)
        nbt_editor.write_file(full_path, nbt_data)
        return jsonify({'success': True, 'message': 'Tag added'})
    except Exception as e:
        return jsonify({'error': f'Failed to add NBT tag: {str(e)}'}), 500

@app.route('/api/servers/<server_id>/nbt/delete', methods=['POST'])
@server_access_required
def delete_nbt_tag(server_id):
    """Delete a tag from an NBT file"""
    data = request.get_json()
    file_path = data.get('path', '')
    tag_path = data.get('tagPath', [])
    server_path = server_manager.get_server_path(server_id)
    
    if not is_safe_path(server_path, file_path):
        return jsonify({'error': 'Access denied'}), 403
    
    full_path = server_path / file_path
    
    try:
        nbt_data = nbt_editor.read_file(full_path)
        nbt_data = nbt_editor.delete_tag(nbt_data, tag_path)
        nbt_editor.write_file(full_path, nbt_data)
        return jsonify({'success': True, 'message': 'Tag deleted'})
    except Exception as e:
        return jsonify({'error': f'Failed to delete NBT tag: {str(e)}'}), 500


# ==================== Player Management Endpoints ====================

def get_player_uuid(player_name):
    """Lookup player UUID from Mojang API"""
    try:
        response = requests.get(f'https://api.mojang.com/users/profiles/minecraft/{player_name}', timeout=5)
        if response.status_code == 200:
            data = response.json()
            # Format UUID with dashes
            uuid_raw = data.get('id', '')
            if len(uuid_raw) == 32:
                uuid_formatted = f"{uuid_raw[:8]}-{uuid_raw[8:12]}-{uuid_raw[12:16]}-{uuid_raw[16:20]}-{uuid_raw[20:]}"
                return uuid_formatted, data.get('name', player_name)
        return None, None
    except:
        return None, None

@app.route('/api/servers/<server_id>/players/ops', methods=['GET'])
@server_access_required
def get_operators(server_id):
    """Get list of operators from ops.json"""
    server_path = server_manager.get_server_path(server_id)
    ops_file = server_path / 'ops.json'
    
    try:
        if ops_file.exists():
            with open(ops_file, 'r') as f:
                ops = json.load(f)
            return jsonify({'operators': ops})
        return jsonify({'operators': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/players/ops', methods=['POST'])
@server_access_required
def add_operator(server_id):
    """Add a player as operator"""
    data = request.get_json()
    player_name = data.get('name', '').strip()
    level = data.get('level', 4)
    bypass_limit = data.get('bypassesPlayerLimit', False)
    
    if not player_name:
        return jsonify({'error': 'Player name is required'}), 400
    
    # Get UUID from Mojang API
    uuid, actual_name = get_player_uuid(player_name)
    if not uuid:
        return jsonify({'error': f'Could not find player "{player_name}". Make sure the name is correct.'}), 404
    
    server_path = server_manager.get_server_path(server_id)
    ops_file = server_path / 'ops.json'
    
    try:
        ops = []
        if ops_file.exists():
            with open(ops_file, 'r') as f:
                ops = json.load(f)
        
        # Check if player already exists
        for op in ops:
            if op.get('uuid') == uuid:
                return jsonify({'error': f'{actual_name} is already an operator'}), 400
        
        # Add new operator
        ops.append({
            'uuid': uuid,
            'name': actual_name,
            'level': int(level),
            'bypassesPlayerLimit': bool(bypass_limit)
        })
        
        with open(ops_file, 'w') as f:
            json.dump(ops, f, indent=2)
        
        return jsonify({'success': True, 'message': f'{actual_name} added as operator'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/players/ops/<uuid>', methods=['PUT'])
@server_access_required
def update_operator(server_id, uuid):
    """Update an operator's settings"""
    data = request.get_json()
    level = data.get('level', 4)
    bypass_limit = data.get('bypassesPlayerLimit', False)
    
    server_path = server_manager.get_server_path(server_id)
    ops_file = server_path / 'ops.json'
    
    try:
        if not ops_file.exists():
            return jsonify({'error': 'Ops file not found'}), 404
        
        with open(ops_file, 'r') as f:
            ops = json.load(f)
        
        found = False
        for op in ops:
            if op.get('uuid') == uuid:
                op['level'] = int(level)
                op['bypassesPlayerLimit'] = bool(bypass_limit)
                found = True
                break
        
        if not found:
            return jsonify({'error': 'Operator not found'}), 404
        
        with open(ops_file, 'w') as f:
            json.dump(ops, f, indent=2)
        
        return jsonify({'success': True, 'message': 'Operator updated'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/players/ops/<uuid>', methods=['DELETE'])
@server_access_required
def remove_operator(server_id, uuid):
    """Remove an operator"""
    server_path = server_manager.get_server_path(server_id)
    ops_file = server_path / 'ops.json'
    
    try:
        if not ops_file.exists():
            return jsonify({'error': 'Ops file not found'}), 404
        
        with open(ops_file, 'r') as f:
            ops = json.load(f)
        
        original_len = len(ops)
        ops = [op for op in ops if op.get('uuid') != uuid]
        
        if len(ops) == original_len:
            return jsonify({'error': 'Operator not found'}), 404
        
        with open(ops_file, 'w') as f:
            json.dump(ops, f, indent=2)
        
        return jsonify({'success': True, 'message': 'Operator removed'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/players/whitelist', methods=['GET'])
@server_access_required
def get_whitelist(server_id):
    """Get whitelist"""
    server_path = server_manager.get_server_path(server_id)
    whitelist_file = server_path / 'whitelist.json'
    
    try:
        if whitelist_file.exists():
            with open(whitelist_file, 'r') as f:
                whitelist = json.load(f)
            return jsonify({'whitelist': whitelist})
        return jsonify({'whitelist': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/players/whitelist', methods=['POST'])
@server_access_required
def add_to_whitelist(server_id):
    """Add a player to whitelist"""
    data = request.get_json()
    player_name = data.get('name', '').strip()
    
    if not player_name:
        return jsonify({'error': 'Player name is required'}), 400
    
    uuid, actual_name = get_player_uuid(player_name)
    if not uuid:
        return jsonify({'error': f'Could not find player "{player_name}"'}), 404
    
    server_path = server_manager.get_server_path(server_id)
    whitelist_file = server_path / 'whitelist.json'
    
    try:
        whitelist = []
        if whitelist_file.exists():
            with open(whitelist_file, 'r') as f:
                whitelist = json.load(f)
        
        for player in whitelist:
            if player.get('uuid') == uuid:
                return jsonify({'error': f'{actual_name} is already whitelisted'}), 400
        
        whitelist.append({'uuid': uuid, 'name': actual_name})
        
        with open(whitelist_file, 'w') as f:
            json.dump(whitelist, f, indent=2)
        
        return jsonify({'success': True, 'message': f'{actual_name} added to whitelist'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/players/whitelist/<uuid>', methods=['DELETE'])
@server_access_required
def remove_from_whitelist(server_id, uuid):
    """Remove a player from whitelist"""
    server_path = server_manager.get_server_path(server_id)
    whitelist_file = server_path / 'whitelist.json'
    
    try:
        if not whitelist_file.exists():
            return jsonify({'error': 'Whitelist file not found'}), 404
        
        with open(whitelist_file, 'r') as f:
            whitelist = json.load(f)
        
        original_len = len(whitelist)
        whitelist = [p for p in whitelist if p.get('uuid') != uuid]
        
        if len(whitelist) == original_len:
            return jsonify({'error': 'Player not found in whitelist'}), 404
        
        with open(whitelist_file, 'w') as f:
            json.dump(whitelist, f, indent=2)
        
        return jsonify({'success': True, 'message': 'Player removed from whitelist'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/players/banned', methods=['GET'])
@server_access_required
def get_banned_players(server_id):
    """Get banned players list"""
    server_path = server_manager.get_server_path(server_id)
    banned_file = server_path / 'banned-players.json'
    
    try:
        if banned_file.exists():
            with open(banned_file, 'r') as f:
                banned = json.load(f)
            return jsonify({'banned': banned})
        return jsonify({'banned': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/players/banned', methods=['POST'])
@server_access_required
def ban_player(server_id):
    """Ban a player"""
    data = request.get_json()
    player_name = data.get('name', '').strip()
    reason = data.get('reason', 'Banned by server administrator')
    
    if not player_name:
        return jsonify({'error': 'Player name is required'}), 400
    
    uuid, actual_name = get_player_uuid(player_name)
    if not uuid:
        return jsonify({'error': f'Could not find player "{player_name}"'}), 404
    
    server_path = server_manager.get_server_path(server_id)
    banned_file = server_path / 'banned-players.json'
    
    try:
        banned = []
        if banned_file.exists():
            with open(banned_file, 'r') as f:
                banned = json.load(f)
        
        for player in banned:
            if player.get('uuid') == uuid:
                return jsonify({'error': f'{actual_name} is already banned'}), 400
        
        banned.append({
            'uuid': uuid,
            'name': actual_name,
            'created': datetime.now().strftime('%Y-%m-%d %H:%M:%S +0000'),
            'source': 'MServerController',
            'expires': 'forever',
            'reason': reason
        })
        
        with open(banned_file, 'w') as f:
            json.dump(banned, f, indent=2)
        
        return jsonify({'success': True, 'message': f'{actual_name} has been banned'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/players/banned/<uuid>', methods=['DELETE'])
@server_access_required
def unban_player(server_id, uuid):
    """Unban a player"""
    server_path = server_manager.get_server_path(server_id)
    banned_file = server_path / 'banned-players.json'
    
    try:
        if not banned_file.exists():
            return jsonify({'error': 'Banned players file not found'}), 404
        
        with open(banned_file, 'r') as f:
            banned = json.load(f)
        
        original_len = len(banned)
        banned = [p for p in banned if p.get('uuid') != uuid]
        
        if len(banned) == original_len:
            return jsonify({'error': 'Player not found in ban list'}), 404
        
        with open(banned_file, 'w') as f:
            json.dump(banned, f, indent=2)
        
        return jsonify({'success': True, 'message': 'Player unbanned'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/players/playerdata', methods=['GET'])
@server_access_required
def get_playerdata(server_id):
    """Get list of player data files"""
    server_path = server_manager.get_server_path(server_id)
    
    # Try different world folder names
    world_folders = ['world', 'world_nether', 'world_the_end']
    playerdata_path = None
    
    for world in world_folders:
        path = server_path / world / 'playerdata'
        if path.exists():
            playerdata_path = path
            break
    
    if not playerdata_path:
        # Try to find any folder with playerdata
        for item in server_path.iterdir():
            if item.is_dir():
                pd_path = item / 'playerdata'
                if pd_path.exists():
                    playerdata_path = pd_path
                    break
    
    if not playerdata_path or not playerdata_path.exists():
        return jsonify({'players': [], 'message': 'No playerdata folder found'})
    
    try:
        players = []
        for item in playerdata_path.iterdir():
            if item.suffix == '.dat':
                stat = item.stat()
                players.append({
                    'uuid': item.stem,
                    'filename': item.name,
                    'size': stat.st_size,
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
        
        return jsonify({'players': players})
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


# ==================== Mods/Plugins API ====================

@app.route('/api/servers/<server_id>/mods', methods=['GET'])
@server_access_required
def list_mods(server_id):
    """List mods and plugins for a server"""
    server_path = server_manager.get_server_path(server_id)
    
    result = {
        'plugins': [],
        'mods': []
    }
    
    # List plugins folder
    plugins_dir = server_path / 'plugins'
    if plugins_dir.exists():
        for item in plugins_dir.iterdir():
            if item.is_file() and (item.suffix == '.jar' or item.name.endswith('.jar.disabled')):
                stat = item.stat()
                result['plugins'].append({
                    'name': item.name,
                    'size': stat.st_size,
                    'modified': stat.st_mtime * 1000
                })
    
    # List mods folder
    mods_dir = server_path / 'mods'
    if mods_dir.exists():
        for item in mods_dir.iterdir():
            if item.is_file() and (item.suffix == '.jar' or item.name.endswith('.jar.disabled')):
                stat = item.stat()
                result['mods'].append({
                    'name': item.name,
                    'size': stat.st_size,
                    'modified': stat.st_mtime * 1000
                })
    
    # Sort by name
    result['plugins'].sort(key=lambda x: x['name'].lower())
    result['mods'].sort(key=lambda x: x['name'].lower())
    
    return jsonify(result)

@app.route('/api/servers/<server_id>/mods/upload', methods=['POST'])
@limiter.limit("20 per 15 minutes")
@server_access_required
def upload_mod(server_id):
    """Upload a mod or plugin"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    mod_type = request.form.get('type', 'plugins')
    
    if mod_type not in ['plugins', 'mods']:
        return jsonify({'error': 'Invalid mod type'}), 400
    
    if not file.filename.endswith('.jar'):
        return jsonify({'error': 'File must be a JAR file'}), 400
    
    server_path = server_manager.get_server_path(server_id)
    target_dir = server_path / mod_type
    target_dir.mkdir(parents=True, exist_ok=True)
    
    filename = secure_filename(file.filename)
    dest_path = target_dir / filename
    
    try:
        file.save(str(dest_path))
        return jsonify({'success': True, 'filename': filename})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/mods/<mod_type>/<filename>/enable', methods=['POST'])
@server_access_required
def enable_mod(server_id, mod_type, filename):
    """Enable a disabled mod"""
    if mod_type not in ['plugins', 'mods']:
        return jsonify({'error': 'Invalid mod type'}), 400
    
    server_path = server_manager.get_server_path(server_id)
    mod_dir = server_path / mod_type
    
    # Security: Validate filename doesn't contain path traversal
    safe_filename = secure_filename(filename)
    if safe_filename != filename or '..' in filename or '/' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    
    disabled_path = mod_dir / filename
    if not disabled_path.exists() or not filename.endswith('.disabled'):
        return jsonify({'error': 'Disabled mod not found'}), 404
    
    # Enable by removing .disabled extension
    enabled_name = filename.rsplit('.disabled', 1)[0]
    enabled_path = mod_dir / enabled_name
    
    try:
        disabled_path.rename(enabled_path)
        return jsonify({'success': True, 'filename': enabled_name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/mods/<mod_type>/<filename>/disable', methods=['POST'])
@server_access_required
def disable_mod(server_id, mod_type, filename):
    """Disable a mod by renaming it"""
    if mod_type not in ['plugins', 'mods']:
        return jsonify({'error': 'Invalid mod type'}), 400
    
    server_path = server_manager.get_server_path(server_id)
    mod_dir = server_path / mod_type
    
    # Security: Validate filename doesn't contain path traversal
    safe_filename = secure_filename(filename)
    if safe_filename != filename or '..' in filename or '/' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    
    mod_path = mod_dir / filename
    if not mod_path.exists():
        return jsonify({'error': 'Mod not found'}), 404
    
    # Disable by adding .disabled extension
    disabled_path = mod_dir / (filename + '.disabled')
    
    try:
        mod_path.rename(disabled_path)
        return jsonify({'success': True, 'filename': filename + '.disabled'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/mods/<mod_type>/<filename>', methods=['DELETE'])
@server_access_required
def delete_mod(server_id, mod_type, filename):
    """Delete a mod or plugin"""
    if mod_type not in ['plugins', 'mods']:
        return jsonify({'error': 'Invalid mod type'}), 400
    
    server_path = server_manager.get_server_path(server_id)
    mod_dir = server_path / mod_type
    
    # Security: Validate filename doesn't contain path traversal
    safe_filename = secure_filename(filename)
    if safe_filename != filename or '..' in filename or '/' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    
    mod_path = mod_dir / filename
    if not mod_path.exists():
        return jsonify({'error': 'Mod not found'}), 404
    
    try:
        mod_path.unlink()
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
    
    # Security: sanitize filename and prevent path traversal
    backup_name = secure_filename(backup_name)
    if not backup_name or '..' in backup_name or '/' in backup_name:
        return jsonify({'error': 'Invalid backup name'}), 400
    
    backup_path = BACKUPS_DIR / server_id / backup_name
    
    # Additional security check: ensure path is within backups directory
    try:
        backup_path = backup_path.resolve()
        if not str(backup_path).startswith(str(BACKUPS_DIR.resolve())):
            return jsonify({'error': 'Invalid backup path'}), 400
    except Exception:
        return jsonify({'error': 'Invalid backup path'}), 400
    
    if not backup_path.exists():
        return jsonify({'error': 'Backup not found'}), 404
    
    return send_file(backup_path, as_attachment=True)

@app.route('/api/servers/<server_id>/backups/delete', methods=['DELETE'])
@server_access_required
def delete_backup(server_id):
    """Delete a backup"""
    data = request.get_json()
    backup_name = data.get('name', '')
    
    # Security: sanitize filename and prevent path traversal
    backup_name = secure_filename(backup_name)
    if not backup_name or '..' in backup_name or '/' in backup_name:
        return jsonify({'error': 'Invalid backup name'}), 400
    
    backup_path = BACKUPS_DIR / server_id / backup_name
    
    # Additional security check: ensure path is within backups directory
    try:
        backup_path = backup_path.resolve()
        if not str(backup_path).startswith(str(BACKUPS_DIR.resolve())):
            return jsonify({'error': 'Invalid backup path'}), 400
    except Exception:
        return jsonify({'error': 'Invalid backup path'}), 400
    
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
    
    # Security: sanitize filename and prevent path traversal
    backup_name = secure_filename(backup_name)
    if not backup_name or '..' in backup_name or '/' in backup_name:
        return jsonify({'error': 'Invalid backup name'}), 400
    
    backup_path = BACKUPS_DIR / server_id / backup_name
    
    # Additional security check: ensure path is within backups directory
    try:
        backup_path = backup_path.resolve()
        if not str(backup_path).startswith(str(BACKUPS_DIR.resolve())):
            return jsonify({'error': 'Invalid backup path'}), 400
    except Exception:
        return jsonify({'error': 'Invalid backup path'}), 400
    
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


# ==================== Backup Schedule API ====================

@app.route('/api/servers/<server_id>/backups/schedule', methods=['GET'])
@server_access_required
def get_backup_schedule(server_id):
    """Get the backup schedule for a server"""
    schedule = backup_scheduler.get_schedule(server_id)
    if schedule:
        return jsonify({'schedule': schedule})
    return jsonify({'schedule': None})

@app.route('/api/servers/<server_id>/backups/schedule', methods=['POST'])
@server_access_required
def set_backup_schedule(server_id):
    """Set or update the backup schedule for a server"""
    data = request.get_json()
    
    # Validate server exists
    server_config = server_manager.get_server_config(server_id)
    if not server_config:
        return jsonify({'error': 'Server not found'}), 404
    
    schedule = backup_scheduler.set_schedule(server_id, {
        'enabled': data.get('enabled', True),
        'type': data.get('type', 'daily'),
        'hour': data.get('hour', 3),
        'minute': data.get('minute', 0),
        'dayOfWeek': data.get('dayOfWeek', 0),
        'cron': data.get('cron', ''),
        'stopServer': data.get('stopServer', True),
        'restartAfter': data.get('restartAfter', True),
        'maxBackups': data.get('maxBackups', 7)
    })
    
    return jsonify({'success': True, 'schedule': schedule})

@app.route('/api/servers/<server_id>/backups/schedule', methods=['DELETE'])
@server_access_required
def delete_backup_schedule(server_id):
    """Delete the backup schedule for a server"""
    if backup_scheduler.delete_schedule(server_id):
        return jsonify({'success': True})
    return jsonify({'error': 'No schedule found for this server'}), 404

@app.route('/api/backups/schedules', methods=['GET'])
@login_required
def get_all_backup_schedules():
    """Get all backup schedules (admin sees all, users see their own)"""
    user = user_manager.get_user(session['user_id'])
    all_schedules = backup_scheduler.get_all_schedules()
    
    if user.get('role') == 'admin':
        return jsonify({'schedules': all_schedules})
    
    # Filter to only user's servers
    user_schedules = {}
    for server_id, schedule in all_schedules.items():
        server_config = server_manager.get_server_config(server_id)
        if server_config and server_config.get('owner') == session['user_id']:
            user_schedules[server_id] = schedule
    
    return jsonify({'schedules': user_schedules})


# ==================== Settings API ====================

@app.route('/api/settings', methods=['GET'])
@login_required
def get_settings():
    """Get application settings"""
    return jsonify(settings_manager.get_settings())

@app.route('/api/settings/branding', methods=['GET'])
def get_branding():
    """Get branding settings (public)"""
    return jsonify(settings_manager.get_branding())

@app.route('/api/settings/branding', methods=['PUT'])
@admin_required
def update_branding():
    """Update branding settings (admin only)"""
    data = request.get_json()
    branding = settings_manager.update_branding(data)
    return jsonify({'success': True, 'branding': branding})

@app.route('/api/settings/app', methods=['GET'])
@admin_required
def get_app_settings():
    """Get app settings (admin only)"""
    return jsonify(settings_manager.get_app_settings())

@app.route('/api/settings/app', methods=['PUT'])
@admin_required
def update_app_settings():
    """Update app settings (admin only)"""
    data = request.get_json()
    app_settings = settings_manager.update_app_settings(data)
    return jsonify({'success': True, 'settings': app_settings})


# ==================== System Stats API ====================

@app.route('/api/stats/current', methods=['GET'])
@admin_required
def get_current_stats():
    """Get current system stats"""
    return jsonify(stats_manager.get_current_stats())

@app.route('/api/stats/history', methods=['GET'])
@admin_required
def get_stats_history():
    """Get stats history"""
    hours = request.args.get('hours', 24, type=int)
    # Limit to 7 days max
    hours = min(hours, 24 * 7)
    history = stats_manager.get_history(hours)
    return jsonify({'history': history})


# ==================== JAR Downloader API ====================

SERVER_EXECUTABLES_DIR = BASE_DIR / 'serverexecutables'

@app.route('/api/tools/jar-downloader/download', methods=['POST'])
@admin_required
def download_jar():
    """Download a JAR file to serverexecutables folder"""
    data = request.get_json()
    server_type = data.get('type', '').strip().lower()
    version = data.get('version', '').strip()
    url = data.get('url', '').strip()
    
    if not server_type or not version or not url:
        return jsonify({'error': 'Missing required fields: type, version, url'}), 400
    
    # Sanitize server type (only allow alphanumeric and dashes)
    import re
    if not re.match(r'^[a-z0-9-]+$', server_type):
        return jsonify({'error': 'Invalid server type. Use only letters, numbers, and dashes.'}), 400
    
    # Create directory structure
    type_dir = SERVER_EXECUTABLES_DIR / server_type
    type_dir.mkdir(parents=True, exist_ok=True)
    
    # Determine filename: <TYPE>-<VERSION>.jar (or .zip for bedrock)
    extension = '.zip' if 'bedrock' in server_type.lower() else '.jar'
    filename = f"{server_type}-{version}{extension}"
    filepath = type_dir / filename
    
    try:
        # Download the file
        response = requests.get(url, stream=True, timeout=120)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
        
        return jsonify({
            'success': True,
            'message': f'Downloaded {filename} successfully',
            'path': str(filepath.relative_to(BASE_DIR)),
            'size': downloaded
        })
        
    except requests.exceptions.RequestException as e:
        # Clean up partial download
        if filepath.exists():
            filepath.unlink()
        return jsonify({'error': f'Download failed: {str(e)}'}), 500
    except Exception as e:
        if filepath.exists():
            filepath.unlink()
        return jsonify({'error': f'Error: {str(e)}'}), 500

@app.route('/api/tools/jar-downloader/list', methods=['GET'])
@admin_required
def list_downloaded_jars():
    """List all downloaded JAR files"""
    jars = {}
    
    if SERVER_EXECUTABLES_DIR.exists():
        for type_dir in SERVER_EXECUTABLES_DIR.iterdir():
            if type_dir.is_dir():
                server_type = type_dir.name
                jars[server_type] = []
                for jar_file in sorted(type_dir.iterdir(), reverse=True):
                    if jar_file.is_file() and (jar_file.suffix in ['.jar', '.zip']):
                        jars[server_type].append({
                            'filename': jar_file.name,
                            'size': jar_file.stat().st_size,
                            'path': str(jar_file.relative_to(BASE_DIR))
                        })
    
    return jsonify({'jars': jars})

@app.route('/api/tools/jar-downloader/delete', methods=['DELETE'])
@admin_required
def delete_downloaded_jar():
    """Delete a downloaded JAR file"""
    data = request.get_json()
    server_type = data.get('type', '').strip().lower()
    filename = data.get('filename', '').strip()
    
    if not server_type or not filename:
        return jsonify({'error': 'Missing required fields: type, filename'}), 400
    
    filepath = SERVER_EXECUTABLES_DIR / server_type / filename
    
    if not filepath.exists():
        return jsonify({'error': 'File not found'}), 404
    
    # Security check - ensure path is within serverexecutables
    try:
        filepath.relative_to(SERVER_EXECUTABLES_DIR)
    except ValueError:
        return jsonify({'error': 'Invalid path'}), 400
    
    try:
        filepath.unlink()
        return jsonify({'success': True, 'message': f'Deleted {filename}'})
    except Exception as e:
        return jsonify({'error': f'Failed to delete: {str(e)}'}), 500


# ==================== Tools API ====================

@app.route('/api/tools', methods=['GET'])
@admin_required
def list_tools():
    """List available tools in the tools directory"""
    tools = []
    try:
        if TOOLS_DIR.exists():
            for item in TOOLS_DIR.iterdir():
                if item.suffix == '.py' and item.is_file():
                    # Read first line for description
                    description = ''
                    try:
                        with open(item, 'r') as f:
                            first_lines = f.readlines()[:5]
                            for line in first_lines:
                                if line.startswith('#') and not line.startswith('#!'):
                                    description = line[1:].strip()
                                    break
                                elif line.startswith('"""') or line.startswith("'''"):
                                    description = line.strip().strip('"\'')
                                    break
                    except Exception:
                        pass
                    
                    tools.append({
                        'name': item.stem,
                        'filename': item.name,
                        'description': description or 'No description'
                    })
        
        # Sort tools alphabetically
        tools.sort(key=lambda x: x['name'].lower())
        
    except Exception as e:
        return jsonify({'error': str(e), 'tools': []}), 500
    
    return jsonify({'tools': tools})

@app.route('/api/tools/upload', methods=['POST'])
@admin_required
def upload_tool():
    """Upload a Python tool file"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    # Validate file extension - only allow .py files
    if not file.filename.lower().endswith('.py'):
        return jsonify({'error': 'Only Python (.py) files are allowed'}), 400
    
    # Secure the filename
    filename = secure_filename(file.filename)
    
    # Ensure it still has .py extension after securing
    if not filename.lower().endswith('.py'):
        filename = filename + '.py'
    
    # Validate the file content is valid Python (basic check)
    try:
        content = file.read().decode('utf-8')
        file.seek(0)  # Reset file pointer
        
        # Check if file starts with shebang or comments (typical Python file)
        # Also compile to check for syntax errors
        compile(content, filename, 'exec')
    except SyntaxError as e:
        return jsonify({'error': f'Invalid Python syntax: {str(e)}'}), 400
    except UnicodeDecodeError:
        return jsonify({'error': 'File must be valid UTF-8 text'}), 400
    except Exception as e:
        return jsonify({'error': f'Invalid file: {str(e)}'}), 400
    
    # Ensure tools directory exists
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Save the file
    tool_path = TOOLS_DIR / filename
    
    try:
        file.save(str(tool_path))
        return jsonify({
            'success': True,
            'message': f'Tool "{filename}" uploaded successfully',
            'filename': filename
        })
    except Exception as e:
        return jsonify({'error': f'Failed to save file: {str(e)}'}), 500


@app.route('/api/tools/<tool_name>/delete', methods=['DELETE'])
@admin_required
def delete_tool(tool_name):
    """Delete a tool from the tools directory"""
    tool_path = TOOLS_DIR / f'{tool_name}.py'
    
    if not tool_path.exists():
        return jsonify({'error': 'Tool not found'}), 404
    
    # Security: ensure path is within tools directory
    try:
        tool_path = tool_path.resolve()
        if not str(tool_path).startswith(str(TOOLS_DIR.resolve())):
            return jsonify({'error': 'Invalid tool path'}), 400
    except Exception:
        return jsonify({'error': 'Invalid tool'}), 400
    
    try:
        tool_path.unlink()
        return jsonify({
            'success': True,
            'message': f'Tool "{tool_name}" deleted successfully'
        })
    except Exception as e:
        return jsonify({'error': f'Failed to delete tool: {str(e)}'}), 500


@app.route('/api/tools/<tool_name>/run', methods=['POST'])
@admin_required
def run_tool(tool_name):
    """Run a tool from the tools directory with optional arguments"""
    tool_path = TOOLS_DIR / f'{tool_name}.py'
    
    if not tool_path.exists():
        return jsonify({'error': 'Tool not found'}), 404
    
    # Security: ensure path is within tools directory
    try:
        tool_path = tool_path.resolve()
        if not str(tool_path).startswith(str(TOOLS_DIR.resolve())):
            return jsonify({'error': 'Invalid tool path'}), 400
    except Exception:
        return jsonify({'error': 'Invalid tool'}), 400
    
    # Get optional arguments from request body
    data = request.get_json() or {}
    args_string = data.get('args', '').strip()
    timeout_seconds = min(data.get('timeout', 300), 600)  # Max 10 minutes
    
    # Parse arguments (split by whitespace, respecting quotes)
    import shlex
    try:
        args_list = shlex.split(args_string) if args_string else []
    except ValueError as e:
        return jsonify({'error': f'Invalid arguments: {str(e)}'}), 400
    
    # Build command
    command = ['python3', str(tool_path)] + args_list
    
    try:
        # Run the tool and capture output
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(BASE_DIR)
        )
        
        return jsonify({
            'success': result.returncode == 0,
            'output': result.stdout,
            'error': result.stderr,
            'returnCode': result.returncode,
            'command': ' '.join(command)
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': f'Tool execution timed out ({timeout_seconds}s limit)'}), 408
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
            # Only send recent output if server is running to avoid stale log spam
            if instance.is_running():
                for line in instance.get_recent_output():
                    emit('message', {'type': 'output', 'data': line, 'serverId': server_id})
            
            # Always send current status
            emit('message', {'type': 'status', 'running': instance.is_running(), 'serverId': server_id})


if __name__ == '__main__':
    print(f'MServerController running on http://localhost:{PORT}')
    print('⚠️  WARNING: Default admin credentials are admin/admin - change immediately!')
    socketio.run(app, host='0.0.0.0', port=PORT, debug=False, allow_unsafe_werkzeug=True)
