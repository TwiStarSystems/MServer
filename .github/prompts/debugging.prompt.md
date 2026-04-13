# Debugging Prompt 

this prompt is designed to guide developers through the process of debugging issues in a web application, ensuring that they follow best practices for diagnosing and resolving problems while maintaining code quality and consistency across the project. The instructions are structured to help identify the root cause of issues effectively, considering the specific requirements of the target operating systems and desktop environments. For server information and supported operating systems,

see /docs/servers.md for server information and the OS support priority matrix for supported operating systems. Also, review the preferred backend stack and application types sections for the technologies being used in the project.

## SSH — Primary Debugging Interface

SSH is the primary channel for all remote debugging, diagnostics, and remediation. Use it to access server logs, check service status, inspect configurations, and deploy fixes. Ensure you have the necessary SSH credentials and permissions to access the servers. see Se

---


## Debugging Instructions

1. **Pull latest changes** before investigating:
   ```bash
   git pull
   ```

2. **Reproduce the bug** 
   - Confirm you can trigger the issue on your local environment (Debian 13 / Firefox) or on the server. Document the exact steps.
   - If the issue is not reproducible locally, focus on collecting diagnostics from the server to understand the context.
   - Document any differences between the local and server environments that might affect the issue.
   - Use the OS/DE priority matrix to determine if the bug is platform-specific.

3. **Collect diagnostics via SSH:**
   - Gather relevant logs (application, web server, database, system).
   - Check service status, resource usage, and connectivity.
   - Inspect configuration files for recent changes or misconfigurations.
   - Check file permissions and ownership if access-related.
   - For Nginx issues: validate config with `nginx -t`, check upstream connectivity, review proxy headers.
   - For database issues: check connection strings, query logs, schema state, and migrations.
   - Frontend debugging: use browser dev tools to check console errors, network requests, and resource loading.
   - Check environment variables for missing or incorrect values.
   - Review recent commits for potential regressions (`git log --oneline -20`, `git diff`).
   - Use the OS/DE priority matrix to determine if the bug is platform-specific.
   - Check network connectivity and firewall rules if the issue involves external services or APIs. (curl -I, ping, nc) — useful for upstream/proxy issues
   - For performance issues: use tools like `top`, `htop`, `iotop`, or APM solutions to identify bottlenecks.
   - For database performance issues: check slow query logs, analyze query plans, and monitor connection pool usage.
   - For Nginx performance issues: check request rates, upstream response times, and resource usage.
   - For frontend performance issues: use browser dev tools to analyze rendering times, resource loading, and JavaScript execution.
   - For memory leaks: monitor memory usage over time, check for unclosed resources, and review code for potential leaks (e.g., event listeners, database connections).

4. **Identify the root cause:**
   - Trace the error from logs back to the responsible code path.
   - Check recent commits for regressions (`git log --oneline -20`, `git diff`).
   - Use the OS/DE priority matrix to determine if the bug is platform-specific.
   - For database issues: check connection strings, query logs, schema state, and migrations.
   - For Nginx issues: validate config with `nginx -t`, check upstream connectivity, review proxy headers.
   - For frontend issues: use browser dev tools to check console errors, network requests, and resource loading.
   - Check environment variables for missing or incorrect values.
   - For performance issues: use tools like `top`, `htop`, `iotop

5. **Implement the fix:**
   - Keep the fix minimal and targeted — only change what is necessary to resolve the issue.
   - Do not refactor surrounding code or add unrelated improvements.
   - If the fix involves config changes on the server, document the change clearly.
   - Implement the fix to local code first and test it before deploying to the server.

6. **Test the fix:**
   - Verify the original reproduction steps no longer trigger the bug.
   - Run any existing test suites to check for regressions.
   - If the bug was platform-specific, test on that platform.
   - Verify that the fix does not introduce new issues or regressions.
   - If the issue was performance-related, verify that the fix improves performance without causing new bottlenecks.

7. **Deploy the fix** via SSH:
   - Transfer updated files using `scp` or `rsync`.
   - Restart affected services.
   - Monitor logs after deployment to confirm the issue is resolved:
     ```bash
     ssh user@host 'journalctl -u <service> -f'
     ```
   - Verify the live app to confirm the fix is effective and no new issues have arisen.

8. **Commit with a clear message** describing the bug, root cause, and fix applied.
