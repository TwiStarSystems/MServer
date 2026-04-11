#!/usr/bin/env python3
"""
MServerController - A web-based Minecraft server controller and manager
Python/Flask implementation with multi-server support and RBAC
"""

import os
import io
import re
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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from enum import Enum
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from flask import Flask, request, jsonify, send_from_directory, send_file, session, redirect, url_for, make_response
from flask_socketio import SocketIO, emit
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect, generate_csrf
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__, static_folder='public', static_url_path='')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False  # HTTP only - no HTTPS
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Disable caching for development

# Configure ProxyFix for reverse proxy (e.g., Nginx) headers
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# Initialize CSRF Protection
csrf = CSRFProtect(app)

# Initialize SocketIO with threading async mode and tuned ping settings.
# Threading mode works natively with the existing subprocess/thread-based
# architecture. The simple-websocket package provides real WebSocket support
# (not just long-polling) without requiring gevent monkey-patching.
socketio = SocketIO(
    app,
    manage_session=False,
    async_mode='threading',
    ping_interval=25,
    ping_timeout=60,
    cors_allowed_origins='*'
)

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


# --- Minecraft version era helpers ---
# MC_LEGACY_MAX: highest version in the pre-1.26 world format.  Legacy servers
#   may upgrade/downgrade within this tier but cannot cross to the modern era.
# MC_MODERN_MIN: first version with the new world storage format.
MC_LEGACY_MAX = '1.21.11'
MC_MODERN_MIN = '1.26'


def _parse_mc_version_tuple(v):
    """Convert a MC version string to a sortable integer tuple (a, b, c).
    Strips modloader suffixes (e.g. '1.21.3-53.0.26' -> '1.21.3').
    Handles '1.21.4', '1.26', '26.1', etc.
    """
    base = str(v).split('-')[0]
    parts = re.findall(r'\d+', base)
    nums = [int(p) for p in parts[:3]]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def mc_version_is_modern(v):
    """Return True if version is in the 1.26+ (new world format) era."""
    m = re.match(r'(\d+)\.(\d+)', str(v))
    if not m:
        return False
    major, minor = int(m.group(1)), int(m.group(2))
    # '1.26', '1.27' ... OR new-scheme '26.1', '27.x'
    return major >= 26 or (major == 1 and minor >= 26)


def mc_version_is_legacy(v):
    """Return True if version is in the legacy (<=1.21.x) era."""
    m = re.match(r'(\d+)\.(\d+)', str(v))
    if not m:
        return True  # unparseable defaults to legacy
    major, minor = int(m.group(1)), int(m.group(2))
    return major == 1 and minor <= 21


