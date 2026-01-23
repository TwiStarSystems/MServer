# MServerController Update Commands - Quick Reference

## Install Directory Path
```
/opt/mservercontroller
```

## Update Your Code First
```bash
cd /path/to/MServerController  # Your git repo
git pull origin main
```

---

## Update Commands

### 🔵 FULL UPDATE (Recommended for Production)
```bash
sudo /path/to/install.sh update
```
- Updates everything: code, dependencies, systemd service
- Preserves all configurations and encryption keys
- Time: 3-5 minutes
- **Best for:** Production updates, dependency changes

**Output shows:**
- Deployment mode detection ✓
- Files being backed up ✓
- Files being updated ✓
- Files being restored ✓
- Summary of what was preserved ✓

---

### ⚡ QUICK UPDATE (Development/Testing)
```bash
sudo /path/to/install.sh quick-update
```
- Updates application files ONLY
- Does NOT reinstall Python dependencies
- Preserves all configurations and encryption keys
- Time: 30 seconds - 1 minute
- **Best for:** Quick hotfixes, testing, development

**Output shows:**
- What updates, what doesn't ✓
- Deployment mode detected ✓
- Files updated ✓
- Note: Dependencies not updated ✓

---

### 📊 CHECK STATUS
```bash
sudo /path/to/install.sh status
```
Shows:
- Installation location
- Deployment mode (Master/Slave)
- Service running status
- Configuration details
- Disk usage

---

## What Gets Preserved

### ✅ ALWAYS PRESERVED (Both Update Types)

| Item | Purpose |
|------|---------|
| `config.json` | Server configurations |
| `users.json` | User accounts & passwords |
| `settings.json` | App settings & branding |
| `stats.json` | Performance metrics |
| `clients.json` | Connected Slave nodes |
| `commands.json` | Command queue |
| `backup_schedules.json` | Backup schedules |
| `task_schedules.json` | Task schedules |
| **`encryption.key`** | **Encryption key** |
| `deployment.conf` | Deployment config |
| `servers/` | All game server data |
| `backups/` | All server backups |
| `ssl/` | SSL certificates (Master) |

---

## Master Node Update

```bash
# Verify it's a Master
grep "DEPLOYMENT_MODE" /opt/mservercontroller/deployment.conf
# Should show: DEPLOYMENT_MODE=master

# Run update
sudo /path/to/install.sh update

# Verify service is running
sudo systemctl status mservercontroller

# Check web interface
# http://localhost:3000 (HTTP)
# https://localhost:443 (HTTPS)
```

**Result:** 
- Master continues running
- All game servers running
- All configs/keys preserved
- Web UI available immediately

---

## Slave Node Update

```bash
# Verify it's a Slave
grep "DEPLOYMENT_MODE" /opt/mservercontroller/deployment.conf
# Should show: DEPLOYMENT_MODE=slave

# Run update
sudo /path/to/install.sh update

# Watch reconnection (takes ~30 seconds)
sudo journalctl -u mservercontroller -f

# Should see: "[Client] ✓ Reconnected to Master!"
```

**Result:**
- Slave updates
- Game servers keep running
- Slave reconnects to Master
- Resumes normal polling (10s)
- No manual intervention needed

---

## Monitoring During Update

### In Terminal 1: Run Update
```bash
cd /path/to/MServerController
sudo ./install.sh update
```

### In Terminal 2: Monitor Logs
```bash
sudo journalctl -u mservercontroller -f
```

### In Terminal 3: Check Status
```bash
watch -n 1 'sudo systemctl status mservercontroller'
```

---

## Rollback If Something Goes Wrong

### Option 1: Restore from Backup
```bash
sudo systemctl stop mservercontroller
sudo tar -xzf /backup/mservercontroller_backup.tar.gz -C /
sudo systemctl start mservercontroller
```

### Option 2: Git Rollback
```bash
cd /path/to/MServerController
git log --oneline -5          # See recent commits
git reset --hard HEAD~1       # Go back one version
sudo /path/to/install.sh update
```

