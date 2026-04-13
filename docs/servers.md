# App Server:
host: 172.16.5.2
port: 22
username: root
password: (PASSWORD provided when prompted)

# Nginx Reverse Proxy:
host: 172.16.6.50
port: 22
username: twistar
password: Cert authentication (use the provided private key for authentication)

## NOTE: the Config file for this app is located at "/etc/nginx/live/twistar.org/panel.mc.conf". You can modify it to change the reverse proxy settings as needed.