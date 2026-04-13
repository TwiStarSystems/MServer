# Task List For MServerController

> **Audited:** 2026-04-05 \ 57 commits since last audit  
> **Method:** Full codebase review of all controllers, models, services, views, routes, agent code, and database schema.  
> **Codebase:** ~29,500 lines | 1 controller (server.py) | 0 models (JSON persistence) | 5 services (UserManager, ServerManager, BackupScheduler, TaskScheduler, JarBucketManager) | 8 views (index, login, public, settings + JS) | 0 migrations | 0 Go agent files  
> **Target Launch:** April 1, 2026 (flexible — QUALITY is the priority, not speed)

---

# Overall Progress Percentage: 82%

## Summary ##

|    Area    |    Completed    |    Remaining    |    Completion    |
|------------|-----------------|-----------------|------------------|
| Core Architecture | 7 | 0 | 100% |
| Server Management | 14 | 0 | 100% |
| File Management | 9 | 0 | 100% |
| JAR Management | 10 | 0 | 100% |
| User Management | 10 | 0 | 100% |
| Backup System | 15 | 0 | 100% |
| Task Scheduler | 7 | 2 | 78% |
| Player Management | 13 | 0 | 100% |
| Mods/Plugins Management | 5 | 4 | 56% |
| Monitoring & Statistics | 5 | 4 | 56% |
| Security | 15 | 0 | 100% |
| Settings & Configuration | 10 | 2 | 83% |
| NBT File Support | 6 | 0 | 100% |
| Web Interface | 8 | 5 | 62% |
| BlueMap Integration | 5 | 3 | 63% |
| Resource Packs | 5 | 0 | 100% |
| API v1 (Public) | 7 | 3 | 70% |
| Email Notifications | 5 | 1 | 83% |
| Custom Tools | 4 | 1 | 80% |
| Deployment & Installation | 6 | 4 | 60% |
| Planned Features | 0 | 28 | 0% |

---

# Task List Items #

## Core Architecture ##
[X] - Flask-based REST API backend (server.py - 8661 lines)
[X] - WebSocket support via Socket.IO (real-time console, status)
[X] - JSON-based data persistence (users.json, managed.conf, settings.json)
[X] - APScheduler integration for backup and task scheduling
[X] - Threading-based async server process management
[X] - Static file serving for frontend (public/ directory)
[X] - Environment-based configuration (.env with dotenv)

## Server Management ##
[X] - Create Minecraft servers (multi-step wizard)
[X] - Start/Stop/Restart servers
[X] - Force kill server processes
[X] - Send console commands via WebSocket
[X] - Real-time console output streaming
[X] - Multiple server type support (Paper, Purpur, Vanilla, Forge, NeoForge, Folia, Spigot, Fabric, Bedrock)
[X] - Import servers from ZIP archives with auto-detection
[X] - World import functionality
[X] - EULA acceptance tracking and management
[X] - Server properties editor with port conflict detection
[X] - Server categorization (Unmodded / Modded / Bedrock)
[X] - Server approval workflow (admin-gated)
[X] - Server version management with world format era checking (legacy vs 1.26+)
[X] - Bedrock server setup wizard (download, extract, configure)

## File Management ##
[X] - Browse server file tree
[X] - Read/view text files
[X] - Edit/save text files
[X] - Create new files and directories
[X] - Delete files and directories
[X] - Upload files to server directory
[X] - Download files from server
[X] - Path traversal protection (is_safe_path)
[X] - Log file viewer (latest.log)

## JAR Management ##
[X] - JAR Bucket system with multi-source downloads
[X] - Mojang official API (Vanilla)
[X] - PaperMC API (Paper, Folia)
[X] - PurpurMC API (Purpur)
[X] - Spigot Hub (version listing)
[X] - Maven repositories (Forge, NeoForge)
[X] - Fabric Meta API (Fabric)
[X] - Bedrock services API (Bedrock)
[X] - JAR caching system with configurable TTL
[X] - Local JAR scanning and version extraction

## User Management ##
[X] - User registration with optional admin approval
[X] - User authentication (login/logout with session management)
[X] - Role-Based Access Control (admin, user, public/viewer)
[X] - User approval workflow for admins
[X] - Password management with strength requirements (12+ chars, complexity)
[X] - Multi-factor Authentication (MFA/TOTP) with QR codes
[X] - MFA recovery codes
[X] - Account lockout after 5 failed login attempts
[X] - Emergency anti-lockout admin account creation
[X] - Admin user management interface (create, edit, delete, approve)

