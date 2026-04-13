# Note for Debugging

## URL of app: 
<APP_URL> - publicly accessible URL.

## SSH = Enabled - SSH access is available for all developers to connect to the server and perform debugging tasks. SSH can be used to upload the latest code changes, run commands, check logs, and perform other debugging activities on the server. The SSH credentials for the variousservers are as follows:

Linux Dev Machines (SSH Access to Server): ssh <USERNAME>@<IP_ADDRESS>:<PORT> - For file upload, command execution, and debugging on the server.

### <APP_NAME> Server Information:
- IP Address: <IP_ADDRESS>
- SSH Port: <PORT>
- SSH Username: <USERNAME>
- SSH Password: <PASSWORD> (if applicable, otherwise use SSH key authentication)

## Dev Aid/Addons

- Debugging in Firefox and Firefox Developer Edition available in VSCODE.
- All developers are operating systems are either Windows, Linux(Debian based) and MacOS.
- All developers have admin access to the server and can use SSH to connect to the server for debugging purposes.

## Debugging Instructions

1. **Pull latest changes** before investigating:
   ```bash
   git pull
   ```

2. **Reproduce the bug** — confirm you can trigger the issue on your local environment (Debian 13 / Firefox) or on the server. Document the exact steps.

3. **Collect diagnostics via SSH:**
   - Gather relevant logs (application, web server, database, system).
   - Check service status, resource usage, and connectivity.
   - Inspect configuration files for recent changes or misconfigurations.
   - Check file permissions and ownership if access-related.

4. **Identify the root cause:**
   - Trace the error from logs back to the responsible code path.
   - Check recent commits for regressions (`git log --oneline -20`, `git diff`).
   - Use the OS/DE priority matrix to determine if the bug is platform-specific.
   - For database issues: check connection strings, query logs, schema state, and migrations.
   - For Nginx issues: validate config with `nginx -t`, check upstream connectivity, review proxy headers.

5. **Implement the fix:**
   - Keep the fix minimal and targeted — only change what is necessary to resolve the issue.
   - Do not refactor surrounding code or add unrelated improvements.
   - If the fix involves config changes on the server, document the change clearly.

6. **Test the fix:**
   - Verify the original reproduction steps no longer trigger the bug.
   - Run any existing test suites to check for regressions.
   - If the bug was platform-specific, test on that platform.

7. **Deploy the fix** via SSH:
   - Transfer updated files using `scp` or `rsync`.
   - Restart affected services.
   - Monitor logs after deployment to confirm the issue is resolved:
     ```bash
     ssh user@host 'journalctl -u <service> -f'
     ```

8. **Commit with a clear message** describing the bug, root cause, and fix applied.