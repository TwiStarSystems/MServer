# Distributed Deployment API Reference

## Overview

This document describes the API endpoints for distributed server deployment and node management.

## Authentication

All endpoints require authentication via session cookies:
```
Cookie: user_id=<user_id>
```

Admin endpoints additionally require admin role.

---

## Endpoints

### 1. Get Available Nodes

Get a list of all available nodes (central + online clients) with resource statistics and load scores.

**Endpoint:** `GET /api/nodes/available`

**Authentication:** Required (any logged-in user)

**Request:**
```bash
curl -X GET http://localhost:3000/api/nodes/available \
  -H "Cookie: user_id=abc123"
```

**Response:** `200 OK`
```json
{
  "nodes": [
    {
      "node_id": "central",
      "node_type": "central",
      "name": "Central Controller",
      "status": "online",
      "servers": 3,
      "stats": {
        "cpu_percent": 25.5,
        "memory_percent": 42.1,
        "disk_percent": 35.2,
        "uptime": 86400
      },
      "load_score": 0.87,
      "recommended": false
    },
    {
      "node_id": "node-1",
      "node_type": "client",
      "name": "production-server-01",
      "status": "online",
      "servers": 1,
      "stats": {
        "cpu_percent": 15.2,
        "memory_percent": 28.5,
        "disk_percent": 22.1,
        "uptime": 43200
      },
      "system_info": {
        "hostname": "production-server-01",
        "platform": "Linux",
        "platform_version": "5.15.0-generic",
        "cpu_count": 8,
        "total_memory_gb": 32.0
      },
      "load_score": 0.38,
      "recommended": true
    }
  ]
}
```

**Fields:**
- `node_id` - Unique identifier ("central" or client node ID)
- `node_type` - "central" or "client"
- `name` - Display name (hostname for clients)
- `status` - "online" or "offline"
- `servers` - Number of servers running on this node
- `stats` - Current resource usage statistics
- `load_score` - Calculated load score (lower is better)
- `recommended` - True if this is the best node for deployment
- `system_info` - Hardware/OS information (clients only)

**Load Score Calculation:**
```
load_score = (cpu_percent * 0.4) + (memory_percent * 0.4) + (server_count * 0.2)
```

---

### 2. Create Server (Modified)

Create a new server on a specific node or let the system auto-select.

**Endpoint:** `POST /api/servers`

**Authentication:** Required

**Request:**
```bash
curl -X POST http://localhost:3000/api/servers \
  -H "Content-Type: application/json" \
  -H "Cookie: user_id=abc123" \
  -d '{
    "name": "Survival Server",
    "serverPath": "/servers/survival",
    "executable": "paper.jar",
    "javaArgs": "-Xmx4G -Xms2G",
    "serverType": "paper",
    "version": "1.21",
    "category": "survival",
    "targetNode": "auto"
  }'
```

**Parameters:**
- `name` (string, required) - Server display name
- `serverPath` (string, required) - Absolute path for server files
- `executable` (string, required) - Server JAR filename
- `javaArgs` (string, required) - JVM arguments
- `serverType` (string, required) - Server type (vanilla, paper, forge, etc.)
- `version` (string, optional) - Minecraft version
- `category` (string, optional) - Server category
- `downloadJar` (boolean, optional) - Auto-download JAR
- **`targetNode` (string, optional, default: "central")** - Target deployment node
  - `"central"` - Deploy on central controller
  - `"auto"` - Auto-select best node via load balancing
  - `"<node_id>"` - Deploy on specific client node

**Response (Central Deployment):** `200 OK`
```json
{
  "success": true,
  "serverId": "server-abc123",
  "node": "central"
}
```

**Response (Client Deployment):** `200 OK`
```json
{
  "success": true,
  "serverId": "pending",
  "node": "node-1",
  "commandId": "cmd-xyz789",
  "message": "Server creation queued on node node-1",
  "pending": true
}
```

**Response (Pending Approval):** `200 OK`
```json
{
  "success": true,
  "serverId": "server-abc123",
  "node": "central",
  "pendingApproval": true,
  "message": "Server created and pending admin approval"
}
```

**Error Responses:**

`404 Not Found` - Client node not found
```json
{
  "error": "Client node node-xyz not found"
}
```