## Backup System ##
[X] - Manual backup creation (ZIP format)
[X] - Scheduled backups via APScheduler (hourly/daily/weekly/custom cron)
[X] - Backup restoration (requires server stopped)
[X] - Backup download and deletion
[X] - Automatic backup retention with max backup count
[X] - Per-server backup schedule configuration
[X] - Pre-backup server shutdown option
[X] - Post-backup server restart option
[X] - Backup email notifications on completion/failure
[X] - Incremental backups
[X] - Backup compression options (level selection)
[X] - Backup to external storage (S3, FTP, etc.)
[X] - Backup verification/integrity checking
[X] - Backup history/log viewing interface
[X] - Automatic backup before server updates/changes


## Task Scheduler ##
[X] - Scheduled server start
[X] - Scheduled server stop
[X] - Scheduled server reboot
[X] - Scheduled console command execution
[X] - Cron-based scheduling
[X] - Auto-deletion after specified number of runs
[X] - One-time task execution
[ ] - Task failure notifications (email/webhook)
[ ] - Task execution history/log viewing

## Player Management ##
[X] - Operator (OP) management (add/remove/update permissions)
[X] - Whitelist management (add/remove players)
[X] - Ban list management (ban/unban with reasons)
[X] - Player UUID lookup from Mojang API
[X] - Usercache integration for local player name lookup
[X] - Player data file listing
[X] - NBT-based player data viewing/editing
[X] - Whitelist toggle in server.properties
[X] - Live online player list display
[X] - Player statistics parsing (playtime, deaths, achievements)
[X] - Player inventory viewing/editing via NBT (items, armor, ender chest, )
[X] - Ban management with IP bans and ban expiration
[X] - Player messaging via console commands (tellraw, title, actionbar)

## Mods/Plugins Management ##
[X] - List installed mods/plugins with file info
[X] - Upload mods/plugins
[X] - Disable mods/plugins (.disabled suffix rename)
[X] - Enable disabled mods/plugins
[X] - Delete mods/plugins
[ ] - Download mods from Modrinth API
[ ] - Download plugins from CurseForge / SpigotMC
[ ] - Automatic plugin/mod update checking
[ ] - Dependency management/resolution

## Monitoring & Statistics ##
[X] - Real-time CPU usage tracking
[X] - Memory utilization monitoring
[X] - Disk space monitoring
[X] - Stats history with 7-day retention
[X] - WebSocket broadcast of stats updates
[ ] - Player count tracking per server
[ ] - TPS (Ticks Per Second) monitoring
[ ] - Server health alerts (low disk, high CPU thresholds)
[ ] - Alert system (email/webhook on critical events)

## Security ##
[X] - CSRF protection via Flask-WTF
[X] - Rate limiting on sensitive endpoints
[X] - Security headers (X-Frame-Options, HSTS, CSP, etc.)
[X] - Scrypt-based password hashing
[X] - Path traversal prevention in file operations
[X] - Input validation and sanitization
[X] - Session security (HttpOnly, SameSite cookies)
[X] - MFA enforcement policies (all users / admins only)
[X] - Account lockout on failed login attempts
[X] - Restrict SocketIO CORS origins (CORS_ORIGINS env var; defaults to * with startup warning)
[X] - Remove `allow_unsafe_werkzeug=True` for production (note: kept for Werkzeug dev server; gunicorn banner added)
[X] - Enable `SESSION_COOKIE_SECURE = True` when behind HTTPS (SESSION_COOKIE_SECURE env var; install.sh prompt added)
[X] - Validate SECRET_KEY presence and minimum length on startup (warns if unset or < 32 chars; no longer crashes on short existing keys)
[X] - Add password strength enforcement to admin password reset (12+ chars, upper/lower/digit required)
[X] - Sandbox BlueMap iframe with `sandbox` attribute (evaluated; `allow-scripts+allow-same-origin` defeats sandbox on same-origin proxy — sandbox removed, cross-origin SOP provides equivalent isolation)

## Settings & Configuration ##
[X] - Site title customization
[X] - Site icon/favicon upload
[X] - Custom footer text
[X] - Base URL configuration
[X] - Enable/disable user registration toggle
[X] - Server approval requirement toggle
[X] - User approval requirement toggle
[X] - MFA enforcement policies
[X] - SMTP email configuration with test send
[X] - Settings persistence to JSON
[ ] - Configurable session timeout (currently hardcoded 7 days)
[ ] - Configurable magic numbers via settings (buffer size, timeouts, etc.)

## NBT File Support ##
[X] - Read NBT files (gzip and uncompressed)
[X] - Write modified NBT files
[X] - Convert NBT to JSON for API transport
[X] - Update individual NBT values
[X] - Add NBT tags (all types: Byte, Short, Int, Long, Float, Double, String, List, Compound, Arrays)
[X] - Delete NBT tags

