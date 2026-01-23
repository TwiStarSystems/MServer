# MServerController - Refactoring Architecture

## Overview
This document describes the refactoring of MServerController to support both **Central Mode** (full UI controller) and **Client Mode** (headless managed node).

## Current Status: Phase 1 Complete ✓

### ✅ Completed:
1. **Added --mode startup parameter** with argparse
   - `--mode central` (default) - Full UI controller
   - `--mode client` - Headless managed node
   - Additional parameters: `--controller`, `--node-id`, `--port`, `--host`

### 🚧 In Progress:
2. **Core Logic Extraction** (Planned)
   - Extract business logic from server.py → server_core.py
   - Create server_client.py for client mode functionality
   - Modularize Flask routes into separate concerns

## Architecture Plan

```
┌─────────────────────────────────────────────────────────────┐
│                    MServerController                        │
├─────────────────────────────────────────────────────────────┤
│  server.py (Entry Point)                                    │
│    ├─ parse_arguments()                                     │
│    ├─ run_central_mode()  → Full UI + API                   │
│    └─ run_client_mode()   → Headless + API Only             │
└─────────────────────────────────────────────────────────────┘
         │                                    │
         ▼                                    ▼
┌──────────────────────┐         ┌──────────────────────────┐
│   CENTRAL MODE       │         │    CLIENT MODE           │
│   (server.py)        │         │   (server_client.py)     │
├──────────────────────┤         ├──────────────────────────┤
│ • Flask Web UI       │         │ • No Web UI              │
│ • All API Routes     │         │ • Limited API (health)   │
│ • User Management    │         │ • Connects to Central    │
│ • Multi-node Control │         │ • Executes Commands      │
│ • Aggregated View    │         │ • Reports Status         │
└──────────────────────┘         └──────────────────────────┘
         │                                    │
         └────────────┬───────────────────────┘
                      ▼
         ┌─────────────────────────┐
         │   server_core.py        │
         │   (Shared Logic)        │
         ├─────────────────────────┤
         │ • ServerManager         │
         │ • ServerInstance        │
         │ • BackupScheduler       │
         │ • TaskScheduler         │
         │ • JarVersionManager     │
         │ • NBTEditor             │
         │ • StatsManager          │
         │ • SettingsManager       │
         │ • UserManager           │
         └─────────────────────────┘
```

## File Structure

```
MServerController/
├── server.py                 # Main entry point, mode dispatcher
├── server_core.py           # Shared business logic (IN PROGRESS)
├── server_client.py         # Client mode implementation (STUB)
├── requirements.txt         # Python dependencies
├── README.md               # User documentation
├── REFACTORING.md          # This file - architecture docs
│
├── public/                  # Static files (UI - central mode only)
│   ├── index.html
│   ├── login.html
│   ├── app.js
│   └── ...
│
├── servers/                 # Server instances
├── backups/                 # Backup storage
├── configs/                 # Configuration files
└── serverexecutables/      # JAR files repository
```

## Usage Examples

### Central Mode (Default)
```bash
# Run with UI on default port 3000
python server.py

# Run on custom port
python server.py --mode central --port 8080

# Run on specific host
python server.py --mode central --host 192.168.1.100 --port 8080
```

### Client Mode
```bash
# Connect to central controller
python server.py --mode client \
    --controller http://192.168.1.100:3000 \
    --node-id node-1

# Client on custom port
python server.py --mode client \
    --controller http://192.168.1.100:3000 \
    --node-id node-2 \
    --port 3001
```

## API Endpoints (Planned)

### Central Controller APIs
```
# Client Management
POST   /api/client/register          # Register new client node
POST   /api/client/heartbeat         # Client health check
GET    /api/client/commands/{id}     # Get pending commands
POST   /api/client/command-result    # Report command execution
GET    /api/clients                  # List all clients
GET    /api/clients/{id}/status      # Get client status

# Remote Server Control
POST   /api/remote/{node_id}/servers/{id}/start
POST   /api/remote/{node_id}/servers/{id}/stop
POST   /api/remote/{node_id}/servers/{id}/command
```

### Client APIs (Limited)
```
POST   /api/health                   # Health check
GET    /api/status                   # Node status
POST   /api/execute                  # Execute command (from controller)
```

## Communication Protocol

### Client → Controller
1. **Registration** (on startup)
   - POST /api/client/register
   - Payload: node_id, hostname, os, cpu, memory, disk

2. **Heartbeat** (every 30s)
   - POST /api/client/heartbeat
   - Payload: node_id, timestamp, server_statuses, system_stats

3. **Log Streaming** (real-time)
   - WebSocket: /ws/client/{node_id}/logs

### Controller → Client
1. **Commands** (poll-based or webhook)
   - Client polls: GET /api/client/commands/{node_id}
   - Or Controller pushes: POST {client_url}/api/execute

2. **Configuration Updates**
   - POST {client_url}/api/config

## Next Steps

### Phase 2: Core Logic Extraction
- [ ] Move ServerManager to server_core.py
- [ ] Move ServerInstance to server_core.py
- [ ] Move all manager classes to server_core.py
- [ ] Update imports in server.py
- [ ] Test central mode still works

### Phase 3: Client Mode Implementation
- [ ] Implement ClientController.register()
- [ ] Implement heartbeat mechanism
- [ ] Implement command polling
- [ ] Implement command execution
- [ ] Test client-controller communication

### Phase 4: Central Controller Enhancement
- [ ] Add client management UI
- [ ] Add remote server control APIs
- [ ] Add aggregated dashboard
- [ ] Add client assignment for servers
- [ ] Add command queue system

### Phase 5: Testing & Polish
- [ ] End-to-end testing
- [ ] Error handling & reconnection logic
- [ ] Documentation updates
- [ ] Installation scripts for both modes

## Benefits

### For Users:
- Deploy lightweight clients on remote servers
- Centralized management of distributed servers
- Single UI to control all Minecraft servers
- Automatic failover capabilities

### For Development:
- Cleaner separation of concerns
- Easier to test individual components
- Reusable core logic
- Foundation for clustering/HA features

## Configuration Examples

### Central Mode Config
```json
{
  "mode": "central",
  "port": 3000,
  "clients": {
    "node-1": {
      "url": "http://192.168.1.101:3000",
      "status": "online",
      "last_heartbeat": "2026-01-22T10:30:00Z"
    }
  }
}
```

### Client Mode Config
```json
{
  "mode": "client",
  "node_id": "node-1",
  "controller": "http://192.168.1.100:3000",
  "port": 3000,
  "api_key": "secret-key-here"
}
```

## Security Considerations

1. **Authentication**: Clients must authenticate with controller using API keys
2. **Encryption**: All client-controller communication over HTTPS
3. **Authorization**: Controller validates client permissions for each command
4. **Rate Limiting**: Prevent abuse of remote command execution
5. **Audit Log**: Track all remote operations

---

**Last Updated**: January 22, 2026
**Status**: Phase 1 Complete, Phase 2 In Progress
