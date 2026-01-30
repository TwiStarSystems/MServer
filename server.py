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
import socket
import select
import pyotp
import qrcode
import argparse
import sys
from enum import Enum
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
from werkzeug.middleware.proxy_fix import ProxyFix

# Initialize Flask app
app = Flask(__name__, static_folder='public', static_url_path='')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Disable caching for development

# Configure ProxyFix for reverse proxy (e.g., Nginx) headers
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

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
RESOURCEPACKS_DIR = BASE_DIR / 'public' / 'resourcepacks'
CONFIG_PATH = BASE_DIR / 'config.json'
USERS_PATH = BASE_DIR / 'users.json'
SETTINGS_PATH = BASE_DIR / 'settings.json'
SCHEDULES_PATH = BASE_DIR / 'schedules.json'
TASKS_PATH = BASE_DIR / 'tasks.json'
STATS_PATH = BASE_DIR / 'stats.json'
JAR_URLS_PATH = BASE_DIR / 'configs' / 'jarurls.conf'
API_URLS_PATH = BASE_DIR / 'configs' / 'apiurls.json'
TOOLS_DIR = BASE_DIR / 'tools'
VERSION_FILE = BASE_DIR / 'version'

# Ensure directories exist
for directory in [SERVERS_DIR, BACKUPS_DIR, UPLOADS_DIR, TOOLS_DIR, RESOURCEPACKS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)


# ==================== Version Helper Functions ====================

def read_version_file():
    """
    Read version from version file.
    Returns version string or None if file doesn't exist or is invalid.
    Supports both 'version=X.X.X' and 'X.X.X' formats.
    """
    try:
        if not VERSION_FILE.exists():
            return None

        content = VERSION_FILE.read_text().strip()

        # Try 'version=X.X.X' format first
        if '=' in content:
            parts = content.split('=', 1)
            if len(parts) == 2:
                version = parts[1].strip()
                # Validate format
                if version and all(c.isdigit() or c == '.' for c in version):
                    return version

        # Try plain 'X.X.X' format
        if all(c.isdigit() or c == '.' for c in content):
            return content

        return None
    except Exception as e:
        print(f"[Version] Error reading version file: {e}")
        return None