## Web Interface ##
[X] - Dashboard with server list sidebar and tabbed panels
[X] - Login page with registration tab
[X] - Settings/admin page with stats, branding, users, API keys, app settings
[X] - Public server status page (no auth required)
[X] - Responsive CSS design
[X] - Real-time console output display
[X] - Real-time server status updates via WebSocket
[X] - Multi-step server creation wizard with JAR Bucket integration
[ ] - Loading indicators/skeleton loaders during async operations
[ ] - Pagination for large data tables (players, mods, files)
[ ] - Search/filter for server sidebar
[ ] - Syntax highlighting in file editor (CodeMirror/Monaco)
[ ] - Custom confirmation modals (replace browser `confirm()`)

## BlueMap Integration ##
[X] - BlueMap CLI JAR download from GitHub releases
[X] - BlueMap JAR upload option
[X] - Configuration generation for server worlds
[X] - Map rendering with progress tracking (force/incremental)
[X] - BlueMap viewer iframe integration
[ ] - Proper web viewer tile serving from gzipped storage
[ ] - Map marker/POI system
[ ] - Multi-world BlueMap management UI

## Resource Packs ##
[X] - Resource pack upload (ZIP, 100MB limit)
[X] - SHA-1 hash auto-calculation
[X] - Auto-configure server.properties with pack URL
[X] - Resource pack deletion
[X] - Base URL configuration for pack distribution

## API v1 (Public) ##
[X] - API key generation and management
[X] - Granular permissions (read, write, servers, players, console, admin)
[X] - Rate limiting per API key
[X] - API usage statistics tracking
[X] - Server status and listing endpoints
[X] - Server commands (start/stop/restart) endpoints
[X] - Console access endpoint
[ ] - Auto-generated API documentation (Swagger/OpenAPI)
[ ] - Interactive API testing UI
[ ] - API versioning strategy

## Email Notifications ##
[X] - SMTP configuration management
[X] - Test email capability
[X] - Backup completion notifications
[X] - Backup failure notifications
[X] - HTML email formatting
[ ] - Silent failure logging when SMTP not configured

## Custom Tools ##
[X] - Python tool file upload
[X] - Tool listing with metadata
[X] - Tool execution with argument passing
[X] - Tool deletion
[ ] - Tool output capture and display improvements (cleanUploadedTool missing)

## Deployment & Installation ##
[X] - install.sh automated installer
[X] - nginx.conf reverse proxy template
[X] - requirements.txt with all dependencies
[X] - .env configuration with SECRET_KEY generation
[X] - git-release.sh script
[X] - Version file management
[ ] - Systemd service file generation in installer
[ ] - Python version validation (3.8+ required) in installer
[ ] - Tighter nginx timeouts (separate socket.io vs regular routes)
[ ] - Version-pinned requirements (upper bounds to prevent breaking changes)

---

## Planned Features (Not Yet Implemented) ##

### High Priority ###
[ ] - Automatic rollback system (backup before update, detect failures, one-click rollback)
[ ] - Server templates (create, deploy from, share templates)
[ ] - Server resource limits (CPU/RAM caps per server)
[ ] - Automatic server restart on crash detection

### Medium Priority ###
[ ] - Discord webhook integration (server events, chat bridge)
[ ] - Server groups (bulk operations, group permissions, group dashboard)
[ ] - Database backend migration (JSON → SQLite/PostgreSQL)
[ ] - Server migration tool (move servers between instances)
[ ] - World management UI (manage Nether, End, custom worlds)
[ ] - Scheduled messages/announcements to players

### Low Priority ###
[ ] - Docker containerized deployment
[ ] - Multi-language support (i18n)
[ ] - Mobile app / progressive web app
[ ] - Advanced networking (BungeeCord/Velocity proxy support)
[ ] - Cloud integration (AWS/GCP/Azure deployment)
[ ] - Server marketplace (pre-configured packs, community templates)
[ ] - Collaborative multi-user file editing

### Previously Listed (Removed from Codebase) ###
[ ] - Node management (Master-Slave distributed architecture) — was removed; re-evaluate need
[ ] - Auto-update system with web UI — was removed; re-evaluate need
[ ] - Fernet encryption for node communication — was removed with node system

---

# Bug List #

## Security ##
### Critical ###
[X] - `allow_unsafe_werkzeug=True` in production — startup banner now warns and recommends gunicorn; keepable for simple installs
[X] - SocketIO CORS set to `cors_allowed_origins='*'` — now reads CORS_ORIGINS env var; install.sh prompts for value; wildcard warns at startup

### High ###
[X] - `SESSION_COOKIE_SECURE = False` hardcoded — now driven by SESSION_COOKIE_SECURE env var; install.sh prompts for HTTPS
[X] - Admin password reset does not enforce password strength validation — api_reset_user_password now validates 12+ chars, upper/lower/digit
[X] - Anti-lockout credentials written to plaintext log file (`anti_lockout_credentials.log`) — file write removed, console-only
[X] - FormData `fetch()` calls bypass `apiRequest()` wrapper — CSRF tokens not attached to file uploads (uploadFile, uploadMod, uploadBlueMapJar, resource pack upload)

