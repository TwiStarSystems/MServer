# Distributed Server Deployment Guide

## Overview

MServerController now supports creating Minecraft servers on multiple nodes with intelligent load balancing, similar to how Pterodactyl manages distributed panels. This allows you to:

- Deploy servers on the master controller or any connected slave node
- Automatically balance load across multiple machines
- Monitor resource usage per node
- Scale horizontally by adding more slave nodes
- **Secure communication with SSL/TLS and payload encryption**

## Security

Master-Slave communication supports multiple security layers:

- **SSL/TLS (HTTPS)** - Encrypts transport layer
- **Payload Encryption** - Encrypts data with Fernet symmetric encryption
- **API Key Authentication** - Each slave has unique API key

For detailed security setup, see **[SECURITY.md](SECURITY.md)**

Quick start with encryption:
```bash
# Master with SSL + Encryption
export ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
python server.py --mode central --ssl-cert cert.pem --ssl-key key.pem

# Slave with SSL + Encryption
python server.py --mode client \
  --controller https://master-ip:3000 \
  --node-id slave-01 \
  --encryption-key "YOUR_ENCRYPTION_KEY"
```

## Architecture

```
┌─────────────────────────────────────┐
│   Master Controller (Node)          │
│   - Web UI/API                       │
│   - Load Balancer                    │
│   - Can host servers locally         │
└─────────────┬───────────────────────┘
              │
    ┌─────────┴─────────┬──────────────┐
    │                   │              │
┌───▼─────┐      ┌──────▼───┐   ┌─────▼─────┐
│ Slave   │      │ Slave    │   │ Slave     │
│ Node 1  │      │ Node 2   │   │ Node 3    │
│         │      │          │   │           │
│ Servers │      │ Servers  │   │ Servers   │
└─────────┘      └──────────┘   └───────────┘
```

## Node Selection Options

When creating a server, you can specify a target node:

1. **`central`** - Deploy on the master controller itself
2. **`auto`** - Automatically select the best node based on load
3. **`<node_id>`** - Deploy on a specific slave node (e.g., `node-1`)

## Load Balancing Algorithm

The load balancing system calculates a score for each node based on:

- **CPU Usage (40% weight)** - Current CPU utilization
- **Memory Usage (40% weight)** - Current RAM utilization  
- **Server Count (20% weight)** - Number of servers already running

**Lower scores are better.** The node with the lowest score is recommended for deployment.

### Example Calculation

```
Node A: 30% CPU, 40% RAM, 5 servers
Score = (0.30 * 0.4) + (0.40 * 0.4) + (5 * 0.2) = 0.12 + 0.16 + 1.0 = 1.28

Node B: 50% CPU, 60% RAM, 2 servers  
Score = (0.50 * 0.4) + (0.60 * 0.4) + (2 * 0.2) = 0.20 + 0.24 + 0.4 = 0.84

Node C: 20% CPU, 30% RAM, 8 servers
Score = (0.20 * 0.4) + (0.30 * 0.4) + (8 * 0.2) = 0.08 + 0.12 + 1.6 = 1.80

Recommendation: Node B (lowest score)
```

## API Usage

### 1. Get Available Nodes

Get a list of all online nodes with resource statistics:

```bash
curl -X GET http://localhost:3000/api/nodes/available \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  | jq
```

**Response:**
```json
{
  "nodes": [
    {
      "node_id": "central",
      "node_type": "master",
      "name": "Master Controller",
      "status": "online",
      "servers": 3,
      "stats": {
        "cpu_percent": 25.5,
        "memory_percent": 42.1,
        "disk_percent": 35.2
      },
      "load_score": 0.87,
      "recommended": false
    },
    {
      "node_id": "node-1",
      "node_type": "slave",
      "name": "production-server-01",
      "status": "online",
      "servers": 1,
      "stats": {
        "cpu_percent": 15.2,
        "memory_percent": 28.5,
        "disk_percent": 22.1
      },
      "system_info": {
        "hostname": "production-server-01",
        "platform": "Linux",
        "cpu_count": 8,
        "total_memory_gb": 32
      },
      "load_score": 0.38,
      "recommended": true
    }
  ]
}
```

### 2. Create Server on Specific Node

```bash
curl -X POST http://localhost:3000/api/servers \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -d '{
    "name": "Survival Server",
    "serverPath": "/servers/survival",
    "executable": "paper.jar",
    "javaArgs": "-Xmx4G -Xms2G",
    "serverType": "paper",
    "version": "1.21",
    "category": "survival",
    "targetNode": "node-1"
  }'
```

**Response:**
```json
{
  "success": true,
  "serverId": "pending",
  "node": "node-1",
  "commandId": "cmd-abc123",
  "message": "Server creation queued on node node-1",
  "pending": true
}
```

### 3. Create Server with Auto Load Balancing

```bash
curl -X POST http://localhost:3000/api/servers \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -d '{
    "name": "Creative Server",
    "serverPath": "/servers/creative",
    "executable": "paper.jar",
    "javaArgs": "-Xmx2G -Xms1G",
    "serverType": "paper",
    "version": "1.21",
    "category": "creative",
    "targetNode": "auto"
  }'
```

