# MServerController Development Guide

## 🤖 AI-FRIENDLY DEVELOPMENT REFERENCE

**Last Updated:** 2026-01-22  
**Version:** 3.0 (Distributed Architecture)  
**Primary Language:** Python 3.10+

---

## TABLE OF CONTENTS

1. [Core Architecture](#core-architecture)
2. [Technology Stack](#technology-stack)
3. [File Structure](#file-structure)
4. [Class Reference](#class-reference)
5. [API Endpoints Reference](#api-endpoints-reference)
6. [Command Types (Client-Server Parity)](#command-types-client-server-parity)
7. [Development Rules](#development-rules)
8. [Requirements Management](#requirements-management)
9. [Change Checklist](#change-checklist)

---

## CORE ARCHITECTURE

### System Overview

```
┌────────────────────────────────────────────────────────────┐
│                    CENTRAL CONTROLLER                      │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Flask Web Application (server.py)                  │   │
│  │  - REST API                                         │   │
│  │  - WebSocket (Socket.IO)                            │   │
│  │  - Static file serving                              │   │
│  │  - Authentication & RBAC                            │   │
│  └─────────────────────────────────────────────────────┘   │
│                           │                                │
│  ┌────────────────────────┼────────────────────────────┐   │
│  │                        │                            │   │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐    │   │
│  │  │ ServerMgr   │ │ UserManager │ │ ClientMgr   │    │   │
│  │  │ (servers)   │ │ (auth)      │ │ (nodes)     │    │   │
│  │  └─────────────┘ └─────────────┘ └─────────────┘    │   │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐    │   │
│  │  │ BackupSched │ │ TaskSched   │ │ StatsMgr    │    │   │
│  │  │ (backups)   │ │ (tasks)     │ │ (metrics)   │    │   │
│  │  └─────────────┘ └─────────────┘ └─────────────┘    │   │
│  └─────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
┌─────────▼─────────┐ ┌───────▼───────┐ ┌────────▼────────┐
│  CLIENT NODE 1    │ │ CLIENT NODE 2 │ │ CLIENT NODE N   │
│  (server_client)  │ │               │ │                 │
│  ┌─────────────┐  │ │ ┌───────────┐ │ │ ┌─────────────┐ │
│  │ Controller  │  │ │ │Controller │ │ │ │ Controller  │ │
│  │ - Register  │  │ │ │- Register │ │ │ │ - Register  │ │
│  │ - Heartbeat │  │ │ │- Heartbeat│ │ │ │ - Heartbeat │ │
│  │ - Commands  │  │ │ │- Commands │ │ │ │ - Commands  │ │
│  └─────────────┘  │ │ └───────────┘ │ │ └─────────────┘ │
│  ┌─────────────┐  │ │ ┌───────────┐ │ │ ┌─────────────┐ │
│  │ ServerMgr   │  │ │ │ ServerMgr │ │ │ │ ServerMgr   │ │
│  │ (local MC)  │  │ │ │ (local MC)│ │ │ │ (local MC)  │ │
│  └─────────────┘  │ │ └───────────┘ │ │ └─────────────┘ │
└───────────────────┘ └───────────────┘ └─────────────────┘
```

### Operational Modes

| Mode | File | Description |
|------|------|-------------|
| `central` | `server.py` | Full controller with Web UI, API, all managers |
| `client` | `server_client.py` | Headless node, polls central for commands |

---

## TECHNOLOGY STACK

### Backend (Python)

| Component | Library | Purpose |
|-----------|---------|---------|
| Web Framework | Flask 3.0+ | HTTP routes, API |
| WebSocket | Flask-SocketIO 5.3+ | Real-time console output |
| Task Scheduling | APScheduler 3.10+ | Backup/task automation |
| HTTP Client | requests 2.31+ | JAR downloads, client communication |
| MFA/TOTP | pyotp 2.9+ | Two-factor authentication |
| QR Codes | qrcode 7.4+ | MFA setup QR generation |
| Rate Limiting | Flask-Limiter 3.5+ | API protection |
| System Metrics | psutil | CPU, RAM, disk monitoring |
| WSGI Server | gunicorn 21.2+ | Production deployment |
| Async Support | gevent 23.9+ | WebSocket handling |

### Frontend

| Component | Technology | Purpose |
|-----------|------------|---------|
| Markup | HTML5 | Page structure |
| Styling | CSS3 | Custom styles |
| JavaScript | Vanilla ES6+ | Interactivity |
| WebSocket Client | Socket.IO Client | Real-time updates |

### Infrastructure

| Component | Technology | Purpose |
|-----------|------------|---------|
| Reverse Proxy | Nginx | HTTPS, static files, WebSocket proxy |
| Process Manager | systemd | Service management |
| Data Storage | JSON files | Persistent configuration |

---

## FILE STRUCTURE

```
MServerController/
├── server.py                 # MAIN: Central controller (6400+ lines)
├── server_client.py          # Client mode controller (380+ lines)
├── server_core.py            # Shared core logic (placeholder)
├── requirements.txt          # Python dependencies
├── install.sh                # Installation script
├── nginx.conf                # Nginx configuration
│
├── config.json               # Server configurations (generated)
├── users.json                # User accounts (generated)
├── settings.json             # App settings (generated)
├── stats.json                # System statistics (generated)
├── clients.json              # Registered client nodes (generated)
├── commands.json             # Command queue (generated)
├── backup_schedules.json     # Backup schedules (generated)
├── task_schedules.json       # Task schedules (generated)
│
├── public/                   # Frontend files
│   ├── index.html            # Main dashboard
│   ├── login.html            # Login page
│   ├── settings.html         # Settings page
│   ├── public.html           # Public server list
│   ├── app.js                # Main JavaScript
│   ├── login.js              # Login logic
│   ├── settings.js           # Settings logic
│   ├── public.js             # Public page logic
│   └── styles.css            # Stylesheet
│
├── servers/                  # Minecraft server files
│   └── <server_id>/          # Per-server directory
│
├── backups/                  # Server backups
│   └── <server_id>/          # Per-server backups
│
├── uploads/                  # Temporary uploads
├── serverexecutables/        # Pre-downloaded JARs
│   ├── paper/
│   ├── purpur/
│   ├── vanilla/
│   ├── forge/
│   ├── neoforge/
│   ├── folia/
│   └── spigot/
│
├── configs/                  # Configuration templates
│   └── jarurls.conf          # JAR download URLs
│
├── tools/                    # Utility scripts
│   ├── get_paper_jars.py
│   ├── get_purpur_jars.py
│   ├── get_forge_jars.py
│   └── ...
│
└── docs/                     # Documentation
    ├── DEVELOPMENT_GUIDE.md  # THIS FILE
    ├── API_DISTRIBUTED.md
    ├── DISTRIBUTED_DEPLOYMENT.md
    └── ...
```

---

## CLASS REFERENCE

### Central Controller Classes (server.py)

#### SettingsManager
**Purpose:** Manage application settings and branding

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | - | - | Initialize settings |
| `_load_settings` | - | dict | Load from settings.json |
| `_save_settings` | - | - | Save to settings.json |
| `get_settings` | - | dict | Get all settings |
| `get_branding` | - | dict | Get branding settings |
| `update_branding` | branding_data: dict | - | Update branding |
| `get_app_settings` | - | dict | Get app settings |
| `update_app_settings` | app_data: dict | - | Update app settings |

#### StatsManager
**Purpose:** Collect and store system performance metrics

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | - | - | Initialize stats collection |
| `_load_stats` | - | dict | Load historical stats |
| `_save_stats` | - | - | Save stats to file |
| `_cleanup_old_stats` | - | - | Remove stats older than 24h |
| `_get_system_stats` | - | dict | Get current CPU/RAM/disk |
| `_collect_stats` | - | - | Collect and store stats |
| `_start_collection` | - | - | Start background collection |
| `get_current_stats` | - | dict | Get latest stats |
| `get_history` | hours: int = 24 | list | Get historical stats |

#### BackupScheduler
**Purpose:** Manage automated backup schedules

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | - | - | Initialize scheduler |
| `_load_schedules` | - | dict | Load from file |
| `_save_schedules` | - | - | Save to file |
| `_restore_schedules` | - | - | Restore jobs on startup |
| `_add_job` | server_id, schedule | - | Add APScheduler job |
| `_execute_backup` | server_id | - | Execute backup |
| `_cleanup_old_backups` | server_id, max | - | Remove old backups |
| `set_schedule` | server_id, config | dict | Set backup schedule |
| `get_schedule` | server_id | dict | Get schedule for server |
| `delete_schedule` | server_id | bool | Delete schedule |
| `get_all_schedules` | - | dict | Get all schedules |

#### TaskScheduler
**Purpose:** Manage automated server tasks (start, stop, commands)

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | server_manager, socketio | - | Initialize |
| `_load_tasks` | - | dict | Load from file |
| `_save_tasks` | - | - | Save to file |
| `_restore_tasks` | - | - | Restore jobs on startup |
| `_add_job` | server_id, task_id, task | - | Add scheduler job |
| `_execute_task` | server_id, task_id | - | Execute task |
| `_execute_start` | server_id, task | - | Execute START task |
| `_execute_stop` | server_id, task | - | Execute STOP task |
| `_execute_reboot` | server_id, task | - | Execute REBOOT task |
| `_execute_command` | server_id, task | - | Execute COMMAND task |
| `create_task` | server_id, config | dict | Create new task |
| `update_task` | server_id, task_id, config | dict | Update task |
| `delete_task` | server_id, task_id | bool | Delete task |
| `get_tasks` | server_id | list | Get tasks for server |
| `get_task` | server_id, task_id | dict | Get specific task |

#### UserManager
**Purpose:** User authentication, registration, MFA

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | - | - | Initialize |
| `_load_users` | - | dict | Load from users.json |
| `_save_users` | - | - | Save to users.json |
| `_migrate_users` | - | - | Migrate old user format |
| `_ensure_admin_exists` | - | - | Create default admin |
| `authenticate` | username, password | tuple | Authenticate user |
| `register` | username, password | tuple | Register new user |
| `create_user` | username, password, role | str | Admin create user |
| `get_user` | user_id | dict | Get user by ID |
| `get_user_by_username` | username | dict | Get user by username |
| `get_all_users` | - | list | Get all users |
| `approve_user` | user_id | bool | Approve pending user |
| `update_user_role` | user_id, role | bool | Change user role |
| `delete_user` | user_id | bool | Delete user |
| `change_password` | user_id, old, new | bool | Change password |
| `reset_password` | user_id, new | bool | Admin reset password |
| `update_username` | user_id, new | bool | Change username |
| `update_name` | user_id, name | bool | Update display name |
| `generate_mfa_secret` | user_id | str | Generate TOTP secret |
| `generate_recovery_code` | - | str | Generate recovery code |
| `verify_totp` | secret, code | bool | Verify TOTP code |
| `enable_mfa` | user_id, secret, recovery | bool | Enable MFA |
| `disable_mfa` | user_id | bool | Disable MFA |
| `verify_recovery_code` | user_id, code | bool | Verify recovery |
| `get_role_level` | role | int | Get role priority |
| `enable_account` | user_id | bool | Enable disabled account |

#### ClientManager
**Purpose:** Manage connected client nodes (distributed deployment)

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | - | - | Initialize |
| `_load_clients` | - | dict | Load from clients.json |
| `_save_clients` | - | - | Save to clients.json |
| `_load_commands` | - | dict | Load command queue |
| `_save_commands` | - | - | Save command queue |
| `register_client` | node_id, system_info | str | Register new client |
| `update_heartbeat` | node_id, stats, servers | bool | Update client status |
| `get_client` | node_id | dict | Get client info |
| `get_all_clients` | - | list | Get all clients |
| `verify_api_key` | node_id, api_key | bool | Verify client key |
| `add_command` | node_id, action, server_id, params | str | Queue command |
| `get_pending_commands` | node_id | list | Get pending commands |
| `update_command_result` | node_id, cmd_id, result | bool | Update result |
| `disconnect_client` | node_id | bool | Mark client offline |
| `get_available_nodes` | - | list | Get all online nodes |
| `calculate_node_load` | node | float | Calculate load score |
| `get_best_node_for_deployment` | - | str | Get best node |
| `create_server_on_node` | node_id, config | tuple | Create server on node |

#### JarManager
**Purpose:** Manage server JAR files and downloads

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | - | - | Initialize |
| `_load_jar_urls` | - | - | Load URL configuration |
| `_scan_local_jars` | - | - | Scan serverexecutables/ |
| `_extract_version` | filename, type | str | Extract version from filename |
| `get_server_types` | - | list | Get available server types |
| `get_server_engines` | category | list | Get engines by category |
| `get_versions` | server_type | list | Get versions for type |
| `get_local_jar_info` | type, version | dict | Get local JAR info |
| `copy_jar_to_server` | type, version, dest | bool | Copy JAR to server |
| `_get_paper_download_url` | version | str | Get Paper URL |
| `_get_purpur_download_url` | version | str | Get Purpur URL |
| `get_download_url` | type, version | str | Get download URL |
| `download_jar` | type, version, dest, callback | bool | Download JAR |

#### NBTHandler
**Purpose:** Read and write Minecraft NBT files

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | - | - | Initialize |
| `read_file` | filepath | dict | Read NBT file |
| `write_file` | filepath, nbt_data | bool | Write NBT file |
| `_read_named_tag` | reader | dict | Read named tag |
| `_read_tag_payload` | reader, tag_type | any | Read tag value |
| `_write_named_tag` | writer, tag | - | Write named tag |
| `_write_tag_payload` | writer, type, value | - | Write tag value |
| `to_json` | nbt_data | str | Convert to JSON |
| `update_value` | nbt_data, path, value | dict | Update value at path |
| `add_tag` | nbt_data, parent_path, tag | dict | Add new tag |
| `delete_tag` | nbt_data, path | dict | Delete tag at path |

#### ServerManager
**Purpose:** Manage Minecraft server configurations and operations

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | - | - | Initialize |
| `_load_config` | - | dict | Load config.json |
| `_save_config` | - | - | Save config.json |
| `get_servers_list` | include_pending | list | Get all servers |
| `get_pending_servers` | - | list | Get unapproved servers |
| `approve_server` | server_id | bool | Approve server |
| `reject_server` | server_id | bool | Reject and delete |
| `get_server_config` | server_id | dict | Get server config |
| `create_server` | name, path, exe, args, type, ver, owner, approved, category | str | Create server |
| `_create_managed_conf` | dir, id, name, modded, engine, owner | - | Create .managed.conf |
| `_read_managed_conf` | server_dir | dict | Read .managed.conf |
| `_write_managed_conf` | server_dir, config | - | Write .managed.conf |
| `validate_managed_conf` | server_id | dict | Validate .managed.conf |
| `update_managed_conf_field` | server_id, field, value | bool | Update field |
| `is_managed` | server_id | bool | Check if managed |
| `enable_management` | server_id | bool | Enable management |
| `check_eula_accepted` | server_id | bool | Check EULA status |
| `accept_eula` | server_id | bool | Accept EULA |
| `import_server_from_zip` | name, zip_path, args, jar, owner, approved, category | str | Import ZIP |
| `update_server` | server_id, **kwargs | bool | Update server config |
| `delete_server` | server_id, delete_files | bool | Delete server |
| `start_server` | server_id | tuple | Start server |
| `stop_server` | server_id | tuple | Stop server |
| `kill_server` | server_id | tuple | Force kill server |
| `send_command` | server_id, command | tuple | Send console command |
| `get_server_port` | server_id | int | Get server port |
| `get_all_server_ports` | exclude_server_id | list | Get all ports |
| `get_server_path` | server_id | str | Get server directory |

#### MinecraftServer
**Purpose:** Individual Minecraft server process wrapper

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | server_id, path, exe, args | - | Initialize |
| `start` | - | bool | Start server process |
| `_read_output_unbuffered` | - | - | Read stdout/stderr |
| `_monitor_process` | - | - | Monitor process state |
| `_broadcast` | data | - | Emit via SocketIO |
| `_add_to_buffer` | line | - | Add to output buffer |
| `_check_tcp_port` | port, timeout | bool | Check port open |
| `_get_server_port` | - | int | Parse port from props |
| `_monitor_status` | - | - | Monitor server status |
| `get_status` | - | str | Get current status |
| `is_running` | - | bool | Check if running |
| `send_command` | command | bool | Send to stdin |
| `stop` | - | bool | Send 'stop' command |
| `kill` | - | bool | Force terminate |
| `get_recent_output` | lines | list | Get recent console |

### Client Controller Classes (server_client.py)

#### ClientController
**Purpose:** Client-side controller for distributed deployment

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | controller_url, node_id, server_manager | - | Initialize |
| `get_system_info` | - | dict | Get system hardware info |
| `get_current_stats` | - | dict | Get CPU/RAM/disk usage |
| `get_server_statuses` | - | list | Get local server statuses |
| `register` | - | bool | Register with controller |
| `start_heartbeat` | - | - | Start heartbeat thread |
| `_send_heartbeat` | - | - | Send heartbeat to controller |
| `start_command_polling` | - | - | Start command poll thread |
| `_poll_and_execute_commands` | - | - | Poll and execute commands |
| `execute_command` | command | - | Execute received command |
| `_report_command_result` | command_id, result | - | Report result |
| `start` | - | bool | Start client controller |
| `shutdown` | - | - | Graceful shutdown |

---

## API ENDPOINTS REFERENCE

### Authentication Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/auth/login` | None | Login user |
| POST | `/api/auth/logout` | User | Logout user |
| POST | `/api/auth/register` | None | Register new user |
| GET | `/api/auth/me` | User | Get current user |
| POST | `/api/auth/password` | User | Change password |
| PUT | `/api/auth/profile/username` | User | Update username |
| PUT | `/api/auth/profile/name` | User | Update display name |
| POST | `/api/auth/mfa/setup` | User | Setup MFA |
| POST | `/api/auth/mfa/verify` | User | Verify MFA code |
| POST | `/api/auth/mfa/disable` | User | Disable MFA |
| POST | `/api/auth/mfa/verify-login` | None | MFA login verification |

### Admin Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/admin/users` | Admin | List all users |
| POST | `/api/admin/users` | Admin | Create user |
| POST | `/api/admin/users/<id>/approve` | Admin | Approve user |
| PUT | `/api/admin/users/<id>/role` | Admin | Change role |
| POST | `/api/admin/users/<id>/password` | Admin | Reset password |
| DELETE | `/api/admin/users/<id>/mfa` | Admin | Reset MFA |
| POST | `/api/admin/users/<id>/enable` | Admin | Enable account |
| DELETE | `/api/admin/users/<id>` | Admin | Delete user |
| GET | `/api/admin/servers/pending` | Admin | List pending servers |
| POST | `/api/admin/servers/<id>/approve` | Admin | Approve server |
| DELETE | `/api/admin/servers/<id>/reject` | Admin | Reject server |

### Client/Node Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/client/register` | None | Register client node |
| POST | `/api/client/heartbeat` | API Key | Send heartbeat |
| GET | `/api/client/commands/<node_id>` | API Key | Poll for commands |
| POST | `/api/client/command-result` | API Key | Report command result |
| POST | `/api/client/disconnect` | API Key | Disconnect client |
| GET | `/api/clients` | Admin | List all clients |
| GET | `/api/nodes/available` | User | List available nodes |
| POST | `/api/clients/<node_id>/command` | Admin | Send command to client |

### Server Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/servers` | User | List servers |
| POST | `/api/servers` | User | Create server |
| POST | `/api/servers/import` | User | Import from ZIP |
| GET | `/api/servers/<id>` | User | Get server details |
| PUT | `/api/servers/<id>` | User | Update server |
| DELETE | `/api/servers/<id>` | User | Delete server |
| POST | `/api/servers/<id>/upload-jar` | User | Upload JAR |
| POST | `/api/servers/<id>/download-jar` | User | Download JAR |
| POST | `/api/servers/<id>/start` | User | Start server |
| POST | `/api/servers/<id>/stop` | User | Stop server |
| POST | `/api/servers/<id>/kill` | User | Kill server |
| POST | `/api/servers/<id>/command` | User | Send command |
| GET | `/api/servers/<id>/output` | User | Get console output |

### Server Files Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/servers/<id>/files` | User | List files |
| GET | `/api/servers/<id>/files/read` | User | Read file |
| POST | `/api/servers/<id>/files/write` | User | Write file |
| POST | `/api/servers/<id>/files/create` | User | Create file/dir |
| DELETE | `/api/servers/<id>/files/delete` | User | Delete file/dir |
| GET | `/api/servers/<id>/files/download` | User | Download file |
| POST | `/api/servers/<id>/files/upload` | User | Upload file |

### Server Management Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/servers/<id>/managed` | User | Get managed status |
| POST | `/api/servers/<id>/managed/enable` | User | Enable management |
| POST | `/api/servers/<id>/managed/update` | User | Update managed conf |
| GET | `/api/servers/<id>/eula` | User | Check EULA |
| POST | `/api/servers/<id>/eula/accept` | User | Accept EULA |
| GET | `/api/servers/<id>/properties` | User | Get server.properties |
| POST | `/api/servers/<id>/properties` | User | Update properties |

### Server Players Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/servers/<id>/players/ops` | User | Get ops |
| POST | `/api/servers/<id>/players/ops` | User | Add op |
| PUT | `/api/servers/<id>/players/ops/<uuid>` | User | Update op |
| DELETE | `/api/servers/<id>/players/ops/<uuid>` | User | Remove op |
| GET | `/api/servers/<id>/players/whitelist` | User | Get whitelist |
| POST | `/api/servers/<id>/players/whitelist` | User | Add to whitelist |
| DELETE | `/api/servers/<id>/players/whitelist/<uuid>` | User | Remove from whitelist |
| GET | `/api/servers/<id>/players/banned` | User | Get banned |
| POST | `/api/servers/<id>/players/banned` | User | Ban player |
| DELETE | `/api/servers/<id>/players/banned/<uuid>` | User | Unban player |
| GET | `/api/servers/<id>/players/playerdata` | User | Get player data |

### Server Mods/Plugins Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/servers/<id>/mods` | User | List mods/plugins |
| POST | `/api/servers/<id>/mods/upload` | User | Upload mod/plugin |
| POST | `/api/servers/<id>/mods/<type>/<file>/enable` | User | Enable mod |
| POST | `/api/servers/<id>/mods/<type>/<file>/disable` | User | Disable mod |
| DELETE | `/api/servers/<id>/mods/<type>/<file>` | User | Delete mod |

### Server Backups Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/servers/<id>/backups` | User | List backups |
| POST | `/api/servers/<id>/backups/create` | User | Create backup |
| GET | `/api/servers/<id>/backups/download` | User | Download backup |
| DELETE | `/api/servers/<id>/backups/delete` | User | Delete backup |
| POST | `/api/servers/<id>/backups/restore` | User | Restore backup |
| GET | `/api/servers/<id>/backups/schedule` | User | Get schedule |
| POST | `/api/servers/<id>/backups/schedule` | User | Set schedule |
| DELETE | `/api/servers/<id>/backups/schedule` | User | Delete schedule |

### Server Tasks Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/servers/<id>/tasks` | User | List tasks |
| POST | `/api/servers/<id>/tasks` | User | Create task |
| PUT | `/api/servers/<id>/tasks/<task_id>` | User | Update task |
| DELETE | `/api/servers/<id>/tasks/<task_id>` | User | Delete task |

### Utility Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/server-types` | User | Get server types |
| GET | `/api/server-types/<type>/versions` | User | Get versions |
| GET | `/api/server-engines` | User | Get engines |
| GET | `/api/server-engines/<engine>/versions` | User | Get engine versions |
| GET | `/api/default-server-path` | User | Get default path |
| GET | `/api/stats/current` | User | Get current stats |
| GET | `/api/stats/history` | User | Get stats history |
| GET | `/api/settings/branding` | None | Get branding |
| POST | `/api/settings/branding` | Admin | Update branding |
| GET | `/api/settings/app` | Admin | Get app settings |
| POST | `/api/settings/app` | Admin | Update app settings |

---

## COMMAND TYPES (CLIENT-SERVER PARITY)

### ⚠️ CRITICAL: Command Synchronization

**When adding a new command type, you MUST update BOTH:**
1. `server.py` - ClientManager.add_command() and API endpoint
2. `server_client.py` - ClientController.execute_command()

### Current Command Types

| Command | Central Handler | Client Handler | Description |
|---------|-----------------|----------------|-------------|
| `START` | ✅ api_send_command_to_client | ✅ execute_command | Start a server |
| `STOP` | ✅ api_send_command_to_client | ✅ execute_command | Stop a server |
| `RESTART` | ✅ api_send_command_to_client | ✅ execute_command | Restart a server |
| `KILL` | ✅ api_send_command_to_client | ✅ execute_command | Force kill server |
| `COMMAND` | ✅ api_send_command_to_client | ✅ execute_command | Send console command |
| `CREATE_SERVER` | ✅ create_server endpoint | ✅ execute_command | Create new server |
| `BACKUP` | ✅ api_send_command_to_client | ⚠️ Not implemented | Trigger backup |

### Command Structure

```python
# Command sent from central to client
{
    "id": "cmd-uuid",          # Unique command ID
    "node_id": "node-1",       # Target node
    "action": "START",         # Command type
    "server_id": "srv-uuid",   # Target server
    "params": {},              # Additional parameters
    "timestamp": "ISO8601",    # When queued
    "status": "pending"        # pending/delivered/completed/failed
}

# Result from client to central
{
    "node_id": "node-1",
    "command_id": "cmd-uuid",
    "timestamp": "ISO8601",
    "result": {
        "success": true,
        "message": "Server started",
        "server_id": "srv-uuid"  # For CREATE_SERVER
    }
}
```

### Adding New Commands

```python
# 1. In server.py - ensure central can queue the command
# ClientManager.add_command() already handles any action string

# 2. In server_client.py - add handler in execute_command()
def execute_command(self, command):
    # ... existing code ...
    
    elif action == 'NEW_COMMAND':
        # Implement handler
        result = {'success': True, 'message': 'Done'}
    
    # ... rest of code ...
```

---

## DEVELOPMENT RULES

### Rule 1: Language Consistency

```
✅ ALLOWED:
- Python 3.10+ for all backend logic
- HTML5 for markup
- CSS3 for styling (no preprocessors)
- Vanilla JavaScript ES6+ (no frameworks)
- Nginx for reverse proxy

❌ NOT ALLOWED:
- Node.js/npm for backend
- React/Vue/Angular for frontend
- TypeScript
- SASS/LESS
- External CSS frameworks (Bootstrap, Tailwind)
```

### Rule 2: Dependency Management

**ALWAYS update requirements.txt when adding Python dependencies:**

```bash
# After adding a new import
pip freeze | grep -i <package_name> >> requirements.txt
```

**Current requirements.txt structure:**
```
# Category comment
package>=minimum.version
```

### Rule 3: Client-Server Parity

**When modifying core logic that affects both central and client:**

1. **Check both files:** `server.py` AND `server_client.py`
2. **Update command handlers:** If adding new command type
3. **Update imports:** Both files must have required libraries
4. **Test both modes:** Run central, run client, verify communication

### Rule 4: API Consistency

**All API endpoints must:**
1. Use proper HTTP methods (GET/POST/PUT/DELETE)
2. Return JSON responses
3. Use appropriate decorators (@login_required, @admin_required)
4. Handle errors gracefully
5. Return consistent response format:

```python
# Success response
return jsonify({'success': True, 'data': data})

# Error response
return jsonify({'error': 'Error message'}), status_code
```

### Rule 5: Configuration Files

**All persistent data uses JSON files:**
- `config.json` - Server configurations
- `users.json` - User accounts
- `settings.json` - App settings
- `clients.json` - Registered client nodes
- `commands.json` - Command queue
- `stats.json` - System statistics
- `backup_schedules.json` - Backup schedules
- `task_schedules.json` - Task schedules

**File operations must:**
1. Use thread-safe locks when appropriate
2. Handle file not found gracefully
3. Create files if they don't exist

### Rule 6: Security

1. **Authentication:** All sensitive endpoints require @login_required
2. **Authorization:** Admin endpoints require @admin_required
3. **Path traversal:** Use is_safe_path() for file operations
4. **Input validation:** Validate all user input
5. **API keys:** Client nodes use unique API keys

### Rule 7: WebSocket Events

**Socket.IO events for real-time updates:**

| Event | Direction | Description |
|-------|-----------|-------------|
| `connect` | Client→Server | Client connected |
| `disconnect` | Client→Server | Client disconnected |
| `join` | Client→Server | Join server room |
| `leave` | Client→Server | Leave server room |
| `server_output` | Server→Client | Console output |
| `server_status` | Server→Client | Status change |

---

## REQUIREMENTS MANAGEMENT

### Current requirements.txt

```
# MServerController - Python Dependencies

# Web framework
Flask>=3.0.0
Flask-SocketIO>=5.3.6
python-socketio>=5.10.0
python-engineio>=4.8.0

# WebSocket support
gevent>=23.9.0
gevent-websocket>=0.10.1

# Rate limiting
Flask-Limiter>=3.5.0

# File upload security
Werkzeug>=3.0.0

# HTTP requests for JAR downloads and client communication
requests>=2.31.0

# MFA/TOTP support
pyotp>=2.9.0
qrcode[pil]>=7.4.2

# Task scheduling for automated backups
APScheduler>=3.10.0

# WSGI server for production
gunicorn>=21.2.0
eventlet>=0.33.3

# System monitoring (for stats and client mode)
psutil>=5.9.0
```

### Adding New Dependencies

```bash
# 1. Install the package
pip install <package_name>

# 2. Add to requirements.txt with minimum version
echo "<package_name>>=<version>" >> requirements.txt

# 3. Add comment explaining purpose
# Example:
# System monitoring
psutil>=5.9.0
```

### install.sh Integration

The `install.sh` script automatically installs all requirements:

```bash
pip install -r requirements.txt
```

**Ensure:**
1. All imports in server.py have corresponding entries in requirements.txt
2. All imports in server_client.py have corresponding entries in requirements.txt
3. Version numbers are compatible

---

## CHANGE CHECKLIST

### Before Making Any Change

- [ ] Read this development guide
- [ ] Identify affected files (server.py, server_client.py, frontend)
- [ ] Check if change affects client-server communication
- [ ] Check if change requires new dependencies

### After Making Changes

- [ ] Update requirements.txt if new dependencies added
- [ ] Update both server.py AND server_client.py if command changed
- [ ] Test in central mode
- [ ] Test in client mode (if applicable)
- [ ] Update this guide if:
  - [ ] New class added
  - [ ] New method added
  - [ ] New API endpoint added
  - [ ] New command type added
  - [ ] New dependency added
- [ ] Run basic functionality test

### Critical Change Types

| Change Type | Files to Update | Guide Section |
|-------------|-----------------|---------------|
| New API endpoint | server.py | API Endpoints Reference |
| New command type | server.py, server_client.py | Command Types |
| New class | server.py or server_client.py | Class Reference |
| New dependency | requirements.txt | Requirements Management |
| New file type | File Structure section | File Structure |
| Architecture change | Multiple sections | Core Architecture |

---

## QUICK REFERENCE

### Starting Development

```bash
# 1. Activate virtual environment
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run central mode
python server.py --mode central

# 4. (Optional) Run client mode in another terminal
python server.py --mode client --controller http://localhost:3000 --node-id dev-node
```

### Common Tasks

```bash
# Add new dependency
pip install <package>
pip freeze | grep -i <package> >> requirements.txt

# Check for syntax errors
python -m py_compile server.py
python -m py_compile server_client.py

# Run with debug
python server.py --mode central  # Flask debug mode is enabled by default in dev
```

### File Locations

| Purpose | Location |
|---------|----------|
| Main backend | server.py |
| Client mode | server_client.py |
| Shared logic | server_core.py (future) |
| Frontend HTML | public/*.html |
| Frontend JS | public/*.js |
| Frontend CSS | public/styles.css |
| Dependencies | requirements.txt |
| Server configs | config.json |
| User data | users.json |
| App settings | settings.json |
| Client nodes | clients.json |
| Commands queue | commands.json |

---

## VERSION HISTORY

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Initial | Basic server management |
| 2.0 | 2025 | Multi-user, RBAC, MFA |
| 3.0 | 2026-01 | Distributed architecture, load balancing |

---

**This guide must be kept up-to-date with all critical changes.**

**Last Updated:** 2026-01-22