def get_current_version():
    """
    Get current version with fallback to git if version file doesn't exist.
    Returns tuple: (version_string, source)
    source can be: 'file', 'git', or 'unknown'
    """
    # Try reading from version file first
    file_version = read_version_file()
    if file_version:
        return (file_version, 'file')

    # Fallback to git
    try:
        result = subprocess.run(
            ['git', 'describe', '--tags', '--always', '--abbrev=7'],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            return (version, 'git')
    except Exception as e:
        print(f"[Version] Error getting version from git: {e}")

    return ('unknown', 'unknown')


def get_remote_version_file():
    """
    Fetch the version file from the remote repository.
    Returns version string or None if unable to fetch.
    """
    try:
        # Fetch latest from remote
        subprocess.run(
            ['git', 'fetch', 'origin', 'main'],
            cwd=BASE_DIR,
            capture_output=True,
            timeout=10
        )

        # Get version file content from origin/main
        result = subprocess.run(
            ['git', 'show', 'origin/main:version'],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            content = result.stdout.strip()

            # Parse content (supports both formats)
            if '=' in content:
                parts = content.split('=', 1)
                if len(parts) == 2:
                    return parts[1].strip()

            # Plain version format
            if all(c.isdigit() or c == '.' for c in content):
                return content

        return None
    except Exception as e:
        print(f"[Version] Error fetching remote version: {e}")
        return None


# ==================== Settings Manager ====================

class SettingsManager:
    """Manages application settings including branding"""
    
    DEFAULT_SETTINGS = {
        'branding': {
            'siteTitle': 'MServerController',
            'siteIcon': '',
            'footerAddition': '',
            'baseUrl': ''
        },
        'app': {
            'enableRegistration': True,
            'requireApproval': True,
            'requireServerApproval': False
        },
        'mfa': {
            'requireMfaForAdmins': False,
            'requireMfaForAllUsers': False
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
        
        for key in ['siteTitle', 'siteIcon', 'footerAddition', 'baseUrl']:
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


# ==================== Task Scheduler ====================

class TaskScheduler:
    """Manages scheduled tasks for servers (start/stop/reboot/commands)"""
    
    def __init__(self, server_manager, socketio):
        self.server_manager = server_manager
        self.socketio = socketio
        self.tasks = self._load_tasks()
        self.scheduler = BackgroundScheduler()
        self.scheduler.start()
        self._restore_tasks()
    
    def _load_tasks(self):
        """Load tasks from file"""
        if TASKS_PATH.exists():
            try:
                with open(TASKS_PATH, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {'tasks': {}}
    
    def _save_tasks(self):
        """Save tasks to file"""
        with open(TASKS_PATH, 'w') as f:
            json.dump(self.tasks, f, indent=2)
    
    def _restore_tasks(self):
        """Restore all tasks from saved config on startup"""
        for server_id, server_tasks in self.tasks.get('tasks', {}).items():
            for task_id, task in server_tasks.items():
                if task.get('enabled', False):
                    self._add_job(server_id, task_id, task)
    
    def _add_job(self, server_id, task_id, task):
        """Add a scheduled task job"""
        job_id = f"task_{server_id}_{task_id}"
        
        # Remove existing job if any
        try:
            self.scheduler.remove_job(job_id)
        except:
            pass
        
        # Parse cron expression
        cron_expr = task.get('interval', '0 3 * * *')
        try:
            parts = cron_expr.split()
            if len(parts) == 5:
                trigger = CronTrigger(
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4]
                )
                
                self.scheduler.add_job(
                    self._execute_task,
                    trigger=trigger,
                    id=job_id,
                    args=[server_id, task_id]
                )
                print(f"[TaskScheduler] Added job {job_id} with schedule: {cron_expr}")
        except Exception as e:
            print(f"[TaskScheduler] Failed to add job {job_id}: {e}")
    
    def _execute_task(self, server_id, task_id):
        """Execute a scheduled task"""
        print(f"[TaskScheduler] Executing task {task_id} for server {server_id}")
        
        try:
            task = self.tasks.get('tasks', {}).get(server_id, {}).get(task_id)
            if not task:
                print(f"[TaskScheduler] Task {task_id} not found")
                return
            
            if not task.get('enabled', False):
                print(f"[TaskScheduler] Task {task_id} is disabled")
                return
            
            action = task.get('action', '')
            
            # Execute the action
            if action == 'START':
                self._execute_start(server_id, task)
            elif action == 'STOP':
                self._execute_stop(server_id, task)
            elif action == 'REBOOT':
                self._execute_reboot(server_id, task)
            elif action == 'COMMAND':
                self._execute_command(server_id, task)
            
            # Update task execution count
            if 'tasks' not in self.tasks:
                self.tasks['tasks'] = {}
            if server_id not in self.tasks['tasks']:
                self.tasks['tasks'][server_id] = {}
            
            self.tasks['tasks'][server_id][task_id]['lastRun'] = datetime.now().isoformat()
            self.tasks['tasks'][server_id][task_id]['runCount'] = self.tasks['tasks'][server_id][task_id].get('runCount', 0) + 1
            
            # Check if task should be disabled or deleted
            run_limit = task.get('runs', 0)
            run_count = self.tasks['tasks'][server_id][task_id]['runCount']
            delete_after_execution = task.get('deleteAfterExecution', False)
            delete_after_runs = task.get('deleteAfterRunsCount', False)
            
            if delete_after_execution:
                # Delete task immediately
                self.delete_task(server_id, task_id)
                print(f"[TaskScheduler] Deleted task {task_id} after execution")
            elif run_limit > 0 and run_count >= run_limit:
                if delete_after_runs:
                    # Delete task after reaching run limit
                    self.delete_task(server_id, task_id)
                    print(f"[TaskScheduler] Deleted task {task_id} after {run_count} runs")
                else:
                    # Just disable the task
                    self.tasks['tasks'][server_id][task_id]['enabled'] = False
                    self._save_tasks()
                    try:
                        self.scheduler.remove_job(f"task_{server_id}_{task_id}")
                    except:
                        pass
                    print(f"[TaskScheduler] Disabled task {task_id} after {run_count} runs")
            else:
                self._save_tasks()
            
            print(f"[TaskScheduler] Task {task_id} executed successfully")
            
        except Exception as e:
            print(f"[TaskScheduler] Task execution failed for {task_id}: {e}")
    
    def _execute_start(self, server_id, task):
        """Start the server"""
        try:
            if not self.server_manager.is_running(server_id):
                self.server_manager.start_server(server_id)
                print(f"[TaskScheduler] Started server {server_id}")
            else:
                print(f"[TaskScheduler] Server {server_id} is already running")
        except Exception as e:
            print(f"[TaskScheduler] Failed to start server {server_id}: {e}")
    
    def _execute_stop(self, server_id, task):
        """Stop the server"""
        try:
            if self.server_manager.is_running(server_id):
                self.server_manager.stop_server(server_id)
                print(f"[TaskScheduler] Stopped server {server_id}")
            else:
                print(f"[TaskScheduler] Server {server_id} is not running")
        except Exception as e:
            print(f"[TaskScheduler] Failed to stop server {server_id}: {e}")
    
    def _execute_reboot(self, server_id, task):
        """Reboot the server (stop, wait, start)"""
        try:
            if self.server_manager.is_running(server_id):
                print(f"[TaskScheduler] Rebooting server {server_id}...")
                
                # Stop the server
                self.server_manager.stop_server(server_id)
                
                # Wait for process to end
                import time
                max_wait = 60  # Maximum 60 seconds wait
                waited = 0
                while self.server_manager.is_running(server_id) and waited < max_wait:
                    time.sleep(1)
                    waited += 1
                
                # Wait additional 3 seconds
                time.sleep(3)
                
                # Start the server
                self.server_manager.start_server(server_id)
                print(f"[TaskScheduler] Server {server_id} rebooted successfully")
            else:
                # Server not running, just start it
                self.server_manager.start_server(server_id)
                print(f"[TaskScheduler] Server {server_id} was not running, started it")
        except Exception as e:
            print(f"[TaskScheduler] Failed to reboot server {server_id}: {e}")
    
    def _execute_command(self, server_id, task):
        """Execute a custom server command"""
        try:
            command = task.get('command', '')
            if command and self.server_manager.is_running(server_id):
                self.server_manager.send_command(server_id, command)
                print(f"[TaskScheduler] Executed command '{command}' on server {server_id}")
            elif not command:
                print(f"[TaskScheduler] No command specified for task")
            else:
                print(f"[TaskScheduler] Server {server_id} is not running, cannot execute command")
        except Exception as e:
            print(f"[TaskScheduler] Failed to execute command on server {server_id}: {e}")
    
    def create_task(self, server_id, task_config):
        """Create a new task for a server"""
        if 'tasks' not in self.tasks:
            self.tasks['tasks'] = {}
        if server_id not in self.tasks['tasks']:
            self.tasks['tasks'][server_id] = {}
        
        # Generate task ID
        task_id = str(int(datetime.now().timestamp() * 1000))
        
        self.tasks['tasks'][server_id][task_id] = {
            'id': task_id,
            'name': task_config.get('name', 'Unnamed Task'),
            'action': task_config.get('action', 'START'),
            'interval': task_config.get('interval', '0 3 * * *'),
            'command': task_config.get('command', ''),
            'runs': task_config.get('runs', 0),
            'runCount': 0,
            'enabled': task_config.get('enabled', True),
            'deleteAfterExecution': task_config.get('deleteAfterExecution', False),
            'deleteAfterRunsCount': task_config.get('deleteAfterRunsCount', False),
            'createdAt': datetime.now().isoformat(),
            'lastRun': None
        }
        
        self._save_tasks()
        
        if task_config.get('enabled', True):
            self._add_job(server_id, task_id, self.tasks['tasks'][server_id][task_id])
        
        return self.tasks['tasks'][server_id][task_id]
    
    def update_task(self, server_id, task_id, task_config):
        """Update an existing task"""
        if server_id not in self.tasks.get('tasks', {}) or task_id not in self.tasks['tasks'][server_id]:
            return None
        
        task = self.tasks['tasks'][server_id][task_id]
        
        # Update fields
        task['name'] = task_config.get('name', task['name'])
        task['action'] = task_config.get('action', task['action'])
        task['interval'] = task_config.get('interval', task['interval'])
        task['command'] = task_config.get('command', task.get('command', ''))
        task['runs'] = task_config.get('runs', task['runs'])
        task['enabled'] = task_config.get('enabled', task['enabled'])
        task['deleteAfterExecution'] = task_config.get('deleteAfterExecution', task['deleteAfterExecution'])
        task['deleteAfterRunsCount'] = task_config.get('deleteAfterRunsCount', task['deleteAfterRunsCount'])
        
        self._save_tasks()
        
        # Update or remove job
        if task['enabled']:
            self._add_job(server_id, task_id, task)
        else:
            try:
                self.scheduler.remove_job(f"task_{server_id}_{task_id}")
            except:
                pass
        
        return task
    
    def delete_task(self, server_id, task_id):
        """Delete a task"""
        if server_id in self.tasks.get('tasks', {}) and task_id in self.tasks['tasks'][server_id]:
            del self.tasks['tasks'][server_id][task_id]
            self._save_tasks()
            
            try:
                self.scheduler.remove_job(f"task_{server_id}_{task_id}")
            except:
                pass
            
            return True
        return False
    
    def get_tasks(self, server_id):
        """Get all tasks for a server"""
        tasks = self.tasks.get('tasks', {}).get(server_id, {})
        result = []
        
        for task_id, task in tasks.items():
            task_copy = task.copy()
            # Add next run time if job exists
            try:
                job = self.scheduler.get_job(f"task_{server_id}_{task_id}")
                if job and job.next_run_time:
                    task_copy['nextRun'] = job.next_run_time.isoformat()
            except:
                pass
            result.append(task_copy)
        
        return result
    
    def get_task(self, server_id, task_id):
        """Get a specific task"""
        task = self.tasks.get('tasks', {}).get(server_id, {}).get(task_id)
        if task:
            task_copy = task.copy()
            try:
                job = self.scheduler.get_job(f"task_{server_id}_{task_id}")
                if job and job.next_run_time:
                    task_copy['nextRun'] = job.next_run_time.isoformat()
            except:
                pass
            return task_copy
        return None


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
        self._migrate_users()
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
    
    def _migrate_users(self):
        """Migrate existing users to new schema with brute force protection fields"""
        migrated = False
        for user_id, user in self.users.get('users', {}).items():
            if 'failedLoginAttempts' not in user:
                user['failedLoginAttempts'] = 0
                migrated = True
            if 'accountDisabled' not in user:
                user['accountDisabled'] = False
                migrated = True
            if 'disabledAt' not in user:
                user['disabledAt'] = None
                migrated = True
            if 'isAntiLockout' not in user:
                user['isAntiLockout'] = False
                migrated = True
        
        if migrated:
            self._save_users()
            print("User database migrated to include brute force protection fields")
    
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
                'name': '',
                'mfaEnabled': False,
                'mfaSecret': None,
                'mfaRecoveryCode': None,
                'approved': True,
                'created': datetime.now().isoformat(),
                'lastLogin': None,
                'failedLoginAttempts': 0,
                'accountDisabled': False,
                'disabledAt': None,
                'isAntiLockout': False
            }
            self._save_users()
            print("Default admin created - Username: admin, Password: admin")
            print("WARNING: Change the default password immediately!")
    
    def authenticate(self, username, password):
        """Authenticate a user and return user data if successful"""
        with self.lock:
            for user_id, user in self.users.get('users', {}).items():
                if user['username'].lower() == username.lower():
                    # Check if account is disabled
                    if user.get('accountDisabled', False):
                        return None, "Account has been disabled due to multiple failed login attempts. Please contact an administrator."
                    
                    if check_password_hash(user['password'], password):
                        if not user.get('approved', False) and user['role'] != 'admin':
                            return None, "Account pending approval"
                        
                        # Reset failed login attempts on successful login
                        user['failedLoginAttempts'] = 0
                        user['lastLogin'] = datetime.now().isoformat()
                        self._save_users()
                        return user_id, user
                    else:
                        # Increment failed login attempts
                        user['failedLoginAttempts'] = user.get('failedLoginAttempts', 0) + 1
                        
                        # Disable account after 5 failed attempts
                        if user['failedLoginAttempts'] >= 5:
                            user['accountDisabled'] = True
                            user['disabledAt'] = datetime.now().isoformat()
                            self._save_users()
                            
                            # Check if we need to create anti-lockout account
                            self._check_and_create_anti_lockout()
                            
                            return None, "Account has been disabled due to multiple failed login attempts."
                        
                        self._save_users()
                        remaining = 5 - user['failedLoginAttempts']
                        return None, f"Invalid password. {remaining} attempts remaining before account is disabled."
            
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
                'name': '',
                'mfaEnabled': False,
                'mfaSecret': None,
                'mfaRecoveryCode': None,
                'approved': not require_approval,  # Auto-approve if not required
                'created': datetime.now().isoformat(),
                'lastLogin': None,
                'failedLoginAttempts': 0,
                'accountDisabled': False,
                'disabledAt': None,
                'isAntiLockout': False
            }
            self._save_users()
            
            if require_approval:
                return user_id, "Registration successful. Please wait for admin approval."
            return user_id, "Registration successful. You can now log in."
    
    def _has_active_admin(self):
        """Check if there are any active (non-disabled) admin accounts"""
        for user in self.users.get('users', {}).values():
            if (user['role'] == 'admin' and 
                not user.get('accountDisabled', False) and 
                user.get('approved', False)):
                return True
        return False
    
    def _check_and_create_anti_lockout(self):
        """Create anti-lockout account if no active admins exist"""
        if not self._has_active_admin():
            # Remove any existing anti-lockout accounts first
            self._remove_anti_lockout_accounts()
            
            # Generate random credentials
            import secrets
            import string
            
            username = 'emergency_admin_' + ''.join(secrets.choice(string.digits) for _ in range(4))
            password = ''.join(secrets.choice(string.ascii_letters + string.digits + string.punctuation) for _ in range(16))
            
            user_id = str(uuid.uuid4())[:8]
            self.users['users'][user_id] = {
                'username': username,
                'password': generate_password_hash(password),
                'role': 'admin',
                'name': 'Emergency Anti-Lockout Account',
                'mfaEnabled': False,
                'mfaSecret': None,
                'mfaRecoveryCode': None,
                'approved': True,
                'created': datetime.now().isoformat(),
                'lastLogin': None,
                'failedLoginAttempts': 0,
                'accountDisabled': False,
                'disabledAt': None,
                'isAntiLockout': True
            }
            self._save_users()
            
            # Log to console and file
            log_message = f"""
{'='*80}
⚠️  ANTI-LOCKOUT ACCOUNT CREATED ⚠️
{'='*80}
All admin accounts have been disabled due to failed login attempts.
An emergency admin account has been created:

  USERNAME: {username}
  PASSWORD: {password}

⚠️  IMPORTANT:
  1. Use these credentials to log in immediately
  2. Re-enable or create a permanent admin account
  3. This account will be automatically removed when a regular admin is active
  4. Store these credentials securely - they will not be shown again
{'='*80}
"""
            print(log_message)
            
            # Also write to a log file
            try:
                with open('anti_lockout_credentials.log', 'a') as f:
                    f.write(f"\n{datetime.now().isoformat()} - {log_message}\n")
            except Exception as e:
                print(f"Failed to write to log file: {e}")
            
            return username, password
        return None, None
    
    def _remove_anti_lockout_accounts(self):
        """Remove all anti-lockout accounts"""
        to_remove = []
        for user_id, user in self.users.get('users', {}).items():
            if user.get('isAntiLockout', False):
                to_remove.append(user_id)
        
        for user_id in to_remove:
            del self.users['users'][user_id]
        
        if to_remove:
            self._save_users()
            print(f"Removed {len(to_remove)} anti-lockout account(s)")
    
    def enable_account(self, user_id):
        """Enable a disabled user account and reset failed attempts"""
        with self.lock:
            user = self.users.get('users', {}).get(user_id)
            if not user:
                return False, "User not found"
            
            user['accountDisabled'] = False
            user['failedLoginAttempts'] = 0
            user['disabledAt'] = None
            self._save_users()
            
            # Check if we can remove anti-lockout accounts
            if self._has_active_admin():
                self._remove_anti_lockout_accounts()
            
            return True, "Account enabled successfully"
    
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
                'name': '',
                'mfaEnabled': False,
                'mfaSecret': None,
                'mfaRecoveryCode': None,
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
                'name': user.get('name', ''),
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
                
                # If this is an admin being approved, check if we can remove anti-lockout accounts
                user = self.users['users'][user_id]
                if user['role'] == 'admin' and self._has_active_admin():
                    self._remove_anti_lockout_accounts()
                
                return True
        return False
    
    def _has_active_admin(self):
        """Check if there are any active (non-disabled) admin accounts"""
        for user in self.users.get('users', {}).values():
            if (user['role'] == 'admin' and 
                not user.get('accountDisabled', False) and 
                user.get('approved', False) and
                not user.get('isAntiLockout', False)):
                return True
        return False
    
    def _check_and_create_anti_lockout(self):
        """Create anti-lockout account if no active admins exist"""
        if not self._has_active_admin():
            # Remove any existing anti-lockout accounts first
            self._remove_anti_lockout_accounts()
            
            # Generate random credentials
            import secrets
            import string
            
            username = 'emergency_admin_' + ''.join(secrets.choice(string.digits) for _ in range(4))
            password = ''.join(secrets.choice(string.ascii_letters + string.digits + string.punctuation) for _ in range(16))
            
            user_id = str(uuid.uuid4())[:8]
            self.users['users'][user_id] = {
                'username': username,
                'password': generate_password_hash(password),
                'role': 'admin',
                'name': 'Emergency Anti-Lockout Account',
                'mfaEnabled': False,
                'mfaSecret': None,
                'mfaRecoveryCode': None,
                'approved': True,
                'created': datetime.now().isoformat(),
                'lastLogin': None,
                'failedLoginAttempts': 0,
                'accountDisabled': False,
                'disabledAt': None,
                'isAntiLockout': True
            }
            self._save_users()
            
            # Log to console and file
            log_message = f"""
{'='*80}
⚠️  ANTI-LOCKOUT ACCOUNT CREATED ⚠️
{'='*80}
All admin accounts have been disabled due to failed login attempts.
An emergency admin account has been created:

  USERNAME: {username}
  PASSWORD: {password}

⚠️  IMPORTANT:
  1. Use these credentials to log in immediately
  2. Re-enable or create a permanent admin account
  3. This account will be automatically removed when a regular admin is active
  4. Store these credentials securely - they will not be shown again
{'='*80}
"""
            print(log_message)
            
            # Also write to a log file
            try:
                with open('anti_lockout_credentials.log', 'a') as f:
                    f.write(f"\n{datetime.now().isoformat()} - {log_message}\n")
            except Exception as e:
                print(f"Failed to write to log file: {e}")
            
            return username, password
        return None, None
    
    def _remove_anti_lockout_accounts(self):
        """Remove all anti-lockout accounts"""
        to_remove = []
        for user_id, user in self.users.get('users', {}).items():
            if user.get('isAntiLockout', False):
                to_remove.append(user_id)
        
        for user_id in to_remove:
            del self.users['users'][user_id]
        
        if to_remove:
            self._save_users()
            print(f"Removed {len(to_remove)} anti-lockout account(s)")
    
    def enable_account(self, user_id):
        """Enable a disabled user account and reset failed attempts"""
        with self.lock:
            user = self.users.get('users', {}).get(user_id)
            if not user:
                return False, "User not found"
            
            user['accountDisabled'] = False
            user['failedLoginAttempts'] = 0
            user['disabledAt'] = None
            self._save_users()
            
            # Check if we can remove anti-lockout accounts
            if self._has_active_admin():
                self._remove_anti_lockout_accounts()
            
            return True, "Account enabled successfully"
    
    def update_user_role(self, user_id, role):
        """Update user role"""
        if role not in self.ROLES:
            return False
        with self.lock:
            if user_id in self.users.get('users', {}):
                self.users['users'][user_id]['role'] = role
                self._save_users()
                
                # If promoting to admin, check if we can remove anti-lockout accounts
                if role == 'admin' and self._has_active_admin():
                    self._remove_anti_lockout_accounts()
                
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
    
    def update_username(self, user_id, new_username):
        """Update user's username"""
        with self.lock:
            user = self.users.get('users', {}).get(user_id)
            if not user:
                return False, "User not found"
            
            # Validate username
            if len(new_username) < 3 or len(new_username) > 32:
                return False, "Username must be 3-32 characters"
            if not new_username.replace('_', '').replace('-', '').isalnum():
                return False, "Username can only contain letters, numbers, underscores, and hyphens"
            
            # Check if username already exists (case-insensitive)
            for uid, u in self.users.get('users', {}).items():
                if uid != user_id and u['username'].lower() == new_username.lower():
                    return False, "Username already exists"
            
            self.users['users'][user_id]['username'] = new_username
            self._save_users()
            return True, "Username updated successfully"
    
    def update_name(self, user_id, name):
        """Update user's display name"""
        with self.lock:
            user = self.users.get('users', {}).get(user_id)
            if not user:
                return False, "User not found"
            
            # Validate name (optional, can be empty)
            if len(name) > 100:
                return False, "Name must be 100 characters or less"
            
            self.users['users'][user_id]['name'] = name
            self._save_users()
            return True, "Name updated successfully"
    
    def generate_mfa_secret(self, user_id):
        """Generate a new TOTP secret for user"""
        user = self.users.get('users', {}).get(user_id)
        if not user:
            return None, "User not found"
        
        # Generate random secret
        secret = pyotp.random_base32()
        return secret, "Secret generated successfully"
    
    def generate_recovery_code(self):
        """Generate a recovery code in format XXXXXXXX-XXXXXXXX-XXXXXXXX"""
        parts = []
        for _ in range(3):
            # Generate 8 hex characters
            part = ''.join(secrets.choice('ABCDEF0123456789') for _ in range(8))
            parts.append(part)
        return '-'.join(parts)
    
    def verify_totp(self, secret, code):
        """Verify a TOTP code"""
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)  # Allow 1 step before/after for clock drift
    
    def enable_mfa(self, user_id, secret, recovery_code):
        """Enable MFA for user"""
        with self.lock:
            user = self.users.get('users', {}).get(user_id)
            if not user:
                return False, "User not found"
            
            self.users['users'][user_id]['mfaEnabled'] = True
            self.users['users'][user_id]['mfaSecret'] = secret
            self.users['users'][user_id]['mfaRecoveryCode'] = recovery_code
            self._save_users()
            return True, "MFA enabled successfully"
    
    def disable_mfa(self, user_id):
        """Disable MFA for user"""
        with self.lock:
            user = self.users.get('users', {}).get(user_id)
            if not user:
                return False, "User not found"
            
            self.users['users'][user_id]['mfaEnabled'] = False
            self.users['users'][user_id]['mfaSecret'] = None
            self.users['users'][user_id]['mfaRecoveryCode'] = None
            self._save_users()
            return True, "MFA disabled successfully"
    
    def verify_recovery_code(self, user_id, recovery_code):
        """Verify and use recovery code (one-time use)"""
        with self.lock:
            user = self.users.get('users', {}).get(user_id)
            if not user:
                return False
            
            if user.get('mfaRecoveryCode') == recovery_code:
                # Disable MFA after recovery code is used
                self.users['users'][user_id]['mfaEnabled'] = False
                self.users['users'][user_id]['mfaSecret'] = None
                self.users['users'][user_id]['mfaRecoveryCode'] = None
                self._save_users()
                return True
            return False
    
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


# ==================== Server Status Enum ====================

class ServerStatus(Enum):
    """Server status states"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    UNRESPONSIVE = "unresponsive"


# ==================== Server Manager ====================

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
            status = instance.get_status().value if instance else ServerStatus.STOPPED.value
            
            # Get server port if available
            port = self.get_server_port(server_id)
            
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
                'running': is_running,
                'status': status,
                'port': port
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
        
        # Determine engine name
        engine_name = 'Vanilla'
        if is_modded and server_type:
            engine_name = server_type.title()  # paper -> Paper, folia -> Folia, etc.
        
        # Create managed.conf file
        self._create_managed_conf(server_dir, server_id, name, modded=is_modded, engine=engine_name, owner=owner)
        
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
    
    # Required fields for managed.conf
    MANAGED_CONF_REQUIRED_FIELDS = [
        'ManagedBy',
        'ServerId',
        'ServerName',
        'Modded',
        'Engine',
        'Owner',
        'CreatedAt',
        'EULAAccepted'
    ]
    
    def _create_managed_conf(self, server_dir, server_id, name, modded=False, engine=None, owner=None):
        """Create or update the managed.conf file for a server"""
        managed_conf_path = Path(server_dir) / 'managed.conf'
        
        # Determine engine based on modded status
        if engine is None:
            engine = 'Vanilla' if not modded else 'Unknown'
        
        config = {
            'ManagedBy': 'MServerController',
            'ServerId': server_id,
            'ServerName': name,
            'Modded': 'true' if modded else 'false',
            'Engine': engine,
            'Owner': owner or 'admin',
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
            config['Engine'] = engine
            if owner:
                config['Owner'] = owner
        
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
    
    def validate_managed_conf(self, server_id):
        """
        Validate that managed.conf has all required fields.
        Returns (is_valid, missing_fields) tuple.
        """
        server_config = self.get_server_config(server_id)
        if not server_config:
            return False, ['Server not found']
        
        server_dir = Path(server_config.get('serverPath', ''))
        managed_conf_path = server_dir / 'managed.conf'
        
        if not managed_conf_path.exists():
            return False, ['managed.conf file not found']
        
        config = self._read_managed_conf(server_dir)
        
        missing_fields = []
        for field in self.MANAGED_CONF_REQUIRED_FIELDS:
            if field not in config or not config[field]:
                missing_fields.append(field)
        
        return len(missing_fields) == 0, missing_fields
    
    def update_managed_conf_field(self, server_id, field, value):
        """Update a single field in managed.conf"""
        server_config = self.get_server_config(server_id)
        if not server_config:
            return False, "Server not found"
        
        server_dir = Path(server_config.get('serverPath', ''))
        config = self._read_managed_conf(server_dir)
        config[field] = value
        self._write_managed_conf(server_dir, config)
        return True, f"{field} updated"
    
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
        server_type = server_config.get('serverType', '')
        owner = server_config.get('owner', 'admin')
        
        # Determine engine name
        engine_name = 'Vanilla'
        if is_modded and server_type:
            engine_name = server_type.title()
        
        self._create_managed_conf(server_dir, server_id, name, modded=is_modded, engine=engine_name, owner=owner)
        
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
            
            # Create managed.conf file (imported servers have unknown engine)
            engine_name = 'Vanilla' if not is_modded else 'Unknown'
            self._create_managed_conf(server_dir, server_id, name, modded=is_modded, engine=engine_name, owner=owner)
            
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
    
    def get_server_port(self, server_id):
        """Get the port number from server.properties"""
        try:
            server_path = self.get_server_path(server_id)
            properties_path = server_path / 'server.properties'
            
            if properties_path.exists():
                with open(properties_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            if key.strip() == 'server-port':
                                return value.strip()
            return None
        except Exception:
            return None
    
    def get_all_server_ports(self, exclude_server_id=None):
        """Get all server ports currently in use (excluding a specific server if specified)"""
        ports = {}
        for server_id in self.config.get('servers', {}).keys():
            if exclude_server_id and server_id == exclude_server_id:
                continue
            port = self.get_server_port(server_id)
            if port:
                ports[server_id] = port
        return ports
    
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
        self.status = ServerStatus.STOPPED
        self.start_time = None
        self.server_port = None
        self._status_monitor_thread = None
        self._stop_status_monitor = False
    
    def start(self):
        """Start the server process"""
        # Clear the output buffer on start for fresh logs
        self.output_buffer = []
        self.status = ServerStatus.STARTING
        self.start_time = time.time()
        self.server_port = None  # Will be read from properties
        
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
        
        # Start threads
        threading.Thread(target=self._read_output_unbuffered, daemon=True).start()
        threading.Thread(target=self._monitor_process, daemon=True).start()
        
        # Start status monitoring
        self._stop_status_monitor = False
        self._status_monitor_thread = threading.Thread(target=self._monitor_status, daemon=True)
        self._status_monitor_thread.start()
        
        # Broadcast initial status
        self._broadcast({'type': 'status', 'serverId': self.server_id, 'status': self.status.value, 'running': True})
    
    def _read_output_unbuffered(self):
        """Read output from the process in real-time and broadcast to clients"""
        try:
            buffer = b''
            fd = self.process.stdout.fileno()
            
            while self.process.poll() is None:
                # Use select to check if data is available (timeout 0.1s for responsiveness)
                ready, _, _ = select.select([fd], [], [], 0.1)
                
                if ready:
                    # Data is available, read it
                    chunk = os.read(fd, 4096)
                    if chunk:
                        buffer += chunk
                        
                        # Process all complete lines in the buffer
                        while b'\n' in buffer:
                            line_bytes, buffer = buffer.split(b'\n', 1)
                            line_bytes += b'\n'
                            try:
                                line = line_bytes.decode('utf-8', errors='replace')
                            except:
                                line = line_bytes.decode('latin-1', errors='replace')
                            self._broadcast({'type': 'output', 'data': line, 'serverId': self.server_id})
                            self._add_to_buffer(line)
                        
                        # Send partial line immediately if it's been sitting in buffer
                        # This ensures progress bars and non-newline terminated output appears
                        if buffer and len(buffer) > 0:
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
            self._stop_status_monitor = True
            self.status = ServerStatus.STOPPED
            self._broadcast({'type': 'info', 'data': f'Server stopped with code {code}\n', 'serverId': self.server_id})
            self._broadcast({'type': 'status', 'serverId': self.server_id, 'status': self.status.value, 'running': False})
    
    def _broadcast(self, data):
        """Broadcast message to all clients"""
        socketio.emit('message', data, namespace='/')
    
    def _add_to_buffer(self, line):
        """Add line to output buffer"""
        self.output_buffer.append(line)
        if len(self.output_buffer) > self.max_buffer_size:
            self.output_buffer.pop(0)
    
    def _check_tcp_port(self, port, timeout=1):
        """Check if server is responding on TCP port"""
        if not port:
            return False
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex(('localhost', port))
            sock.close()
            return result == 0
        except Exception:
            return False
    
    def _get_server_port(self):
        """Extract server port from server.properties"""
        if self.server_port:
            return self.server_port
        
        props_file = self.server_path / 'server.properties'
        if props_file.exists():
            try:
                with open(props_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith('server-port='):
                            self.server_port = int(line.split('=')[1])
                            return self.server_port
            except Exception:
                pass
        return 25565  # Default Minecraft port
    
    def _monitor_status(self):
        """Background thread to monitor server status"""
        while not self._stop_status_monitor:
            if self.process is None or self.process.poll() is not None:
                # Process not running
                if self.status != ServerStatus.STOPPED:
                    self.status = ServerStatus.STOPPED
                    self._broadcast({'type': 'status', 'serverId': self.server_id, 'status': self.status.value})
                time.sleep(2)
                continue
            
            # Process is running, check state
            elapsed = time.time() - self.start_time if self.start_time else 0
            port = self._get_server_port()
            tcp_responsive = self._check_tcp_port(port)
            
            new_status = None
            
            if tcp_responsive:
                # Server is responding on TCP port
                if self.status != ServerStatus.RUNNING:
                    new_status = ServerStatus.RUNNING
            elif elapsed < 30:
                # Within startup grace period
                if self.status != ServerStatus.STARTING:
                    new_status = ServerStatus.STARTING
            else:
                # Process running but not responding after 30s
                if self.status != ServerStatus.UNRESPONSIVE:
                    new_status = ServerStatus.UNRESPONSIVE
            
            if new_status and new_status != self.status:
                self.status = new_status
                self._broadcast({
                    'type': 'status',
                    'serverId': self.server_id,
                    'status': self.status.value,
                    'running': self.status in [ServerStatus.STARTING, ServerStatus.RUNNING, ServerStatus.UNRESPONSIVE]
                })
            
            time.sleep(2)  # Check every 2 seconds
    
    def get_status(self):
        """Get current server status"""
        return self.status
    
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
            self.status = ServerStatus.STOPPING
            self._broadcast({'type': 'status', 'serverId': self.server_id, 'status': self.status.value, 'running': True})
            self.send_command('stop')
            
            def force_kill():
                time.sleep(30)
                if self.is_running():
                    self.process.kill()
            
            threading.Thread(target=force_kill, daemon=True).start()
    
    def kill(self):
        """Forcefully kill the server process immediately"""
        if self.is_running():
            self.status = ServerStatus.STOPPING
            self._broadcast({'type': 'status', 'serverId': self.server_id, 'status': self.status.value})
            self.process.kill()
            self.process.wait()
            self._stop_status_monitor = True
            self.status = ServerStatus.STOPPED
    
    def get_recent_output(self, lines=100):
        """Get recent output from the buffer"""
        return self.output_buffer[-lines:]


# Initialize server manager
server_manager = ServerManager()

# Initialize backup scheduler
backup_scheduler = BackupScheduler()

# Initialize task scheduler
task_scheduler = TaskScheduler(server_manager, socketio)

# Initialize API Manager
from api_manager import init_api_manager
init_api_manager(app)


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
    
    # Check if MFA is enabled for this user
    if result.get('mfaEnabled', False):
        # Set temporary session for MFA verification
        session['temp_user_id'] = user_id
        session['mfa_required'] = True
        
        return jsonify({
            'success': True,
            'mfaRequired': True,
            'message': 'MFA verification required'
        })
    
    # Check MFA policies
    mfa_settings = settings_manager.get_settings().get('mfa', {})
    require_all = mfa_settings.get('requireMfaForAllUsers', False)
    require_admin = mfa_settings.get('requireMfaForAdmins', False)
    
    if require_all or (require_admin and result['role'] == 'admin'):
        if not result.get('mfaEnabled', False):
            return jsonify({
                'error': 'MFA is required for your account. Please contact an administrator.',
                'code': 'MFA_REQUIRED'
            }), 403
    
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
        'name': user.get('name', ''),
        'role': user['role'],
        'mfaEnabled': user.get('mfaEnabled', False)
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

@app.route('/api/auth/profile/username', methods=['PUT'])
@login_required
def api_update_username():
    """Update current user's username"""
    user_id = session.get('user_id')
    data = request.get_json()
    
    new_username = data.get('username', '').strip()
    
    if not new_username:
        return jsonify({'error': 'Username is required'}), 400
    
    success, message = user_manager.update_username(user_id, new_username)
    
    if not success:
        return jsonify({'error': message}), 400
    
    # Update session with new username
    session['username'] = new_username
    
    return jsonify({'success': True, 'message': message})

@app.route('/api/auth/profile/name', methods=['PUT'])
@login_required
def api_update_name():
    """Update current user's display name"""
    user_id = session.get('user_id')
    data = request.get_json()
    
    name = data.get('name', '').strip()
    
    success, message = user_manager.update_name(user_id, name)
    
    if not success:
        return jsonify({'error': message}), 400
    
    return jsonify({'success': True, 'message': message})

# ==================== MFA API ====================

@app.route('/api/auth/mfa/setup', methods=['POST'])
@login_required
def api_mfa_setup():
    """Generate MFA secret and QR code for setup"""
    user_id = session.get('user_id')
    user = user_manager.get_user(user_id)
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Generate secret
    secret, _ = user_manager.generate_mfa_secret(user_id)
    
    # Generate QR code
    username = user['username']
    app_name = settings_manager.get_branding().get('siteTitle', 'MServerController')
    
    totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=username,
        issuer_name=app_name
    )
    
    # Generate QR code as base64 image
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(totp_uri)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Convert to base64
    img_buffer = io.BytesIO()
    img.save(img_buffer, format='PNG')
    img_buffer.seek(0)
    img_base64 = 'data:image/png;base64,' + hashlib.sha256(img_buffer.getvalue()).hexdigest()[:20]  # Placeholder
    
    # Actually encode as base64
    import base64
    img_buffer.seek(0)
    img_base64 = 'data:image/png;base64,' + base64.b64encode(img_buffer.getvalue()).decode()
    
    return jsonify({
        'success': True,
        'secret': secret,
        'qrCode': img_base64,
        'manualEntry': secret
    })