def compare_mc_versions(v1, v2):
    """Compare two MC version strings. Returns -1, 0, or 1."""
    t1 = _parse_mc_version_tuple(v1)
    t2 = _parse_mc_version_tuple(v2)
    if t1 < t2:
        return -1
    if t1 > t2:
        return 1
    return 0


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
        },
        'smtp': {
            'enabled': False,
            'host': '',
            'port': 587,
            'secure': True,
            'username': '',
            'password': '',
            'fromEmail': '',
            'fromName': 'MServerController'
        },
        'externalBackup': {
            'enabled': False,
            'type': 'ftp',  # 'ftp' or 's3'
            's3': {
                'bucket': '',
                'region': 'us-east-1',
                'accessKey': '',
                'secretKey': '',
                'prefix': 'backups/'
            },
            'ftp': {
                'host': '',
                'port': 21,
                'username': '',
                'password': '',
                'remotePath': '/backups/',
                'passive': True
            }
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
    
    def update_mfa_settings(self, mfa_data):
        """Update MFA settings"""
        if 'mfa' not in self.settings:
            self.settings['mfa'] = {}
        
        for key in ['requireMfaForAdmins', 'requireMfaForAllUsers']:
            if key in mfa_data:
                self.settings['mfa'][key] = mfa_data[key]
        
        self._save_settings()
        return self.settings['mfa']
    
    def get_smtp_settings(self):
        """Get SMTP settings (without password for security)"""
        smtp = self.settings.get('smtp', self.DEFAULT_SETTINGS['smtp']).copy()
        # Don't expose the password
        if 'password' in smtp:
            smtp['password'] = '********' if smtp['password'] else ''
        return smtp
    
    def get_smtp_settings_full(self):
        """Get full SMTP settings including password (for internal use)"""
        return self.settings.get('smtp', self.DEFAULT_SETTINGS['smtp'])
    
    def update_smtp_settings(self, smtp_data):
        """Update SMTP settings"""
        if 'smtp' not in self.settings:
            self.settings['smtp'] = self.DEFAULT_SETTINGS['smtp'].copy()
        
        for key in ['enabled', 'host', 'port', 'secure', 'username', 'fromEmail', 'fromName']:
            if key in smtp_data:
                self.settings['smtp'][key] = smtp_data[key]
        
        # Only update password if it's not the placeholder
        if 'password' in smtp_data and smtp_data['password'] != '********':
            self.settings['smtp']['password'] = smtp_data['password']
        
        self._save_settings()
        return self.get_smtp_settings()
    
    def is_smtp_configured(self):
        """Check if SMTP is properly configured"""
        smtp = self.settings.get('smtp', {})
        return (
            smtp.get('enabled', False) and
            smtp.get('host') and
            smtp.get('fromEmail')
        )

    def get_external_backup_settings(self):
        """Get external backup settings (passwords masked)"""
        ext = self.settings.get('externalBackup',
                                self.DEFAULT_SETTINGS['externalBackup']).copy()
        # Deep copy and mask secrets
        ext = json.loads(json.dumps(ext))
        if ext.get('s3', {}).get('secretKey'):
            ext['s3']['secretKey'] = '********'
        if ext.get('ftp', {}).get('password'):
            ext['ftp']['password'] = '********'
        return ext

    def get_external_backup_settings_full(self):
        """Get full external backup settings including secrets (internal use)"""
        return self.settings.get('externalBackup',
                                 self.DEFAULT_SETTINGS['externalBackup'])

    def update_external_backup_settings(self, data):
        """Update external backup settings"""
        if 'externalBackup' not in self.settings:
            self.settings['externalBackup'] = json.loads(
                json.dumps(self.DEFAULT_SETTINGS['externalBackup'])
            )
        ext = self.settings['externalBackup']

        for key in ['enabled', 'type']:
            if key in data:
                ext[key] = data[key]

        if 's3' in data:
            if 's3' not in ext:
                ext['s3'] = {}
            for key in ['bucket', 'region', 'accessKey', 'prefix']:
                if key in data['s3']:
                    ext['s3'][key] = data['s3'][key]
            if 'secretKey' in data['s3'] and data['s3']['secretKey'] != '********':
                ext['s3']['secretKey'] = data['s3']['secretKey']

        if 'ftp' in data:
            if 'ftp' not in ext:
                ext['ftp'] = {}
            for key in ['host', 'port', 'username', 'remotePath', 'passive']:
                if key in data['ftp']:
                    ext['ftp'][key] = data['ftp'][key]
            if 'password' in data['ftp'] and data['ftp']['password'] != '********':
                ext['ftp']['password'] = data['ftp']['password']

        self._save_settings()
        return self.get_external_backup_settings()


# ==================== Email Service ====================

class EmailService:
    """Handles email sending via SMTP"""
    
    def __init__(self, settings_manager):
        self.settings_manager = settings_manager
    
    def send_email(self, to_email, subject, html_content, text_content=None):
        """Send an email using configured SMTP settings"""
        if not self.settings_manager.is_smtp_configured():
            return False, "SMTP is not configured"
        
        smtp_settings = self.settings_manager.get_smtp_settings_full()
        
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{smtp_settings['fromName']} <{smtp_settings['fromEmail']}>"
            msg['To'] = to_email
            
            # Add text part
            if text_content:
                msg.attach(MIMEText(text_content, 'plain'))
            
            # Add HTML part
            msg.attach(MIMEText(html_content, 'html'))
            
            # Connect to SMTP server
            if smtp_settings.get('secure', True):
                server = smtplib.SMTP(smtp_settings['host'], smtp_settings['port'])
                server.starttls()
            else:
                server = smtplib.SMTP(smtp_settings['host'], smtp_settings['port'])
            
            # Login if credentials provided
            if smtp_settings.get('username') and smtp_settings.get('password'):
                server.login(smtp_settings['username'], smtp_settings['password'])
            
            # Send email
            server.sendmail(smtp_settings['fromEmail'], to_email, msg.as_string())
            server.quit()
            
            return True, "Email sent successfully"
        except smtplib.SMTPAuthenticationError:
            return False, "SMTP authentication failed"
        except smtplib.SMTPException as e:
            return False, f"SMTP error: {str(e)}"
        except Exception as e:
            return False, f"Failed to send email: {str(e)}"
    
    def send_backup_notification(self, to_email, server_name, backup_name, success=True, error_message=None):
        """Send backup completion notification"""
        site_title = self.settings_manager.get_branding().get('siteTitle', 'MServerController')
        
        if success:
            subject = f"[{site_title}] Backup Complete: {server_name}"
            html_content = f"""
            <html>
            <body style="font-family: Arial, sans-serif; background-color: #1a1a2e; color: #e0e0e0; padding: 20px;">
                <div style="max-width: 600px; margin: 0 auto; background-color: #16213e; border-radius: 8px; padding: 30px;">
                    <h2 style="color: #10b981; margin-top: 0;">✅ Backup Completed Successfully</h2>
                    <p style="margin: 10px 0;"><strong>Server:</strong> {server_name}</p>
                    <p style="margin: 10px 0;"><strong>Backup Name:</strong> {backup_name}</p>
                    <p style="margin: 10px 0;"><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                    <hr style="border: 1px solid #333; margin: 20px 0;">
                    <p style="color: #888; font-size: 12px;">This is an automated notification from {site_title}.</p>
                </div>
            </body>
            </html>
            """
            text_content = f"Backup Completed Successfully\nServer: {server_name}\nBackup: {backup_name}\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        else:
            subject = f"[{site_title}] Backup Failed: {server_name}"
            html_content = f"""
            <html>
            <body style="font-family: Arial, sans-serif; background-color: #1a1a2e; color: #e0e0e0; padding: 20px;">
                <div style="max-width: 600px; margin: 0 auto; background-color: #16213e; border-radius: 8px; padding: 30px;">
                    <h2 style="color: #ef4444; margin-top: 0;">❌ Backup Failed</h2>
                    <p style="margin: 10px 0;"><strong>Server:</strong> {server_name}</p>
                    <p style="margin: 10px 0;"><strong>Error:</strong> {error_message or 'Unknown error'}</p>
                    <p style="margin: 10px 0;"><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                    <hr style="border: 1px solid #333; margin: 20px 0;">
                    <p style="color: #888; font-size: 12px;">This is an automated notification from {site_title}.</p>
                </div>
            </body>
            </html>
            """
            text_content = f"Backup Failed\nServer: {server_name}\nError: {error_message or 'Unknown error'}\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return self.send_email(to_email, subject, html_content, text_content)
    
    def send_test_email(self, to_email):
        """Send a test email to verify SMTP configuration"""
        site_title = self.settings_manager.get_branding().get('siteTitle', 'MServerController')
        subject = f"[{site_title}] Test Email"
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background-color: #1a1a2e; color: #e0e0e0; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #16213e; border-radius: 8px; padding: 30px;">
                <h2 style="color: #667eea; margin-top: 0;">🎮 {site_title} - Test Email</h2>
                <p>This is a test email to verify your SMTP configuration is working correctly.</p>
                <p style="margin: 10px 0;"><strong>Sent at:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <hr style="border: 1px solid #333; margin: 20px 0;">
                <p style="color: #10b981;">✅ If you're reading this, your email settings are configured correctly!</p>
            </div>
        </body>
        </html>
        """
        text_content = f"{site_title} - Test Email\n\nThis is a test email to verify your SMTP configuration is working correctly.\n\nSent at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\nIf you're reading this, your email settings are configured correctly!"
        
        return self.send_email(to_email, subject, html_content, text_content)


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


# ==================== Backup Helpers ====================

def verify_backup_file(backup_path):
    """Verify a ZIP backup's integrity and compute its SHA-256 checksum.

    Returns (ok: bool, checksum: str|None, error: str|None).
    Also writes a .sha256 sidecar file next to the backup.
    """
    backup_path = Path(backup_path)
    try:
        with zipfile.ZipFile(backup_path, 'r') as zf:
            bad = zf.testzip()
            if bad is not None:
                return False, None, f"Corrupt entry in ZIP: {bad}"

        sha256 = hashlib.sha256()
        with open(backup_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                sha256.update(chunk)
        checksum = sha256.hexdigest()

        sidecar = backup_path.with_suffix('.sha256')
        sidecar.write_text(f"{checksum}  {backup_path.name}\n")

        return True, checksum, None
    except zipfile.BadZipFile as e:
        return False, None, f"Bad ZIP file: {e}"
    except Exception as e:
        return False, None, str(e)


def upload_backup_to_external(backup_path, server_id, backup_name):
    """Upload a backup file to configured external storage (S3 or FTP).

    Returns (ok: bool, message: str).
    """
    ext = settings_manager.get_external_backup_settings_full()
    if not ext.get('enabled', False):
        return True, 'External backup not enabled'

    storage_type = ext.get('type', 'ftp')
    backup_path = Path(backup_path)

    if storage_type == 's3':
        try:
            import boto3
            s3_cfg = ext.get('s3', {})
            bucket = s3_cfg.get('bucket', '')
            region = s3_cfg.get('region', 'us-east-1')
            access_key = s3_cfg.get('accessKey', '')
            secret_key = s3_cfg.get('secretKey', '')
            prefix = s3_cfg.get('prefix', 'backups/').rstrip('/') + '/'

            if not bucket:
                return False, 'S3 bucket not configured'

            s3 = boto3.client(
                's3',
                region_name=region,
                aws_access_key_id=access_key or None,
                aws_secret_access_key=secret_key or None,
            )
            key = f"{prefix}{server_id}/{backup_name}"
            s3.upload_file(str(backup_path), bucket, key)
            return True, f"Uploaded to s3://{bucket}/{key}"
        except ImportError:
            return False, 'boto3 is not installed. Run: pip install boto3'
        except Exception as e:
            return False, f"S3 upload failed: {e}"

    elif storage_type == 'ftp':
        import ftplib
        ftp_cfg = ext.get('ftp', {})
        host = ftp_cfg.get('host', '')
        port = int(ftp_cfg.get('port', 21))
        username = ftp_cfg.get('username', '')
        password = ftp_cfg.get('password', '')
        remote_path = ftp_cfg.get('remotePath', '/backups/').rstrip('/') + '/'
        passive = ftp_cfg.get('passive', True)

        if not host:
            return False, 'FTP host not configured'

        try:
            ftp = ftplib.FTP()
            ftp.connect(host, port, timeout=30)
            ftp.login(username, password)
            ftp.set_pasv(passive)

            # Ensure remote directory exists
            remote_dir = f"{remote_path}{server_id}"
            try:
                ftp.mkd(remote_dir)
            except ftplib.error_perm:
                pass  # Directory already exists

            with open(backup_path, 'rb') as f:
                ftp.storbinary(f"STOR {remote_dir}/{backup_name}", f)
            ftp.quit()
            return True, f"Uploaded to ftp://{host}{remote_dir}/{backup_name}"
        except Exception as e:
            return False, f"FTP upload failed: {e}"

    return False, f"Unknown external storage type: {storage_type}"


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
            is_incremental = schedule.get('incremental', False)
            compression_level = max(0, min(9, int(schedule.get('compressionLevel', 6))))

            if is_incremental:
                backup_name = f'incremental-backup-{timestamp}.zip'
            else:
                backup_name = f'scheduled-backup-{timestamp}.zip'
            backup_path = backup_dir / backup_name

            # Determine cutoff time for incremental backups
            cutoff_time = None
            if is_incremental:
                cutoff_time = self._get_last_backup_time(server_id)
                if cutoff_time:
                    print(f"[Scheduler] Incremental backup since: {cutoff_time.isoformat()}")
                else:
                    print(f"[Scheduler] No previous backup found; performing full backup")
                    is_incremental = False  # fall back to full

            # Create the backup
            print(f"[Scheduler] Creating backup: {backup_name}")
            included_files = []
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED,
                                 compresslevel=compression_level) as zipf:
                for root, dirs, files in os.walk(server_path):
                    for file in files:
                        file_path = Path(root) / file
                        if cutoff_time is not None:
                            mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                            if mtime < cutoff_time:
                                continue
                        arcname = file_path.relative_to(server_path)
                        zipf.write(file_path, arcname)
                        included_files.append(str(arcname))

                # Write manifest for incremental backups
                if cutoff_time is not None:
                    manifest = {
                        'type': 'incremental',
                        'base_time': cutoff_time.isoformat(),
                        'created': timestamp,
                        'file_count': len(included_files)
                    }
                    zipf.writestr('backup_manifest.json', json.dumps(manifest, indent=2))
                else:
                    manifest = {
                        'type': 'full',
                        'created': timestamp,
                        'file_count': len(included_files)
                    }
                    zipf.writestr('backup_manifest.json', json.dumps(manifest, indent=2))

            size = backup_path.stat().st_size
            print(f"[Scheduler] Backup created: {backup_name} ({size} bytes)")

            # Verify backup integrity
            ok, checksum, verify_err = verify_backup_file(backup_path)
            if not ok:
                print(f"[Scheduler] Backup verification warning: {verify_err}")

            # Upload to external storage if configured
            ext_ok, ext_msg = upload_backup_to_external(backup_path, server_id, backup_name)
            if not ext_ok:
                print(f"[Scheduler] External upload warning: {ext_msg}")

            # Update last backup time
            self.schedules['schedules'][server_id]['lastBackup'] = datetime.now().isoformat()
            self._save_schedules()

            # Log backup event
            self._log_backup_event(server_id, {
                'type': 'scheduled',
                'backup_name': backup_name,
                'size': size,
                'is_incremental': cutoff_time is not None,
                'compression_level': compression_level,
                'verified': ok,
                'checksum': checksum,
                'uploaded_to_external': ext_ok,
                'success': True
            })

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
                'scheduled': True,
                'verified': ok,
                'checksum': checksum
            })

            print(f"[Scheduler] Scheduled backup completed for server: {server_id}")

        except Exception as e:
            print(f"[Scheduler] Backup failed for server {server_id}: {e}")
            self._log_backup_event(server_id, {
                'type': 'scheduled',
                'backup_name': None,
                'success': False,
                'error': str(e)
            })
            socketio.emit('backup_failed', {
                'serverId': server_id,
                'error': str(e),
                'scheduled': True
            })
    
    def _get_history_path(self, server_id):
        """Return path to the backup history log for a server"""
        return BACKUPS_DIR / server_id / '_backup_log.json'

    def _log_backup_event(self, server_id, event):
        """Append a backup event to the per-server history log"""
        history_path = self._get_history_path(server_id)
        try:
            if history_path.exists():
                with open(history_path, 'r') as f:
                    history = json.load(f)
            else:
                history = {'events': []}

            event.setdefault('id', str(uuid.uuid4()))
            event.setdefault('timestamp', datetime.now().isoformat())
            history['events'].insert(0, event)

            # Keep at most 500 events
            history['events'] = history['events'][:500]

            history_path.parent.mkdir(parents=True, exist_ok=True)
            with open(history_path, 'w') as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            print(f"[Backup] Failed to log backup event: {e}")

    def get_backup_history(self, server_id):
        """Return backup event history for a server"""
        history_path = self._get_history_path(server_id)
        if not history_path.exists():
            return []
        try:
            with open(history_path, 'r') as f:
                data = json.load(f)
            return data.get('events', [])
        except Exception:
            return []

    def _get_last_backup_time(self, server_id):
        """Return datetime of the most recent successful backup, or None"""
        history = self.get_backup_history(server_id)
        for event in history:
            if event.get('success'):
                try:
                    return datetime.fromisoformat(event['timestamp'])
                except Exception:
                    pass
        return None

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
                # Remove sidecar checksum file if present
                sidecar = backup_file.with_suffix('.sha256')
                if sidecar.exists():
                    sidecar.unlink()
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
            'compressionLevel': schedule_config.get('compressionLevel', 6),
            'incremental': schedule_config.get('incremental', False),
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
    
    def _is_server_running(self, server_id):
        """Check if a server is running via its ServerInstance"""
        instance = self.server_manager.servers.get(server_id)
        return instance is not None and instance.is_running()

    def _execute_start(self, server_id, task):
        """Start the server"""
        try:
            if not self._is_server_running(server_id):
                self.server_manager.start_server(server_id)
                print(f"[TaskScheduler] Started server {server_id}")
            else:
                print(f"[TaskScheduler] Server {server_id} is already running")
        except Exception as e:
            print(f"[TaskScheduler] Failed to start server {server_id}: {e}")
    
    def _execute_stop(self, server_id, task):
        """Stop the server"""
        try:
            if self._is_server_running(server_id):
                self.server_manager.stop_server(server_id)
                print(f"[TaskScheduler] Stopped server {server_id}")
            else:
                print(f"[TaskScheduler] Server {server_id} is not running")
        except Exception as e:
            print(f"[TaskScheduler] Failed to stop server {server_id}: {e}")
    
    def _execute_reboot(self, server_id, task):
        """Reboot the server (stop, wait, start)"""
        try:
            if self._is_server_running(server_id):
                print(f"[TaskScheduler] Rebooting server {server_id}...")
                
                # Stop the server
                self.server_manager.stop_server(server_id)
                
                # Wait for process to end
                max_wait = 60  # Maximum 60 seconds wait
                waited = 0
                while self._is_server_running(server_id) and waited < max_wait:
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
            if command and self._is_server_running(server_id):
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
                'email': 'admin@example.com',
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
            
            # Validate password - strengthened for production security
            if len(password) < 12:
                return None, "Password must be at least 12 characters"
            if not any(c.isupper() for c in password):
                return None, "Password must contain at least one uppercase letter"
            if not any(c.islower() for c in password):
                return None, "Password must contain at least one lowercase letter"
            if not any(c.isdigit() for c in password):
                return None, "Password must contain at least one number"
            
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
    
    def create_user(self, username, password, role='user', email=''):
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
                'email': email,
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
    
    def get_user_by_id(self, user_id):
        """Get user by ID with safe data (for admin panel)"""
        user = self.users.get('users', {}).get(user_id)
        if not user:
            return None
        return {
            'id': user_id,
            'username': user['username'],
            'name': user.get('name', ''),
            'email': user.get('email', ''),
            'role': user['role'],
            'mfaEnabled': user.get('mfaEnabled', False),
            'approved': user.get('approved', False),
            'created': user.get('created'),
            'lastLogin': user.get('lastLogin')
        }
    
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
                'email': user.get('email', ''),
                'role': user['role'],
                'mfaEnabled': user.get('mfaEnabled', False),
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
            
            # Validate password - strengthened for production security
            if len(new_password) < 12:
                return False, "New password must be at least 12 characters"
            if not any(c.isupper() for c in new_password):
                return False, "Password must contain at least one uppercase letter"
            if not any(c.islower() for c in new_password):
                return False, "Password must contain at least one lowercase letter"
            if not any(c.isdigit() for c in new_password):
                return False, "Password must contain at least one number"
            
            self.users['users'][user_id]['password'] = generate_password_hash(new_password)
            self._save_users()
            return True, "Password changed successfully"
    
    def reset_password(self, user_id, new_password):
        """Admin reset user password"""
        with self.lock:
            if user_id not in self.users.get('users', {}):
                return False
            # Validate password strength
            if len(new_password) < 12:
                return False
            if not any(c.isupper() for c in new_password):
                return False
            if not any(c.islower() for c in new_password):
                return False
            if not any(c.isdigit() for c in new_password):
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
    
    def update_email(self, user_id, email):
        """Update user's email address"""
        with self.lock:
            user = self.users.get('users', {}).get(user_id)
            if not user:
                return False, "User not found"
            
            # Validate email (basic validation, optional field)
            if email and len(email) > 254:
                return False, "Email must be 254 characters or less"
            
            # Basic email format check if provided
            if email and '@' not in email:
                return False, "Invalid email format"
            
            self.users['users'][user_id]['email'] = email
            self._save_users()
            return True, "Email updated successfully"
    
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
        """Enable MFA for user with hashed recovery code"""
        with self.lock:
            user = self.users.get('users', {}).get(user_id)
            if not user:
                return False, "User not found"
            
            # Hash recovery code before storage for security
            recovery_code_hash = generate_password_hash(recovery_code)
            
            self.users['users'][user_id]['mfaEnabled'] = True
            self.users['users'][user_id]['mfaSecret'] = secret
            self.users['users'][user_id]['mfaRecoveryCode'] = recovery_code_hash
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
        """Verify and use recovery code (one-time use) - now supports hashed codes"""
        with self.lock:
            user = self.users.get('users', {}).get(user_id)
            if not user:
                return False
            
            stored_code_hash = user.get('mfaRecoveryCode')
            if not stored_code_hash:
                return False
            
            # Verify hashed recovery code
            if check_password_hash(stored_code_hash, recovery_code):
                # Disable MFA after successful recovery
                self.disable_mfa(user_id)
                return True
            
            return False
    
    def get_role_level(self, role):
        """Get numeric role level"""
        return self.ROLES.get(role, 0)


# Initialize managers (settings_manager must be first as UserManager uses it)
settings_manager = SettingsManager()
user_manager = UserManager()
stats_manager = StatsManager()
email_service = EmailService(settings_manager)


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
    
    # Server type metadata - categorized as 'unmodded' (Java Vanilla), 'modded' (Java Modded), or 'bedrock'
    SERVER_TYPE_INFO = {
        'vanilla': {'name': 'Vanilla', 'description': 'Official Minecraft Java Edition server', 'category': 'unmodded'},
        'bedrock': {'name': 'Bedrock', 'description': 'Official Minecraft Bedrock Edition server', 'category': 'bedrock'},
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
                'javaArgs': server_config.get('javaArgs', '-Xmx4G -Xms1G'),
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
    
    def create_server(self, name, server_path='', executable='server.jar', java_args='-Xmx4G -Xms1G', 
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
        is_bedrock = category == 'bedrock'
        
        # Determine engine name
        engine_name = 'Vanilla'
        if is_bedrock:
            engine_name = 'Bedrock'
        elif is_modded and server_type:
            engine_name = server_type.title()  # paper -> Paper, folia -> Folia, etc.
        
        # Create managed.conf file
        self._create_managed_conf(server_dir, server_id, name, modded=is_modded, engine=engine_name, owner=owner, version=version)
        
        # Create canned_commands.conf so the server dir has it from the start
        self._ensure_canned_commands_conf(server_dir)
        
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
        'EULAAccepted',
        'Version'
    ]
    
    def _create_managed_conf(self, server_dir, server_id, name, modded=False, engine=None, owner=None, version=None):
        """Create or update the managed.conf file for a server"""
        managed_conf_path = Path(server_dir) / 'managed.conf'
        
        # Determine engine based on modded status
        if engine is None:
            engine = 'Vanilla' if not modded else 'Unknown'
        
        # Version is now required - default to 'Unknown' if not provided
        if not version:
            version = 'Unknown'
        
        config = {
            'ManagedBy': 'MServerController',
            'ServerId': server_id,
            'ServerName': name,
            'Modded': 'true' if modded else 'false',
            'Engine': engine,
            'Version': version,
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
            config['Version'] = version  # Always update version
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
        is_bedrock = category == 'bedrock'
        server_type = server_config.get('serverType', '')
        owner = server_config.get('owner', 'admin')
        version = server_config.get('version', 'Unknown')  # Default to 'Unknown' if not set
        
        # Determine engine name
        engine_name = 'Vanilla'
        if is_bedrock:
            engine_name = 'Bedrock'
        elif is_modded and server_type:
            engine_name = server_type.title()
        
        self._create_managed_conf(server_dir, server_id, name, modded=is_modded, engine=engine_name, owner=owner, version=version)
        
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
    
    def import_server_from_zip(self, name, zip_path, java_args='-Xmx4G -Xms1G', executable_name=None, owner=None, approved=True, category='unmodded'):
        """Import a server from a ZIP file"""
        server_id = str(uuid.uuid4())[:8]
        server_dir = SERVERS_DIR / server_id
        
        try:
            # Create server directory
            server_dir.mkdir(parents=True, exist_ok=True)
            
            # Extract ZIP file
            with zipfile.ZipFile(zip_path, 'r') as zipf:
                zipf.extractall(server_dir)
            
            # Check if files are in a subdirectory (common with some ZIPs)
            subdirs = [d for d in server_dir.iterdir() if d.is_dir()]
            if len(subdirs) == 1 and not any(server_dir.glob('*.jar')):
                # Move files from subdirectory to server_dir
                subdir = subdirs[0]
                for item in subdir.iterdir():
                    shutil.move(str(item), str(server_dir / item.name))
                subdir.rmdir()
            
            # Find the server executable JAR
            found_jar = None
            if executable_name:
                # User specified the executable name within the ZIP
                target = server_dir / executable_name
                if target.exists() and target.suffix == '.jar':
                    found_jar = target
            
            if not found_jar:
                # Auto-detect: prefer known server jar names, then fall back to any JAR
                priority_names = ['server.jar', 'paper.jar', 'purpur.jar', 'folia.jar', 'forge.jar', 'neoforge.jar']
                fallback = None
                for item in server_dir.iterdir():
                    if item.suffix == '.jar' and item.is_file():
                        if item.name in priority_names:
                            found_jar = item
                            break
                        elif ('server' in item.name.lower() or 'paper' in item.name.lower()) and not fallback:
                            fallback = item
                if not found_jar:
                    found_jar = fallback
            
            # Rename found JAR to server.jar to standardise the executable name
            if found_jar and found_jar.name != 'server.jar':
                standard_jar = server_dir / 'server.jar'
                if standard_jar.exists():
                    standard_jar.unlink()
                found_jar.rename(standard_jar)
            
            # Always use server.jar as the standard executable
            executable = 'server.jar'
            
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
        
        # Enforce executable name based on category
        category = kwargs.get('category', self.config['servers'][server_id].get('category', 'unmodded'))
        kwargs['executable'] = 'server.sh' if category == 'bedrock' else 'server.jar'
        
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
            java_args = server_config.get('javaArgs', '-Xmx4G -Xms1G')
            is_bedrock = server_config.get('category') == 'bedrock'
            
            if not server_path.exists():
                return False, "Server path does not exist"
            
            executable_path = server_path / executable
            if not executable_path.exists():
                return False, f"Server executable '{executable}' not found"
            
            # Ensure canned_commands.conf exists (create if missing for older servers)
            self._ensure_canned_commands_conf(server_path)

            try:
                instance = ServerInstance(server_id, server_path, executable, java_args, is_bedrock=is_bedrock)
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
    
    def _ensure_canned_commands_conf(self, server_dir):
        """Create canned_commands.conf in server_dir if it does not already exist."""
        conf_path = Path(server_dir) / 'canned_commands.conf'
        if not conf_path.exists():
            default = {'auto_execute': False, 'commands': []}
            conf_path.write_text(json.dumps(default, indent=2), encoding='utf-8')

    def get_server_path(self, server_id):
        """Get the path for a specific server"""
        server_config = self.get_server_config(server_id)
        if server_config:
            return Path(server_config.get('serverPath', SERVERS_DIR))
        return SERVERS_DIR


class ServerInstance:
    """Represents a running Minecraft server instance"""
    
    def __init__(self, server_id, server_path, executable, java_args, is_bedrock=False):
        self.server_id = server_id
        self.server_path = Path(server_path)
        self.executable = executable
        self.java_args = java_args
        self.is_bedrock = is_bedrock
        self.process = None
        self.output_buffer = []
        self.max_buffer_size = 1000
        self.status = ServerStatus.STOPPED
        self.start_time = None
        self.server_port = None
        self._status_monitor_thread = None
        self._stop_status_monitor = False
        self.online_players = {}  # name -> join_time (epoch float)
    
    def start(self):
        """Start the server process"""
        # Clear the output buffer on start for fresh logs
        self.output_buffer = []
        self.online_players = {}
        self.status = ServerStatus.STARTING
        self.start_time = time.time()
        self.server_port = None  # Will be read from properties
        
        # Set environment
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'
        
        if self.is_bedrock:
            # Bedrock server: run the server.sh wrapper script
            executable_path = self.server_path / self.executable
            args = ['bash', str(executable_path)]
        else:
            # Java server: run java -jar
            args = ['java'] + self.java_args.split() + ['-jar', self.executable, 'nogui']
        
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
            last_partial_send = 0
            
            while self.process.poll() is None:
                # Use select to check if data is available (timeout 0.01s for faster response)
                ready, _, _ = select.select([fd], [], [], 0.01)
                
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
                            self._parse_player_events(line)
                            last_partial_send = 0  # Reset partial send timer
                        
                        # Send partial line only if:
                        # 1. Buffer has content AND
                        # 2. Either buffer is large (>100 bytes) OR 0.1s has passed since last partial send
                        # This prevents sending every single character while still showing progress
                        current_time = time.time()
                        if buffer and (len(buffer) > 100 or (last_partial_send and current_time - last_partial_send > 0.1)):
                            try:
                                line = buffer.decode('utf-8', errors='replace')
                            except:
                                line = buffer.decode('latin-1', errors='replace')
                            self._broadcast({'type': 'output', 'data': line, 'serverId': self.server_id})
                            self._add_to_buffer(line)
                            buffer = b''
                            last_partial_send = current_time
            
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
            self.online_players = {}
            self._broadcast({'type': 'info', 'data': f'Server stopped with code {code}\n', 'serverId': self.server_id})
            self._broadcast({'type': 'status', 'serverId': self.server_id, 'status': self.status.value, 'running': False})

    def _parse_player_events(self, line):
        """Parse console output for player join/leave events and update online_players"""
        # Java Minecraft: "[HH:MM:SS] [Server thread/INFO]: PlayerName joined the game"
        # Also handles Paper/Spigot/Folia variants
        join_match = re.search(r':\s+(\S+) joined the game', line)
        if join_match:
            name = join_match.group(1)
            self.online_players[name] = time.time()
            self._broadcast({'type': 'player_join', 'serverId': self.server_id, 'player': name})
            return

        leave_match = re.search(r':\s+(\S+) left the game', line)
        if leave_match:
            name = leave_match.group(1)
            self.online_players.pop(name, None)
            self._broadcast({'type': 'player_leave', 'serverId': self.server_id, 'player': name})
            return

        # Bedrock: "Player connected: PlayerName, xuid: ..."
        bedrock_join = re.search(r'Player connected:\s+([^,]+)', line)
        if bedrock_join:
            name = bedrock_join.group(1).strip()
            self.online_players[name] = time.time()
            self._broadcast({'type': 'player_join', 'serverId': self.server_id, 'player': name})
            return

        bedrock_leave = re.search(r'Player disconnected:\s+([^,]+)', line)
        if bedrock_leave:
            name = bedrock_leave.group(1).strip()
            self.online_players.pop(name, None)
            self._broadcast({'type': 'player_leave', 'serverId': self.server_id, 'player': name})

    
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
            
            # Bedrock servers: simplified status detection (process-based only)
            # Bedrock uses UDP for queries which is more complex, so we just check if process is running
            if self.is_bedrock:
                if elapsed < 10:
                    # Short startup grace period for Bedrock
                    if self.status != ServerStatus.STARTING:
                        self.status = ServerStatus.STARTING
                        self._broadcast({
                            'type': 'status',
                            'serverId': self.server_id,
                            'status': self.status.value,
                            'running': True
                        })
                else:
                    # Process is running, assume server is ready
                    if self.status != ServerStatus.RUNNING:
                        self.status = ServerStatus.RUNNING
                        self._broadcast({
                            'type': 'status',
                            'serverId': self.server_id,
                            'status': self.status.value,
                            'running': True
                        })
            else:
                # Java servers: TCP port-based detection
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

# ---- Auto-start servers after a short delay ----
def _auto_start_servers():
    """Start all servers marked autoStart=True, 15 seconds after the controller launches.

    The delay gives the web server, database, and networking time to fully
    initialise before Minecraft JVMs start competing for CPU.  Servers are
    started sequentially (30-second gap between each) to reduce the CPU spike
    that occurs during JVM initialisation.
    """
    time.sleep(15)
    servers_cfg = server_manager.config.get('servers', {})
    auto_start_ids = [
        sid for sid, cfg in servers_cfg.items()
        if cfg.get('autoStart', False) and cfg.get('approved', True)
    ]
    if not auto_start_ids:
        return
    print(f"[AutoStart] {len(auto_start_ids)} server(s) queued for auto-start")
    for idx, server_id in enumerate(auto_start_ids):
        name = server_manager.config['servers'][server_id].get('name', server_id)
        success, msg = server_manager.start_server(server_id)
        if success:
            print(f"[AutoStart] Started: {name}")
        else:
            print(f"[AutoStart] Failed to start '{name}': {msg}")
        # Stagger subsequent starts to prevent overlapping JVM init CPU spikes
        if idx < len(auto_start_ids) - 1:
            time.sleep(30)

threading.Thread(target=_auto_start_servers, daemon=True).start()
# ------------------------------------------------

# Initialize backup scheduler
backup_scheduler = BackupScheduler()

# Initialize task scheduler
task_scheduler = TaskScheduler(server_manager, socketio)

# Initialize API Manager
from api_manager import init_api_manager, api_v1
init_api_manager(app)

# Exempt API v1 from CSRF protection (uses API key authentication)
csrf.exempt(api_v1)


def is_safe_path(base_path, requested_path):
    """Check if the requested path is within the base path (prevent directory traversal)"""
    try:
        base = Path(base_path).resolve()
        full = (base / requested_path).resolve()
        return str(full).startswith(str(base))
    except Exception:
        return False

# ==================== CSRF Token Endpoint ====================

@app.route('/api/csrf-token', methods=['GET'])
def get_csrf_token():
    """Get CSRF token for authenticated sessions"""
    token = generate_csrf()
    return jsonify({'csrf_token': token})


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
    public_files = ['styles.css', 'app.js', 'login.js', 'public.js', 'settings.js', 'utils.js']
    if path in public_files or path.startswith('assets/'):
        response = send_from_directory('public', path)
        # Add cache-control headers to prevent caching of JS/CSS files
        # This ensures users get the latest version after updates
        if path.endswith('.js') or path.endswith('.css'):
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response
    
    # Check auth for other files
    user_id, user = get_current_user()
    if not user:
        return redirect('/login.html')
    
    response = send_from_directory('public', path)
    # Add cache-control headers for authenticated files too
    if path.endswith('.js') or path.endswith('.css'):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


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
        # Set temporary session for MFA verification with timestamp
        session['temp_user_id'] = user_id
        session['mfa_required'] = True
        session['mfa_timestamp'] = time.time()
        
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
        'displayName': user.get('name', ''),  # Alias for frontend compatibility
        'email': user.get('email', ''),
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

@app.route('/api/auth/profile/email', methods=['PUT'])
@login_required
def api_update_email():
    """Update current user's email address"""
    user_id = session.get('user_id')
    data = request.get_json()
    
    email = data.get('email', '').strip()
    
    success, message = user_manager.update_email(user_id, email)
    
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
    import base64
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
    mfa_timestamp = session.get('mfa_timestamp')
    
    if not temp_user_id:
        return jsonify({'error': 'No pending MFA verification'}), 400
    
    # Check for MFA timeout (5 minutes)
    if mfa_timestamp:
        mfa_age = time.time() - mfa_timestamp
        if mfa_age > 300:  # 5 minutes
            session.pop('temp_user_id', None)
            session.pop('mfa_required', None)
            session.pop('mfa_timestamp', None)
            return jsonify({'error': 'MFA verification timeout. Please login again.'}), 400
    
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
    email = data.get('email', '').strip()
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    if role not in ['admin', 'user', 'public']:
        return jsonify({'error': 'Invalid role'}), 400
    
    user_id, message = user_manager.create_user(username, password, role, email)
    
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

@app.route('/api/admin/users/<user_id>', methods=['GET'])
@admin_required
def api_get_user(user_id):
    """Get a specific user's details (admin only)"""
    user = user_manager.get_user_by_id(user_id)
    if user:
        return jsonify({'user': user})
    return jsonify({'error': 'User not found'}), 404

@app.route('/api/admin/users/<user_id>/username', methods=['PUT'])
@admin_required
def api_admin_update_username(user_id):
    """Update a user's username (admin only)"""
    data = request.get_json()
    new_username = data.get('username', '').strip()
    
    if not new_username:
        return jsonify({'error': 'Username required'}), 400
    
    success, message = user_manager.update_username(user_id, new_username)
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 400

@app.route('/api/admin/users/<user_id>/name', methods=['PUT'])
@admin_required
def api_admin_update_name(user_id):
    """Update a user's display name (admin only)"""
    data = request.get_json()
    name = data.get('name', '').strip()
    
    success, message = user_manager.update_name(user_id, name)
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 400

@app.route('/api/admin/users/<user_id>/email', methods=['PUT'])
@admin_required
def api_admin_update_email(user_id):
    """Update a user's email address (admin only)"""
    data = request.get_json()
    email = data.get('email', '').strip()
    
    success, message = user_manager.update_email(user_id, email)
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 400

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


def _generate_server_properties(custom_properties, server_name='A Minecraft Server'):
    """Generate a server.properties file with custom properties merged with defaults"""
    # Default server.properties template with common settings
    default_properties = {
        'server-port': '25565',
        'max-players': '20',
        'gamemode': 'survival',
        'difficulty': 'easy',
        'motd': f'{server_name}, Powered by MServer',
        'level-name': 'world',
        'online-mode': 'true',
        'white-list': 'false',
        'enable-command-block': 'false',
        'spawn-protection': '16',
        'view-distance': '10',
        'simulation-distance': '10',
        'pvp': 'true',
        'allow-flight': 'false',
        'allow-nether': 'true',
        'spawn-npcs': 'true',
        'spawn-animals': 'true',
        'spawn-monsters': 'true',
        'generate-structures': 'true',
        'max-world-size': '29999984',
        'enable-rcon': 'false',
        'enable-query': 'false',
        'enable-status': 'true',
        'enforce-whitelist': 'false',
        'network-compression-threshold': '256',
        'sync-chunk-writes': 'true',
    }
    
    # Merge custom properties (convert all values to strings)
    for key, value in custom_properties.items():
        default_properties[key] = str(value)
    
    # Truncate motd if needed (59 char limit)
    if 'motd' in default_properties and len(default_properties['motd']) > 59:
        default_properties['motd'] = default_properties['motd'][:59]
    
    # Build the properties file content
    lines = [
        '# Minecraft server properties',
        f'# Generated by MServerController',
        ''
    ]
    
    for key, value in sorted(default_properties.items()):
        lines.append(f'{key}={value}')
    
    return '\n'.join(lines) + '\n'


@app.route('/api/servers', methods=['POST'])
@login_required
def create_server():
    """Create a new server"""
    user_id, user = get_current_user()
    
    data = request.get_json()
    name = data.get('name', 'New Server')
    server_path = data.get('serverPath', '')
    java_args = data.get('javaArgs', '-Xmx4G -Xms1G')
    category = data.get('category', 'unmodded')
    executable = 'server.sh' if category == 'bedrock' else 'server.jar'
    server_engine = data.get('serverEngine')  # New: engine (paper, folia, etc.)
    server_type = data.get('serverType') or server_engine  # Backward compat
    version = data.get('version')
    download_jar = data.get('downloadJar', False)
    server_properties = data.get('serverProperties', {})  # Server properties from form
    
    # Check if server approval is required (admins are always auto-approved)
    is_admin = user.get('role') == 'admin'
    require_approval = settings_manager.get_app_settings().get('requireServerApproval', False)
    approved = is_admin or not require_approval
    
    # Check for duplicate port if server-port is provided
    if 'server-port' in server_properties:
        new_port = str(server_properties['server-port'])
        existing_ports = server_manager.get_all_server_ports()
        
        for other_server_id, port in existing_ports.items():
            if port == new_port:
                other_server_config = server_manager.get_server_config(other_server_id)
                other_server_name = other_server_config.get('name', 'Unknown Server') if other_server_config else 'Unknown Server'
                return jsonify({
                    'error': f'Port {new_port} is already in use by server: {other_server_name}'
                }), 400
    
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
    
    # Get server directory for creating files
    server_config = server_manager.get_server_config(server_id)
    server_dir = Path(server_config['serverPath'])
    
    # Handle Bedrock server setup
    if category == 'bedrock':
        # server.properties is written by setup-bedrock after ZIP extraction
        response = {'success': True, 'serverId': server_id}
        if not approved:
            response['pendingApproval'] = True
            response['message'] = 'Server created and pending admin approval'
        
        return jsonify(response)
    
    # Copy JAR from serverexecutables if requested (Java servers only)
    if download_jar and server_type and version:
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
    
    # Create server.properties with the provided settings
    if server_properties:
        properties_path = server_dir / 'server.properties'
        properties_content = _generate_server_properties(server_properties, name)
        properties_path.write_text(properties_content, encoding='utf-8')
    
    response = {'success': True, 'serverId': server_id}
    if not approved:
        response['pendingApproval'] = True
        response['message'] = 'Server created and pending admin approval'
    
    return jsonify(response)


@app.route('/api/servers/<server_id>/setup-bedrock', methods=['POST'])
@login_required
def setup_bedrock_server(server_id):
    """Download and set up a Bedrock server: download zip, extract, write server.properties, set permissions"""
    server_config = server_manager.get_server_config(server_id)
    if not server_config:
        return jsonify({'error': 'Server not found'}), 404
    
    if server_config.get('category') != 'bedrock':
        return jsonify({'error': 'Server is not a Bedrock server'}), 400
    
    server_dir = Path(server_config['serverPath'])
    progress_id = str(uuid.uuid4())
    
    # Accept server properties and name from request body
    data = request.get_json(silent=True) or {}
    server_properties = data.get('serverProperties', {})
    server_name = data.get('serverName', server_config.get('name', 'Bedrock Server'))
    
    # Initialize progress
    jar_bucket.download_progress[progress_id] = {
        'status': 'initializing',
        'message': 'Starting Bedrock server download...',
        'progress': 0,
        'step': 1
    }
    
    def do_bedrock_setup():
        zip_path = server_dir / 'bedrock_server.zip'
        try:
            # Step 2: Fetch download URL
            jar_bucket.download_progress[progress_id] = {
                'status': 'downloading',
                'message': 'Fetching Bedrock server download URL...',
                'progress': 5,
                'step': 2
            }
            
            download_url, _ = jar_bucket._fetch_bedrock_download_url()
            if not download_url:
                jar_bucket.download_progress[progress_id] = {
                    'status': 'error',
                    'error': 'Could not get Bedrock server download URL'
                }
                return
            
            # Download the zip
            jar_bucket.download_progress[progress_id] = {
                'status': 'downloading',
                'message': 'Downloading latest Bedrock server...',
                'progress': 10,
                'step': 2
            }
            
            response = requests.get(download_url, stream=True, timeout=300, headers={
                'User-Agent': 'Mozilla/5.0 (Linux; x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
            })
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size:
                            pct = 10 + int((downloaded / total_size) * 70)  # 10-80%
                            jar_bucket.download_progress[progress_id] = {
                                'status': 'downloading',
                                'message': f'Downloading... ({downloaded // 1024 // 1024} MB / {total_size // 1024 // 1024} MB)',
                                'progress': pct,
                                'total': total_size,
                                'downloaded': downloaded,
                                'step': 2
                            }
            
            # Step 3: Extract the zip
            jar_bucket.download_progress[progress_id] = {
                'status': 'downloading',
                'message': 'Extracting Bedrock server files...',
                'progress': 85,
                'step': 3
            }
            
            # Preserve existing user files
            preserve_files = {'server.properties', 'permissions.json', 'allowlist.json', 'worlds'}
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                for member in zip_ref.namelist():
                    if any(member.startswith(pf) for pf in preserve_files) and (server_dir / member).exists():
                        continue
                    zip_ref.extract(member, server_dir)
            
            # Set executable permissions on Linux
            if os.name != 'nt':
                bedrock_exe = server_dir / 'bedrock_server'
                if bedrock_exe.exists():
                    os.chmod(str(bedrock_exe), 0o744)
            
            # Create server.sh launcher wrapper
            server_sh = server_dir / 'server.sh'
            with open(str(server_sh), 'w') as f:
                f.write('#!/bin/bash\n')
                f.write('cd "$(dirname "$0")"\n')
                f.write('LD_LIBRARY_PATH=. ./bedrock_server\n')
            if os.name != 'nt':
                os.chmod(str(server_sh), 0o755)
            
            # Delete the zip
            zip_path.unlink()
            
            # Step 4: Write server.properties with user-selected settings
            jar_bucket.download_progress[progress_id] = {
                'status': 'downloading',
                'message': 'Writing server.properties...',
                'progress': 92,
                'step': 4
            }
            
            properties_path = server_dir / 'server.properties'
            bedrock_props = {
                'server-name': server_name,
                'server-port': server_properties.get('server-port', 19132),
                'server-portv6': server_properties.get('server-portv6', 19133),
                'max-players': server_properties.get('max-players', 10),
                'gamemode': server_properties.get('gamemode', 'survival'),
                'difficulty': server_properties.get('difficulty', 'easy'),
                'level-seed': server_properties.get('level-seed', ''),
                'allow-cheats': 'false',
                'online-mode': 'true',
                'white-list': 'true' if server_properties.get('white-list') else 'false',
                'view-distance': 32,
                'tick-distance': 4,
                'player-idle-timeout': 30,
                'level-name': 'Bedrock level',
                'default-player-permission-level': 'member',
            }
            lines = [
                '# Bedrock server properties',
                '# Generated by MServerController',
                '',
            ]
            for key, value in bedrock_props.items():
                lines.append(f'{key}={value}')
            properties_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            
            # Update server config with the correct executable
            server_config['executable'] = 'server.sh'
            server_config['version'] = 'latest'
            server_manager._save_config()
            
            jar_bucket.download_progress[progress_id] = {
                'status': 'complete',
                'message': 'Bedrock server setup complete!',
                'progress': 100,
                'step': 5,
                'success': True
            }
            
        except Exception as e:
            if zip_path.exists():
                zip_path.unlink()
            
            jar_bucket.download_progress[progress_id] = {
                'status': 'error',
                'error': f'Bedrock setup failed: {str(e)}'
            }
    
    thread = threading.Thread(target=do_bedrock_setup, daemon=True)
    thread.start()
    
    return jsonify({
        'progress_id': progress_id,
        'message': 'Starting Bedrock server setup...'
    })


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
    executable_name = request.form.get('executableName', '').strip()
    java_args = request.form.get('javaArgs', '-Xmx4G -Xms1G')
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
            executable_name=executable_name or None,
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

@app.route('/api/servers/<server_id>/import-world', methods=['POST'])
@server_access_required
@limiter.limit("5 per 15 minutes")
def import_world(server_id):
    """Import a world ZIP into an existing server, placing it as the world/ folder"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if not file.filename.endswith('.zip'):
        return jsonify({'error': 'File must be a ZIP archive'}), 400

    server_config = server_manager.get_server_config(server_id)
    if not server_config:
        return jsonify({'error': 'Server not found'}), 404

    server_path = Path(server_config['serverPath']).resolve()
    filename = secure_filename(file.filename)
    temp_path = UPLOADS_DIR / filename

    try:
        file.save(str(temp_path))

        with zipfile.ZipFile(temp_path, 'r') as zipf:
            names = zipf.namelist()

            # Security: reject entries that contain path traversal sequences
            for member in names:
                if '..' in member or member.startswith('/'):
                    return jsonify({'error': 'Invalid ZIP: contains unsafe paths'}), 400

            # Determine the structure of the world ZIP
            top_level_items = set()
            for n in names:
                part = n.split('/')[0]
                if part:
                    top_level_items.add(part)

            if 'level.dat' in names:
                # World files are at ZIP root → extract into world/ subfolder
                world_dir = server_path / 'world'
                if world_dir.exists():
                    shutil.rmtree(world_dir)
                world_dir.mkdir()
                for member in names:
                    if member.endswith('/'):
                        continue
                    target = world_dir / member
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zipf.open(member) as src, open(target, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
            else:
                # Extract to a temp directory, then locate the world folder
                tmp_dir = server_path / '_world_import_tmp'
                if tmp_dir.exists():
                    shutil.rmtree(tmp_dir)
                tmp_dir.mkdir()
                zipf.extractall(tmp_dir)

                # Find a directory that contains level.dat
                world_found = None
                for candidate in tmp_dir.iterdir():
                    if candidate.is_dir() and (candidate / 'level.dat').exists():
                        world_found = candidate
                        break

                if world_found:
                    target_world = server_path / 'world'
                    if target_world.exists():
                        shutil.rmtree(target_world)
                    shutil.move(str(world_found), str(target_world))
                elif len(top_level_items) == 1:
                    # Single top-level directory — use it as the world
                    single = tmp_dir / list(top_level_items)[0]
                    target_world = server_path / 'world'
                    if target_world.exists():
                        shutil.rmtree(target_world)
                    shutil.move(str(single), str(target_world))
                else:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    return jsonify({'error': 'Could not locate a valid world in the ZIP (level.dat not found)'}), 400

                shutil.rmtree(tmp_dir, ignore_errors=True)

        return jsonify({'success': True})
    except zipfile.BadZipFile:
        return jsonify({'error': 'Invalid or corrupted ZIP file'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
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
    create_bk = data.get('createBackup', False)
    executable = 'server.jar'  # Always use server.jar for Java server JARs

    if not server_type or not version:
        return jsonify({'error': 'Server type and version required'}), 400

    server_config = server_manager.get_server_config(server_id)
    if not server_config:
        return jsonify({'error': 'Server not found'}), 404

    server_path = Path(server_config['serverPath'])
    jar_path = server_path / executable

    # --- Era compatibility guard ---
    current_version = server_config.get('version', '')
    if current_version and current_version not in ('Unknown', ''):
        cur_modern = mc_version_is_modern(current_version)
        new_mod = mc_version_is_modern(version)
        new_leg = mc_version_is_legacy(version)

        if cur_modern and not new_mod:
            return jsonify({
                'error': (
                    f'Cannot assign legacy JAR ({version}) to a 1.26+ server ({current_version}). '
                    f'Create a new server if you need a legacy version.'
                )
            }), 400

        if mc_version_is_legacy(current_version) and not new_leg:
            return jsonify({
                'error': (
                    f'Cannot assign a 1.26+ JAR ({version}) to a legacy server ({current_version}). '
                    f'Create a new server to run Minecraft 1.26 or higher.'
                )
            }), 400

        if mc_version_is_legacy(current_version) and compare_mc_versions(version, MC_LEGACY_MAX) > 0:
            return jsonify({
                'error': (
                    f'Legacy servers cannot exceed {MC_LEGACY_MAX}. '
                    f'Create a new server to run Minecraft 1.26 or higher.'
                )
            }), 400

    # Automatic backup before JAR update if requested
    if create_bk:
        try:
            backup_dir = BACKUPS_DIR / server_id
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime('%Y-%m-%dT%H-%M-%S')
            bk_name = f'pre-jar-update-{timestamp}.zip'
            bk_path = backup_dir / bk_name
            with zipfile.ZipFile(bk_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipf:
                fc = 0
                for root, dirs, files in os.walk(server_path):
                    for file in files:
                        fp = Path(root) / file
                        zipf.write(fp, fp.relative_to(server_path))
                        fc += 1
                zipf.writestr('backup_manifest.json', json.dumps({
                    'type': 'full', 'created': timestamp, 'file_count': fc
                }))
            bk_size = bk_path.stat().st_size
            ok, checksum, _ = verify_backup_file(bk_path)
            backup_scheduler._log_backup_event(server_id, {
                'type': 'pre-jar-update',
                'backup_name': bk_name,
                'size': bk_size,
                'is_incremental': False,
                'compression_level': 6,
                'verified': ok,
                'checksum': checksum,
                'success': True
            })
        except Exception as e:
            return jsonify({'error': f'Failed to create backup: {str(e)}'}), 500

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


# ==================== Canned Commands API ====================

@app.route('/api/servers/<server_id>/canned-commands', methods=['GET'])
@server_access_required
def get_canned_commands(server_id):
    """Return the canned_commands.conf for a server, creating it if missing."""
    server_path = server_manager.get_server_path(server_id)
    conf_path = server_path / 'canned_commands.conf'
    server_manager._ensure_canned_commands_conf(server_path)
    try:
        data = json.loads(conf_path.read_text(encoding='utf-8'))
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/canned-commands', methods=['PUT'])
@server_access_required
def save_canned_commands(server_id):
    """Save (overwrite) the canned_commands.conf for a server."""
    server_path = server_manager.get_server_path(server_id)
    body = request.get_json()
    if body is None:
        return jsonify({'error': 'Invalid JSON'}), 400

    auto_execute = bool(body.get('auto_execute', False))
    raw_commands = body.get('commands', [])

    # Sanitise each command entry
    commands = []
    for item in raw_commands:
        cmd_name = str(item.get('cmd_name', '')).strip()[:25]
        cmd = str(item.get('cmd', '')).strip()
        if cmd_name and cmd:
            commands.append({'cmd_name': cmd_name, 'cmd': cmd})

    conf_data = {'auto_execute': auto_execute, 'commands': commands}
    conf_path = server_path / 'canned_commands.conf'
    try:
        conf_path.write_text(json.dumps(conf_data, indent=2), encoding='utf-8')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/servers/<server_id>/change-version', methods=['POST'])
@server_access_required
def change_server_version(server_id):
    """Change the server version.

    Era rules
    ---------
    Modern (1.26+): may only upgrade, never downgrade.  Cross-era moves blocked.
    Legacy (<=1.21.11): may upgrade/downgrade within the legacy tier only.
      Downgrades are allowed but include a warning in the response.
      Upgrades are capped at MC_LEGACY_MAX (1.21.11).
      Cannot cross to the modern era — create a new server instead.
    """
    data = request.get_json()

    if not data:
        return jsonify({'error': 'No data provided'}), 400

    new_version = data.get('version')
    create_backup = data.get('createBackup', False)

    if not new_version:
        return jsonify({'error': 'Version is required'}), 400

    server_config = server_manager.get_server_config(server_id)
    if not server_config:
        return jsonify({'error': 'Server not found'}), 404

    server_dir = Path(server_config.get('serverPath', ''))
    managed_conf = server_manager._read_managed_conf(server_dir)
    current_version = managed_conf.get('Version', server_config.get('version', ''))

    current_modern = mc_version_is_modern(current_version)
    current_legacy = mc_version_is_legacy(current_version)
    new_modern = mc_version_is_modern(new_version)
    new_legacy = mc_version_is_legacy(new_version)

    # --- Cross-era blocks ---
    if current_modern and not new_modern:
        return jsonify({
            'error': (
                f'Cannot downgrade a 1.26+ server to legacy version {new_version}. '
                f'The new world storage format is incompatible with older versions. '
                f'Create a new server if you need a legacy version.'
            )
        }), 400

    if current_legacy and not new_legacy:
        return jsonify({
            'error': (
                f'Cannot upgrade legacy server from {current_version} to {new_version}. '
                f'Minecraft 1.26 introduced incompatible world storage changes. '
                f'The maximum upgrade path for this server is {MC_LEGACY_MAX}. '
                f'Create a new server to run Minecraft 1.26 or higher.'
            )
        }), 400

    # --- Legacy: cap at MC_LEGACY_MAX ---
    if current_legacy and compare_mc_versions(new_version, MC_LEGACY_MAX) > 0:
        return jsonify({
            'error': (
                f'Legacy servers cannot be upgraded beyond {MC_LEGACY_MAX}. '
                f'Create a new server to run Minecraft 1.26 or higher.'
            )
        }), 400

    # --- Legacy downgrade: allowed with warning ---
    downgrade_warning = None
    if current_legacy and compare_mc_versions(new_version, current_version) < 0:
        downgrade_warning = (
            f'Downgrading from {current_version} to {new_version}: '
            f'Minecraft world data is generally not backwards-compatible. '
            f'Ensure you have a backup before starting the server.'
        )

    # Check if server is running
    instance = server_manager.servers.get(server_id)
    if instance and instance.is_running():
        return jsonify({'error': 'Server must be stopped before changing version'}), 400
    
    # Create backup if requested
    if create_backup:
        try:
            # Create backup directory for this server
            backup_dir = BACKUPS_DIR / server_id
            backup_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime('%Y-%m-%dT%H-%M-%S')
            backup_name = f'pre-version-change-{timestamp}.zip'
            backup_path = backup_dir / backup_name

            # Create the backup
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED,
                                 compresslevel=6) as zipf:
                file_count = 0
                for root, dirs, files in os.walk(server_dir):
                    for file in files:
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(server_dir)
                        zipf.write(file_path, arcname)
                        file_count += 1
                zipf.writestr('backup_manifest.json', json.dumps({
                    'type': 'full', 'created': timestamp, 'file_count': file_count
                }))

            bk_size = backup_path.stat().st_size
            ok, checksum, _ = verify_backup_file(backup_path)
            backup_scheduler._log_backup_event(server_id, {
                'type': 'pre-version-change',
                'backup_name': backup_name,
                'size': bk_size,
                'is_incremental': False,
                'compression_level': 6,
                'verified': ok,
                'checksum': checksum,
                'success': True
            })
        except Exception as e:
            return jsonify({'error': f'Failed to create backup: {str(e)}'}), 500
    
    # Update version in config.json
    if 'servers' in server_manager.config and server_id in server_manager.config['servers']:
        server_manager.config['servers'][server_id]['version'] = new_version
        server_manager._save_config()
    
    # Update version in managed.conf
    managed_conf['Version'] = new_version
    server_manager._write_managed_conf(server_dir, managed_conf)
    
    response = {
        'success': True,
        'message': f'Version updated from {current_version} to {new_version}',
        'oldVersion': current_version,
        'newVersion': new_version,
    }
    if downgrade_warning:
        response['warning'] = downgrade_warning
    return jsonify(response)

@app.route('/api/servers/<server_id>/eula', methods=['GET'])
@server_access_required
def check_eula(server_id):
    """Check if EULA has been accepted for a server"""
    # Bedrock servers don't require EULA acceptance
    server_config = server_manager.get_server_config(server_id)
    if server_config and server_config.get('category') == 'bedrock':
        return jsonify({'accepted': True})
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
    server_config = server_manager.get_server_config(server_id)
    if not server_config:
        return jsonify({'content': 'Server not found.', 'success': False})
    
    # Bedrock servers don't have log files - they only output to console
    if server_config.get('category') == 'bedrock':
        return jsonify({
            'content': 'Bedrock servers do not store log files.\n\nConsole output is available in the Console tab while the server is running.',
            'success': False
        })
    
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

@app.route('/api/servers/<server_id>/players/online', methods=['GET'])
@server_access_required
def get_online_players(server_id):
    """Get currently online players tracked from console output"""
    instance = server_manager.servers.get(server_id)
    if not instance or not instance.is_running():
        return jsonify({'online': [], 'count': 0})
    players = [
        {'name': name, 'since': since}
        for name, since in instance.online_players.items()
    ]
    return jsonify({'online': players, 'count': len(players)})

@app.route('/api/servers/<server_id>/players/<uuid>/stats', methods=['GET'])
@server_access_required
def get_player_stats(server_id, uuid):
    """Read player statistics from world/stats/<uuid>.json"""
    server_path = server_manager.get_server_path(server_id)
    stats_file = None

    for item in server_path.iterdir():
        if not item.is_dir():
            continue
        # 1.26+ path: world/players/stats/<uuid>.json
        new_path = item / 'players' / 'stats' / f'{uuid}.json'
        if new_path.exists():
            stats_file = new_path
            break
        # Legacy path: world/stats/<uuid>.json
        old_path = item / 'stats' / f'{uuid}.json'
        if old_path.exists():
            stats_file = old_path
            break

    if not stats_file:
        return jsonify({'error': 'Stats file not found for this player'}), 404

    try:
        with open(stats_file, 'r', encoding='utf-8') as f:
            raw = json.load(f)

        # Flatten nested stat categories
        stats = raw.get('stats', raw)
        flat = {}
        for category, entries in stats.items():
            if isinstance(entries, dict):
                for stat_key, value in entries.items():
                    display_cat = category.replace('minecraft:', '')
                    display_key = stat_key.replace('minecraft:', '')
                    flat[f'{display_cat}.{display_key}'] = value

        highlights = {
            'playtime_ticks': flat.get('custom.play_time', flat.get('custom.play_one_minute', 0)),
            'deaths': flat.get('custom.deaths', 0),
            'player_kills': flat.get('custom.player_kills', 0),
            'mob_kills': flat.get('custom.mob_kills', 0),
            'damage_dealt': flat.get('custom.damage_dealt', 0),
            'damage_taken': flat.get('custom.damage_taken', 0),
            'jumps': flat.get('custom.jump', 0),
            'distance_walked_cm': flat.get('custom.walk_one_cm', 0),
        }
        return jsonify({'stats': flat, 'highlights': highlights})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/players/<uuid>/inventory', methods=['GET'])
@server_access_required
def get_player_inventory(server_id, uuid):
    """Extract inventory, armor and ender chest from player NBT data"""
    server_path = server_manager.get_server_path(server_id)
    player_dat = None

    for item in server_path.iterdir():
        if not item.is_dir():
            continue
        new_path = item / 'players' / 'data' / f'{uuid}.dat'
        if new_path.exists():
            player_dat = new_path
            break
        old_path = item / 'playerdata' / f'{uuid}.dat'
        if old_path.exists():
            player_dat = old_path
            break

    if not player_dat:
        return jsonify({'error': 'Player data file not found'}), 404

    try:
        nbt_data = nbt_editor.read_file(player_dat)
        nbt_json = nbt_editor.nbt_to_json(nbt_data)

        return jsonify({
            'inventory': nbt_json.get('Inventory', []),
            'armor': nbt_json.get('ArmorItems', []),
            'enderChest': nbt_json.get('EnderItems', []),
            'offhand': nbt_json.get('OffhandItem', []),
            'health': nbt_json.get('Health'),
            'food': nbt_json.get('foodLevel'),
            'xpLevel': nbt_json.get('XpLevel'),
            'gameType': nbt_json.get('playerGameType'),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/players/banned-ips', methods=['GET'])
@server_access_required
def get_banned_ips(server_id):
    """Get banned IPs list"""
    server_path = server_manager.get_server_path(server_id)
    banned_ips_file = server_path / 'banned-ips.json'
    try:
        if banned_ips_file.exists():
            with open(banned_ips_file, 'r') as f:
                banned_ips = json.load(f)
            return jsonify({'banned_ips': banned_ips})
        return jsonify({'banned_ips': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/players/banned-ips', methods=['POST'])
@server_access_required
def ban_ip(server_id):
    """Ban an IP address"""
    data = request.get_json()
    ip_address = data.get('ip', '').strip()
    reason = data.get('reason', 'Banned By Admin')
    expires = data.get('expires', 'forever')

    if not ip_address:
        return jsonify({'error': 'IP address is required'}), 400

    # Validate IP address format (IPv4/IPv6/wildcards Minecraft allows)
    if not re.match(r'^[\d\.\:a-fA-F\*]+$', ip_address):
        return jsonify({'error': 'Invalid IP address format'}), 400

    server_path = server_manager.get_server_path(server_id)
    banned_ips_file = server_path / 'banned-ips.json'

    try:
        banned_ips = []
        if banned_ips_file.exists():
            with open(banned_ips_file, 'r') as f:
                banned_ips = json.load(f)

        for entry in banned_ips:
            if entry.get('ip') == ip_address:
                return jsonify({'error': f'{ip_address} is already banned'}), 400

        banned_ips.append({
            'ip': ip_address,
            'created': datetime.now().strftime('%Y-%m-%d %H:%M:%S +0000'),
            'source': 'MServerController',
            'expires': expires,
            'reason': reason
        })

        with open(banned_ips_file, 'w') as f:
            json.dump(banned_ips, f, indent=2)

        return jsonify({'success': True, 'message': f'{ip_address} has been banned'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/players/banned-ips/<path:ip_address>', methods=['DELETE'])
@server_access_required
def unban_ip(server_id, ip_address):
    """Unban an IP address"""
    server_path = server_manager.get_server_path(server_id)
    banned_ips_file = server_path / 'banned-ips.json'

    try:
        if not banned_ips_file.exists():
            return jsonify({'error': 'Banned IPs file not found'}), 404

        with open(banned_ips_file, 'r') as f:
            banned_ips = json.load(f)

        original_len = len(banned_ips)
        banned_ips = [e for e in banned_ips if e.get('ip') != ip_address]

        if len(banned_ips) == original_len:
            return jsonify({'error': 'IP not found in ban list'}), 404

        with open(banned_ips_file, 'w') as f:
            json.dump(banned_ips, f, indent=2)

        return jsonify({'success': True, 'message': f'{ip_address} has been unbanned'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/players/message', methods=['POST'])
@server_access_required
def message_players(server_id):
    """Send a message to players via console commands (tellraw/title/actionbar)"""
    data = request.get_json()
    msg_type = data.get('type', 'chat')
    target = data.get('target', '@a').strip()
    message = data.get('message', '').strip()

    if not message:
        return jsonify({'error': 'Message is required'}), 400

    safe = message.replace('\\', '\\\\').replace('"', '\\"')

    if msg_type == 'chat':
        command = f'tellraw {target} {{"text":"{safe}","color":"white"}}'
    elif msg_type == 'title':
        command = f'title {target} title {{"text":"{safe}","bold":true}}'
    elif msg_type == 'subtitle':
        command = f'title {target} subtitle {{"text":"{safe}"}}'
    elif msg_type == 'actionbar':
        command = f'title {target} actionbar {{"text":"{safe}"}}'
    else:
        return jsonify({'error': f'Unknown message type: {msg_type}'}), 400

    success, msg = server_manager.send_command(server_id, command)
    if not success:
        return jsonify({'error': msg}), 400

    return jsonify({'success': True, 'message': f'Message sent to {target}'})

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
    player_uuid = data.get('uuid', '').strip()
    level = data.get('level', 4)
    bypass_limit = data.get('bypassesPlayerLimit', False)

    server_path = server_manager.get_server_path(server_id)
    ops_file = server_path / 'ops.json'

    uuid = None
    actual_name = None

    if player_uuid:
        # UUID provided directly — look up name from usercache.json
        usercache_file = server_path / 'usercache.json'
        if usercache_file.exists():
            try:
                with open(usercache_file, 'r') as f:
                    cache = json.load(f)
                for entry in cache:
                    if entry.get('uuid') == player_uuid:
                        actual_name = entry.get('name', player_uuid)
                        uuid = player_uuid
                        break
            except Exception:
                pass
        if not uuid:
            # Not in usercache — use the UUID as-is with whatever name was supplied
            uuid = player_uuid
            actual_name = player_name or player_uuid
    elif player_name:
        # Name provided — look up UUID from Mojang API
        uuid, actual_name = get_player_uuid(player_name)
        if not uuid:
            return jsonify({'error': f'Could not find player "{player_name}". Make sure the name is correct.'}), 404
    else:
        return jsonify({'error': 'Player name or UUID is required'}), 400
    
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
    player_uuid = data.get('uuid', '').strip()

    server_path = server_manager.get_server_path(server_id)
    whitelist_file = server_path / 'whitelist.json'

    uuid = actual_name = None

    if player_uuid:
        # UUID provided directly — look up name from usercache.json
        usercache_file = server_path / 'usercache.json'
        if usercache_file.exists():
            try:
                with open(usercache_file, 'r') as f:
                    cache = json.load(f)
                for entry in cache:
                    if entry.get('uuid') == player_uuid:
                        actual_name = entry.get('name', player_uuid)
                        uuid = player_uuid
                        break
            except Exception:
                pass
        if not uuid:
            uuid = player_uuid
            actual_name = player_name or player_uuid
    elif player_name:
        uuid, actual_name = get_player_uuid(player_name)
        if not uuid:
            return jsonify({'error': f'Could not find player "{player_name}"'}), 404
    else:
        return jsonify({'error': 'Player name or UUID is required'}), 400
    
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
    player_uuid = data.get('uuid', '').strip()
    reason = data.get('reason', 'Banned By Admin')
    expires = data.get('expires', 'forever')  # 'forever' or ISO datetime string

    server_path = server_manager.get_server_path(server_id)
    banned_file = server_path / 'banned-players.json'

    uuid = actual_name = None

    if player_uuid:
        # UUID provided directly — look up name from usercache.json
        usercache_file = server_path / 'usercache.json'
        if usercache_file.exists():
            try:
                with open(usercache_file, 'r') as f:
                    cache = json.load(f)
                for entry in cache:
                    if entry.get('uuid') == player_uuid:
                        actual_name = entry.get('name', player_uuid)
                        uuid = player_uuid
                        break
            except Exception:
                pass
        if not uuid:
            uuid = player_uuid
            actual_name = player_name or player_uuid
    elif player_name:
        uuid, actual_name = get_player_uuid(player_name)
        if not uuid:
            return jsonify({'error': f'Could not find player "{player_name}"'}), 404
    else:
        return jsonify({'error': 'Player name or UUID is required'}), 400
    
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
            'expires': expires,
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

@app.route('/api/servers/<server_id>/players/whitelist-status', methods=['GET'])
@server_access_required
def get_whitelist_status(server_id):
    """Return whether whitelist is enabled in server.properties"""
    server_path = server_manager.get_server_path(server_id)
    properties_path = server_path / 'server.properties'
    if not properties_path.exists():
        return jsonify({'enabled': False, 'available': False})
    try:
        with open(properties_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('white-list='):
                    value = line.split('=', 1)[1].strip().lower()
                    return jsonify({'enabled': value == 'true', 'available': True})
        return jsonify({'enabled': False, 'available': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/players/whitelist-toggle', methods=['PATCH'])
@server_access_required
def toggle_whitelist_setting(server_id):
    """Toggle white-list in server.properties"""
    server_path = server_manager.get_server_path(server_id)
    properties_path = server_path / 'server.properties'
    if not properties_path.exists():
        return jsonify({'error': 'server.properties not found'}), 404
    try:
        lines = []
        current = False
        with open(properties_path, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith('white-list='):
                    current = stripped.split('=', 1)[1].strip().lower() == 'true'
                    new_val = 'false' if current else 'true'
                    lines.append(f'white-list={new_val}\n')
                else:
                    lines.append(line)
        with open(properties_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        return jsonify({'success': True, 'enabled': not current})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<server_id>/players/playerdata', methods=['GET'])
@server_access_required
def get_playerdata(server_id):
    """Get list of player data files"""
    # Check if this is a Bedrock server
    server_config = server_manager.get_server_config(server_id)
    if server_config and server_config.get('category') == 'bedrock':
        return jsonify({
            'players': [], 
            'message': 'Bedrock servers store player data in LevelDB format (worlds/db/). Individual player data files are not accessible. Use permissions.json and allowlist.json to manage players.'
        })
    
    server_path = server_manager.get_server_path(server_id)

    # Player data lives only in the main world folder (nether/end never had it).
    # Pre-1.26: world/playerdata/<uuid>.dat
    # 1.26+:    world/players/data/<uuid>.dat
    # Search all subdirectories for either layout.
    playerdata_path = None
    
    for item in server_path.iterdir():
        if not item.is_dir():
            continue
        # 1.26+ layout first
        new_path = item / 'players' / 'data'
        if new_path.exists():
            playerdata_path = new_path
            break
        # Legacy layout
        old_path = item / 'playerdata'
        if old_path.exists():
            playerdata_path = old_path
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
                    'path': str(item.relative_to(server_path)),
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


@app.route('/api/servers/<server_id>/files/zip', methods=['GET'])
@server_access_required
def zip_server_folder(server_id):
    """Download a folder as a ZIP archive"""
    requested_path = request.args.get('path', '')
    server_path = server_manager.get_server_path(server_id)

    if not is_safe_path(server_path, requested_path):
        return jsonify({'error': 'Access denied'}), 403

    full_path = server_path / requested_path

    if not full_path.exists():
        return jsonify({'error': 'Path not found'}), 404

    if not full_path.is_dir():
        return jsonify({'error': 'Path is not a directory'}), 400

    folder_name = full_path.name or 'server'
    zip_filename = f"{folder_name}.zip"

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_path in full_path.rglob('*'):
            if file_path.is_file():
                arcname = file_path.relative_to(full_path)
                zf.write(str(file_path), str(arcname))
    zip_buffer.seek(0)

    return send_file(
        zip_buffer,
        as_attachment=True,
        download_name=zip_filename,
        mimetype='application/zip'
    )

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
    server_config = server_manager.get_server_config(server_id)
    if server_config and server_config.get('category') == 'bedrock':
        return jsonify({'error': 'Resource packs are not supported for Bedrock servers'}), 400
    
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
    server_config = server_manager.get_server_config(server_id)
    if server_config and server_config.get('category') == 'bedrock':
        return jsonify({'error': 'Resource packs are not supported for Bedrock servers'}), 400
    
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
    server_config = server_manager.get_server_config(server_id)
    if server_config and server_config.get('category') == 'bedrock':
        return jsonify({'error': 'Resource packs are not supported for Bedrock servers'}), 400
    
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
            entry = {
                'name': item.name,
                'size': stat.st_size,
                'created': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                'is_incremental': item.name.startswith('incremental-backup-'),
                'is_scheduled': item.name.startswith('scheduled-backup-'),
                'has_checksum': item.with_suffix('.sha256').exists()
            }
            backups.append(entry)

    backups.sort(key=lambda x: x['created'], reverse=True)
    return jsonify({'backups': backups})

@app.route('/api/servers/<server_id>/backups/create', methods=['POST'])
@limiter.limit("5 per 15 minutes")
@server_access_required
def create_backup(server_id):
    """Start an async manual backup.

    Stops the server if running, creates the backup, then restarts the server.
    Returns 202 immediately; completion is pushed via socket events:
      backup_manual_completed / backup_manual_failed
    """
    server_path = server_manager.get_server_path(server_id)

    if not server_path.exists():
        return jsonify({'error': 'Server path not found'}), 400

    data = request.get_json(silent=True) or {}
    compression_level = max(0, min(9, int(data.get('compressionLevel', 6))))
    is_incremental_req = bool(data.get('incremental', False))
    backup_type = str(data.get('backupType', 'manual'))

    def run_backup():
        timestamp = datetime.now().strftime('%Y-%m-%dT%H-%M-%S')
        backup_dir = BACKUPS_DIR / server_id
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Stop server if running
        instance = server_manager.servers.get(server_id)
        was_running = instance is not None and instance.is_running()
        if was_running:
            server_manager.send_command(server_id, "say [Backup] Server is being stopped for a manual backup...")
            time.sleep(2)
            server_manager.stop_server(server_id)
            for _ in range(60):
                time.sleep(1)
                inst = server_manager.servers.get(server_id)
                if inst is None or not inst.is_running():
                    break

        is_incremental = is_incremental_req
        backup_name = f'incremental-backup-{timestamp}.zip' if is_incremental else f'backup-{timestamp}.zip'
        backup_path = backup_dir / backup_name

        try:
            cutoff_time = None
            if is_incremental:
                cutoff_time = backup_scheduler._get_last_backup_time(server_id)
                if cutoff_time is None:
                    is_incremental = False

            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED,
                                 compresslevel=compression_level) as zipf:
                file_count = 0
                for root, dirs, files in os.walk(server_path):
                    for file in files:
                        file_path = Path(root) / file
                        if cutoff_time is not None:
                            mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                            if mtime < cutoff_time:
                                continue
                        arcname = file_path.relative_to(server_path)
                        zipf.write(file_path, arcname)
                        file_count += 1

                manifest = {
                    'type': 'incremental' if cutoff_time else 'full',
                    'created': timestamp,
                    'file_count': file_count
                }
                if cutoff_time:
                    manifest['base_time'] = cutoff_time.isoformat()
                zipf.writestr('backup_manifest.json', json.dumps(manifest, indent=2))

            size = backup_path.stat().st_size
            ok, checksum, verify_err = verify_backup_file(backup_path)

            ext_ok, ext_msg = upload_backup_to_external(backup_path, server_id, backup_name)
            if not ext_ok:
                print(f"[Backup] External upload warning: {ext_msg}")

            backup_scheduler._log_backup_event(server_id, {
                'type': backup_type,
                'backup_name': backup_name,
                'size': size,
                'is_incremental': cutoff_time is not None,
                'compression_level': compression_level,
                'verified': ok,
                'checksum': checksum,
                'uploaded_to_external': ext_ok,
                'success': True
            })

            if was_running:
                server_manager.start_server(server_id)

            socketio.emit('backup_manual_completed', {
                'serverId': server_id,
                'backup': backup_name,
                'size': size,
                'is_incremental': cutoff_time is not None,
                'verified': ok,
                'checksum': checksum
            })

        except Exception as e:
            backup_scheduler._log_backup_event(server_id, {
                'type': backup_type,
                'backup_name': backup_name,
                'success': False,
                'error': str(e)
            })
            if was_running:
                try:
                    server_manager.start_server(server_id)
                except Exception:
                    pass
            socketio.emit('backup_manual_failed', {
                'serverId': server_id,
                'error': str(e)
            })

    socketio.start_background_task(run_backup)
    return jsonify({'started': True}), 202

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
    """Restore a backup. Stops the server if running, clears the server directory,
    extracts the backup, then restarts the server if it was running.
    Returns 202 immediately; result is pushed via socket events:
      restore_completed / restore_failed
    """
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

    server_path = server_manager.get_server_path(server_id)

    def run_restore():
        instance = server_manager.servers.get(server_id)
        was_running = instance is not None and instance.is_running()
        if was_running:
            server_manager.send_command(server_id, "say [Restore] Server is being stopped to restore a backup...")
            time.sleep(2)
            server_manager.stop_server(server_id)
            for _ in range(60):
                time.sleep(1)
                inst = server_manager.servers.get(server_id)
                if inst is None or not inst.is_running():
                    break

        try:
            # Clear server directory
            for item in server_path.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

            # Extract backup
            with zipfile.ZipFile(backup_path, 'r') as zipf:
                zipf.extractall(server_path)

            if was_running:
                server_manager.start_server(server_id)

            socketio.emit('restore_completed', {
                'serverId': server_id,
                'backup': backup_name
            })

        except Exception as e:
            if was_running:
                try:
                    server_manager.start_server(server_id)
                except Exception:
                    pass
            socketio.emit('restore_failed', {
                'serverId': server_id,
                'error': str(e)
            })

    socketio.start_background_task(run_restore)
    return jsonify({'started': True}), 202


@app.route('/api/servers/<server_id>/backups/import', methods=['POST'])
@server_access_required
def import_backup(server_id):
    """Import a backup ZIP file uploaded by the user"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    f = request.files['file']
    if not f or not f.filename:
        return jsonify({'error': 'No file selected'}), 400

    filename = secure_filename(f.filename)
    if not filename.lower().endswith('.zip'):
        return jsonify({'error': 'Only .zip files are supported'}), 400

    backup_dir = BACKUPS_DIR / server_id
    backup_dir.mkdir(parents=True, exist_ok=True)

    dest_path = backup_dir / filename

    # Avoid overwriting an existing file by appending a timestamp
    if dest_path.exists():
        ts = datetime.now().strftime('%Y%m%dT%H%M%S')
        stem = filename[:-4]
        filename = f"{stem}-imported-{ts}.zip"
        dest_path = backup_dir / filename

    try:
        f.save(str(dest_path))

        # Validate it is a real zip
        if not zipfile.is_zipfile(dest_path):
            dest_path.unlink()
            return jsonify({'error': 'Uploaded file is not a valid ZIP archive'}), 400

        size = dest_path.stat().st_size
        return jsonify({'success': True, 'backup': filename, 'size': size})
    except Exception as e:
        if dest_path.exists():
            dest_path.unlink()
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
        'maxBackups': data.get('maxBackups', 7),
        'compressionLevel': data.get('compressionLevel', 6),
        'incremental': data.get('incremental', False)
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


@app.route('/api/servers/<server_id>/backups/history', methods=['GET'])
@server_access_required
def get_backup_history(server_id):
    """Get the backup event history for a server"""
    events = backup_scheduler.get_backup_history(server_id)
    return jsonify({'events': events})


@app.route('/api/servers/<server_id>/backups/verify', methods=['POST'])
@server_access_required
def verify_backup(server_id):
    """Verify a backup file's integrity and compute its checksum"""
    data = request.get_json()
    backup_name = data.get('name', '')

    backup_name = secure_filename(backup_name)
    if not backup_name or '..' in backup_name or '/' in backup_name:
        return jsonify({'error': 'Invalid backup name'}), 400

    backup_path = BACKUPS_DIR / server_id / backup_name
    try:
        backup_path = backup_path.resolve()
        if not str(backup_path).startswith(str(BACKUPS_DIR.resolve())):
            return jsonify({'error': 'Invalid backup path'}), 400
    except Exception:
        return jsonify({'error': 'Invalid backup path'}), 400

    if not backup_path.exists():
        return jsonify({'error': 'Backup not found'}), 404

    ok, checksum, error = verify_backup_file(backup_path)

    return jsonify({
        'success': ok,
        'backup': backup_name,
        'checksum': checksum,
        'error': error
    })


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
    # Extract form data
    site_title = request.form.get('siteTitle', '')
    footer_addition = request.form.get('footerAddition', '')
    base_url = request.form.get('baseUrl', '')
    favicon_file = request.files.get('favicon')
    
    # Prepare branding data
    branding_data = {
        'siteTitle': site_title,
        'footerAddition': footer_addition,
        'baseUrl': base_url
    }
    
    # Handle favicon file upload
    if favicon_file and favicon_file.filename != '':
        # Validate file type
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'ico'}
        file_ext = favicon_file.filename.rsplit('.', 1)[1].lower() if '.' in favicon_file.filename else ''
        
        if file_ext not in allowed_extensions:
            return jsonify({'success': False, 'error': 'Invalid file type. Allowed: PNG, JPEG, GIF, ICO'}), 400
        
        # Create favicons directory if it doesn't exist
        favicons_dir = os.path.join('public', 'favicons')
        os.makedirs(favicons_dir, exist_ok=True)
        
        # Generate a unique filename to prevent overwriting
        filename = f"{uuid.uuid4().hex}.{file_ext}"
        filepath = os.path.join(favicons_dir, filename)
        
        try:
            favicon_file.save(filepath)
            branding_data['siteIcon'] = filename
        except Exception as e:
            return jsonify({'success': False, 'error': f'Failed to save favicon: {str(e)}'}), 500
    
    # Update branding
    try:
        branding = settings_manager.update_branding(branding_data)
        return jsonify({'success': True, 'branding': branding})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Failed to update branding: {str(e)}'}), 500

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
    
    settings_manager.update_mfa_settings(mfa_settings)
    return jsonify({'success': True, 'settings': mfa_settings})

@app.route('/api/settings/smtp', methods=['GET'])
@admin_required
def get_smtp_settings():
    """Get SMTP settings (admin only)"""
    return jsonify(settings_manager.get_smtp_settings())

@app.route('/api/settings/smtp', methods=['PUT'])
@admin_required
def update_smtp_settings():
    """Update SMTP settings (admin only)"""
    data = request.get_json()
    smtp_settings = settings_manager.update_smtp_settings(data)
    return jsonify({'success': True, 'settings': smtp_settings})

@app.route('/api/settings/smtp/test', methods=['POST'])
@admin_required
def test_smtp_settings():
    """Send a test email to verify SMTP configuration"""
    data = request.get_json()
    to_email = data.get('email')
    
    if not to_email:
        return jsonify({'error': 'Email address required'}), 400
    
    success, message = email_service.send_test_email(to_email)
    
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'error': message}), 400


