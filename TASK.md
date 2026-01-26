# MServerController - Feature Tracking

**Last Updated:** 2026-01-26
**Version:** 3.2

---

## Legend

- ✅ **Completed** - Feature is fully implemented and tested
- 🚧 **In Progress** - Currently being developed
- 📋 **Planned** - Scheduled for future development
- 💡 **Proposed** - Under consideration
- ❌ **Blocked** - Development is blocked by dependencies or issues

---

## Current Features

### 1. Core Architecture ✅

- [x] Central Controller mode (Master)
- [x] Client mode (Slave/Node)
- [x] Master-Slave distributed architecture
- [x] Heartbeat system (10s intervals)
- [x] Command polling system (10s normal, 30s orphaned)
- [x] Orphaned state handling (automatic reconnection)
- [x] Client offline detection (10s timeout)
- [x] Flask-based REST API
- [x] WebSocket support (Socket.IO)
- [x] JSON-based data persistence

### 2. Server Management ✅

- [x] Create Minecraft servers
- [x] Start/Stop/Restart servers
- [x] Force kill servers
- [x] Send console commands
- [x] Real-time console output (WebSocket)
- [x] Multiple server type support:
  - [x] Paper
  - [x] Purpur
  - [x] Vanilla
  - [x] Forge
  - [x] NeoForge
  - [x] Folia
  - [x] Spigot
- [x] Import servers from ZIP
- [x] EULA management
- [x] Server properties editor
- [x] Server categorization
- [x] Server approval workflow

### 3. File Management ✅

- [x] Browse server files
- [x] Read text files
- [x] Edit text files
- [x] Create files and directories
- [x] Delete files and directories
- [x] Upload files
- [x] Download files
- [x] Path traversal protection

### 4. JAR Management ✅

- [x] Pre-download server JARs
- [x] Automatic JAR downloads from APIs:
  - [x] Paper API
  - [x] Purpur API
  - [x] Vanilla (Mojang)
  - [x] Forge
  - [x] NeoForge
  - [x] Folia
  - [x] Spigot
- [x] Version selection per server type
- [x] Upload custom JARs
- [x] Local JAR scanning and caching

### 5. User Management ✅

- [x] User registration
- [x] User authentication (login/logout)
- [x] Role-Based Access Control (RBAC):
  - [x] Admin role
  - [x] User role
  - [x] Viewer role
- [x] User approval workflow
- [x] Password management
- [x] Username and display name management
- [x] Multi-factor Authentication (MFA/TOTP)
- [x] MFA recovery codes
- [x] Account enable/disable
- [x] Admin user management interface

### 6. Node Management ✅

- [x] Node registration
- [x] Node heartbeat monitoring
- [x] Node health scoring (0-100%):
  - [x] CPU usage
  - [x] Memory usage
  - [x] Disk usage
- [x] Online/offline status (10s timeout)
- [x] Node encryption configuration
- [x] Encryption key visibility toggle
- [x] Node Manager UI (Settings tab)
- [x] Load balancing for server deployment
- [x] Node command queue system
- [x] Node statistics collection

### 7. Backup System ✅

- [x] Manual backup creation
- [x] Scheduled backups (cron-based)
- [x] Backup restoration
- [x] Backup retention policies
- [x] Automatic old backup cleanup
- [x] Backup download
- [x] Backup deletion
- [x] Per-server backup schedules

### 8. Task Scheduler ✅

- [x] Scheduled server start
- [x] Scheduled server stop
- [x] Scheduled server reboot
- [x] Scheduled console commands
- [x] Cron-based scheduling
- [x] Task management (create/update/delete)
- [x] Per-server task lists

### 9. Player Management ✅

- [x] Operator (OP) management:
  - [x] Add operators
  - [x] Remove operators
  - [x] Update operator permissions
- [x] Whitelist management:
  - [x] Add to whitelist
  - [x] Remove from whitelist
- [x] Ban management:
  - [x] Ban players
  - [x] Unban players
- [x] Player data viewing (NBT files)

### 10. Mods/Plugins Management ✅

- [x] List installed mods/plugins
- [x] Upload mods/plugins
- [x] Enable mods
- [x] Disable mods
- [x] Delete mods/plugins

### 11. Monitoring & Statistics ✅

- [x] System resource monitoring:
  - [x] CPU usage
  - [x] Memory usage
  - [x] Disk usage
- [x] Historical data collection (24 hours)
- [x] Stats cleanup (remove old data)
- [x] Real-time stats updates
- [x] Per-node statistics

### 12. Security ✅

- [x] Fernet encryption for client-server communication
- [x] Automatic encryption key generation (Master)
- [x] Encryption key sharing (Slave setup)
- [x] API key authentication for nodes
- [x] Session-based authentication for users
- [x] Rate limiting on API endpoints
- [x] Path traversal protection
- [x] Input validation

### 13. Settings & Configuration ✅

- [x] Custom branding:
  - [x] App name
  - [x] Logo URL
  - [x] Primary color
- [x] Application settings
- [x] Settings UI interface

### 14. NBT File Support ✅

- [x] Read NBT files
- [x] Write NBT files
- [x] Convert NBT to JSON
- [x] Update NBT values
- [x] Add NBT tags
- [x] Delete NBT tags

### 15. Web Interface ✅

- [x] Dashboard (server overview)
- [x] Login page
- [x] Settings page
- [x] Public server list page
- [x] Responsive design
- [x] Real-time console output
- [x] Real-time server status updates

