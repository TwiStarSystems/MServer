# Bug Fix Deployment Guide

## Bugs Fixed

1. **Paper JAR Download JSON Parse Error** - Fixed JSON parsing issues when downloading Paper versions
2. **+ Add Button Not Working** - Fixed error handling that was preventing the modal from opening
3. **Display Name Not Showing** - Fixed user UI to show display name when available

## Files Modified

- `public/app.js` - Fixed `apiRequest()` function and `updateUserUI()` function
- `public/settings.js` - Fixed `pollDownloadProgress()` function  
- `public/index.html` - Added cache-control meta tags
- `public/login.html` - Added cache-control meta tags
- `public/settings.html` - Added cache-control meta tags
- `public/public.html` - Added cache-control meta tags
- `server.py` - Added cache-control headers for JS/CSS files
- `install.sh` - Enhanced update process with better verification

## Deployment Steps

### Step 1: Commit Changes to Git

```bash
cd "/home/twistar/VSC Repos/TwiStarSystems/MServerController"

# Check what files have changed
git status

# Add all changes
git add public/app.js public/settings.js public/*.html server.py install.sh

# Commit the changes
git commit -m "Fix: JSON parse errors, + Add button, and display name issues

- Fixed JSON parsing errors in Paper JAR downloads by adding proper response validation
- Fixed + Add button not working due to improper error handling in apiRequest
- Fixed display name not showing in user UI (now shows displayName when available)
- Added cache-control headers to prevent browser caching issues
- Enhanced update process in install.sh with better verification"

# Push to GitHub
git push origin main
```

### Step 2: Deploy to Server

If you're running this on a server with the installed version:

```bash
# SSH to your server (if remote)
ssh user@your-server

# Navigate to installation directory
cd /opt/mservercontroller

# Pull latest changes
sudo git pull origin main

# Restart the service
sudo systemctl restart mservercontroller

# Check if service is running
sudo systemctl status mservercontroller
```

OR use the install.sh update command:

```bash
cd /path/to/your/repo
sudo ./install.sh update
```

### Step 3: Clear Browser Cache

**CRITICAL**: After deploying, users must clear their browser cache to see the changes!

**Option 1: Hard Refresh (Recommended)**
- Windows/Linux: Press `Ctrl + Shift + R`
- Mac: Press `Cmd + Shift + R`

**Option 2: Clear Browser Cache**
- Chrome: Settings → Privacy → Clear browsing data → Cached images and files
- Firefox: Settings → Privacy & Security → Clear Data → Cached Web Content  
- Edge: Settings → Privacy → Choose what to clear → Cached data and files

**Option 3: Use Incognito/Private Mode**
- Open the website in an incognito/private window to bypass cache

### Step 4: Verify Fixes

After deployment and clearing cache:

1. **Test Paper JAR Download**:
   - Go to Settings → Server JAR Manager → JAR Bucket
   - Select "Paper" server type
   - Try downloading version 1.19.4 or older
   - Should download without JSON parse errors

2. **Test + Add Button**:
   - Go to Dashboard
   - Click the "+ Add" button in the sidebar
   - Modal should open without errors
   - Check browser console (F12) for any errors

3. **Test Display Name**:
   - Go to Settings → User Management
   - Edit a user and add a Display Name
   - Save the user
   - Check top-right corner - should show Display Name instead of Username

## Troubleshooting

### Changes Not Appearing

If changes don't appear after deployment:

1. **Verify files were copied**:
   ```bash
   sudo ls -la /opt/mservercontroller/public/app.js
   sudo cat /opt/mservercontroller/public/app.js | grep "displayName"
   ```

2. **Check service is running**:
   ```bash
   sudo systemctl status mservercontroller
   sudo journalctl -u mservercontroller -n 50
   ```

3. **Verify permissions**:
   ```bash
   sudo chown -R www-data:www-data /opt/mservercontroller
   sudo chmod -R 755 /opt/mservercontroller
   ```

4. **Force browser cache clear**:
   - Open DevTools (F12)
   - Right-click the refresh button
   - Select "Empty Cache and Hard Reload"

### + Add Button Still Not Working

Check browser console (F12) for errors:
```javascript
// Should see these in console when clicking + Add:
// "API request failed: [error message]"
// "URL: /api/default-server-path"
```

If you see errors, check:
1. Is the service running? `sudo systemctl status mservercontroller`
2. Are you logged in? Try logging out and back in
3. Check server logs: `sudo journalctl -u mservercontroller -f`

### Paper Download Still Failing

If older Paper versions still fail:
1. Check if the version actually exists: `curl -s "https://api.papermc.io/v2/projects/paper/versions/1.19.4"`
2. Check server logs during download: `sudo journalctl -u mservercontroller -f`
3. Verify the error message has changed (should not be "JSON.parse" anymore)

## Development Mode Testing

If you want to test locally before deploying:

```bash
cd "/home/twistar/VSC Repos/TwiStarSystems/MServerController"

# Create virtual environment if needed
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run in development mode
python server.py

# Access at http://localhost:3000
```

Then test the fixes locally before pushing to production.

## Rollback

If something goes wrong, you can rollback:

```bash
cd /opt/mservercontroller
sudo git log --oneline  # Find the previous commit hash
sudo git reset --hard <previous-commit-hash>
sudo systemctl restart mservercontroller
```

## Cache-Control Headers

The fixes include cache-control headers to prevent future caching issues:

- Server-side: `server.py` now sends `Cache-Control: no-cache` for JS/CSS
- Client-side: HTML files include meta tags to prevent caching
- This ensures users always get the latest version after updates

## Support

If issues persist after following this guide:
1. Check browser console (F12) for JavaScript errors
2. Check server logs: `sudo journalctl -u mservercontroller -xe`
3. Verify all files were updated correctly
4. Try completely clearing browser data (nuclear option)
