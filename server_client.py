"""
MServerController - Client Mode

This module implements the headless client mode that connects to a central controller.
In client mode, the application:
  - Runs without UI (no Flask routes for web interface)
  - Registers with the central controller
  - Receives commands from the central controller
  - Executes server operations locally
  - Reports status and logs back to the controller
"""

import requests
import threading
import time
import platform
import socket
import os
import psutil
import json
import ssl
import urllib3
from datetime import datetime
from cryptography.fernet import Fernet
from pathlib import Path


class ClientController:
    """Manages the client connection to the central controller"""
    
    def __init__(self, controller_url, node_id, local_server_manager, verify_ssl=True, encryption_key=None):
        self.controller_url = controller_url.rstrip('/')
        self.node_id = node_id
        self.server_manager = local_server_manager
        self.registered = False
        self.running = True
        self.heartbeat_interval = 30  # seconds
        self.poll_interval = 5  # seconds
        self.api_key = None  # Will be set during registration
        self.session = requests.Session()
        self.verify_ssl = verify_ssl
        
        # Encryption support
        self.encryption_key = encryption_key
        self.fernet = None
        if encryption_key:
            try:
                self.fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
                print('[Client] Payload encryption enabled')
            except Exception as e:
                print(f'[Client] Failed to initialize encryption: {e}')
                self.fernet = None
        
        # SSL configuration
        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            print('[Client] WARNING: SSL verification disabled')
        
        # Configure session for SSL
        self.session.verify = verify_ssl
        
    def _encrypt_payload(self, data):
        """Encrypt payload data if encryption is enabled"""
        if not self.fernet:
            return data
        
        try:
            json_data = json.dumps(data)
            encrypted = self.fernet.encrypt(json_data.encode())
            return {'encrypted': True, 'data': encrypted.decode()}
        except Exception as e:
            print(f"[Client] Encryption error: {e}")
            return data
    
    def _decrypt_payload(self, data):
        """Decrypt payload data if encryption is enabled"""
        if not self.fernet or not isinstance(data, dict) or not data.get('encrypted'):
            return data
        
        try:
            encrypted_data = data['data'].encode()
            decrypted = self.fernet.decrypt(encrypted_data)
            return json.loads(decrypted.decode())
        except Exception as e:
            print(f"[Client] Decryption error: {e}")
            return data
    
    def get_system_info(self):
        """Get system information for registration"""
        try:
            return {
                'hostname': socket.gethostname(),
                'platform': platform.system(),
                'platform_release': platform.release(),
                'platform_version': platform.version(),
                'architecture': platform.machine(),
                'processor': platform.processor(),
                'cpu_count': psutil.cpu_count(),
                'memory_total': psutil.virtual_memory().total,
                'disk_total': psutil.disk_usage('/').total,
                'python_version': platform.python_version()
            }
        except Exception as e:
            print(f"[Client] Error getting system info: {e}")
            return {
                'hostname': socket.gethostname(),
                'platform': platform.system(),
                'error': str(e)
            }
    
    def get_current_stats(self):
        """Get current system statistics"""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            return {
                'cpu_percent': cpu_percent,
                'memory_used': memory.used,
                'memory_total': memory.total,
                'memory_percent': memory.percent,
                'disk_used': disk.used,
                'disk_total': disk.total,
                'disk_percent': disk.percent
            }
        except Exception as e:
            print(f"[Client] Error getting stats: {e}")
            return {}
    
    def get_server_statuses(self):
        """Get status of all local servers"""
        try:
            servers = []
            for server_id, server_config in self.server_manager.config.get('servers', {}).items():
                instance = self.server_manager.servers.get(server_id)
                is_running = instance is not None and instance.is_running()
                status = instance.get_status().value if instance else 'stopped'
                
                servers.append({
                    'id': server_id,
                    'name': server_config.get('name', 'Unnamed'),
                    'running': is_running,
                    'status': status
                })
            return servers
        except Exception as e:
            print(f"[Client] Error getting server statuses: {e}")
            return []
    
    def register(self):
        """Register this client node with the central controller"""
        try:
            print(f"[Client] Registering with controller: {self.controller_url}")
            print(f"[Client] Node ID: {self.node_id}")
            
            system_info = self.get_system_info()
            
            payload = {
                'node_id': self.node_id,
                'system_info': system_info,
                'timestamp': datetime.now().isoformat(),
                'encryption_enabled': self.fernet is not None
            }
            
            # Encrypt payload if encryption is enabled
            encrypted_payload = self._encrypt_payload(payload)
            
            response = self.session.post(
                f"{self.controller_url}/api/client/register",
                json=encrypted_payload,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                # Decrypt response if needed
                data = self._decrypt_payload(data)
                
                self.api_key = data.get('api_key')
                self.registered = True
                
                # Set API key in session headers
                if self.api_key:
                    self.session.headers.update({'X-Client-API-Key': self.api_key})
                
                print(f"[Client] ✓ Registration successful!")
                print(f"[Client] API Key: {self.api_key[:10]}..." if self.api_key else "[Client] No API key provided")
                return True
            else:
                print(f"[Client] ✗ Registration failed: {response.status_code}")
                print(f"[Client] Response: {response.text}")
                return False
                
        except requests.RequestException as e:
            print(f"[Client] ✗ Registration failed - Network error: {e}")
            return False
        except Exception as e:
            print(f"[Client] ✗ Registration failed: {e}")
            return False
    
    def start_heartbeat(self):
        """Start heartbeat thread to report status to controller"""
        def heartbeat_loop():
            while self.running:
                try:
                    if self.registered:
                        self._send_heartbeat()
                except Exception as e:
                    print(f"[Client] Heartbeat error: {e}")
                time.sleep(self.heartbeat_interval)
        
        thread = threading.Thread(target=heartbeat_loop, daemon=True)
        thread.start()
        print(f"[Client] Heartbeat started (interval: {self.heartbeat_interval}s)")
    
    def _send_heartbeat(self):
        """Send heartbeat with current status to controller"""
        try:
            payload = {
                'node_id': self.node_id,
                'timestamp': datetime.now().isoformat(),
                'stats': self.get_current_stats(),
                'servers': self.get_server_statuses()
            }
            
            # Encrypt payload if encryption is enabled
            encrypted_payload = self._encrypt_payload(payload)
            
            response = self.session.post(
                f"{self.controller_url}/api/client/heartbeat",
                json=encrypted_payload,
                timeout=5
            )
            
            if response.status_code == 200:
                # Heartbeat successful
                pass
            else:
                print(f"[Client] Heartbeat failed: {response.status_code}")
                
        except requests.RequestException as e:
            print(f"[Client] Heartbeat network error: {e}")
        except Exception as e:
            print(f"[Client] Heartbeat error: {e}")
    
    def start_command_polling(self):
        """Start command polling thread"""
        def poll_loop():
            while self.running:
                try:
                    if self.registered:
                        self._poll_and_execute_commands()
                except Exception as e:
                    print(f"[Client] Command poll error: {e}")
                time.sleep(self.poll_interval)
        
        thread = threading.Thread(target=poll_loop, daemon=True)
        thread.start()
        print(f"[Client] Command polling started (interval: {self.poll_interval}s)")
    
    def _poll_and_execute_commands(self):
        """Poll for commands from the controller and execute them"""
        try:
            response = self.session.get(
                f"{self.controller_url}/api/client/commands/{self.node_id}",
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                # Decrypt response if needed
                data = self._decrypt_payload(data)
                
                commands = data.get('commands', [])
                
                for command in commands:
                    self.execute_command(command)
                    
        except requests.RequestException:
            # Network errors are expected, don't spam logs
            pass
        except Exception as e:
            print(f"[Client] Command poll error: {e}")
    
    def execute_command(self, command):
        """Execute a command received from the controller"""
        try:
            command_id = command.get('id')
            action = command.get('action')
            server_id = command.get('server_id')
            params = command.get('params', {})
            
            print(f"[Client] Executing command {command_id}: {action} for server {server_id}")
            
            result = {'success': False, 'message': ''}
            
            if action == 'START':
                success, message = self.server_manager.start_server(server_id)
                result = {'success': success, 'message': message}
                
            elif action == 'STOP':
                success, message = self.server_manager.stop_server(server_id)
                result = {'success': success, 'message': message}
                
            elif action == 'RESTART':
                success, message = self.server_manager.stop_server(server_id)
                if success:
                    time.sleep(5)
                    success, message = self.server_manager.start_server(server_id)
                result = {'success': success, 'message': message}
                
            elif action == 'KILL':
                success, message = self.server_manager.kill_server(server_id)
                result = {'success': success, 'message': message}
                
            elif action == 'COMMAND':
                cmd = params.get('command', '')
                success, message = self.server_manager.send_command(server_id, cmd)
                result = {'success': success, 'message': f'Sent command: {cmd}'}
                
            elif action == 'CREATE_SERVER':
                # Create a new server on this client node
                try:
                    name = params.get('name', 'New Server')
                    server_path = params.get('server_path', '')
                    executable = params.get('executable', 'server.jar')
                    java_args = params.get('java_args', '-Xmx2G -Xms1G')
                    server_type = params.get('server_type', 'vanilla')
                    version = params.get('version')
                    owner = params.get('owner', 'admin')
                    approved = params.get('approved', True)
                    category = params.get('category', 'unmodded')
                    
                    # Create server using local ServerManager
                    new_server_id = self.server_manager.create_server(
                        name=name,
                        server_path=server_path,
                        executable=executable,
                        java_args=java_args,
                        server_type=server_type,
                        version=version,
                        owner=owner,
                        approved=approved,
                        category=category
                    )
                    
                    result = {
                        'success': True,
                        'message': f'Server created successfully with ID: {new_server_id}',
                        'server_id': new_server_id
                    }
                    
                except Exception as e:
                    result = {
                        'success': False,
                        'message': f'Failed to create server: {str(e)}'
                    }
                
            elif action == 'BACKUP':
                # Trigger backup - would need backup_scheduler integration
                result = {'success': False, 'message': 'Backup not yet implemented in client mode'}
                
            else:
                result = {'success': False, 'message': f'Unknown action: {action}'}
            
            # Report command execution result back to controller
            self._report_command_result(command_id, result)
            
            print(f"[Client] Command {command_id} executed: {result['message']}")
            
        except Exception as e:
            print(f"[Client] Command execution failed: {e}")
            if 'command_id' in locals():
                self._report_command_result(command_id, {
                    'success': False,
                    'message': str(e)
                })
    
    def _report_command_result(self, command_id, result):
        """Report command execution result to controller"""
        try:
            payload = {
                'node_id': self.node_id,
                'command_id': command_id,
                'timestamp': datetime.now().isoformat(),
                'result': result
            }
            
            # Encrypt payload if encryption is enabled
            encrypted_payload = self._encrypt_payload(payload)
            
            response = self.session.post(
                f"{self.controller_url}/api/client/command-result",
                json=encrypted_payload,
                timeout=5
            )
            
            if response.status_code != 200:
                print(f"[Client] Failed to report command result: {response.status_code}")
                
        except requests.RequestException as e:
            print(f"[Client] Failed to report command result - Network error: {e}")
        except Exception as e:
            print(f"[Client] Failed to report command result: {e}")
    
    def start(self):
        """Start the client controller"""
        print("[Client] Starting client controller...")
        
        # Try to register
        if self.register():
            # Start background threads
            self.start_heartbeat()
            self.start_command_polling()
            print("[Client] Client controller started successfully!")
            return True
        else:
            print("[Client] Failed to start - registration failed")
            return False
    
    def shutdown(self):
        """Shutdown client gracefully"""
        print("[Client] Shutting down...")
        self.running = False
        
        # Send final status update
        if self.registered:
            try:
                self.session.post(
                    f"{self.controller_url}/api/client/disconnect",
                    json={'node_id': self.node_id},
                    timeout=2
                )
            except:
                pass
        
        self.session.close()
        print("[Client] Shutdown complete")


print("server_client.py - Client mode controller loaded")