`503 Service Unavailable` - Node offline
```json
{
  "error": "Client node node-1 is offline"
}
```

`503 Service Unavailable` - No available nodes
```json
{
  "error": "No available nodes for deployment"
}
```

---

### 3. Get All Clients (Admin)

Get list of all registered client nodes.

**Endpoint:** `GET /api/clients`

**Authentication:** Required (admin only)

**Request:**
```bash
curl -X GET http://localhost:3000/api/clients \
  -H "Cookie: user_id=abc123"
```

**Response:** `200 OK`
```json
{
  "clients": [
    {
      "node_id": "node-1",
      "api_key": "key-abc123...",
      "status": "online",
      "registered_at": "2024-01-15T10:30:00Z",
      "last_heartbeat": "2024-01-15T12:45:30Z",
      "system_info": {
        "hostname": "production-server-01",
        "platform": "Linux",
        "cpu_count": 8,
        "total_memory_gb": 32.0
      },
      "stats": {
        "cpu_percent": 15.2,
        "memory_percent": 28.5,
        "disk_percent": 22.1
      },
      "servers": [
        {
          "id": "server-1",
          "name": "Survival",
          "status": "running"
        }
      ]
    }
  ]
}
```

---

### 4. Send Command to Client (Admin)

Send a command to a specific client node.

**Endpoint:** `POST /api/clients/<node_id>/command`

**Authentication:** Required (admin only)

**Request:**
```bash
curl -X POST http://localhost:3000/api/clients/node-1/command \
  -H "Content-Type: application/json" \
  -H "Cookie: user_id=abc123" \
  -d '{
    "action": "START",
    "server_id": "server-123",
    "params": {}
  }'
```

**Parameters:**
- `action` (string, required) - Command action
  - `START` - Start a server
  - `STOP` - Stop a server
  - `RESTART` - Restart a server
  - `KILL` - Force kill a server
  - `COMMAND` - Send console command
  - `CREATE_SERVER` - Create a new server (internal use)
- `server_id` (string, required) - Target server ID
- `params` (object, optional) - Additional parameters
  - For `COMMAND`: `{"command": "say Hello"}`
  - For `CREATE_SERVER`: Full server config object

**Response:** `200 OK`
```json
{
  "success": true,
  "command_id": "cmd-xyz789",
  "message": "Command queued successfully"
}
```

**Error Responses:**

`404 Not Found` - Client not found
```json
{
  "error": "Client not found"
}
```

`503 Service Unavailable` - Client offline
```json
{
  "error": "Client is offline"
}
```

---

## Client-Side Endpoints

These endpoints are called by client nodes, not by users.

### 5. Register Client

Register a new client node with the central controller.

**Endpoint:** `POST /api/client/register`

**Authentication:** None (generates API key)

**Request:**
```json
{
  "node_id": "node-1",
  "system_info": {
    "hostname": "production-server-01",
    "platform": "Linux",
    "cpu_count": 8,
    "total_memory_gb": 32.0
  }
}
```

**Response:** `200 OK`
```json
{
  "success": true,
  "api_key": "key-abc123def456...",
  "node_id": "node-1",
  "message": "Client registered successfully"
}
```

---

### 6. Client Heartbeat

Send heartbeat with current status and statistics.

**Endpoint:** `POST /api/client/heartbeat`

**Authentication:** Required (API key in JSON body)

**Request:**
```json
{
  "node_id": "node-1",
  "api_key": "key-abc123...",
  "stats": {
    "cpu_percent": 15.2,
    "memory_percent": 28.5,
    "disk_percent": 22.1,
    "uptime": 43200
  },
  "servers": [
    {
      "id": "server-1",
      "name": "Survival",
      "status": "running"
    }
  ]
}
```

**Response:** `200 OK`
```json
{
  "success": true,
  "message": "Heartbeat received"
}
```

---

### 7. Poll for Commands

Get pending commands for a client node.

**Endpoint:** `GET /api/client/commands/<node_id>`

**Authentication:** Required (API key in query or headers)

**Request:**
```bash
curl "http://localhost:3000/api/client/commands/node-1?api_key=key-abc123..."
```

**Response:** `200 OK`
```json
{
  "commands": [
    {
      "id": "cmd-xyz789",
      "node_id": "node-1",
      "action": "START",
      "server_id": "server-123",
      "params": {},
      "timestamp": "2024-01-15T12:45:00Z",
      "status": "pending"
    }
  ]
}
```

