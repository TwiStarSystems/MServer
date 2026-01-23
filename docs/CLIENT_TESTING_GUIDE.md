# Client-Controller Testing Guide

## ✅ Implementation Complete!

The client-controller communication system is now fully implemented. Here's how to test it:

## Quick Test

### Terminal 1: Start Central Controller
```bash
cd "/home/twistar/VSC Repos/TwiStarSystems/MServerController"
source venv/bin/activate
python server.py --mode central --port 3000
```

Expected output:
```
============================================================
MServerController - CENTRAL MODE
============================================================
Web Interface: http://localhost:3000
Listening on: 0.0.0.0:3000
⚠️  WARNING: Default admin credentials are admin/admin
            Change immediately after first login!
============================================================
```

### Terminal 2: Start Client Node
```bash
cd "/home/twistar/VSC Repos/TwiStarSystems/MServerController"
source venv/bin/activate
python server.py --mode client \
    --controller http://localhost:3000 \
    --node-id test-node-1
```

Expected output:
```
============================================================
MServerController - CLIENT MODE
============================================================
Node ID: test-node-1
Controller: http://localhost:3000
Local API: 0.0.0.0:3000
============================================================
[Client] Starting client controller...
[Client] Registering with controller: http://localhost:3000
[Client] Node ID: test-node-1
[Client] ✓ Registration successful!
[Client] Heartbeat started (interval: 30s)
[Client] Command polling started (interval: 5s)
[Client] Client controller started successfully!
[Client] Client controller running...
[Client] Press Ctrl+C to stop
```

## What to Check

### 1. Client Registration
- Client should connect and register with central controller
- Check `clients.json` file in the workspace
- Should contain client node info, system specs, and API key

### 2. Heartbeat
- Every 30 seconds, client sends status update
- Check central controller console for heartbeat messages
- Client reports server statuses and system stats

### 3. Command Polling
- Every 5 seconds, client polls for commands
- Commands queued by central controller are picked up
- Results are reported back

## Testing Commands

### From Central Controller (requires admin login first)

1. Open web UI: http://localhost:3000
2. Login with: admin / admin
3. In browser console or via API:

```javascript
// View registered clients
fetch('/api/clients', {
  headers: {'Content-Type': 'application/json'},
  credentials: 'include'
}).then(r => r.json()).then(console.log)

// Send command to client
fetch('/api/clients/test-node-1/command', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  credentials: 'include',
  body: JSON.stringify({
    action: 'START',
    server_id: 'some-server-id'
  })
}).then(r => r.json()).then(console.log)
```

Or use curl:
```bash
# Get session cookie first by logging in via web UI, then:

# View clients
curl -X GET http://localhost:3000/api/clients \
  --cookie "session=YOUR_SESSION_COOKIE"

# Send command
curl -X POST http://localhost:3000/api/clients/test-node-1/command \
  -H "Content-Type: application/json" \
  --cookie "session=YOUR_SESSION_COOKIE" \
  -d '{"action":"START", "server_id":"test-server"}'
```

## File Structure

After running, you should see:
```
MServerController/
├── clients.json          # ✓ Registered client nodes
├── commands.json         # ✓ Command queue
├── config.json           # Server configs
├── users.json            # User accounts
└── ...
```

### clients.json Example:
```json
{
  "clients": {
    "test-node-1": {
      "node_id": "test-node-1",
      "api_key": "abc123...",
      "system_info": {
        "hostname": "my-server",
        "platform": "Linux",
        "cpu_count": 8,
        "memory_total": 16777216000
      },
      "status": "online",
      "registered_at": "2026-01-22T10:00:00",
      "last_heartbeat": "2026-01-22T10:05:30",
      "servers": [],
      "stats": {
        "cpu_percent": 15.2,
        "memory_percent": 45.3
      }
    }
  }
}
```

### commands.json Example:
```json
{
  "commands": {
    "test-node-1": [
      {
        "id": "abc12345",
        "action": "START",
        "server_id": "server-1",
        "params": {},
        "created_at": "2026-01-22T10:00:00",
        "status": "completed",
        "delivered_at": "2026-01-22T10:00:05",
        "completed_at": "2026-01-22T10:00:10",
        "result": {
          "success": true,
          "message": "Server started"
        }
      }
    ]
  }
}
```

## Supported Commands

Clients can execute these actions:
- **START**: Start a server
- **STOP**: Stop a server gracefully
- **RESTART**: Stop and start a server
- **KILL**: Force kill a server
- **COMMAND**: Send custom command to server console
- **BACKUP**: Trigger server backup (planned)

## Troubleshooting

### Client won't connect
- Check controller URL is correct and reachable
- Verify controller is running on specified port
- Check firewall settings if on different machines

### Heartbeat not updating
- Check client console for errors
- Verify `clients.json` exists and has write permissions
- Check network connectivity

### Commands not executing
- Verify server exists in client's config
- Check command queue in `commands.json`
- Look for error messages in client console

## Advanced: Multi-Client Setup

You can run multiple clients:

```bash
# Terminal 1: Controller
python server.py --mode central --port 3000

# Terminal 2: Client 1
python server.py --mode client \
    --controller http://localhost:3000 \
    --node-id client-1 \
    --port 3001

# Terminal 3: Client 2  
python server.py --mode client \
    --controller http://localhost:3000 \
    --node-id client-2 \
    --port 3002

# Terminal 4: Client 3 (on different machine)
python server.py --mode client \
    --controller http://192.168.1.100:3000 \
    --node-id remote-client-1 \
    --port 3000
```

All clients will report to the same central controller!

## Security Notes

- API keys are generated during registration
- All client->controller communication uses API key authentication
- Store API keys securely
- In production, use HTTPS for controller URL
- Consider adding IP whitelisting for clients

## Next Steps

1. Build UI for managing clients in central controller
2. Add real-time log streaming from clients
3. Add bulk command execution across clients
4. Add client grouping and tagging
5. Add automated failover capabilities

---

**Status**: Fully Functional! 🎉
**Last Updated**: January 22, 2026
