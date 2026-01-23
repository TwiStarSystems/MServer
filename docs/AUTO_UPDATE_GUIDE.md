# Auto-Update System Guide

## Overview

The MServerController now includes a complete auto-update system that allows administrators to check for and install updates directly from the web interface. The system intelligently handles both Master and Slave node deployments.

## Features

✅ **One-Click Update Checking** - Check GitHub for the latest version with a single button click
✅ **Non-Blocking Updates** - Application continues running during updates with automatic restart
✅ **Master-Slave Coordination** - Master node automatically notifies all Slave nodes to update
✅ **Changelog Display** - View all commits since your current version
✅ **Automatic Reconnection** - Slaves automatically reconnect after update
✅ **Version Information** - Display current version and deployment mode

## Using the Update Tool

### Step 1: Access the Tools Tab

1. Go to **Settings** → **🛠️ Tools** tab
2. Scroll to the **🔄 Auto-Update** section

### Step 2: Check for Updates

1. Click the **🔍 Check For Updates** button
2. The system will:
   - Fetch the latest version from GitHub
   - Compare with your current version
   - Display changelog if updates are available

### Step 3: Review Available Updates

When an update is available, you'll see:
- **Current Version**: Your installed version
- **Latest Version**: Available version on GitHub
- **Changelog**: List of commits/changes included in the update

### Step 4: Install Update

1. Click the **📥 Install Update** button
2. Confirm the update when prompted
3. The system will:
   - **For Master**: Send update command to all online Slave nodes, then update itself
   - **For Slave**: Update itself (receives command from Master)
   - Preserve all configurations during update
   - Maintain all data files (users.json, servers/, etc.)
   - Continue running game servers throughout

### Step 5: Monitor Progress

- The update progress section shows real-time status
- Estimated completion time: 30 seconds to 1 minute
- Game servers keep running and are unaffected
- The web interface will restart automatically

## Technical Details

### Backend API Endpoints

#### GET `/api/system/version`
Returns current version information.

**Response:**
```json
{
  "version": "v3.1-abc1234",
  "commit_date": "2026-01-23 18:30:00 +0000",
  "deployment_mode": "master",
  "installed_at": "/opt/mservercontroller"
}
```

#### GET `/api/system/updates/check`
Checks GitHub for available updates.

**Response:**
```json
{
  "update_available": true,
  "current_version": "v3.1-abc1234",
  "latest_version": "v3.2-def5678",
  "current_commit": "abc1234",
  "latest_commit": "def5678",
  "changelog": [
    "abc1234 - Add auto-update system",
    "def5678 - Improve Node Manager UI"
  ]
}
```

#### POST `/api/system/updates/install`
Triggers the update installation.

**Response:**
```json
{
  "status": "update_started",
  "deployment_mode": "master",
  "message": "Update started for master node"
}
```

### Update Process Flow

#### Master Node Update:
1. API receives `/api/system/updates/install` request
2. Master sends `UPDATE` command to all online Slave nodes (via command queue)
3. Slaves execute update in background thread
4. Master updates itself in background thread
5. Service restarts (handled by systemd)
6. Both Master and Slaves automatically reconnect

#### Slave Node Update:
1. Receives `UPDATE` command from Master (via polling)
2. Spawns background thread to run quick-update
3. Continues command polling during update
4. Service restarts (handled by systemd)
5. Automatically reconnects to Master

### Non-Interactive Mode

The installer supports non-interactive mode for automated updates:

```bash
sudo /opt/mservercontroller/install.sh quick-update --non-interactive
```

When `--non-interactive` flag is used:
- Loads all settings from `deployment.conf`
- Skips all interactive prompts
- Preserves existing configurations
- Updates only application files

### Files Preserved During Update

All of these files are ALWAYS preserved:
- `config.json` - Application configuration
- `users.json` - User accounts and credentials
- `encryption.key` - Encryption key for Master-Slave communication
- `deployment.conf` - Deployment mode and connection settings
- `servers/` - All game server data
- `backups/` - Backup files
- `ssl/` - SSL certificates

## Troubleshooting

### Update Stuck or Not Responding

If the update appears to hang:
1. Wait up to 10 minutes (installation timeout)
2. Check system logs: `systemctl status mservercontroller`
3. If needed, manually restart: `sudo systemctl restart mservercontroller`

### Failed to Check for Updates

Common causes:
- No internet connection (can't reach GitHub)
- Git not installed or misconfigured
- SSH keys not set up for git operations

Solution: Check git connectivity:
```bash
cd /opt/mservercontroller
git fetch origin main --dry-run
```

### Slave Not Receiving Update

If a Slave doesn't update when Master updates:
1. Verify Slave is online (check Node Manager)
2. Check Master's logs: `journalctl -u mservercontroller -n 50`
3. Manually update Slave: `ssh user@slave sudo /opt/mservercontroller/install.sh quick-update --non-interactive`

## Best Practices

1. **Check regularly** - Enable browser notifications to know about new updates
2. **Update during low-traffic** - Updates take <1 minute but restart the interface
3. **Keep Slaves online** - Master will update all online Slaves
4. **Monitor logs** - Check `/var/log/mservercontroller.log` after update

## Version History

- **v3.1** - Initial auto-update system implementation
  - Version checking from GitHub
  - One-click updates
  - Master-Slave update coordination
  - Non-interactive installer support

## FAQ

**Q: Will my game servers go down during update?**
A: No! Game servers continue running. Only the MServerController interface restarts.

**Q: Can I update just one Slave node?**
A: Yes, use SSH to connect and run: `sudo /opt/mservercontroller/install.sh quick-update --non-interactive`

**Q: What if the update fails halfway?**
A: The installer preserves all data. It's safe to retry the update.

**Q: Can I rollback an update?**
A: Rollback isn't automatic, but all your data is preserved. Reinstall the previous version or restore from backup.

**Q: How long does an update take?**
A: 30 seconds to 1 minute for quick-update. Full update takes 3-5 minutes but includes dependency installation.

## Support

For issues or questions about the auto-update system:
1. Check `/var/log/mservercontroller.log` for error messages
2. Review this guide's troubleshooting section
3. Check GitHub for known issues: https://github.com/TwiStarSystems/MServerController
