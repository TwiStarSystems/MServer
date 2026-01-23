# Quick Start: Distributed Deployment

## 🎯 What You Can Do Now

Create Minecraft servers on multiple machines with automatic load balancing!

## Setup (5 Minutes)

### 1. Start Master Controller

On your main server:
```bash
python server.py --mode central
```

Access web UI at: `http://localhost:3000`

### 2. Start Slave Nodes

On each worker machine:
```bash
python server.py --mode client \
  --controller http://MASTER_IP:3000 \
  --node-id production-node-1
```

Replace:
- `MASTER_IP` with your master controller's IP address
- `production-node-1` with a unique identifier for this node

### 3. Verify Registration

Check that slave nodes appear as online:
```bash
curl http://localhost:3000/api/clients \
  -H "Cookie: user_id=YOUR_USER_ID"
```

Or check via web UI (admin users only).

## Creating Servers

### Option 1: Auto Load Balancing (Recommended)

Let the system pick the best node:

```bash
curl -X POST http://localhost:3000/api/servers \
  -H "Content-Type: application/json" \
  -H "Cookie: user_id=YOUR_USER_ID" \
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

### Option 2: Specific Node

Deploy on a specific node:

```bash
curl -X POST http://localhost:3000/api/servers \
  -H "Content-Type: application/json" \
  -H "Cookie: user_id=YOUR_USER_ID" \
  -d '{
    "name": "Creative Server",
    "serverPath": "/servers/creative",
    "executable": "paper.jar",
    "javaArgs": "-Xmx2G -Xms1G",
    "serverType": "paper",
    "version": "1.21",
    "category": "creative",
    "targetNode": "production-node-1"
  }'
```

### Option 3: Central Controller

Deploy locally on the central controller:

```bash
curl -X POST http://localhost:3000/api/servers \
  -H "Content-Type: application/json" \
  -H "Cookie: user_id=YOUR_USER_ID" \
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

## Check Available Nodes

See which nodes are online and their load:

```bash
curl http://localhost:3000/api/nodes/available \
  -H "Cookie: user_id=YOUR_USER_ID" \
  | jq
```

Example output:
```json
{
  "nodes": [
    {
      "node_id": "central",
      "name": "Central Controller",
      "status": "online",
      "servers": 2,
      "load_score": 0.65,
      "recommended": false,
      "stats": {
        "cpu_percent": 30.0,
        "memory_percent": 45.0
      }
    },
    {
      "node_id": "production-node-1",
      "name": "worker-01",
      "status": "online",
      "servers": 1,
      "load_score": 0.28,
      "recommended": true,
      "stats": {
        "cpu_percent": 15.0,
        "memory_percent": 25.0
      }
    }
  ]
}
```

The node with `"recommended": true` has the lowest load.

## Testing

Run the automated test suite:

```bash
# Edit test file to set your admin credentials
nano test_distributed_deployment.py
# Change TEST_ADMIN_PASSWORD

# Run tests
python test_distributed_deployment.py
```

This will:
1. Check available nodes
2. Create a server on central
3. Create a server with auto selection
4. Create a server on a client node (if available)
5. Verify load balancing algorithm

## Monitoring

### View Connected Clients

**API:**
```bash
curl http://localhost:3000/api/clients \
  -H "Cookie: user_id=YOUR_ADMIN_USER_ID"
```

**Files:**
```bash
# Check registered clients
cat clients.json | jq

# Check command queue
cat commands.json | jq
```

### Client Logs

Clients print status updates:
```
[Client] Starting client controller...
[Client] Registering with controller...
[Client] Registered successfully! API Key: abc123...
[Client] Heartbeat thread started (interval: 30s)
[Client] Command polling started (interval: 5s)
[Client] Client controller started successfully!
```

## Troubleshooting

### Client Won't Connect

1. **Check controller URL:**
   ```bash
   curl http://CENTRAL_IP:3000/api/health
   ```

2. **Check firewall:**
   ```bash
   sudo ufw status
   sudo ufw allow 3000/tcp
   ```

3. **View client logs for errors**

### Server Creation Pending

If server creation shows "pending":
- Wait 5-10 seconds for client to poll
- Check client is online: `GET /api/clients`
- Check command queue: `cat commands.json`
- View client logs for execution errors

### Node Shows Offline

- Check client process is running
- Verify heartbeat interval (30s)
- Check network connectivity
- Review client logs for errors

## Architecture

```
┌───────────────────────────────┐
│  Central Controller           │
│  - Web UI                     │
│  - Load Balancer              │
│  - API                        │
│  Port: 3000                   │
└────────────┬──────────────────┘
             │
  ┌──────────┴──────────┬────────────┐
  │                     │            │
┌─▼────────┐     ┌──────▼──┐   ┌────▼──────┐
│ Client 1 │     │Client 2 │   │ Client 3  │
│ Node 1   │     │ Node 2  │   │ Node 3    │
│ 2 Servers│     │5 Servers│   │ 1 Server  │
└──────────┘     └─────────┘   └───────────┘
```

## Next Steps

1. **Add more client nodes** - Scale horizontally by adding more machines
2. **Monitor resources** - Watch CPU/RAM usage on each node
3. **Test load balancing** - Create multiple servers and verify distribution
4. **Configure firewall** - Secure your central controller
5. **Set up HTTPS** - Use nginx/caddy for production deployments

## Documentation

- **[DISTRIBUTED_DEPLOYMENT.md](DISTRIBUTED_DEPLOYMENT.md)** - Complete guide
- **[DISTRIBUTED_DEPLOYMENT_SUMMARY.md](DISTRIBUTED_DEPLOYMENT_SUMMARY.md)** - Feature overview
- **[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)** - Implementation status
- **[CLIENT_TESTING_GUIDE.md](CLIENT_TESTING_GUIDE.md)** - Testing guide

## Support

If you run into issues:
1. Check the logs (central and client)
2. Verify network connectivity
3. Ensure all nodes are online
4. Review the documentation

---

**Happy distributed server hosting! 🚀**
