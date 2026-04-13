###############################################################################
# TwiStar.org Nginx Reverse Proxy - Secure & Optimized Template
# Version: 2.0
# Last Updated: February 2026
# 
# Production-ready configuration with enterprise-grade security and performance
# 
# USAGE:
# 1. Copy this template for each service
# 2. Replace placeholders: <HOST>, <IP:PORT>, <CERT>, <CERTKEY>
# 3. Uncomment optional directives as needed
# 4. Test with: sudo nginx -t
# 5. Reload: sudo systemctl reload nginx
###############################################################################

###############################################################################
# [REQUIRED] HTTP to HTTPS Redirect
###############################################################################
server {
    listen 80;
    listen [::]:80;
    server_name <HOST>.twistar.org;
    
    # Redirect all HTTP traffic to HTTPS
    return 301 https://$server_name$request_uri;
}

###############################################################################
# [REQUIRED] Main HTTPS Server Block
###############################################################################
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name <HOST>.twistar.org;
    
    ###########################################################################
    # SSL/TLS Configuration
    ###########################################################################
    
    # Certificate paths (generate with: sudo certbot certonly --nginx)
    ssl_certificate /etc/letsencrypt/live/<SERVER_NAME>/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/<SERVER_NAME>/privkey.pem;
    
    # HTTP Strict Transport Security (HSTS) - 2 years
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    # Prevent clickjacking attacks
    add_header X-Frame-Options "SAMEORIGIN" always;
    # Prevent MIME type sniffing
    add_header X-Content-Type-Options "nosniff" always;
    # Enable XSS protection
    add_header X-XSS-Protection "1; mode=block" always;
    # Referrer policy for privacy
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    # Content Security Policy (customize per service if needed)
    # add_header Content-Security-Policy "default-src 'self' https:; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline';" always;
    # Permissions Policy (formerly Feature-Policy)
    add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
    
    ###########################################################################
    # Performance & Buffer Configuration
    ###########################################################################
    
    # Client body size limit [DEFAULT: 2GB for large file uploads]
    # REQUIRED: Must be set per-service (global is disabled in nginx.conf)
    # Adjust per service: Nextcloud/Emby may need more, simple sites need less
    client_max_body_size 2048M;
    
    # Buffer sizes for proxy
    client_body_buffer_size 512k;
    proxy_buffering on;
    proxy_buffer_size 8k;
    proxy_buffers 8 8k;
    proxy_busy_buffers_size 16k;
    
    # Timeout configurations (override global if needed for specific services)
    # client_body_timeout 300s;  # Uncomment for long uploads
    # send_timeout 300s;         # Uncomment for long responses
    
    # Proxy timeouts (extend for long-running requests)
    proxy_connect_timeout 60s;
    proxy_send_timeout 300s;
    proxy_read_timeout 300s;
    
    # [OPTIONAL] For services with very long operations (e.g., Emby transcoding)
    # Uncomment and adjust as needed:
    # proxy_send_timeout 600s;
    # proxy_read_timeout 600s;
    
    ###########################################################################
    # Compression
    ###########################################################################
    
    # Note: Gzip settings inherited from nginx.conf
    
    ###########################################################################
    # Rate Limiting (Optional - Uncomment to Enable)
    ###########################################################################
    
    # Define rate limit zone in http context (add to main nginx.conf):
    # limit_req_zone $binary_remote_addr zone=general:10m rate=10r/s;
    # limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;
    
    # Apply rate limiting (uncomment as needed)
    # limit_req zone=general burst=20 nodelay;
    # limit_conn_zone $binary_remote_addr zone=addr:10m;
    # limit_conn addr 100;
    
    ###########################################################################
    # Access Control (Optional - Uncomment to Restrict Access)
    ###########################################################################
    
    # [OPTIONAL] IP Allowlist - For internal/private services only
    # Uncomment and modify IP ranges as needed:
    # allow 172.16.0.0/21;        # Internal network range
    # allow 10.0.0.0/24;          # VPN or management network
    # deny all;                    # Deny all other IPs
    
    ###########################################################################
    # Custom Error Pages - settings inherited from nginx.conf
    ###########################################################################
    
    # error_page 401 /401_loginfailed.html;
    # location = /401_loginfailed.html {
    #    root /usr/share/nginx/html;
    #    internal;
    # }
    
    # error_page 403 /403_accessdenied.html;
    # location = /403_accessdenied.html {
    #    root /usr/share/nginx/html;
    #    internal;
    # }
    
    # error_page 404 /404_notfound.html;
    # location = /404_notfound.html {
    #     root /usr/share/nginx/html;
    #     internal;
    # }
    
    # error_page 500 502 503 504 /50x_serviceoffline.html;
    # location = /50x_serviceoffline.html {
    #     root /usr/share/nginx/html;
    #     internal;
    # }
    
    ###########################################################################
    # [OPTIONAL] Static Website Hosting
    ###########################################################################
    
    # Uncomment if hosting static files directly on this proxy:
    # root /var/www/html/<PATH>;
    # index index.html index.htm;
    
    ###########################################################################
    # Main Proxy Location Block
    ###########################################################################
    
    location / {
        # Backend service URL
        proxy_pass http://<IP:PORT>;
        
        #######################################################################
        # Essential Proxy Headers
        #######################################################################
        
        # Preserve original host header
        proxy_set_header Host $host;
        # Forward real client IP
        proxy_set_header X-Real-IP $remote_addr;
        # Forward proxy chain
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        # Forward protocol (http/https)
        proxy_set_header X-Forwarded-Proto $scheme;
        # Forward server name
        proxy_set_header X-Forwarded-Host $server_name;
        # Forward port information
        proxy_set_header X-Forwarded-Port $server_port;

        #######################################################################
        # WebSocket Support (Required for: Matrix, Emby, Meshcentral, etc.)
        #######################################################################
        
        # Uncomment for services that use WebSockets:
        # proxy_http_version 1.1;
        # proxy_set_header Upgrade $http_upgrade;
        # proxy_set_header Connection "upgrade";
        
        #######################################################################
        # Additional Proxy Settings
        #######################################################################
        
        # Disable buffering for real-time applications (streaming, WebRTC)
        # Uncomment for: Emby, Jellyfin, video conferencing
        # proxy_buffering off;
        
        # Preserve original Accept-Encoding (some apps need this)
        # proxy_set_header Accept-Encoding "";
        
        # Redirect handling
        proxy_redirect off;
        
        # Handle cookies properly
        proxy_cookie_path / /;
    }
    
    ###########################################################################
    # [OPTIONAL] Additional Location Blocks
    ###########################################################################
    
    # Example: WebDAV endpoints for Nextcloud
    # location /.well-known/carddav {
    #     return 301 $scheme://$host/remote.php/dav;
    # }
    # 
    # location /.well-known/caldav {
    #     return 301 $scheme://$host/remote.php/dav;
    # }
    
    # Example: Matrix federation (requires port 8448)
    # location ~ ^(/_matrix|/_synapse/client) {
    #     proxy_pass http://<IP:PORT>;
    #     proxy_set_header Host $host;
    #     proxy_set_header X-Real-IP $remote_addr;
    #     proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    #     proxy_set_header X-Forwarded-Proto $scheme;
    #     proxy_http_version 1.1;
    #     proxy_set_header Upgrade $http_upgrade;
    #     proxy_set_header Connection "upgrade";
    # }
    
    # Example: Block specific paths for security
    # location ~ /\. {
    #     deny all;
    #     access_log off;
    #     log_not_found off;
    # }
    
    # Example: API endpoint with different rate limit
    # location /api/ {
    #     limit_req zone=login burst=5 nodelay;
    #     proxy_pass http://<IP:PORT>;
    #     include proxy_params;
    # }
    
    ###########################################################################
    # Logging Configuration
    ###########################################################################
    
    access_log /var/log/nginx/<SERVER_NAME>.access.log;
    error_log /var/log/nginx/<SERVER_NAME>.error.log warn;
}