@app.route('/api/auth/mfa/verify', methods=['POST'])
@login_required
def api_mfa_verify():
    """Verify TOTP code and enable MFA"""
    user_id = session.get('user_id')
    data = request.get_json()
    
    secret = data.get('secret', '')
    code = data.get('code', '')
    
    if not secret or not code:
        return jsonify({'error': 'Secret and code are required'}), 400
    
    # Verify the code
    if not user_manager.verify_totp(secret, code):
        return jsonify({'error': 'Invalid verification code'}), 400
    
    # Generate recovery code
    recovery_code = user_manager.generate_recovery_code()
    
    # Enable MFA
    success, message = user_manager.enable_mfa(user_id, secret, recovery_code)
    
    if not success:
        return jsonify({'error': message}), 400
    
    return jsonify({
        'success': True,
        'message': 'MFA enabled successfully',
        'recoveryCode': recovery_code
    })

@app.route('/api/auth/mfa/disable', methods=['POST'])
@login_required
def api_mfa_disable():
    """Disable MFA for current user"""
    user_id = session.get('user_id')
    data = request.get_json()
    
    password = data.get('password', '')
    
    if not password:
        return jsonify({'error': 'Password required to disable MFA'}), 400
    
    # Verify password
    user = user_manager.get_user(user_id)
    if not check_password_hash(user['password'], password):
        return jsonify({'error': 'Invalid password'}), 401
    
    success, message = user_manager.disable_mfa(user_id)
    
    if not success:
        return jsonify({'error': message}), 400
    
    return jsonify({'success': True, 'message': message})

