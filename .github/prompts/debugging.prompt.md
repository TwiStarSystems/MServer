# Note for Debugging

## URL of app: 
<APP_URL> - publicly accessible URL.

## SSH = Enabled - SSH access is available for all developers to connect to the server and perform debugging tasks. SSH can be used to upload the latest code changes, run commands, check logs, and perform other debugging activities on the server. The SSH credentials for the variousservers are as follows:

Linux Dev Machines (SSH Access to Server): ssh root@<IP_ADDRESS>:<PORT> - For file upload, command execution, and debugging on the server.

### <APP_NAME> Server Information:
- IP Address: <IP_ADDRESS>
- SSH Port: <PORT>
- SSH Username: root
- SSH Password: <PASSWORD> (if applicable, otherwise use SSH key authentication)

## Dev Aid/Addons

- Debugging in Firefox and Firefox Developer Edition available in VSCODE.
- All developers are operating systems are either Windows or Linux(Debian based). No MacOS.
- All developers have admin access to the server and can use SSH to connect to the server for debugging purposes.
- The Linux dev machines have the same OS (Debian 12 and Debian 13) as the server, so they can use similar tools and commands for debugging. The Windows dev machines do not use WSL (Windows Subsystem for Linux), so they may have to use different tools or commands for debugging. However, they can still use SSH to connect to the server and run commands remotely for debugging purposes.
- The Linux dev machines have Firefox installed with Debugging Extensions (Debugging For Firefox) configured(see .vscode/launch.json, Launch option configured), so they can use the Firefox Developer Tools for debugging the web application. Not all Windows dev machines have Firefox installed, so they may have to use a different browser or tool for debugging the web application. However, they can still use SSH to connect to the server and run commands remotely for debugging purposes.
- All developers have access to the server logs, which can be used for debugging purposes. The logs can be accessed through SSH by navigating to the appropriate log files on the server. The specific log files and their locations may vary depending on the server configuration and the web application being debugged. Developers can use commands like `tail`, `less`, or `cat` to view the log files and analyze any errors or issues that may be occurring in the application.