---

## Troubleshooting

### Service Won't Start
```bash
# Check logs
sudo journalctl -u mservercontroller -n 50 --no-pager

# Check syntax
/opt/mservercontroller/venv/bin/python3 -m py_compile server.py

# Try manual restart
sudo systemctl restart mservercontroller
sudo systemctl status mservercontroller
```

### Lost Encryption Key
```bash
# Check if backup exists
ls -la /tmp/mservercontroller_update_backup_*/encryption.key

# Restore
sudo cp /tmp/mservercontroller_update_backup_*/encryption.key /opt/mservercontroller/

# Restart
sudo systemctl restart mservercontroller
```

### Slave Won't Reconnect
```bash
# Check deployment config
cat /opt/mservercontroller/deployment.conf

# Check connectivity to Master
curl -I https://MASTER_IP:443/api/health

# Check logs
sudo journalctl -u mservercontroller -n 100 --no-pager

# Manually restart
sudo systemctl restart mservercontroller
sudo journalctl -u mservercontroller -f
```

---

## Automated Updates (Optional - Set Once)

### Create Update Script
```bash
sudo nano /usr/local/bin/mservercontroller_update.sh
```

Add content:
```bash
#!/bin/bash
cd /path/to/MServerController
git pull origin main
sudo /path/to/install.sh quick-update
```

Make executable:
```bash
sudo chmod +x /usr/local/bin/mservercontroller_update.sh
```

### Schedule Weekly Update (Sunday 2 AM)
```bash
# Edit crontab
sudo crontab -e

# Add line:
0 2 * * 0 /usr/local/bin/mservercontroller_update.sh >> /var/log/mservercontroller_update.log 2>&1
```

Check logs:
```bash
sudo tail -f /var/log/mservercontroller_update.log
```

---

## Before/After Checklist

### Before Update
- [ ] Git repo pulled latest (`git pull origin main`)
- [ ] Disk space available (500MB+)
- [ ] Users notified (if needed)
- [ ] Backup made (optional but recommended)
- [ ] Note current version (git log -1)

### After Update
- [ ] Service running: `sudo systemctl status mservercontroller`
- [ ] Web interface loads (Master only)
- [ ] Game servers running: `curl http://localhost:3000/api/servers`
- [ ] Slaves connected (Master only): Check Node Manager
- [ ] No errors in logs: `sudo journalctl -u mservercontroller -n 100`
- [ ] Version updated: `git log -1`

---

## Performance Tips

### Quick Testing
Use quick-update for rapid iteration:
```bash
sudo ./install.sh quick-update  # 30 seconds
```

### Production Deployment
Use full update weekly:
```bash
sudo ./install.sh update  # 3-5 minutes
```

### Batch Updates
For multiple Slaves:
1. Update Master first
2. Update Slaves one at a time (staggered)
3. Verify each reconnects before next

---

## Support Commands

```bash
# See installation guide
cat /opt/mservercontroller/docs/INSTALLATION.md

# See update guide (detailed)
cat /opt/mservercontroller/docs/UPDATE_GUIDE.md

# See implementation summary
cat /opt/mservercontroller/UPDATE_IMPLEMENTATION.md

# Check current Git version
cd /path/to/MServerController && git log -1 --oneline

# View deployment mode
cat /opt/mservercontroller/deployment.conf

# View deployment configuration
grep -E "^DEPLOYMENT_MODE|^CONTROLLER_URL|^NODE_ID" /opt/mservercontroller/deployment.conf
```

---

## Quick Start Example

```bash
# 1. Clone/pull latest code
cd ~/projects/MServerController
git pull origin main

# 2. Update Master (full)
sudo ./install.sh update

# 3. Verify
sudo systemctl status mservercontroller
curl http://localhost:3000/api/servers

# 4. Check logs
sudo journalctl -u mservercontroller -n 20

# ✅ Done!
```

---

**Last Updated:** 2026-01-23  
**Version:** 3.1  
**Status:** ✅ Ready for Production