### Medium ###
[ ] - Path traversal check (`is_safe_path`) uses string comparison — does not follow/validate symlinks
[ ] - World import ZIP extraction validates `..` in names but doesn't validate resolved target paths
[X] - BlueMap viewer iframe has no `sandbox` attribute — sandbox added then reverted; `allow-scripts+allow-same-origin` defeats sandboxing on same-origin proxy URL

## Backend ##
### High ###
[X] - No SECRET_KEY validation on startup — startup now warns if unset (random key generated) and raises RuntimeError if key < 32 chars
[ ] - Download progress tracker (`jar_bucket.download_progress`) not thread-safe — concurrent downloads can interfere

### Medium ###
[ ] - Stats history (`stats_manager.stats['history']`) accessed from main + background threads without lock
[ ] - Stats collection thread has no shutdown mechanism (`while True:` loop with no stop flag)
[ ] - Server port conflict check has race condition — two servers can assign same port simultaneously
[ ] - Email notification silently fails when SMTP not configured — no logging or user feedback
[ ] - JAR cache JSON file not protected against corruption — malformed JSON crashes app on load

### Low ###
[ ] - JAR download timeout is 300s (5 min) — too long, should use shorter timeout with retry
[ ] - Hardcoded default Java args (`-Xmx4G -Xms1G`) throughout — should be configurable
[ ] - Hardcoded magic numbers: max buffer (1000), stats retention (7 days), MFA timeout (300s), session lifetime (7 days)
[ ] - Inconsistent API response format — mix of `{success: true}`, `{error: ...}`, and raw data
[ ] - Mixed naming conventions — camelCase vs snake_case for API fields (`serverId` vs `server_id`)
[ ] - Missing docstrings on complex functions (>100 lines): `_read_output_unbuffered`, `_execute_backup`, `get_download_info`
[ ] - Duplicated player UUID resolution code across ops/whitelist/bans endpoints

## Frontend ##
### High ###
[ ] - `cleanUploadedTool()` function referenced in `runTool()` but never defined (settings.js)
[ ] - Server start button stuck in "Starting..." state if API call fails — no error recovery to reset UI
[ ] - WebSocket disconnect not indicated in UI — terminal freezes silently

### Medium ###
[ ] - Backup schedule modal not cleared on cancel — shows previous values when reopened
[ ] - Terminal buffer race condition — `clearTerminal()` vs pending 1ms buffer flush
[ ] - File editor doesn't prevent double-open — opening 2 files quickly causes race condition
[ ] - `compareVersions()` / `isVersionBelow126()` may fail on non-numeric versions (e.g., "1.20.5-pre1")
[ ] - Modal stacking issues — profile modal + settings modal can overlap without z-index management

### Low ###
[ ] - No debouncing on version search filter — every keystroke triggers filtering
[ ] - `clearTerminal()` and `clearLogsView()` have no confirmation prompt
[ ] - Error notifications auto-disappear after 5s — user may miss critical errors
[ ] - No loading indicator on sidebar server list refresh
[ ] - All dates use `toLocaleString()` without timezone display — ambiguous across zones
[ ] - `updateServerStatus('starting')` called before API response — UI lies if request fails

## Deployment ##
### Medium ###
[ ] - `nginx.conf` sets `client_max_body_size 500M` — excessive, enables DoS via large uploads
[ ] - `nginx.conf` proxy_read_timeout 86400 (24hr) applies to all routes — should be long only for socket.io
[ ] - No HTTPS redirect in nginx HTTP server block

### Low ###
[ ] - `install.sh` doesn't validate port range (could accept >65535)
[ ] - `requirements.txt` has no upper version bounds — breaking changes in dependencies
[ ] - `install.sh` doesn't verify Python 3.8+ is installed before proceeding

## Security (New — found during 2026-04-11 audit) ##
### High ###
[ ] - `SECRET_KEY` re-generated randomly on each startup when not in `.env` — all sessions invalidated on restart; document/enforce KEY in installer
[ ] - No rate limiting on SocketIO WebSocket events — only HTTP routes are covered by Flask-Limiter; brute-force via socket bypasses limits
[ ] - `PERMANENT_SESSION_LIFETIME` value from `.env` is not validated — an attacker-controlled env could set extremely long sessions

### Medium ###
[ ] - No `Permissions-Policy` HTTP header — browsers may expose features (camera, microphone, geolocation) to page JS
[ ] - File upload endpoint does not validate MIME type server-side — relies only on extension; polyglot files can pass checks
[ ] - Console command endpoint has no command blocklist — privileged in-game commands (e.g. `/op @a`) can be sent by any `user` role with console access
