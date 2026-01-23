# MServerController Update Guide

## Overview

MServerController supports safe updates that preserve all configurations, encryption keys, and user data. The system automatically detects whether you're running a Master or Slave installation and updates accordingly.

**Version:** 3.1  
**Last Updated:** 2026-01-23

---

## Update Types

### 1. Full Update (Recommended for Production)

**Command:**
```bash
sudo /path/to/install.sh update
```

**What gets updated:**
- ✅ All application files (server.py, server_client.py, etc.)
- ✅ Frontend files (public/ directory)
- ✅ Documentation (docs/ directory)
- ✅ Configuration templates (configs/ directory)
- ✅ Python dependencies (venv)
- ✅ Systemd service file (if deployment mode changed)
- ✅ Nginx configuration (Master only)

**What gets preserved:**
- ✅ config.json (server configurations)
- ✅ users.json (user accounts and passwords)
- ✅ settings.json (app settings and branding)
- ✅ stats.json (performance metrics)
- ✅ clients.json (registered Slave nodes)
- ✅ commands.json (command queue)
- ✅ backup_schedules.json (backup schedules)
- ✅ task_schedules.json (task schedules)
- ✅ **encryption.key** (CRITICAL - encryption key)
- ✅ **deployment.conf** (deployment configuration)
- ✅ servers/ directory (all game server data)
- ✅ backups/ directory (all backups)
- ✅ ssl/ directory (SSL certificates for Master)
- ✅ logs (all system and application logs)

**Time required:** 3-5 minutes (depends on dependencies)

**Best for:**
- Production updates
- When dependencies need updating
- When you want comprehensive update

---

### 2. Quick Update (Development/Testing)

**Command:**
```bash
sudo /path/to/install.sh quick-update
```

**What gets updated:**
- ✅ Application files (server.py, server_client.py, etc.)
- ✅ Frontend files (public/)
- ✅ Documentation (docs/)
- ✅ Configuration templates (configs/)
- ✅ Tool scripts (tools/)

**What does NOT get updated:**
- ❌ Python dependencies (faster!)
- ❌ Systemd service file (uses existing)
- ❌ Nginx configuration

**What gets preserved:**
- ✅ All configuration files
- ✅ All user data
- ✅ Encryption keys
- ✅ SSL certificates
- ✅ Everything else

**Time required:** 30 seconds - 1 minute

**Best for:**
- Development/testing environments
- Quick hotfixes
- When dependencies haven't changed
- Fast iteration during development

---

## Update Process Details

### Master Node Update

When updating a Master installation:

1. **Detection:** Script detects `DEPLOYMENT_MODE=master` from deployment.conf
2. **Backup:** Creates temporary backup of critical files
3. **Update:** Downloads and installs new application files
4. **Restore:** Restores all critical files from backup
5. **Dependencies:** Updates Python virtual environment (full update only)
6. **Service:** Regenerates systemd service for Master mode
7. **Restart:** Stops and restarts the service
8. **Verification:** Confirms service is running

**Configuration preserved:**
- Master's encryption key (if enabled)
- All registered Slave nodes in clients.json
- Web UI branding and settings
- User accounts and permissions
- All game server configurations

---

### Slave Node Update

When updating a Slave installation:

1. **Detection:** Script detects `DEPLOYMENT_MODE=slave` from deployment.conf
2. **Backup:** Creates temporary backup of critical files
3. **Update:** Downloads and installs new Slave controller code
4. **Restore:** Restores deployment configuration and encryption key
5. **Dependencies:** Updates Python virtual environment (full update only)
6. **Service:** Regenerates systemd service for Slave mode with correct parameters
7. **Restart:** Stops and restarts the service
8. **Reconnection:** Automatically reconnects to Master after update

**Configuration preserved:**
- Slave's encryption key (provided by Master during install)
- Deployment configuration (controller URL, node ID)
- All local game server configurations
- All local backups and logs

**During Slave update:**
- Slave enters orphaned state while restarting
- Game servers on Slave continue running
- Slave reconnects to Master within 30 seconds
- No downtime for hosted game servers

---

## Auto-Update Strategy (Future Implementation)

### Master-Initiated Updates

The system is designed for future auto-update capability:

1. **Master checks repository** for new versions
2. **Master notifies connected Slaves** of new version available
3. **Slaves download update** in background
4. **Coordinated restart:** Optional - Slaves update at scheduled time
5. **No data loss:** All configurations and keys preserved
6. **Automatic reconnection:** Slaves reconnect after restart

### Benefits

- Zero-downtime updates for Slave-hosted servers
- All configurations automatically preserved
- No manual intervention on Slave nodes needed
- Encryption keys remain synchronized
- Rolled back if health check fails

---

## How to Perform Updates

### From Console (Recommended)

**Step 1:** Backup current installation (optional but recommended)
```bash
sudo tar -czf /backup/mservercontroller_$(date +%Y%m%d_%H%M%S).tar.gz /opt/mservercontroller
```

**Step 2:** Navigate to source directory
```bash
cd /path/to/MServerController  # Your repo directory
```

**Step 3:** Run update
```bash
# Full update (with dependency refresh)
sudo ./install.sh update

# OR Quick update (files only)
sudo ./install.sh quick-update
```

**Step 4:** Monitor the update
```bash
# In another terminal, watch the service
watch -n 1 'sudo systemctl status mservercontroller'

# Or check logs
sudo journalctl -u mservercontroller -f
```

### From Remote Server

**Step 1:** Pull latest code
```bash
cd /path/to/MServerController
git pull origin main
```

**Step 2:** Run update
```bash
sudo ./install.sh update
```

### Automated Updates (Cron - Future Use)

Create `/usr/local/bin/mservercontroller_update.sh`:
```bash
#!/bin/bash
cd /path/to/MServerController
git pull origin main
sudo ./install.sh quick-update
```