@app.route('/api/settings/external-backup', methods=['GET'])
@admin_required
def get_external_backup_settings_api():
    """Get external backup storage settings (admin only)"""
    return jsonify(settings_manager.get_external_backup_settings())


@app.route('/api/settings/external-backup', methods=['PUT'])
@admin_required
def update_external_backup_settings_api():
    """Update external backup storage settings (admin only)"""
    data = request.get_json()
    updated = settings_manager.update_external_backup_settings(data)
    return jsonify({'success': True, 'settings': updated})


@app.route('/api/settings/external-backup/test', methods=['POST'])
@admin_required
def test_external_backup_settings():
    """Test external backup storage connectivity by uploading a tiny probe file"""
    import tempfile

    ext = settings_manager.get_external_backup_settings_full()
    if not ext.get('enabled', False):
        return jsonify({'error': 'External backup is not enabled'}), 400

    try:
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
            tmp_path = Path(tmp.name)
            with zipfile.ZipFile(tmp_path, 'w') as zf:
                zf.writestr('test.txt', 'MServerController external backup test')

        ok, msg = upload_backup_to_external(tmp_path, '_test', 'connectivity-test.zip')
        tmp_path.unlink(missing_ok=True)
        # Remove sidecar (no checksum for test file)
        sidecar = tmp_path.with_suffix('.sha256')
        if sidecar.exists():
            sidecar.unlink()

        if ok:
            return jsonify({'success': True, 'message': msg})
        return jsonify({'error': msg}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== Server Backup/Restore (All Servers) ====================

@app.route('/api/tools/servers/backup-all', methods=['POST'])
@admin_required
def backup_all_servers():
    """Create a ZIP archive of all server directories and stream it for download.
    Running servers are NOT stopped; their files are snapshotted live.
    The archive preserves the directory structure: servers/<server_id>/...
    """
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        archive_name = f'mserver_backup_all_{timestamp}.zip'

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            if SERVERS_DIR.exists():
                for server_dir in sorted(SERVERS_DIR.iterdir()):
                    if not server_dir.is_dir():
                        continue
                    for file_path in server_dir.rglob('*'):
                        if file_path.is_file():
                            # Store as servers/<server_id>/... so it restores cleanly
                            arcname = file_path.relative_to(SERVERS_DIR.parent)
                            try:
                                zf.write(file_path, arcname)
                            except (PermissionError, OSError):
                                pass  # Skip locked / unreadable files

        buf.seek(0)
        response = make_response(buf.read())
        response.headers['Content-Type'] = 'application/zip'
        response.headers['Content-Disposition'] = f'attachment; filename="{archive_name}"'
        return response

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tools/servers/restore-all', methods=['POST'])
@admin_required
def restore_all_servers():
    """Restore servers from an uploaded backup ZIP.
    Expects a multipart/form-data POST with a 'backup' file field.
    Query param ?mode=merge (default) keeps existing servers not in the archive.
    Query param ?mode=replace stops and removes ALL existing server data first.
    Running servers inside the archive are stopped before their data is replaced.
    """
    if 'backup' not in request.files:
        return jsonify({'error': 'No backup file provided'}), 400

    backup_file = request.files['backup']
    if not backup_file.filename:
        return jsonify({'error': 'Empty filename'}), 400

    filename = secure_filename(backup_file.filename)
    if not filename.lower().endswith('.zip'):
        return jsonify({'error': 'Only ZIP archives are supported'}), 400

    mode = request.args.get('mode', 'merge')
    if mode not in ('merge', 'replace'):
        return jsonify({'error': 'Invalid mode; use "merge" or "replace"'}), 400

    try:
        data = backup_file.read()
        buf = io.BytesIO(data)

        if not zipfile.is_zipfile(buf):
            return jsonify({'error': 'Uploaded file is not a valid ZIP archive'}), 400

        buf.seek(0)
        restored = []
        skipped = []

        with zipfile.ZipFile(buf, 'r') as zf:
            # Collect server IDs inside the archive (top-level dirs under servers/)
            server_ids_in_archive = set()
            for name in zf.namelist():
                parts = Path(name).parts
                # Expected layout: servers/<server_id>/...
                if len(parts) >= 2 and parts[0] == 'servers':
                    server_ids_in_archive.add(parts[1])

            if not server_ids_in_archive:
                return jsonify({'error': 'No server directories found in archive (expected servers/<id>/...)'}), 400

            if mode == 'replace':
                # Stop all running servers and wipe SERVERS_DIR
                for sid in list(server_manager.servers.keys()):
                    inst = server_manager.servers.get(sid)
                    if inst and inst.is_running():
                        server_manager.stop_server(sid)
                if SERVERS_DIR.exists():
                    shutil.rmtree(SERVERS_DIR)
                SERVERS_DIR.mkdir(parents=True, exist_ok=True)
            else:
                # Merge: stop only the servers that will be overwritten
                for sid in server_ids_in_archive:
                    inst = server_manager.servers.get(sid)
                    if inst and inst.is_running():
                        server_manager.stop_server(sid)
                    target = SERVERS_DIR / sid
                    if target.exists():
                        shutil.rmtree(target)

            # Extract
            for name in zf.namelist():
                parts = Path(name).parts
                if len(parts) >= 2 and parts[0] == 'servers':
                    # Security: prevent path traversal
                    safe_relative = Path(*parts)
                    dest = SERVERS_DIR.parent / safe_relative
                    try:
                        resolved = dest.resolve()
                        if not str(resolved).startswith(str(SERVERS_DIR.resolve())):
                            skipped.append(name)
                            continue
                    except Exception:
                        skipped.append(name)
                        continue

                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if not name.endswith('/'):
                        with zf.open(name) as src, open(dest, 'wb') as dst:
                            shutil.copyfileobj(src, dst)
                        restored.append(name)

        return jsonify({
            'success': True,
            'mode': mode,
            'serversRestored': list(server_ids_in_archive),
            'filesRestored': len(restored),
            'filesSkipped': len(skipped)
        })

    except zipfile.BadZipFile:
        return jsonify({'error': 'Corrupt or invalid ZIP archive'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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
JAR_URL_CACHE_MAX_AGE_HOURS = 12  # How long to keep cached download URLs (hours)

class JarBucketManager:
    """
    Manager for downloading Minecraft server JAR files from various sources.
    Inspired by Crafty Controller's Big Bucket system.
    """
    
    # Server type metadata with descriptions
    SERVER_TYPES = {
        'vanilla': {
            'name': 'Vanilla',
            'description': 'Official Minecraft Java Edition server',
            'category': 'java_servers',
            'api_url': 'https://launchermeta.mojang.com/mc/game/version_manifest.json',
            'icon': '🎮'
        },
        'bedrock': {
            'name': 'Bedrock',
            'description': 'Official Minecraft Bedrock Edition server',
            'category': 'bedrock',
            'api_url': 'https://net-secondary.web.minecraft-services.net/api/v1.0/download/links',
            'icon': '🪨'
        },
        'paper': {
            'name': 'Paper',
            'description': 'High-performance Spigot fork with optimizations',
            'category': 'java_servers',
            'api_url': 'https://api.papermc.io/v2/',
            'icon': '📄'
        },
        'purpur': {
            'name': 'Purpur',
            'description': 'Paper fork with extra features and configuration',
            'category': 'java_servers',
            'api_url': 'https://api.purpurmc.org/v2/purpur/',
            'icon': '💜'
        },
        'folia': {
            'name': 'Folia',
            'description': 'Paper fork for multi-threaded regions',
            'category': 'java_servers',
            'api_url': 'https://api.papermc.io/v2/',
            'icon': '🌿'
        },
        'spigot': {
            'name': 'Spigot',
            'description': 'Modified Minecraft server with Bukkit plugin support',
            'category': 'java_servers',
            'api_url': 'https://hub.spigotmc.org/versions/',
            'icon': '🔧'
        },
        'fabric': {
            'name': 'Fabric',
            'description': 'Lightweight mod loader for Minecraft',
            'category': 'modded',
            'api_url': 'https://meta.fabricmc.net/v2/versions',
            'icon': '🧵'
        },
        'forge': {
            'name': 'Forge',
            'description': 'Popular mod loader for Minecraft mods',
            'category': 'modded',
            'api_url': 'https://maven.minecraftforge.net/net/minecraftforge/forge/',

            'icon': '⚒️'
        },
        'neoforge': {
            'name': 'NeoForge',
            'description': 'Modern community-driven Forge fork',
            'category': 'modded',
            'api_url': 'https://maven.neoforged.net/releases/net/neoforged/neoforge/',
            'icon': '🔨'
        }
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
        types_by_category = {'java_servers': [], 'bedrock': [], 'modded': []}

        for type_id, info in self.SERVER_TYPES.items():
            category = info.get('category', 'java_servers')
            if category == 'proxies':
                continue
            types_by_category.setdefault(category, []).append({
                'id': type_id,
                **info
            })

        return types_by_category
    
    def _fetch_paper_versions(self, project='paper'):
        """Fetch versions from Paper API (Paper, Folia)"""
        try:
            url = f"{self.SERVER_TYPES[project]['api_url']}projects/{project}"
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
            base = self.SERVER_TYPES[project]['api_url']
            url = f"{base}projects/{project}/versions/{version}"
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                print(f"[JarBucket] {project} API returned status {response.status_code} for version {version}")
                return None, None
            
            try:
                data = response.json()
            except ValueError as json_err:
                print(f"[JarBucket] Invalid JSON from {project} API for version {version}: {json_err}")
                print(f"[JarBucket] Response content: {response.text[:200]}")
                return None, None
            builds = data.get('builds', [])
            if not builds:
                return None, None
            
            latest_build = max(builds)
            
            # Get download info
            build_url = f"{base}projects/{project}/versions/{version}/builds/{latest_build}"
            build_response = requests.get(build_url, timeout=10)
            if build_response.status_code != 200:
                print(f"[JarBucket] {project} API returned status {build_response.status_code} for build {latest_build}")
                return None, None
            
            try:
                build_data = build_response.json()
            except ValueError as json_err:
                print(f"[JarBucket] Invalid JSON from {project} API for build {latest_build}: {json_err}")
                return None, None
            downloads = build_data.get('downloads', {})
            application = downloads.get('application', {})
            jar_name = application.get('name')
            sha256 = application.get('sha256')
            
            if jar_name:
                download_url = f"{base}projects/{project}/versions/{version}/builds/{latest_build}/downloads/{jar_name}"
                return download_url, sha256
        except Exception as e:
            print(f"[JarBucket] Error getting {project} download URL: {e}")
        return None, None
    
    def _fetch_purpur_versions(self):
        """Fetch versions from Purpur API"""
        try:
            response = requests.get(self.SERVER_TYPES['purpur']['api_url'], timeout=15)
            if response.status_code == 200:
                data = response.json()
                return list(reversed(data.get('versions', [])))
        except Exception as e:
            print(f"[JarBucket] Error fetching Purpur versions: {e}")
        return []
    
    def _fetch_purpur_download_url(self, version):
        """Get download URL for Purpur"""
        try:
            base = self.SERVER_TYPES['purpur']['api_url']
            url = f"{base}{version}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                builds = data.get('builds', {})
                latest = builds.get('latest')
                if latest:
                    return f"{base}{version}/{latest}/download", None
        except Exception as e:
            print(f"[JarBucket] Error getting Purpur download URL: {e}")
        return None, None
    
    def _fetch_vanilla_versions(self):
        """Fetch versions from Mojang manifest"""
        try:
            response = requests.get(self.SERVER_TYPES['vanilla']['api_url'], timeout=15)
            if response.status_code == 200:
                data = response.json()
                versions = []
                for ver in data.get('versions', []):
                    if ver.get('type') == 'release':
                        versions.append({
                            'id': ver['id'],
                            'url': ver['url']
                        })
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
            game_url = f"{self.SERVER_TYPES['fabric']['api_url']}game"
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
            url = f"{self.SERVER_TYPES['fabric']['api_url']}loader"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for loader in data:
                    if loader.get('stable'):
                        return loader['version']
        except Exception as e:
            print(f"[JarBucket] Error getting Fabric loader version: {e}")
        return None

    def _get_fabric_installer_version(self):
        """Get latest stable Fabric installer version"""
        try:
            url = f"{self.SERVER_TYPES['fabric']['api_url']}installer"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for installer in data:
                    if installer.get('stable'):
                        return installer['version']
        except Exception as e:
            print(f"[JarBucket] Error getting Fabric installer version: {e}")
        return None

    def _fetch_fabric_download_url(self, game_version):
        """Get download URL for Fabric server (uses latest stable loader + installer)"""
        try:
            loader_version = self._get_fabric_loader_version()
            installer_version = self._get_fabric_installer_version()
            if not loader_version or not installer_version:
                print(f"[JarBucket] Could not resolve Fabric loader/installer versions from API")
                return None, None
            download_url = f"https://meta.fabricmc.net/v2/versions/loader/{game_version}/{loader_version}/{installer_version}/server/jar"
            return download_url, None
        except Exception as e:
            print(f"[JarBucket] Error getting Fabric download URL: {e}")
        return None, None
    
    def _fetch_bedrock_download_url(self):
        """Get the latest Bedrock server download URL from Minecraft services API"""
        try:
            response = requests.get(
                self.SERVER_TYPES['bedrock']['api_url'],
                headers={
                    'User-Agent': 'Mozilla/5.0 (Linux; x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
                },
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            
            links = {}
            for link in data.get('result', {}).get('links', []):
                dtype = link.get('downloadType', '')
                url = link.get('downloadUrl', '')
                
                import re as _re
                match = _re.match(r'serverBedrock(Preview)?(Windows|Linux)', dtype)
                if match:
                    is_preview = match.group(1) is not None
                    platform = match.group(2).lower()
                    key = f"{platform}_{'preview' if is_preview else 'stable'}"
                    links[key] = url
            
            # Return Linux stable URL (since this runs on Linux)
            if os.name == 'nt':
                return links.get('windows_stable'), None
            else:
                return links.get('linux_stable'), None
                
        except Exception as e:
            print(f"[JarBucket] Error fetching Bedrock download URL: {e}")
        return None, None
    
    def _fetch_bedrock_versions(self):
        """Bedrock only has 'latest' version available"""
        return ['latest']

    def _fetch_forge_versions(self):
        """Dynamically fetch Forge versions from Maven metadata (mc_version -> forge_version map)"""
        import re
        import xml.etree.ElementTree as ET
        try:
            url = 'https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml'
            response = requests.get(url, timeout=20)
            if response.status_code == 200:
                root = ET.fromstring(response.text)
                versions_elem = root.find('.//versioning/versions')
                if versions_elem is None:
                    return {}
                forge_map = {}
                for v in versions_elem.findall('version'):
                    ver_str = v.text.strip()
                    ver_lower = ver_str.lower()
                    # Skip non-stable (rc, beta, pre, alpha)
                    if any(x in ver_lower for x in ['rc', 'beta', 'pre', 'alpha']):
                        continue
                    # Modern format: "1.21.5-55.1.6"
                    if '-' not in ver_str:
                        continue
                    mc_ver, forge_ver = ver_str.split('-', 1)
                    # Validate clean MC version format
                    if not re.match(r'^\d+\.\d+(?:\.\d+)?$', mc_ver):
                        continue
                    # Limit to MC 1.12+
                    try:
                        mc_parts = [int(x) for x in mc_ver.split('.')]
                        if mc_parts[1] < 12:
                            continue
                    except (ValueError, IndexError):
                        continue
                    # Last write wins — Maven lists ascending, so latest forge build per MC survives
                    forge_map[mc_ver] = forge_ver
                return forge_map
        except Exception as e:
            print(f'[JarBucket] Error fetching Forge versions from Maven: {e}')
        return {}

    def _fetch_neoforge_versions(self):
        """Dynamically fetch NeoForge versions from Maven metadata (mc_version -> neoforge_version map)"""
        import xml.etree.ElementTree as ET
        try:
            url = 'https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml'
            response = requests.get(url, timeout=20)
            if response.status_code == 200:
                root = ET.fromstring(response.text)
                versions_elem = root.find('.//versioning/versions')
                if versions_elem is None:
                    return {}
                neo_map = {}
                for v in versions_elem.findall('version'):
                    ver_str = v.text.strip()
                    ver_lower = ver_str.lower()
                    # Skip non-stable (rc, beta, pre, alpha)
                    if any(x in ver_lower for x in ['rc', 'beta', 'pre', 'alpha']):
                        continue
                    # NeoForge format: "21.5.96" -> MC "1.21.5"; "21.0.167" -> MC "1.21"
                    parts = ver_str.split('.')
                    if len(parts) < 2:
                        continue
                    mc_ver = f'1.{parts[0]}' if parts[1] == '0' else f'1.{parts[0]}.{parts[1]}'
                    # Last write wins — latest NeoForge build per MC version survives
                    neo_map[mc_ver] = ver_str
                return neo_map
        except Exception as e:
            print(f'[JarBucket] Error fetching NeoForge versions from Maven: {e}')
        return {}

    def _fetch_spigot_versions(self):
        """Fetch available Spigot build versions from hub.spigotmc.org directory listing"""
        import re
        try:
            response = requests.get(self.SERVER_TYPES['spigot']['api_url'], timeout=15)
            if response.status_code == 200:
                # Parse HTML directory listing for version JSON file links (e.g. "1.21.5.json")
                matches = re.findall(r'href="(\d+\.\d+(?:\.\d+)?)\.json"', response.text)
                if matches:
                    # Filter to stable versions only
                    versions = [v for v in matches if not any(
                        x in v.lower() for x in ['rc', 'beta', 'pre', 'alpha', 'snapshot']
                    )]
                    # Sort newest first
                    def _ver_key(ver):
                        try:
                            return tuple(int(x) for x in ver.split('.'))
                        except Exception:
                            return (0,)
                    versions.sort(key=_ver_key, reverse=True)
                    return versions
        except Exception as e:
            print(f'[JarBucket] Error fetching Spigot versions: {e}')
        # Fallback to known stable versions
        return [
            '1.21.4', '1.21.3', '1.21.1', '1.21', '1.20.6', '1.20.4',
            '1.20.2', '1.20.1', '1.19.4', '1.19.3', '1.19.2', '1.18.2',
            '1.17.1', '1.16.5', '1.15.2', '1.14.4', '1.13.2', '1.12.2'
        ]

    def _get_cached_url(self, server_type, version):
        """Return a cached download URL entry if it is still within the max-age window"""
        cache_key = f'{server_type}::{version}'
        entry = self.cache.get('download_urls', {}).get(cache_key)
        if not entry or not entry.get('cached_at'):
            return None
        try:
            cached_at = datetime.fromisoformat(entry['cached_at'])
            age_hours = (datetime.now() - cached_at).total_seconds() / 3600
            if age_hours < JAR_URL_CACHE_MAX_AGE_HOURS:
                return entry
        except Exception:
            pass
        return None

    def _store_cached_url(self, server_type, version, url_info):
        """Persist a resolved download URL into the cache file"""
        cache_key = f'{server_type}::{version}'
        if 'download_urls' not in self.cache:
            self.cache['download_urls'] = {}
        self.cache['download_urls'][cache_key] = {
            **url_info,
            'cached_at': datetime.now().isoformat()
        }
        self._save_cache()

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
        elif server_type == 'purpur':
            versions = self._fetch_purpur_versions()
        elif server_type == 'vanilla':
            vanilla_data = self._fetch_vanilla_versions()
            versions = [{'version': v['id'], 'manifest_url': v['url']} for v in vanilla_data]
        elif server_type == 'fabric':
            versions = self._fetch_fabric_versions()
        elif server_type == 'forge':
            forge_map = self._fetch_forge_versions()
            def _mc_key(v):
                try:
                    return tuple(int(x) for x in v.split('.'))
                except Exception:
                    return (0,)
            if forge_map:
                versions = sorted(forge_map.keys(), key=_mc_key, reverse=True)
                # Persist the resolved map so get_download_info can use it without re-fetching
                if 'versions' not in self.cache:
                    self.cache['versions'] = {}
                self.cache['versions'].setdefault('forge', {})['forge_map'] = forge_map
        elif server_type == 'neoforge':
            neo_map = self._fetch_neoforge_versions()
            def _mc_key(v):
                try:
                    return tuple(int(x) for x in v.split('.'))
                except Exception:
                    return (0,)
            if neo_map:
                versions = sorted(neo_map.keys(), key=_mc_key, reverse=True)
                if 'versions' not in self.cache:
                    self.cache['versions'] = {}
                self.cache['versions'].setdefault('neoforge', {})['neoforge_map'] = neo_map
        elif server_type == 'spigot':
            versions = self._fetch_spigot_versions()
        elif server_type == 'bedrock':
            versions = self._fetch_bedrock_versions()
        
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
        # Spigot has no downloadable JAR — short-circuit before cache check
        if server_type == 'spigot':
            return {
                'requires_build': True,
                'message': 'Spigot requires BuildTools to compile. Download BuildTools and run: java -jar BuildTools.jar --rev ' + version,
                'buildtools_url': 'https://hub.spigotmc.org/jenkins/job/BuildTools/lastSuccessfulBuild/artifact/target/BuildTools.jar'
            }

        # Return cached URL if still fresh
        cached = self._get_cached_url(server_type, version)
        if cached:
            return {
                'url': cached['url'],
                'hash': cached.get('hash'),
                'filename': cached['filename'],
                'hash_type': cached.get('hash_type', 'sha256')
            }

        download_url = None
        file_hash = None
        filename = None

        if server_type in ['paper', 'folia']:
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
            # Prefer the dynamically fetched map stored during get_versions(); re-fetch on cache miss
            forge_map = self.cache.get('versions', {}).get('forge', {}).get('forge_map') or self._fetch_forge_versions()
            forge_ver = forge_map.get(version) if forge_map else None
            if forge_ver:
                download_url = f"{self.SERVER_TYPES['forge']['api_url']}{version}-{forge_ver}/forge-{version}-{forge_ver}-installer.jar"
                filename = f"forge-{version}-{forge_ver}-installer.jar"
        elif server_type == 'neoforge':
            neo_map = self.cache.get('versions', {}).get('neoforge', {}).get('neoforge_map') or self._fetch_neoforge_versions()
            neo_ver = neo_map.get(version) if neo_map else None
            if neo_ver:
                download_url = f"{self.SERVER_TYPES['neoforge']['api_url']}{neo_ver}/neoforge-{neo_ver}-installer.jar"
                filename = f"neoforge-{neo_ver}-installer.jar"
        elif server_type == 'bedrock':
            download_url, file_hash = self._fetch_bedrock_download_url()
            filename = 'bedrock_server.zip'

        if download_url:
            result = {
                'url': download_url,
                'hash': file_hash,
                'filename': filename,
                'hash_type': 'sha256' if file_hash and len(file_hash) == 64 else 'sha1'
            }
            # Cache the resolved URL so the next request doesn't need to poll the API
            self._store_cached_url(server_type, version, result)
            return result

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
                    'progress': 0
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
                                'progress': int((downloaded / total_size) * 100)
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
                    'progress': 100
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
    
    def refresh_all_versions(self, progress_callback=None):
        """
        Fetch fresh version lists from every upstream API and pre-cache download URLs.
        This keeps the local jar_cache.json up-to-date so the UI never needs to wait
        on external API calls.  Runs synchronously; call from a background thread.
        """
        results = {}
        all_types = list(self.SERVER_TYPES.keys())

        for idx, server_type in enumerate(all_types):
            if progress_callback:
                progress_callback(server_type, idx, len(all_types))

            try:
                versions = self.get_versions(server_type, force_refresh=True)
                urls_cached = 0
                errors = []

                # Pre-cache download URLs.  For types backed purely by a static map
                # (forge, neoforge) or with trivially cheap URLs (bedrock, spigot)
                # cache every version; for API-heavy types limit to the 10
                # most-recent releases to avoid hammering upstream servers.
                if server_type in ('forge', 'neoforge', 'bedrock'):
                    versions_to_cache = versions
                elif server_type == 'spigot':
                    versions_to_cache = []  # BuildTools only; nothing to cache
                else:
                    versions_to_cache = versions[:10] if len(versions) > 10 else versions

                for v in versions_to_cache:
                    version_str = v.get('version', str(v)) if isinstance(v, dict) else str(v)
                    try:
                        info = self.get_download_info(server_type, version_str)
                        if info and info.get('url'):
                            urls_cached += 1
                    except Exception as exc:
                        errors.append(str(exc))

                results[server_type] = {
                    'versions': len(versions),
                    'urls_cached': urls_cached,
                    'errors': errors
                }
            except Exception as exc:
                results[server_type] = {'error': str(exc)}

        return results

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

def is_stable_version(version_string):
    """Check if a version is a stable release (not snapshot, RC, pre-release, or beta)"""
    version_lower = str(version_string).lower()

    # Substring-based exclusions for clearly unstable labels
    excluded_substrings = [
        'snapshot', '-pre', 'pre-', '-rc', 'rc-', 'release candidate',
        'beta', 'alpha', 'experimental',
    ]
    for pattern in excluded_substrings:
        if pattern in version_lower:
            return False

    # Weekly snapshot pattern like "24w14a" or "1.21-rc1"
    import re
    if re.match(r'^\d{2}w\d{2}[a-z]$', version_lower):
        return False
    # RC suffix attached to a version number, e.g. "1.21-rc1", "1.21.1-pre3"
    if re.search(r'-(rc|pre)\d+$', version_lower):
        return False

    return True

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
            version_str = v.get('version', str(v))
        else:
            version_str = str(v)
        
        # Filter out non-stable versions (snapshots, RC, etc.)
        if is_stable_version(version_str):
            normalized.append(version_str)
    
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
    
    # Initialize progress immediately to avoid race condition
    jar_bucket.download_progress[progress_id] = {
        'status': 'initializing',
        'message': 'Starting download...'
    }
    
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
@limiter.exempt
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
    """Force refresh the version cache for one or all server types"""
    data = request.get_json() or {}
    server_type = data.get('type')

    if server_type:
        jar_bucket.get_versions(server_type, force_refresh=True)
        return jsonify({'message': f'Refreshed {server_type} versions'})
    else:
        for st in jar_bucket.SERVER_TYPES.keys():
            jar_bucket.get_versions(st, force_refresh=True)
        return jsonify({'message': 'Refreshed all versions'})

@app.route('/api/jar-bucket/refresh-all', methods=['POST'])
@admin_required
def api_jar_bucket_refresh_all():
    """
    Refresh every upstream API version list AND pre-cache download URLs.
    Runs in a background thread; poll /api/jar-bucket/progress/<refresh_id> for status.
    """
    refresh_id = 'refresh_' + str(uuid.uuid4())

    jar_bucket.download_progress[refresh_id] = {
        'status': 'running',
        'current': None,
        'completed': 0,
        'total': len(jar_bucket.SERVER_TYPES)
    }

    def do_refresh():
        def on_progress(server_type, index, total):
            jar_bucket.download_progress[refresh_id].update({
                'current': server_type,
                'completed': index
            })

        try:
            results = jar_bucket.refresh_all_versions(progress_callback=on_progress)
            jar_bucket.download_progress[refresh_id] = {
                'status': 'complete',
                'completed': len(jar_bucket.SERVER_TYPES),
                'total': len(jar_bucket.SERVER_TYPES),
                'results': results
            }
        except Exception as exc:
            jar_bucket.download_progress[refresh_id] = {
                'status': 'error',
                'error': str(exc)
            }

    threading.Thread(target=do_refresh, daemon=True).start()

    return jsonify({
        'refresh_id': refresh_id,
        'message': 'Full version refresh started — poll /api/jar-bucket/progress/' + refresh_id
    })

@app.route('/api/jar-bucket/check/<server_type>/<version>', methods=['GET'])
@login_required
def api_jar_bucket_check(server_type, version):
    """Check if a specific JAR version is downloaded locally"""
    # Check in both the old jar_manager and new jar_bucket
    local_jar = jar_manager.get_local_jar_info(server_type, version)
    
    if local_jar:
        return jsonify({
            'downloaded': True,
            'filename': local_jar.get('filename'),
            'size': local_jar.get('size'),
            'path': local_jar.get('path')
        })
    
    return jsonify({'downloaded': False})

@app.route('/api/jar-bucket/all-types', methods=['GET'])
@login_required
def api_jar_bucket_all_types():
    """Get all JAR Bucket server types (regardless of local availability)"""
    types = []
    for type_id, info in jar_bucket.SERVER_TYPES.items():
        types.append({
            'id': type_id,
            'name': info['name'],
            'description': info['description'],
            'category': info['category'],
            'icon': info.get('icon', '📦')
        })
    types.sort(key=lambda x: x['name'])
    return jsonify({'types': types})

@app.route('/api/jar-bucket/all-versions/<server_type>', methods=['GET'])
@login_required
def api_jar_bucket_all_versions(server_type):
    """Get all available versions for a server type from JAR Bucket API (not just local)"""
    versions = jar_bucket.get_versions(server_type, force_refresh=False)
    
    # Also get list of locally downloaded versions
    downloaded = set()
    jars = jar_bucket.list_downloaded_jars()
    if server_type in jars:
        for jar in jars[server_type].get('files', []):
            downloaded.add(jar.get('version'))
    
    # Normalize version format and add download status - filter out non-stable versions
    result = []
    for v in versions:
        version_str = v.get('version', str(v)) if isinstance(v, dict) else str(v)
        
        # Filter out non-stable versions (snapshots, RC, etc.)
        if is_stable_version(version_str):
            result.append({
                'version': version_str,
                'downloaded': version_str in downloaded
            })
    
    return jsonify({
        'server_type': server_type,
        'versions': result,
        'count': len(result)
    })


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


# ==================== BlueMap (World Map) API ====================

BLUEMAP_DIR = TOOLS_DIR / 'bluemap'
BLUEMAP_JAR = BLUEMAP_DIR / 'bluemap-cli.jar'
BLUEMAP_GITHUB_API = 'https://api.github.com/repos/BlueMap-Minecraft/BlueMap/releases/latest'

# Track active render processes per server
_bluemap_renders = {}  # server_id -> { process, started, status }


def _get_bluemap_config_dir(server_id):
    """Get the BlueMap config directory for a server"""
    server_path = server_manager.get_server_path(server_id)
    return server_path / 'bluemap-config'


def _get_bluemap_web_dir(server_id):
    """Get the BlueMap web output directory for a server"""
    server_path = server_manager.get_server_path(server_id)
    return server_path / 'bluemap' / 'web'


def _bluemap_is_installed():
    """Check if the BlueMap CLI JAR exists"""
    return BLUEMAP_JAR.exists()


def _get_bluemap_version():
    """Get BlueMap version from the JAR filename pattern or by running --version"""
    if not _bluemap_is_installed():
        return None
    try:
        result = subprocess.run(
            ['java', '-jar', str(BLUEMAP_JAR), '--version'],
            capture_output=True, text=True, timeout=15
        )
        output = (result.stdout + result.stderr).strip()
        # BlueMap prints version info on stdout
        for line in output.splitlines():
            line = line.strip()
            if line and any(c.isdigit() for c in line):
                return line
        return 'Installed'
    except Exception:
        return 'Installed'


def _bluemap_has_map_data(server_id):
    """Check if any rendered map data exists for this server"""
    web_dir = _get_bluemap_web_dir(server_id)
    maps_dir = web_dir / 'maps'
    if not maps_dir.exists():
        return False
    # Check if any map subdirectory has hires data
    for item in maps_dir.iterdir():
        if item.is_dir():
            return True
    return False


def _bluemap_last_render_time(server_id):
    """Get the last render timestamp"""
    config_dir = _get_bluemap_config_dir(server_id)
    marker_file = config_dir / '.last_render'
    if marker_file.exists():
        try:
            ts = marker_file.read_text().strip()
            dt = datetime.fromisoformat(ts)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            pass
    return None


def _bluemap_generate_configs(server_id):
    """Run BlueMap once with -c to generate default configs, then patch world paths"""
    config_dir = _get_bluemap_config_dir(server_id)
    config_dir.mkdir(parents=True, exist_ok=True)

    server_path = server_manager.get_server_path(server_id)

    # Generate default configs
    subprocess.run(
        ['java', '-jar', str(BLUEMAP_JAR), '-c', str(config_dir)],
        capture_output=True, text=True, timeout=30,
        cwd=str(server_path)
    )

    # Accept the download in core.conf
    core_conf = config_dir / 'core.conf'
    if core_conf.exists():
        content = core_conf.read_text()
        content = content.replace('accept-download: false', 'accept-download: true')
        core_conf.write_text(content)

    # Set webserver to disabled (we serve via Flask)
    webserver_conf = config_dir / 'webserver.conf'
    if webserver_conf.exists():
        content = webserver_conf.read_text()
        content = content.replace('enabled: true', 'enabled: false')
        webserver_conf.write_text(content)

    # Point webapp.conf webroot to our output dir
    webapp_conf = config_dir / 'webapp.conf'
    web_dir = _get_bluemap_web_dir(server_id)
    if webapp_conf.exists():
        content = webapp_conf.read_text()
        content = re.sub(
            r'webroot\s*:\s*"[^"]*"',
            f'webroot: "{str(web_dir)}"',
            content
        )
        webapp_conf.write_text(content)

    # Point file storage root to web/maps
    file_conf = config_dir / 'storages' / 'file.conf'
    if file_conf.exists():
        content = file_conf.read_text()
        content = re.sub(
            r'root\s*:\s*"[^"]*"',
            f'root: "{str(web_dir / "maps")}"',
            content
        )
        file_conf.write_text(content)

    # Patch map configs to point to the correct world directory
    maps_conf_dir = config_dir / 'maps'
    if maps_conf_dir.exists():
        world_dir = server_path / 'world'
        for map_conf in maps_conf_dir.glob('*.conf'):
            content = map_conf.read_text()
            content = re.sub(
                r'world\s*:\s*"[^"]*"',
                f'world: "{str(world_dir)}"',
                content
            )
            map_conf.write_text(content)


def _run_bluemap_render(server_id, force=False):
    """Run BlueMap render in background thread"""
    config_dir = _get_bluemap_config_dir(server_id)
    server_path = server_manager.get_server_path(server_id)

    cmd = ['java', '-jar', str(BLUEMAP_JAR), '-c', str(config_dir), '-r', '-g']
    if force:
        cmd.append('-f')

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(server_path)
        )
        _bluemap_renders[server_id] = {
            'process': process,
            'started': datetime.now().isoformat(),
            'status': 'Rendering...',
            'progress': 0
        }

        # Read output for progress
        for line in iter(process.stdout.readline, ''):
            line = line.strip()
            if not line:
                continue
            # Try to parse progress from BlueMap output
            _bluemap_renders[server_id]['status'] = line[-120:] if len(line) > 120 else line
            # Look for percentage patterns
            pct_match = re.search(r'(\d+(?:\.\d+)?)\s*%', line)
            if pct_match:
                _bluemap_renders[server_id]['progress'] = min(float(pct_match.group(1)), 100)

        process.wait()

        # Mark completion
        marker_file = config_dir / '.last_render'
        marker_file.write_text(datetime.now().isoformat())

    except Exception as e:
        print(f'[BlueMap] Render error for {server_id}: {e}')
    finally:
        _bluemap_renders.pop(server_id, None)


@app.route('/api/servers/<server_id>/bluemap/status', methods=['GET'])
@server_access_required
@limiter.exempt
def bluemap_status(server_id):
    """Get BlueMap status for a server"""
    installed = _bluemap_is_installed()
    rendering = server_id in _bluemap_renders
    render_info = _bluemap_renders.get(server_id, {})

    return jsonify({
        'installed': installed,
        'version': _get_bluemap_version() if installed else None,
        'hasMapData': _bluemap_has_map_data(server_id) if installed else False,
        'lastRender': _bluemap_last_render_time(server_id),
        'rendering': rendering,
        'renderStatus': render_info.get('status', ''),
        'renderProgress': render_info.get('progress', 0)
    })


def _download_bluemap_jar():
    """Download the latest BlueMap CLI JAR from GitHub releases.
    Uses the GitHub API to find the correct asset URL (name varies by version).
    """
    # Query GitHub API for latest release
    api_resp = requests.get(BLUEMAP_GITHUB_API, timeout=30, headers={'Accept': 'application/vnd.github.v3+json'})
    api_resp.raise_for_status()
    release = api_resp.json()

    # Find the CLI asset (pattern: bluemap-*-cli.jar)
    cli_asset_url = None
    for asset in release.get('assets', []):
        name = asset.get('name', '')
        if name.endswith('-cli.jar'):
            cli_asset_url = asset['browser_download_url']
            break

    if not cli_asset_url:
        raise RuntimeError(f"No CLI JAR found in release {release.get('tag_name', 'unknown')}")

    # Download the JAR
    resp = requests.get(cli_asset_url, stream=True, timeout=120)
    resp.raise_for_status()
    BLUEMAP_DIR.mkdir(parents=True, exist_ok=True)
    with open(BLUEMAP_JAR, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    return release.get('tag_name', 'latest')


@app.route('/api/servers/<server_id>/bluemap/setup', methods=['POST'])
@server_access_required
def bluemap_setup(server_id):
    """Download BlueMap CLI JAR (or use existing) and generate configs"""
    BLUEMAP_DIR.mkdir(parents=True, exist_ok=True)

    if not BLUEMAP_JAR.exists():
        try:
            tag = _download_bluemap_jar()
            print(f'[BlueMap] Downloaded {tag}')
        except Exception as e:
            return jsonify({'error': f'Failed to download BlueMap: {str(e)}'}), 500

    # Generate configs for this server
    try:
        _bluemap_generate_configs(server_id)
    except Exception as e:
        return jsonify({'error': f'Failed to generate configs: {str(e)}'}), 500

    return jsonify({'success': True, 'message': 'BlueMap installed and configured'})


@app.route('/api/servers/<server_id>/bluemap/update', methods=['POST'])
@server_access_required
def bluemap_update(server_id):
    """Force re-download the latest BlueMap CLI JAR"""
    # Remove old JAR
    if BLUEMAP_JAR.exists():
        BLUEMAP_JAR.unlink()

    try:
        tag = _download_bluemap_jar()
    except Exception as e:
        return jsonify({'error': f'Failed to download BlueMap: {str(e)}'}), 500

    return jsonify({'success': True, 'message': f'BlueMap updated to {tag})'})


@app.route('/api/servers/<server_id>/bluemap/upload', methods=['POST'])
@server_access_required
def bluemap_upload(server_id):
    """Upload a BlueMap CLI JAR from local storage"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '' or not file.filename.lower().endswith('.jar'):
        return jsonify({'error': 'Please upload a .jar file'}), 400

    BLUEMAP_DIR.mkdir(parents=True, exist_ok=True)
    file.save(str(BLUEMAP_JAR))

    # Generate configs for this server
    try:
        _bluemap_generate_configs(server_id)
    except Exception as e:
        return jsonify({'error': f'Failed to generate configs: {str(e)}'}), 500

    return jsonify({'success': True, 'message': 'BlueMap JAR uploaded and configured'})


@app.route('/api/servers/<server_id>/bluemap/render', methods=['POST'])
@server_access_required
def bluemap_render(server_id):
    """Start a BlueMap render for this server"""
    if not _bluemap_is_installed():
        return jsonify({'error': 'BlueMap is not installed. Run setup first.'}), 400

    if server_id in _bluemap_renders:
        return jsonify({'error': 'A render is already in progress for this server'}), 409

    # Ensure configs exist
    config_dir = _get_bluemap_config_dir(server_id)
    if not config_dir.exists():
        _bluemap_generate_configs(server_id)

    data = request.get_json(silent=True) or {}
    force = data.get('force', False)

    # Start render in background thread
    thread = threading.Thread(
        target=_run_bluemap_render,
        args=(server_id,),
        kwargs={'force': force},
        daemon=True
    )
    thread.start()

    return jsonify({'success': True, 'message': 'Render started'})


@app.route('/api/servers/<server_id>/bluemap/viewer/', defaults={'path': 'index.html'}, methods=['GET'])
@app.route('/api/servers/<server_id>/bluemap/viewer/<path:path>', methods=['GET'])
@server_access_required
@limiter.exempt
def bluemap_viewer(server_id, path):
    """Serve BlueMap web viewer files"""
    web_dir = _get_bluemap_web_dir(server_id)

    if not web_dir.exists():
        return jsonify({'error': 'No map data available'}), 404

    # Security: prevent directory traversal
    if not is_safe_path(str(web_dir), str(web_dir / path)):
        return jsonify({'error': 'Invalid path'}), 403

    full_path = web_dir / path
    if full_path.is_file():
        return send_from_directory(str(web_dir), path)

    # Try with .gz extension (BlueMap stores tiles gzipped)
    gz_path = web_dir / (path + '.gz')
    if gz_path.is_file():
        response = make_response(send_from_directory(str(web_dir), path + '.gz'))
        response.headers['Content-Encoding'] = 'gzip'
        return response

    return jsonify({'error': 'File not found'}), 404


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


# ==================== Security Headers Middleware ====================

@app.after_request
def add_security_headers(response):
    """Add security headers to all responses for production hardening"""
    # Prevent clickjacking attacks.
    # BlueMap viewer is served same-origin inside an iframe, so allow SAMEORIGIN for those paths.
    bluemap_viewer_path = '/bluemap/viewer'
    if bluemap_viewer_path in request.path:
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    else:
        response.headers['X-Frame-Options'] = 'DENY'
    
    # Prevent MIME-sniffing vulnerabilities
    response.headers['X-Content-Type-Options'] = 'nosniff'
    
    # Enable XSS protection for legacy browsers
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    # Strict Transport Security (HSTS) - enforce HTTPS in production
    if os.environ.get('FLASK_ENV') != 'development' and request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    
    # Content Security Policy - restrictive default, adjust for your needs
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.socket.io https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' ws: wss:; "
        "font-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self';"
    )
    
    # Referrer Policy - prevent sensitive URL leakage
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # Permissions Policy - disable unnecessary features
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    
    return response


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
    
    return parser.parse_args()


def run_server(host='0.0.0.0', port=3000):
    """Run the MServerController server"""
    print('=' * 60)
    print('MServerController')
    print('=' * 60)
    print(f'Web Interface: http://localhost:{port}')
    print(f'Listening on: {host}:{port}')
    print('⚠️  WARNING: Default admin credentials are admin/admin')
    print('            Change immediately after first login!')
    print('=' * 60)

    socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    args = parse_arguments()

    run_server(host=args.host, port=args.port)