###############################################################################
# [OPTIONAL] Additional Server Block for Federation/Special Ports
###############################################################################

# Example: Matrix Federation on port 8448
# server {
#     listen 8448 ssl http2;
#     listen [::]:8448 ssl http2;
#     server_name <HOST>.twistar.org;
#     
#     ssl_certificate <CERT>;
#     ssl_certificate_key <CERTKEY>;
#     # Note: SSL protocols and ciphers inherited from nginx.conf
#     
#     location / {
#         proxy_pass http://<IP:PORT>;
#         proxy_set_header Host $host;
#         proxy_set_header X-Real-IP $remote_addr;
#         proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
#         proxy_set_header X-Forwarded-Proto $scheme;
#     }
# }

###############################################################################
# Service-Specific Recommended Settings
###############################################################################

# NEXTCLOUD:
#   - client_max_body_size: 10240M (or higher)
#   - proxy_read_timeout: 86400s
#   - Add WebDAV location blocks (see above)
#   - Uncomment WebSocket support

# EMBY/JELLYFIN:
#   - client_max_body_size: 4096M
#   - proxy_buffering: off
#   - Uncomment WebSocket support
#   - proxy_read_timeout: 600s (for transcoding)

# MATRIX HOMESERVER:
#   - Add port 8448 server block for federation
#   - client_max_body_size: 4096M
#   - Uncomment WebSocket support
#   - Location block for /_matrix and /_synapse paths

# MESHCENTRAL:
#   - Uncomment WebSocket support (required)
#   - proxy_read_timeout: 600s

# REMINNA/REMOTE DESKTOP:
#   - Uncomment WebSocket support
#   - Consider IP restrictions for security
#   - proxy_read_timeout: 600s

# PORTAINER/DOCKER MANAGEMENT:
#   - Uncomment WebSocket support
#   - Strong IP restrictions recommended
#   - Consider client certificate authentication

# PHOTOPRISM/IMAGE GALLERIES:
#   - client_max_body_size: 4096M
#   - gzip types: add image/webp

# PIHOLE:
#   - Strong IP restrictions (internal only)
#   - No WebSocket needed

###############################################################################
# End of Configuration Template
###############################################################################