Make executable:
```bash
chmod +x /usr/local/bin/mservercontroller_update.sh
```

Add to crontab (weekly at 2 AM):
```bash
0 2 * * 0 /usr/local/bin/mservercontroller_update.sh >> /var/log/mservercontroller_update.log 2>&1
```

---

## File Preservation During Updates

### Protected Files (Never Modified)

| File/Directory | Purpose | Preserved During |
|---|---|---|
| `config.json` | Server configurations | Update ✅ |
| `users.json` | User accounts | Update ✅ |
| `settings.json` | App settings | Update ✅ |
| `stats.json` | Metrics | Update ✅ |
| `clients.json` | Registered Slaves | Update ✅ |
| `commands.json` | Command queue | Update ✅ |
| `backup_schedules.json` | Backup schedules | Update ✅ |
| `task_schedules.json` | Task schedules | Update ✅ |
| **`encryption.key`** | **Encryption key** | **Update ✅** |
| `deployment.conf` | Deployment config | Update ✅ |
| `servers/*` | Game server data | Update ✅ |
| `backups/*` | Server backups | Update ✅ |
| `ssl/*` | SSL certificates | Update ✅ |
| `logs/*` | System logs | Update ✅ |

### Updated Files

| File/Directory | Purpose |
|---|---|
| `server.py` | Master application |
| `server_client.py` | Slave application |
| `server_core.py` | Shared core logic |
| `system_info.py` | System utilities |
| `requirements.txt` | Python dependencies |
| `public/*` | Frontend files (HTML, JS, CSS) |
| `docs/*` | Documentation |
| `configs/*` | Configuration templates |
| `tools/*` | Utility scripts |
| `venv/*` | Python virtual environment |

---

## Troubleshooting Updates

### Service Fails to Start After Update

**Check logs:**
```bash
sudo journalctl -u mservercontroller -n 50 --no-pager
```

**Common causes:**
1. Python syntax error in new code
2. Missing dependency in requirements.txt
3. Permission issues on files
4. Configuration file corruption (unlikely with preservation)

**Solution:**
```bash
# Restart service
sudo systemctl restart mservercontroller

# Check status
sudo systemctl status mservercontroller

# View detailed logs
sudo journalctl -u mservercontroller -xe
```

### Lost Connection to Slave During Update

**Expected behavior:**
- Slave enters orphaned state during restart
- Game servers continue running
- Slave reconnects automatically within 30 seconds
- Status returns to normal

**If Slave doesn't reconnect:**
1. Check network connectivity from Slave to Master
2. Check Slave logs: `sudo journalctl -u mservercontroller -n 100`
3. Verify encryption key is correct (if enabled)
4. Manually restart: `sudo systemctl restart mservercontroller`

### Encryption Key Lost

**This should NOT happen** - encryption.key is backed up before update.

**If it occurs:**
1. Check backup: `ls -la /tmp/mservercontroller_update_backup_*/`
2. Restore from backup: `sudo cp /tmp/mservercontroller_update_backup_*/encryption.key /opt/mservercontroller/`
3. Restart service: `sudo systemctl restart mservercontroller`

### Slave Node Won't Restart After Update

**Check deployment configuration:**
```bash
cat /opt/mservercontroller/deployment.conf
```

Verify:
- `DEPLOYMENT_MODE=slave`
- `CONTROLLER_URL` is correct
- `NODE_ID` is set
- `USE_ENCRYPTION` matches Master

**Manually restart:**
```bash
sudo systemctl stop mservercontroller
sudo systemctl start mservercontroller
sudo journalctl -u mservercontroller -f
```

---

## Rollback Procedure

If update causes issues:

### Option 1: Restore from Backup (if available)

```bash
# Stop service
sudo systemctl stop mservercontroller

# Restore from backup
sudo tar -xzf /backup/mservercontroller_20260123_100000.tar.gz -C /

# Start service
sudo systemctl start mservercontroller
```

### Option 2: Reset to Previous Git Commit

```bash
cd /path/to/MServerController

# View recent commits
git log --oneline -10

# Reset to previous version
git reset --hard HEAD~1

# Run update to restore
sudo ./install.sh update
```

---

## Update Checklist

Before updating:
- [ ] Backup important data (automated by update script)
- [ ] Notify users of maintenance window (if needed)
- [ ] Check available disk space (at least 500MB free)
- [ ] Verify internet connection for dependency download

During update:
- [ ] Do not kill the update process
- [ ] Do not make changes to config files
- [ ] Do not restart the service manually

After update:
- [ ] Verify service is running: `sudo systemctl status mservercontroller`
- [ ] Check web UI loads (Master only)
- [ ] Verify game servers are running
- [ ] Confirm Slaves are connected (Master only)
- [ ] Review logs for any errors: `sudo journalctl -u mservercontroller -n 100`

---

## Version Tracking

Check current version:
```bash
# View deployment configuration
cat /opt/mservercontroller/deployment.conf

# Check last update from systemd
sudo journalctl -u mservercontroller --no-pager | grep -i "starting\|started" | tail -5
```

---

## For Developers

When modifying code:

1. **Test locally first:** `./install.sh dev`
2. **Commit changes:** `git commit -am "description"`
3. **Push to repository:** `git push origin main`
4. **Update production:** `sudo ./install.sh update` or `sudo ./install.sh quick-update`

The update system will automatically preserve all your configurations!

---

## Support

For issues during update:

1. Check logs: `sudo journalctl -u mservercontroller -xe`
2. Review this guide's troubleshooting section
3. Verify deployment configuration: `cat /opt/mservercontroller/deployment.conf`
4. Test connectivity: `ping /CONTROLLER_URL` (for Slaves)

