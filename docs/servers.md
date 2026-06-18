# Deploy/Debuging Servers info

*connection methods* SSH (Secure Shell) is used for remote access to the servers. You can use an SSH client like PuTTY (for Windows) or the terminal (for Linux/Mac) to connect to the servers using the provided credentials.

## App Server:
host: 172.16.5.2
port: 22
username: root
password: 123QWEasdZXC!@#

## Nginx Reverse Proxy:
host: 172.16.6.50
port: 22
username: twistar
password: Cert authentication (use the provided private key for authentication)

## NOTE: the Config file for this app is located at "/etc/nginx/live/twistar.org/panel.mc.conf". You can modify it to change the reverse proxy settings as needed.