@app.route('/api/auth/mfa/verify-login', methods=['POST'])
@limiter.limit("10 per minute")
def api_mfa_verify_login():
    """Verify MFA code during login"""
    temp_user_id = session.get('temp_user_id')
    
    if not temp_user_id:
        return jsonify({'error': 'No pending MFA verification'}), 400
    
    data = request.get_json()
    code = data.get('code', '')
    use_recovery = data.get('useRecovery', False)
    
    if not code:
        return jsonify({'error': 'Code is required'}), 400
    
    user = user_manager.get_user(temp_user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    verified = False
    
    if use_recovery:
        # Verify recovery code
        verified = user_manager.verify_recovery_code(temp_user_id, code)
        if verified:
            # Recovery code disables MFA
            message = 'MFA has been disabled using recovery code'
        else:
            return jsonify({'error': 'Invalid recovery code'}), 401
    else:
        # Verify TOTP code
        if not user.get('mfaSecret'):
            return jsonify({'error': 'MFA not enabled for this user'}), 400
        
        verified = user_manager.verify_totp(user.get('mfaSecret'), code)
        if not verified:
            return jsonify({'error': 'Invalid verification code'}), 401
        message = 'Login successful'
    
    if verified:
        # Complete login
        session.permanent = True
        session['user_id'] = temp_user_id
        session['username'] = user['username']
        session['role'] = user['role']
        session.pop('temp_user_id', None)
        session.pop('mfa_required', None)
        
        return jsonify({
            'success': True,
            'message': message,
            'user': {
                'id': temp_user_id,
                'username': user['username'],
                'role': user['role']
            }
        })
    
    return jsonify({'error': 'Verification failed'}), 401


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

@app.route('/api/admin/users/<user_id>/mfa', methods=['DELETE'])
@admin_required
def api_clear_user_mfa(user_id):
    """Clear user MFA (admin only)"""
    # Prevent clearing own MFA
    if user_id == session.get('user_id'):
        return jsonify({'error': 'Cannot clear your own MFA. Use the profile settings instead.'}), 400
    
    success, message = user_manager.disable_mfa(user_id)
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 404

@app.route('/api/admin/users/<user_id>/enable', methods=['POST'])
@admin_required
def api_enable_user_account(user_id):
    """Enable a disabled user account (admin only)"""
    success, message = user_manager.enable_account(user_id)
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 404

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
    
    # Create server locally
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
    status = instance.get_status().value if instance else ServerStatus.STOPPED.value
    
    return jsonify({
        'id': server_id,
        'running': is_running,
        'status': status,
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
    """Check if a server has managed.conf and validate its fields"""
    is_managed = server_manager.is_managed(server_id)
    
    if not is_managed:
        return jsonify({'managed': False, 'valid': False, 'missingFields': ['managed.conf file not found']})
    
    # Validate managed.conf
    is_valid, missing_fields = server_manager.validate_managed_conf(server_id)
    
    # Get current managed.conf data
    server_config = server_manager.get_server_config(server_id)
    server_dir = Path(server_config.get('serverPath', ''))
    managed_data = server_manager._read_managed_conf(server_dir)
    
    return jsonify({
        'managed': True, 
        'valid': is_valid, 
        'missingFields': missing_fields,
        'data': managed_data
    })

@app.route('/api/servers/<server_id>/managed/enable', methods=['POST'])
@server_access_required
def enable_management(server_id):
    """Create managed.conf for a server"""
    success, message = server_manager.enable_management(server_id)
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 400

@app.route('/api/servers/<server_id>/managed/update', methods=['POST'])
@server_access_required
def update_managed_conf(server_id):
    """Update fields in managed.conf"""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    server_config = server_manager.get_server_config(server_id)
    if not server_config:
        return jsonify({'error': 'Server not found'}), 404
    
    server_dir = Path(server_config.get('serverPath', ''))
    managed_conf = server_manager._read_managed_conf(server_dir)
    
    # Update provided fields
    for field, value in data.items():
        if field in server_manager.MANAGED_CONF_REQUIRED_FIELDS or field == 'EULAAcceptedAt':
            managed_conf[field] = value
    
    server_manager._write_managed_conf(server_dir, managed_conf)
    
    return jsonify({'success': True, 'message': 'Configuration updated'})

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

@app.route('/api/servers/<server_id>/logs', methods=['GET'])
@server_access_required
def read_server_logs(server_id):
    """Read latest.log from the logs folder"""
    server_path = server_manager.get_server_path(server_id)
    logs_path = server_path / 'logs' / 'latest.log'
    
    if not logs_path.exists():
        return jsonify({'content': 'No logs available. The server may not have been started yet.', 'success': False})
    
    try:
        content = logs_path.read_text(encoding='utf-8', errors='replace')
        return jsonify({'content': content, 'success': True})
    except Exception as e:
        return jsonify({'content': f'Error reading logs: {str(e)}', 'success': False})

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


# ==================== Properties API ====================

@app.route('/api/servers/<server_id>/properties/exists', methods=['GET'])
@server_access_required
def check_properties_exists(server_id):
    """Check if server.properties file exists"""
    server_path = server_manager.get_server_path(server_id)
    properties_path = server_path / 'server.properties'
    
    return jsonify({'exists': properties_path.exists()})

@app.route('/api/servers/<server_id>/properties', methods=['GET'])
@server_access_required
def get_properties(server_id):
    """Get server properties"""
    server_path = server_manager.get_server_path(server_id)
    properties_path = server_path / 'server.properties'
    
    if not properties_path.exists():
        return jsonify({'error': 'server.properties not found. Start the server at least once to generate it.'}), 404
    
    try:
        properties = {}
        with open(properties_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        properties[key.strip()] = value.strip()
        
        return jsonify({'properties': properties})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/properties', methods=['POST'])
@server_access_required
def save_properties(server_id):
    """Save server properties"""
    server_path = server_manager.get_server_path(server_id)
    properties_path = server_path / 'server.properties'
    
    if not properties_path.exists():
        return jsonify({'error': 'server.properties not found'}), 404
    
    data = request.json
    if not data or 'properties' not in data:
        return jsonify({'error': 'Missing properties'}), 400
    
    new_properties = data['properties']
    
    # Check for duplicate port if server-port is being changed
    if 'server-port' in new_properties:
        new_port = new_properties['server-port']
        existing_ports = server_manager.get_all_server_ports(exclude_server_id=server_id)
        
        # Check if this port is already in use by another server
        for other_server_id, port in existing_ports.items():
            if port == new_port:
                other_server_config = server_manager.get_server_config(other_server_id)
                other_server_name = other_server_config.get('name', 'Unknown Server') if other_server_config else 'Unknown Server'
                return jsonify({
                    'error': f'Port {new_port} is already in use by server: {other_server_name}'
                }), 400
    
    try:
        # Read existing file to preserve comments and order
        lines = []
        with open(properties_path, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                # Preserve comments and empty lines
                if not stripped or stripped.startswith('#'):
                    lines.append(line)
                elif '=' in stripped:
                    key, _ = stripped.split('=', 1)
                    key = key.strip()
                    # Update with new value if exists, otherwise keep original
                    if key in new_properties:
                        lines.append(f'{key}={new_properties[key]}\n')
                        # Mark as processed
                        new_properties.pop(key)
                    else:
                        lines.append(line)
                else:
                    lines.append(line)
        
        # Append any new properties that weren't in the original file
        if new_properties:
            lines.append('\n# Added by MServerController\n')
            for key, value in new_properties.items():
                lines.append(f'{key}={value}\n')
        
        # Write back to file
        with open(properties_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== Resource Pack API ====================

@app.route('/api/servers/<server_id>/resourcepack', methods=['GET'])
@server_access_required
def get_resourcepack_info(server_id):
    """Get resource pack information for a server"""
    server_path = server_manager.get_server_path(server_id)
    resourcepack_path = RESOURCEPACKS_DIR / f"{server_id}.zip"
    
    if not resourcepack_path.exists():
        return jsonify({'exists': False})
    
    try:
        stat = resourcepack_path.stat()
        
        # Calculate SHA1 hash
        sha1_hash = hashlib.sha1()
        with open(resourcepack_path, 'rb') as f:
            while chunk := f.read(8192):
                sha1_hash.update(chunk)
        
        # Get base URL from settings
        base_url = settings_manager.get_branding().get('baseUrl', '')
        pack_url = f"{base_url}/resourcepacks/{server_id}.zip" if base_url else ''
        
        return jsonify({
            'exists': True,
            'filename': resourcepack_path.name,
            'size': stat.st_size,
            'uploaded': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            'sha1': sha1_hash.hexdigest(),
            'url': pack_url
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/resourcepack/upload', methods=['POST'])
@server_access_required
def upload_resourcepack(server_id):
    """Upload a resource pack for a server"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    # Check file extension
    if not file.filename.lower().endswith('.zip'):
        return jsonify({'error': 'File must be a .zip file'}), 400
    
    # Check file size (100MB limit)
    MAX_SIZE = 100 * 1024 * 1024  # 100MB in bytes
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    
    if file_size > MAX_SIZE:
        return jsonify({'error': f'File size exceeds 100MB limit (size: {file_size / (1024*1024):.2f}MB)'}), 400
    
    try:
        # Save the file
        resourcepack_path = RESOURCEPACKS_DIR / f"{server_id}.zip"
        file.save(str(resourcepack_path))
        
        # Calculate SHA1 hash
        sha1_hash = hashlib.sha1()
        with open(resourcepack_path, 'rb') as f:
            while chunk := f.read(8192):
                sha1_hash.update(chunk)
        
        sha1_hex = sha1_hash.hexdigest()
        
        # Get base URL from settings
        base_url = settings_manager.get_branding().get('baseUrl', '')
        if not base_url:
            return jsonify({'error': 'Base URL is not configured. Please set it in Settings > Branding.'}), 400
        
        pack_url = f"{base_url}/resourcepacks/{server_id}.zip"
        
        # Update server.properties if it exists
        properties_path = server_manager.get_server_path(server_id) / 'server.properties'
        if properties_path.exists():
            # Read existing properties
            lines = []
            resource_pack_found = False
            resource_pack_sha1_found = False
            
            with open(properties_path, 'r', encoding='utf-8') as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith('resource-pack='):
                        lines.append(f'resource-pack={pack_url}\n')
                        resource_pack_found = True
                    elif stripped.startswith('resource-pack-sha1='):
                        lines.append(f'resource-pack-sha1={sha1_hex}\n')
                        resource_pack_sha1_found = True
                    else:
                        lines.append(line)
            
            # Add properties if they don't exist
            if not resource_pack_found or not resource_pack_sha1_found:
                lines.append('\n# Resource Pack Configuration (added by MServerController)\n')
                if not resource_pack_found:
                    lines.append(f'resource-pack={pack_url}\n')
                if not resource_pack_sha1_found:
                    lines.append(f'resource-pack-sha1={sha1_hex}\n')
            
            # Write back
            with open(properties_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
        
        stat = resourcepack_path.stat()
        
        return jsonify({
            'success': True,
            'filename': resourcepack_path.name,
            'size': stat.st_size,
            'sha1': sha1_hex,
            'url': pack_url,
            'propertiesUpdated': properties_path.exists()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/resourcepack', methods=['DELETE'])
@server_access_required
def delete_resourcepack(server_id):
    """Delete resource pack for a server"""
    resourcepack_path = RESOURCEPACKS_DIR / f"{server_id}.zip"
    
    if not resourcepack_path.exists():
        return jsonify({'error': 'No resource pack found'}), 404
    
    try:
        resourcepack_path.unlink()
        
        # Remove from server.properties if it exists
        properties_path = server_manager.get_server_path(server_id) / 'server.properties'
        if properties_path.exists():
            lines = []
            with open(properties_path, 'r', encoding='utf-8') as f:
                for line in f:
                    stripped = line.strip()
                    # Remove resource pack lines
                    if not stripped.startswith('resource-pack=') and not stripped.startswith('resource-pack-sha1='):
                        lines.append(line)
            
            with open(properties_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
        
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


# ==================== Task Scheduler API ====================

@app.route('/api/servers/<server_id>/tasks', methods=['GET'])
@server_access_required
def get_server_tasks(server_id):
    """Get all tasks for a server"""
    tasks = task_scheduler.get_tasks(server_id)
    return jsonify({'tasks': tasks})

@app.route('/api/servers/<server_id>/tasks', methods=['POST'])
@server_access_required
def create_server_task(server_id):
    """Create a new task for a server"""
    data = request.get_json()
    
    # Validate server exists
    server_config = server_manager.get_server_config(server_id)
    if not server_config:
        return jsonify({'error': 'Server not found'}), 404
    
    # Validate required fields
    if not data.get('name'):
        return jsonify({'error': 'Task name is required'}), 400
    
    if not data.get('action'):
        return jsonify({'error': 'Task action is required'}), 400
    
    if data.get('action') == 'COMMAND' and not data.get('command'):
        return jsonify({'error': 'Command is required for COMMAND action'}), 400
    
    task = task_scheduler.create_task(server_id, {
        'name': data.get('name'),
        'action': data.get('action', 'START'),
        'interval': data.get('interval', '0 3 * * *'),
        'command': data.get('command', ''),
        'runs': data.get('runs', 0),
        'enabled': data.get('enabled', True),
        'deleteAfterExecution': data.get('deleteAfterExecution', False),
        'deleteAfterRunsCount': data.get('deleteAfterRunsCount', False)
    })
    
    return jsonify({'success': True, 'task': task})

@app.route('/api/servers/<server_id>/tasks/<task_id>', methods=['GET'])
@server_access_required
def get_server_task(server_id, task_id):
    """Get a specific task"""
    task = task_scheduler.get_task(server_id, task_id)
    if task:
        return jsonify({'task': task})
    return jsonify({'error': 'Task not found'}), 404

@app.route('/api/servers/<server_id>/tasks/<task_id>', methods=['PUT'])
@server_access_required
def update_server_task(server_id, task_id):
    """Update an existing task"""
    data = request.get_json()
    
    task = task_scheduler.update_task(server_id, task_id, {
        'name': data.get('name'),
        'action': data.get('action'),
        'interval': data.get('interval'),
        'command': data.get('command', ''),
        'runs': data.get('runs'),
        'enabled': data.get('enabled'),
        'deleteAfterExecution': data.get('deleteAfterExecution'),
        'deleteAfterRunsCount': data.get('deleteAfterRunsCount')
    })
    
    if task:
        return jsonify({'success': True, 'task': task})
    return jsonify({'error': 'Task not found'}), 404

@app.route('/api/servers/<server_id>/tasks/<task_id>', methods=['DELETE'])
@server_access_required
def delete_server_task(server_id, task_id):
    """Delete a task"""
    if task_scheduler.delete_task(server_id, task_id):
        return jsonify({'success': True})
    return jsonify({'error': 'Task not found'}), 404


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

@app.route('/api/settings/mfa', methods=['GET'])
@admin_required
def get_mfa_settings():
    """Get MFA settings (admin only)"""
    settings = settings_manager.get_settings().get('mfa', {})
    return jsonify(settings)

@app.route('/api/settings/mfa', methods=['PUT'])
@admin_required
def update_mfa_settings():
    """Update MFA settings (admin only)"""
    data = request.get_json()
    
    mfa_settings = {
        'requireMfaForAdmins': data.get('requireMfaForAdmins', False),
        'requireMfaForAllUsers': data.get('requireMfaForAllUsers', False)
    }
    
    settings_manager.update_settings({'mfa': mfa_settings})
    return jsonify({'success': True, 'settings': mfa_settings})


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


# ==================== System Info API ====================

@app.route('/api/system/version', methods=['GET'])
@login_required
def api_get_current_version():
    """Get current version from version file"""
    try:
        # Get current version (from file or fallback to git)
        version, source = get_current_version()

        # Get commit date
        commit_date = "unknown"
        try:
            result = subprocess.run(
                ['git', 'log', '-1', '--format=%ai'],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                timeout=5
            )
            commit_date = result.stdout.strip() if result.returncode == 0 else "unknown"
        except:
            pass

        return jsonify({
            'version': version,
            'version_source': source,
            'commit_date': commit_date,
            'installed_at': str(BASE_DIR)
        })
    except Exception as e:
        print(f"[API] Error getting version: {e}")
        return jsonify({'error': str(e)}), 500


# ==================== JAR Bucket Manager ====================

SERVER_EXECUTABLES_DIR = BASE_DIR / 'serverexecutables'
JAR_CACHE_FILE = BASE_DIR / 'jar_cache.json'
JAR_CACHE_MAX_AGE_HOURS = 6  # Refresh cache every 6 hours

class JarBucketManager:
    """
    Manager for downloading Minecraft server JAR files from various sources.
    Inspired by Crafty Controller's Big Bucket system.
    """
    
    # API URLs for various server types
    API_URLS = {
        'paper': 'https://api.papermc.io/v2/',
        'velocity': 'https://api.papermc.io/v2/',
        'waterfall': 'https://api.papermc.io/v2/',
        'folia': 'https://api.papermc.io/v2/',
        'purpur': 'https://api.purpurmc.org/v2/purpur/',
        'vanilla': 'https://launchermeta.mojang.com/mc/game/version_manifest.json',
        'fabric': 'https://meta.fabricmc.net/v2/',
        'forge': 'https://maven.minecraftforge.net/net/minecraftforge/forge/',
        'neoforge': 'https://maven.neoforged.net/releases/net/neoforged/neoforge/',
        'spigot': 'https://hub.spigotmc.org/versions/',
        'bungeecord': 'https://ci.md-5.net/job/BungeeCord/lastSuccessfulBuild/artifact/bootstrap/target/BungeeCord.jar'
    }
    
    # Server type metadata with descriptions
    SERVER_TYPES = {
        'vanilla': {
            'name': 'Vanilla',
            'description': 'Official Minecraft Java Edition server',
            'category': 'servers',
            'icon': '🎮'
        },
        'paper': {
            'name': 'Paper',
            'description': 'High-performance Spigot fork with optimizations',
            'category': 'servers',
            'icon': '📄'
        },
        'purpur': {
            'name': 'Purpur',
            'description': 'Paper fork with extra features and configuration',
            'category': 'servers',
            'icon': '💜'
        },
        'folia': {
            'name': 'Folia',
            'description': 'Paper fork for multi-threaded regions',
            'category': 'servers',
            'icon': '🌿'
        },
        'spigot': {
            'name': 'Spigot',
            'description': 'Modified Minecraft server with Bukkit plugin support',
            'category': 'servers',
            'icon': '🔧'
        },
        'fabric': {
            'name': 'Fabric',
            'description': 'Lightweight mod loader for Minecraft',
            'category': 'modded',
            'icon': '🧵'
        },
        'forge': {
            'name': 'Forge',
            'description': 'Popular mod loader for Minecraft mods',
            'category': 'modded',
            'icon': '⚒️'
        },
        'neoforge': {
            'name': 'NeoForge',
            'description': 'Modern community-driven Forge fork',
            'category': 'modded',
            'icon': '🔨'
        },
        'velocity': {
            'name': 'Velocity',
            'description': 'Modern, high-performance Minecraft proxy',
            'category': 'proxies',
            'icon': '⚡'
        },
        'waterfall': {
            'name': 'Waterfall',
            'description': 'BungeeCord fork with improvements',
            'category': 'proxies',
            'icon': '💧'
        },
        'bungeecord': {
            'name': 'BungeeCord',
            'description': 'Minecraft server proxy for multiple servers',
            'category': 'proxies',
            'icon': '🔗'
        }
    }
    
    # Known Forge versions mapping (MC version -> Forge version)
    FORGE_VERSIONS = {
        '1.21.5': '55.1.6', '1.21.4': '54.1.12', '1.21.3': '53.1.6',
        '1.21.1': '52.1.9', '1.21': '51.0.33', '1.20.6': '50.2.4',
        '1.20.4': '49.2.4', '1.20.3': '49.0.2', '1.20.2': '48.1.0',
        '1.20.1': '47.4.15', '1.20': '46.0.14', '1.19.4': '45.4.3',
        '1.19.3': '44.1.23', '1.19.2': '43.5.2', '1.19.1': '42.0.9',
        '1.19': '41.1.0', '1.18.2': '40.3.12', '1.18.1': '39.1.2',
        '1.18': '38.0.17', '1.17.1': '37.1.1', '1.16.5': '36.2.42',
        '1.16.4': '35.1.37', '1.16.3': '34.1.42', '1.16.2': '33.0.61',
        '1.16.1': '32.0.108', '1.15.2': '31.2.60', '1.14.4': '28.2.28',
        '1.12.2': '14.23.5.2864'
    }
    
    # Known NeoForge versions mapping (MC version -> NeoForge version)
    NEOFORGE_VERSIONS = {
        '1.21.5': '21.5.96', '1.21.4': '21.4.156', '1.21.3': '21.3.95',
        '1.21.1': '21.1.218', '1.21': '21.0.167', '1.20.6': '20.6.139',
        '1.20.4': '20.4.251', '1.20.3': '20.3.8-beta', '1.20.2': '20.2.93'
    }
    
    def __init__(self):
        self.cache = self._load_cache()
        self.download_progress = {}  # Track download progress by ID
    
    def _load_cache(self):
        """Load cached version data from file"""
        if JAR_CACHE_FILE.exists():
            try:
                with open(JAR_CACHE_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[JarBucket] Error loading cache: {e}")
        return {'last_updated': None, 'versions': {}}
    
    def _save_cache(self):
        """Save version data to cache file"""
        try:
            with open(JAR_CACHE_FILE, 'w') as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            print(f"[JarBucket] Error saving cache: {e}")
    
    def _is_cache_valid(self, server_type=None):
        """Check if cache is still valid (not too old)"""
        if not self.cache.get('last_updated'):
            return False
        
        # Check specific server type cache
        if server_type:
            type_cache = self.cache.get('versions', {}).get(server_type)
            if not type_cache or not type_cache.get('last_updated'):
                return False
            last_updated = datetime.fromisoformat(type_cache['last_updated'])
        else:
            last_updated = datetime.fromisoformat(self.cache['last_updated'])
        
        age_hours = (datetime.now() - last_updated).total_seconds() / 3600
        return age_hours < JAR_CACHE_MAX_AGE_HOURS
    
    def get_server_types(self):
        """Get list of available server types with metadata"""
        types_by_category = {'servers': [], 'modded': [], 'proxies': []}
        
        for type_id, info in self.SERVER_TYPES.items():
            category = info.get('category', 'servers')
            types_by_category.setdefault(category, []).append({
                'id': type_id,
                **info
            })
        
        return types_by_category
    
    def _fetch_paper_versions(self, project='paper'):
        """Fetch versions from Paper API (Paper, Folia, Velocity, Waterfall)"""
        try:
            url = f"{self.API_URLS['paper']}projects/{project}"
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                return list(reversed(data.get('versions', [])))
        except Exception as e:
            print(f"[JarBucket] Error fetching {project} versions: {e}")
        return []
    
    def _fetch_paper_download_url(self, project, version):
        """Get download URL for Paper-based project"""
        try:
            # Get builds for version
            url = f"{self.API_URLS['paper']}projects/{project}/versions/{version}"
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                return None, None
            
            data = response.json()
            builds = data.get('builds', [])
            if not builds:
                return None, None
            
            latest_build = max(builds)
            
            # Get download info
            build_url = f"{self.API_URLS['paper']}projects/{project}/versions/{version}/builds/{latest_build}"
            build_response = requests.get(build_url, timeout=10)
            if build_response.status_code != 200:
                return None, None
            
            build_data = build_response.json()
            downloads = build_data.get('downloads', {})
            application = downloads.get('application', {})
            jar_name = application.get('name')
            sha256 = application.get('sha256')
            
            if jar_name:
                download_url = f"{self.API_URLS['paper']}projects/{project}/versions/{version}/builds/{latest_build}/downloads/{jar_name}"
                return download_url, sha256
        except Exception as e:
            print(f"[JarBucket] Error getting {project} download URL: {e}")
        return None, None
    
    def _fetch_purpur_versions(self):
        """Fetch versions from Purpur API"""
        try:
            response = requests.get(self.API_URLS['purpur'], timeout=15)
            if response.status_code == 200:
                data = response.json()
                return list(reversed(data.get('versions', [])))
        except Exception as e:
            print(f"[JarBucket] Error fetching Purpur versions: {e}")
        return []
    
    def _fetch_purpur_download_url(self, version):
        """Get download URL for Purpur"""
        try:
            url = f"{self.API_URLS['purpur']}{version}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                builds = data.get('builds', {})
                latest = builds.get('latest')
                if latest:
                    return f"{self.API_URLS['purpur']}{version}/{latest}/download", None
        except Exception as e:
            print(f"[JarBucket] Error getting Purpur download URL: {e}")
        return None, None
    
    def _fetch_vanilla_versions(self):
        """Fetch versions from Mojang manifest"""
        try:
            response = requests.get(self.API_URLS['vanilla'], timeout=15)
            if response.status_code == 200:
                data = response.json()
                versions = []
                for ver in data.get('versions', []):
                    if ver.get('type') == 'release':
                        try:
                            # Filter versions 1.10+
                            minor = int(ver['id'].split('.')[1])
                            if minor >= 10:
                                versions.append({
                                    'id': ver['id'],
                                    'url': ver['url']
                                })
                        except (ValueError, IndexError):
                            continue
                return versions
        except Exception as e:
            print(f"[JarBucket] Error fetching Vanilla versions: {e}")
        return []
    
    def _fetch_vanilla_download_url(self, version_url):
        """Get download URL for Vanilla server"""
        try:
            response = requests.get(version_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                server = data.get('downloads', {}).get('server', {})
                return server.get('url'), server.get('sha1')
        except Exception as e:
            print(f"[JarBucket] Error getting Vanilla download URL: {e}")
        return None, None
    
    def _fetch_fabric_versions(self):
        """Fetch Fabric loader versions and game versions"""
        try:
            # Get supported game versions
            game_url = f"{self.API_URLS['fabric']}game"
            response = requests.get(game_url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                versions = []
                for ver in data:
                    if ver.get('stable'):
                        versions.append(ver['version'])
                return versions
        except Exception as e:
            print(f"[JarBucket] Error fetching Fabric versions: {e}")
        return []
    
    def _get_fabric_loader_version(self):
        """Get latest stable Fabric loader version"""
        try:
            url = f"{self.API_URLS['fabric']}loader"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for loader in data:
                    if loader.get('stable'):
                        return loader['version']
        except Exception as e:
            print(f"[JarBucket] Error getting Fabric loader version: {e}")
        return '0.16.10'  # Fallback
    
    def _fetch_fabric_download_url(self, game_version):
        """Get download URL for Fabric server"""
        try:
            loader_version = self._get_fabric_loader_version()
            installer_version = '1.0.1'  # Stable installer
            # Server JAR URL format
            download_url = f"https://meta.fabricmc.net/v2/versions/loader/{game_version}/{loader_version}/{installer_version}/server/jar"
            return download_url, None
        except Exception as e:
            print(f"[JarBucket] Error getting Fabric download URL: {e}")
        return None, None
    
    def get_versions(self, server_type, force_refresh=False):
        """Get available versions for a server type"""
        # Check cache first
        if not force_refresh and self._is_cache_valid(server_type):
            cached = self.cache.get('versions', {}).get(server_type, {}).get('data', [])
            if cached:
                return cached
        
        versions = []
        
        # Fetch based on server type
        if server_type == 'paper':
            versions = self._fetch_paper_versions('paper')
        elif server_type == 'folia':
            versions = self._fetch_paper_versions('folia')
        elif server_type == 'velocity':
            versions = self._fetch_paper_versions('velocity')
        elif server_type == 'waterfall':
            versions = self._fetch_paper_versions('waterfall')
        elif server_type == 'purpur':
            versions = self._fetch_purpur_versions()
        elif server_type == 'vanilla':
            vanilla_data = self._fetch_vanilla_versions()
            versions = [{'version': v['id'], 'manifest_url': v['url']} for v in vanilla_data]
        elif server_type == 'fabric':
            versions = self._fetch_fabric_versions()
        elif server_type == 'forge':
            versions = list(self.FORGE_VERSIONS.keys())
        elif server_type == 'neoforge':
            versions = list(self.NEOFORGE_VERSIONS.keys())
        elif server_type == 'spigot':
            # Spigot requires BuildTools, return common versions
            versions = ['1.21.4', '1.21.3', '1.21.1', '1.21', '1.20.6', '1.20.4', 
                       '1.20.2', '1.20.1', '1.19.4', '1.19.3', '1.19.2', '1.18.2', 
                       '1.17.1', '1.16.5', '1.15.2', '1.14.4', '1.13.2', '1.12.2']
        elif server_type == 'bungeecord':
            versions = ['latest']
        
        # Update cache
        if versions:
            if 'versions' not in self.cache:
                self.cache['versions'] = {}
            self.cache['versions'][server_type] = {
                'last_updated': datetime.now().isoformat(),
                'data': versions
            }
            self.cache['last_updated'] = datetime.now().isoformat()
            self._save_cache()
        
        return versions
    
    def get_download_info(self, server_type, version):
        """Get download URL and hash for a specific version"""
        download_url = None
        file_hash = None
        filename = None
        
        if server_type in ['paper', 'folia', 'velocity', 'waterfall']:
            download_url, file_hash = self._fetch_paper_download_url(server_type, version)
            filename = f"{server_type}-{version}.jar"
        elif server_type == 'purpur':
            download_url, file_hash = self._fetch_purpur_download_url(version)
            filename = f"purpur-{version}.jar"
        elif server_type == 'vanilla':
            # Need to look up manifest URL
            vanilla_versions = self.get_versions('vanilla')
            for v in vanilla_versions:
                if isinstance(v, dict) and v.get('version') == version:
                    download_url, file_hash = self._fetch_vanilla_download_url(v['manifest_url'])
                    break
            filename = f"vanilla-{version}.jar"
        elif server_type == 'fabric':
            download_url, file_hash = self._fetch_fabric_download_url(version)
            filename = f"fabric-{version}.jar"
        elif server_type == 'forge':
            forge_ver = self.FORGE_VERSIONS.get(version)
            if forge_ver:
                download_url = f"{self.API_URLS['forge']}{version}-{forge_ver}/forge-{version}-{forge_ver}-installer.jar"
                filename = f"forge-{version}-{forge_ver}-installer.jar"
        elif server_type == 'neoforge':
            neo_ver = self.NEOFORGE_VERSIONS.get(version)
            if neo_ver:
                download_url = f"{self.API_URLS['neoforge']}{neo_ver}/neoforge-{neo_ver}-installer.jar"
                filename = f"neoforge-{neo_ver}-installer.jar"
        elif server_type == 'bungeecord':
            download_url = self.API_URLS['bungeecord']
            filename = "BungeeCord.jar"
        elif server_type == 'spigot':
            # Spigot requires BuildTools - return info about that
            return {
                'requires_build': True,
                'message': 'Spigot requires BuildTools to compile. Download BuildTools and run: java -jar BuildTools.jar --rev ' + version,
                'buildtools_url': 'https://hub.spigotmc.org/jenkins/job/BuildTools/lastSuccessfulBuild/artifact/target/BuildTools.jar'
            }
        
        if download_url:
            return {
                'url': download_url,
                'hash': file_hash,
                'filename': filename,
                'hash_type': 'sha256' if file_hash and len(file_hash) == 64 else 'sha1'
            }
        
        return None
    
    def download_jar(self, server_type, version, progress_id=None):
        """Download a JAR file to serverexecutables folder"""
        download_info = self.get_download_info(server_type, version)
        
        if not download_info:
            return {'success': False, 'error': 'Could not find download URL for this version'}
        
        if download_info.get('requires_build'):
            return {'success': False, 'error': download_info.get('message'), 'requires_build': True}
        
        url = download_info['url']
        filename = download_info['filename']
        
        # Create directory
        type_dir = SERVER_EXECUTABLES_DIR / server_type
        type_dir.mkdir(parents=True, exist_ok=True)
        filepath = type_dir / filename
        
        try:
            # Download with progress tracking
            response = requests.get(url, stream=True, timeout=300)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            if progress_id:
                self.download_progress[progress_id] = {
                    'status': 'downloading',
                    'total': total_size,
                    'downloaded': 0,
                    'percent': 0
                }
            
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_id and total_size:
                            self.download_progress[progress_id] = {
                                'status': 'downloading',
                                'total': total_size,
                                'downloaded': downloaded,
                                'percent': int((downloaded / total_size) * 100)
                            }
            
            # Verify hash if available
            if download_info.get('hash'):
                file_hash = self._calculate_hash(filepath, download_info.get('hash_type', 'sha256'))
                if file_hash != download_info['hash']:
                    filepath.unlink()  # Delete mismatched file
                    return {'success': False, 'error': 'Hash verification failed'}
            
            if progress_id:
                self.download_progress[progress_id] = {
                    'status': 'complete',
                    'total': total_size,
                    'downloaded': downloaded,
                    'percent': 100
                }
            
            return {
                'success': True,
                'message': f'Downloaded {filename} successfully',
                'path': str(filepath.relative_to(BASE_DIR)),
                'filename': filename,
                'size': downloaded
            }
            
        except requests.exceptions.RequestException as e:
            if filepath.exists():
                filepath.unlink()
            if progress_id:
                self.download_progress[progress_id] = {'status': 'error', 'error': str(e)}
            return {'success': False, 'error': f'Download failed: {str(e)}'}
        except Exception as e:
            if filepath.exists():
                filepath.unlink()
            if progress_id:
                self.download_progress[progress_id] = {'status': 'error', 'error': str(e)}
            return {'success': False, 'error': f'Error: {str(e)}'}
    
    def _calculate_hash(self, filepath, hash_type='sha256'):
        """Calculate file hash"""
        if hash_type == 'sha1':
            hasher = hashlib.sha1()
        else:
            hasher = hashlib.sha256()
        
        with open(filepath, 'rb') as f:
            while True:
                data = f.read(65536)
                if not data:
                    break
                hasher.update(data)
        
        return hasher.hexdigest()
    
    def list_downloaded_jars(self):
        """List all downloaded JAR files organized by type"""
        jars = {}
        
        if SERVER_EXECUTABLES_DIR.exists():
            for type_dir in SERVER_EXECUTABLES_DIR.iterdir():
                if type_dir.is_dir():
                    server_type = type_dir.name
                    type_info = self.SERVER_TYPES.get(server_type, {})
                    jars[server_type] = {
                        'name': type_info.get('name', server_type.title()),
                        'icon': type_info.get('icon', '📦'),
                        'files': []
                    }
                    
                    for jar_file in sorted(type_dir.iterdir(), reverse=True):
                        if jar_file.is_file() and jar_file.suffix in ['.jar', '.zip']:
                            # Extract version from filename
                            version = self._extract_version_from_filename(jar_file.name, server_type)
                            jars[server_type]['files'].append({
                                'filename': jar_file.name,
                                'version': version,
                                'size': jar_file.stat().st_size,
                                'path': str(jar_file.relative_to(BASE_DIR)),
                                'modified': datetime.fromtimestamp(jar_file.stat().st_mtime).isoformat()
                            })
        
        return jars
    
    def _extract_version_from_filename(self, filename, server_type):
        """Extract version from filename"""
        import re
        name = filename.replace('.jar', '').replace('.zip', '').replace('-installer', '')
        
        # Try to extract version pattern
        match = re.search(rf'{server_type}-([\d.]+(?:-[\d.]+)?(?:-beta)?)', name, re.IGNORECASE)
        if match:
            return match.group(1)
        
        # Generic version pattern
        match = re.search(r'(\d+\.\d+(?:\.\d+)?(?:-[\d.]+)?)', name)
        if match:
            return match.group(1)
        
        return 'unknown'
    
    def delete_jar(self, server_type, filename):
        """Delete a downloaded JAR file"""
        filepath = SERVER_EXECUTABLES_DIR / server_type / filename
        
        if not filepath.exists():
            return {'success': False, 'error': 'File not found'}
        
        try:
            filepath.relative_to(SERVER_EXECUTABLES_DIR)
        except ValueError:
            return {'success': False, 'error': 'Invalid path'}
        
        try:
            filepath.unlink()
            return {'success': True, 'message': f'Deleted {filename}'}
        except Exception as e:
            return {'success': False, 'error': f'Failed to delete: {str(e)}'}


# Initialize JAR Bucket Manager
jar_bucket = JarBucketManager()


# ==================== JAR Bucket API Endpoints ====================

@app.route('/api/jar-bucket/types', methods=['GET'])
@admin_required
def api_jar_bucket_types():
    """Get available server types organized by category"""
    return jsonify(jar_bucket.get_server_types())

@app.route('/api/jar-bucket/versions/<server_type>', methods=['GET'])
@admin_required
def api_jar_bucket_versions(server_type):
    """Get available versions for a server type"""
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'
    versions = jar_bucket.get_versions(server_type, force_refresh)
    
    # Normalize version format
    normalized = []
    for v in versions:
        if isinstance(v, dict):
            normalized.append(v.get('version', str(v)))
        else:
            normalized.append(str(v))
    
    return jsonify({
        'server_type': server_type,
        'versions': normalized,
        'count': len(normalized)
    })

@app.route('/api/jar-bucket/download', methods=['POST'])
@admin_required
def api_jar_bucket_download():
    """Download a specific server JAR"""
    data = request.get_json()
    server_type = data.get('type', '').strip().lower()
    version = data.get('version', '').strip()
    
    if not server_type or not version:
        return jsonify({'error': 'Missing server type or version'}), 400
    
    # Validate server type
    import re
    if not re.match(r'^[a-z0-9-]+$', server_type):
        return jsonify({'error': 'Invalid server type'}), 400
    
    # Generate progress ID
    progress_id = str(uuid.uuid4())
    
    # Start download in background thread
    def do_download():
        result = jar_bucket.download_jar(server_type, version, progress_id)
        jar_bucket.download_progress[progress_id] = {
            'status': 'complete' if result.get('success') else 'error',
            **result
        }
    
    thread = threading.Thread(target=do_download, daemon=True)
    thread.start()
    
    return jsonify({
        'progress_id': progress_id,
        'message': f'Starting download of {server_type} {version}'
    })

@app.route('/api/jar-bucket/progress/<progress_id>', methods=['GET'])
@admin_required
def api_jar_bucket_progress(progress_id):
    """Get download progress"""
    progress = jar_bucket.download_progress.get(progress_id)
    if progress:
        return jsonify(progress)
    return jsonify({'status': 'unknown'}), 404

@app.route('/api/jar-bucket/list', methods=['GET'])
@admin_required
def api_jar_bucket_list():
    """List all downloaded JAR files"""
    return jsonify({'jars': jar_bucket.list_downloaded_jars()})

@app.route('/api/jar-bucket/delete', methods=['DELETE'])
@admin_required
def api_jar_bucket_delete():
    """Delete a downloaded JAR file"""
    data = request.get_json()
    server_type = data.get('type', '').strip().lower()
    filename = data.get('filename', '').strip()
    
    if not server_type or not filename:
        return jsonify({'error': 'Missing type or filename'}), 400
    
    result = jar_bucket.delete_jar(server_type, filename)
    if result.get('success'):
        return jsonify(result)
    return jsonify(result), 400

@app.route('/api/jar-bucket/info/<server_type>/<version>', methods=['GET'])
@admin_required
def api_jar_bucket_info(server_type, version):
    """Get download info for a specific version (URL, hash, etc.)"""
    info = jar_bucket.get_download_info(server_type, version)
    if info:
        return jsonify(info)
    return jsonify({'error': 'Version not found'}), 404

@app.route('/api/jar-bucket/refresh', methods=['POST'])
@admin_required
def api_jar_bucket_refresh():
    """Force refresh the version cache"""
    data = request.get_json() or {}
    server_type = data.get('type')
    
    if server_type:
        jar_bucket.get_versions(server_type, force_refresh=True)
        return jsonify({'message': f'Refreshed {server_type} versions'})
    else:
        # Refresh all
        for st in jar_bucket.SERVER_TYPES.keys():
            jar_bucket.get_versions(st, force_refresh=True)
        return jsonify({'message': 'Refreshed all versions'})


# ==================== Legacy JAR Downloader API (for backward compatibility) ====================

@app.route('/api/tools/jar-downloader/download', methods=['POST'])
@admin_required
def download_jar_legacy():
    """Download a JAR file to serverexecutables folder (legacy endpoint)"""
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
def list_downloaded_jars_legacy():
    """List all downloaded JAR files (legacy endpoint)"""
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
def delete_downloaded_jar_legacy():
    """Delete a downloaded JAR file (legacy endpoint)"""
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


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='MServerController - Minecraft Server Management System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Run the server (default)
  python server.py
  
  # Run on a custom port
  python server.py --port 8080
  
  # Run with SSL/HTTPS
  python server.py --ssl-cert /path/to/cert.pem --ssl-key /path/to/key.pem
        '''
    )
    
    parser.add_argument(
        '--port',
        type=int,
        default=PORT,
        help=f'Port to run the server on (default: {PORT})'
    )
    
    parser.add_argument(
        '--host',
        type=str,
        default='0.0.0.0',
        help='Host address to bind to (default: 0.0.0.0)'
    )
    
    parser.add_argument(
        '--ssl-cert',
        type=str,
        help='Path to SSL certificate file for HTTPS'
    )
    
    parser.add_argument(
        '--ssl-key',
        type=str,
        help='Path to SSL private key file for HTTPS'
    )
    
    return parser.parse_args()


def run_server(host='0.0.0.0', port=3000, ssl_cert=None, ssl_key=None):
    """Run the MServerController server"""
    print('=' * 60)
    print('MServerController')
    print('=' * 60)
    
    # Determine protocol
    protocol = 'https' if ssl_cert and ssl_key else 'http'
    print(f'Web Interface: {protocol}://localhost:{port}')
    print(f'Listening on: {host}:{port}')
    
    if ssl_cert and ssl_key:
        print(f'✓ SSL/TLS Enabled')
        print(f'  Certificate: {ssl_cert}')
        print(f'  Key: {ssl_key}')
    else:
        print('⚠️  WARNING: Running without SSL/TLS encryption')
    
    print('⚠️  WARNING: Default admin credentials are admin/admin')
    print('            Change immediately after first login!')
    print('=' * 60)
    
    # Configure SSL context if certificates provided
    if ssl_cert and ssl_key:
        # For Flask-SocketIO with eventlet, we need to pass certfile and keyfile
        socketio.run(app, host=host, port=port, debug=False, 
                    certfile=ssl_cert, keyfile=ssl_key)
    else:
        socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    args = parse_arguments()
    
    # Validate SSL arguments
    if (args.ssl_cert and not args.ssl_key) or (args.ssl_key and not args.ssl_cert):
        print('ERROR: Both --ssl-cert and --ssl-key are required for SSL')
        sys.exit(1)
    
    # Update PORT global if custom port specified
    if args.port != PORT:
        globals()['PORT'] = args.port
    
    # Run the server
    run_server(
        host=args.host, 
        port=args.port,
        ssl_cert=args.ssl_cert,
        ssl_key=args.ssl_key
    )