### 16. Auto-Update System ✅

- [x] Version tracking and display
- [x] Check for updates from GitHub
- [x] Compare current vs latest version
- [x] Display changelog with commit history
- [x] One-click update installation
- [x] Master-Slave update coordination
- [x] Non-interactive update mode
- [x] Preserve all configurations during update
- [x] Preserve encryption keys during update
- [x] Auto-reconnection after update
- [x] Web UI in Settings → Tools tab
- [x] Background update execution
- [x] Automatic service restart
- [x] GitHub Actions workflow for releases
- [x] Semantic versioning support

### 17. GitHub Release Automation ✅

- [x] Automatic release creation on version tags
- [x] Auto-generated changelog from commits
- [x] Installation instructions in releases
- [x] Manual and automatic trigger options
- [x] Release notes formatting
- [x] Version comparison links

---

## Planned Features

### High Priority 📋

- [ ] **Automatic Rollback System**
  - [ ] Backup before update
  - [ ] Auto-detect failed updates
  - [ ] One-click rollback to previous version
  - [ ] Rollback capability in web UI

- [ ] **Enhanced Backup Features**
  - [ ] Incremental backups
  - [ ] Backup compression options
  - [ ] Backup to external storage (S3, FTP, etc.)
  - [ ] Backup verification

- [ ] **Server Templates**
  - [ ] Create server templates
  - [ ] Deploy servers from templates
  - [ ] Template library
  - [ ] Share templates between nodes

- [ ] **Performance Optimization**
  - [ ] Server resource limits (CPU/RAM)
  - [ ] Automatic server restart on crash
  - [ ] Memory leak detection
  - [ ] Performance profiling

### Medium Priority 📋

- [ ] **Advanced Monitoring**
  - [ ] Player count tracking
  - [ ] TPS (Ticks Per Second) monitoring
  - [ ] Plugin/mod crash detection
  - [ ] Alert system (email, webhook)

- [ ] **Plugin/Mod Management Enhancements**
  - [ ] Download from Modrinth
  - [ ] Download from CurseForge
  - [ ] Download from SpigotMC
  - [ ] Automatic plugin updates
  - [ ] Dependency management

- [ ] **Backup Command Client-Side** ❌
  - [ ] Implement BACKUP command in server_client.py
  - [ ] Remote backup triggering
  - Note: Currently blocked - not implemented in client

- [ ] **Server Groups**
  - [ ] Group servers together
  - [ ] Bulk operations on groups
  - [ ] Group-based permissions
  - [ ] Group monitoring dashboard

- [ ] **Database Backend** 💡
  - [ ] Migrate from JSON to SQLite/PostgreSQL
  - [ ] Improved query performance
  - [ ] Better data integrity
  - [ ] Transaction support

### Low Priority 📋

- [ ] **Docker Support**
  - [ ] Containerized deployment
  - [ ] Docker Compose configuration
  - [ ] Container orchestration

- [ ] **API Documentation**
  - [ ] Auto-generated API docs
  - [ ] Interactive API testing (Swagger/OpenAPI)
  - [ ] API versioning

- [ ] **Mobile App**
  - [ ] Mobile-responsive web interface improvements
  - [ ] Native mobile app (iOS/Android)
  - [ ] Push notifications

- [ ] **Multi-Language Support**
  - [ ] Internationalization (i18n)
  - [ ] Translation management
  - [ ] Language selection in UI

---

## Proposed Features

### Under Consideration 💡

- [ ] **Server Migration Tool**
  - Move servers between nodes
  - Zero-downtime migration
  - Automatic configuration updates

- [ ] **Advanced Networking**
  - Bungeecord/Velocity proxy support
  - Automatic proxy configuration
  - Cross-server communication

- [ ] **Cloud Integration**
  - AWS deployment
  - Google Cloud deployment
  - Azure deployment
  - Cloud resource management

- [ ] **Advanced Analytics**
  - Player behavior analytics
  - Server performance trends
  - Cost analysis (cloud hosting)
  - Usage reports

- [ ] **Server Marketplace**
  - Pre-configured server packs
  - Community templates
  - One-click deployment

- [ ] **Webhook Integration**
  - Discord webhooks
  - Slack webhooks
  - Custom webhook support
  - Event-based notifications

---

## Completed Milestones

### Version 3.2 (2026-01-26) ✅
- Auto-update system with web UI
- GitHub Actions workflow for automatic releases
- Version tracking and changelog display
- Master-Slave update coordination
- Non-interactive update mode
- Semantic versioning support
- One-click updates from Settings page

### Version 3.1 (2026-01-23) ✅
- Polling rate standardization (10s normal, 30s orphaned)
- Orphaned state handling
- Node Manager UI
- Encryption key flow improvements

### Version 3.0 (2026-01) ✅
- Distributed architecture
- Client-server encryption
- Load balancing
- Node health scoring

### Version 2.0 (2025) ✅
- Multi-user support
- RBAC implementation
- MFA/TOTP support

### Version 1.0 (Initial) ✅
- Basic server management
- Single-user mode
- Core functionality

---

## Notes

- Add new planned features to this file as they are identified
- Update feature status as development progresses
- Reference the [DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md) for implementation details
- When implementing a feature, move it from Planned to Current and mark as ✅

---

**For contributors:** Please update this file when adding or completing features!