The system will automatically select the node with the lowest load score.

### 4. Create Server on Central Controller

```bash
curl -X POST http://localhost:3000/api/servers \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -d '{
    "name": "Hub Server",
    "serverPath": "/servers/hub",
    "executable": "paper.jar",
    "javaArgs": "-Xmx1G -Xms512M",
    "serverType": "paper",
    "version": "1.21",
    "category": "hub",
    "targetNode": "central"
  }'
```

**Response:**
```json
{
  "success": true,
  "serverId": "server-abc123",
  "node": "central"
}
```

## Web UI Integration

### Node Selection Dropdown

When implementing the UI for server creation, fetch available nodes:

```javascript
// Fetch available nodes when page loads
async function loadAvailableNodes() {
  const response = await fetch('/api/nodes/available');
  const data = await response.json();
  
  const nodeSelect = document.getElementById('nodeSelect');
  
  // Add "Auto (Recommended)" option
  const autoOption = document.createElement('option');
  autoOption.value = 'auto';
  autoOption.textContent = 'Auto (Recommended)';
  nodeSelect.appendChild(autoOption);
  
  // Add each node
  data.nodes.forEach(node => {
    const option = document.createElement('option');
    option.value = node.node_id;
    
    const label = `${node.name} (${node.servers} servers, ${node.stats.cpu_percent.toFixed(1)}% CPU)`;
    option.textContent = label;
    
    if (node.recommended) {
      option.textContent += ' ⭐';
    }
    
    nodeSelect.appendChild(option);
  });
}

// Include targetNode in server creation request
async function createServer(formData) {
  const response = await fetch('/api/servers', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      name: formData.name,
      serverPath: formData.serverPath,
      executable: formData.executable,
      javaArgs: formData.javaArgs,
      serverType: formData.serverType,
      version: formData.version,
      category: formData.category,
      targetNode: formData.targetNode || 'auto'
    })
  });
  
  return await response.json();
}
```

## Command Queue System

When a server is created on a remote client, the central controller:

1. **Queues a CREATE_SERVER command** with all server parameters
2. **Client polls for commands** every 5 seconds
3. **Client executes CREATE_SERVER** using its local ServerManager
4. **Client reports result** back to the controller with the new server ID

### Command Structure

```json
{
  "id": "cmd-abc123",
  "node_id": "node-1",
  "action": "CREATE_SERVER",
  "server_id": "pending",
  "params": {
    "name": "Survival Server",
    "server_path": "/servers/survival",
    "executable": "paper.jar",
    "java_args": "-Xmx4G -Xms2G",
    "server_type": "paper",
    "version": "1.21",
    "owner": "admin",
    "approved": true,
    "category": "survival"
  },
  "timestamp": "2024-01-15T10:30:00",
  "status": "pending"
}
```

## Monitoring & Management

### Check Node Status

All nodes report their status via heartbeat:

```bash
curl -X GET http://localhost:3000/api/clients \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  | jq
```

### View Command Queue

Admins can check pending/completed commands:

```bash
# Commands are stored in commands.json on the central controller
cat commands.json | jq
```

## Best Practices

1. **Set up monitoring** - Monitor CPU/RAM on all nodes to ensure accurate load balancing
2. **Use descriptive node names** - Set meaningful hostnames for easy identification
3. **Test auto mode** - Verify that auto selection chooses appropriate nodes
4. **Consider geographic distribution** - Deploy nodes close to your player base
5. **Plan for failover** - If a client goes offline, servers on it become unavailable

## Scaling Up

To add more capacity:

1. **Deploy a new machine** with adequate resources
2. **Install MServerController** on the new machine
3. **Start in client mode**: `python server.py --mode client --controller http://central:3000 --node-id node-4`
4. **Verify registration** on the central controller
5. **New node appears automatically** in deployment options

## Troubleshooting

### Server Creation Fails

- Check that the target node is online: `GET /api/clients`
- Verify the node has sufficient disk space
- Check client logs for server creation errors

### Load Balancing Not Working

- Ensure all nodes are reporting stats via heartbeat
- Check that `stats.json` is being updated on each node
- Verify clients are polling regularly (every 5s)

### Node Shows as Offline

- Check network connectivity between client and controller
- Verify the controller URL is correct in client startup
- Check that the API key is valid
- Review client logs for heartbeat errors

## Security Considerations

- **API Keys**: Each client receives a unique API key at registration
- **Admin Only**: Only admins can send commands to clients or view client list
- **Authentication**: All client endpoints require authentication
- **Network**: Use HTTPS/TLS in production environments
- **Firewall**: Restrict controller port to known client IPs

## Future Enhancements

Potential improvements for the distributed system:

- **Resource limits per node** - Set max servers/CPU/RAM per node
- **Server migration** - Move running servers between nodes
- **Health checks** - Automatic failover if node becomes unhealthy
- **Web UI for node management** - Visual dashboard for monitoring nodes
- **Load balancing policies** - Configurable algorithms (round-robin, least-connections, etc.)
- **Node groups/tags** - Organize nodes by region, purpose, or tier

---

**🎉 You now have a distributed Minecraft server controller with intelligent load balancing!**