**Response (No Commands):** `200 OK`
```json
{
  "commands": []
}
```

---

### 8. Report Command Result

Report the result of command execution back to controller.

**Endpoint:** `POST /api/client/command-result`

**Authentication:** Required (API key in JSON body)

**Request:**
```json
{
  "node_id": "node-1",
  "command_id": "cmd-xyz789",
  "timestamp": "2024-01-15T12:45:10Z",
  "result": {
    "success": true,
    "message": "Server started successfully",
    "server_id": "server-123"
  }
}
```

**Response:** `200 OK`
```json
{
  "success": true,
  "message": "Result received"
}
```

---

## Error Codes

| Code | Meaning | Common Causes |
|------|---------|---------------|
| 200 | OK | Request successful |
| 400 | Bad Request | Missing/invalid parameters |
| 401 | Unauthorized | Not logged in |
| 403 | Forbidden | Insufficient permissions |
| 404 | Not Found | Node/server not found |
| 503 | Service Unavailable | Node offline, no capacity |

---

## Examples

### Complete Workflow: Auto Deploy Server

```bash
# 1. Check available nodes
curl http://localhost:3000/api/nodes/available \
  -H "Cookie: user_id=abc123" | jq

# 2. Create server with auto selection
curl -X POST http://localhost:3000/api/servers \
  -H "Content-Type: application/json" \
  -H "Cookie: user_id=abc123" \
  -d '{
    "name": "PvP Arena",
    "serverPath": "/servers/pvp",
    "executable": "paper.jar",
    "javaArgs": "-Xmx3G -Xms2G",
    "serverType": "paper",
    "version": "1.21",
    "category": "minigames",
    "targetNode": "auto"
  }' | jq

# 3. Response shows which node was selected
{
  "success": true,
  "serverId": "pending",
  "node": "node-2",
  "commandId": "cmd-123",
  "message": "Server creation queued on node node-2",
  "pending": true
}

# 4. Wait for client to process (5-10 seconds)

# 5. Check if server was created (via admin API or web UI)
```

### Load Balancing in Action

```bash
# Check load scores
curl http://localhost:3000/api/nodes/available -H "Cookie: user_id=abc123" | jq '.nodes[] | {node_id, load_score, recommended}'

# Output:
{
  "node_id": "central",
  "load_score": 1.25,
  "recommended": false
}
{
  "node_id": "node-1",
  "load_score": 0.42,
  "recommended": true  # Lowest load
}
{
  "node_id": "node-2",
  "load_score": 0.88,
  "recommended": false
}

# Auto selection will choose node-1
```

---

## Integration Notes

### JavaScript/TypeScript

```typescript
interface Node {
  node_id: string;
  node_type: 'central' | 'client';
  name: string;
  status: 'online' | 'offline';
  servers: number;
  stats: {
    cpu_percent: number;
    memory_percent: number;
    disk_percent: number;
  };
  load_score: number;
  recommended: boolean;
}

async function getAvailableNodes(): Promise<Node[]> {
  const response = await fetch('/api/nodes/available');
  const data = await response.json();
  return data.nodes;
}

async function createServer(config: ServerConfig): Promise<CreateServerResponse> {
  const response = await fetch('/api/servers', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config)
  });
  return await response.json();
}
```

### Python

```python
import requests

def get_available_nodes(session):
    """Get list of available nodes with load info"""
    response = session.get('http://localhost:3000/api/nodes/available')
    return response.json()['nodes']

def create_server_auto(session, server_config):
    """Create server with automatic node selection"""
    server_config['targetNode'] = 'auto'
    response = session.post(
        'http://localhost:3000/api/servers',
        json=server_config
    )
    return response.json()
```

---

## Rate Limits

- No rate limits currently implemented
- Clients poll every 5 seconds (configurable)
- Heartbeat every 30 seconds (configurable)

## Security

- All endpoints require authentication except `/api/client/register`
- Admin endpoints restricted to admin role
- API keys are unique per client and validated on each request
- Commands are node-specific (clients can only see their own)

---

**For complete documentation, see [DISTRIBUTED_DEPLOYMENT.md](DISTRIBUTED_DEPLOYMENT.md)**
