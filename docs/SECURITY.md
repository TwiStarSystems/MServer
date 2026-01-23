# Security Guide - Encrypted Master-Slave Communication

## Overview

MServerController supports secure communication between Master and Slave nodes through:

1. **SSL/TLS Encryption (HTTPS)** - Encrypts the transport layer
2. **Payload Encryption (Fernet)** - Encrypts the actual data being transmitted

Both layers can be used independently or together for maximum security.

## Architecture

```
┌─────────────────────────────────────────────┐
│           Master Node (Controller)          │
│  ┌────────────────────────────────────────┐ │
│  │   SSL/TLS Layer (HTTPS)               │ │
│  │   ├─ Certificate Verification          │ │
│  │   └─ Transport Encryption              │ │
│  └────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────┐ │
│  │   Payload Encryption (Fernet)         │ │
│  │   ├─ Symmetric Encryption              │ │
│  │   └─ Authenticated Encryption          │ │
│  └────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
                    ▲ │
         Encrypted  │ │ Encrypted
         HTTPS + Payload │ HTTPS + Payload
                    │ ▼
┌─────────────────────────────────────────────┐
│           Slave Node (Worker)               │
│  ┌────────────────────────────────────────┐ │
│  │   SSL/TLS Layer                       │ │
│  │   ├─ Certificate Verification          │ │
│  │   └─ Transport Decryption              │ │
│  └────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────┐ │
│  │   Payload Decryption (Fernet)         │ │
│  │   ├─ Symmetric Decryption              │ │
│  │   └─ Authentication Verification       │ │
│  └────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

## Installation with Encryption

### Option 1: Automated Installation (Recommended)

During installation, the script will prompt for encryption options:

```bash
sudo ./install.sh install
```

**For Master Node:**
- Select "Master Node" mode
- Enable SSL/TLS when prompted (generates self-signed certificate)
- Enable payload encryption when prompted (generates encryption key)
- Save the encryption key displayed - you'll need it for Slave nodes

**For Slave Node:**
- Select "Slave Node" mode
- Enter Master URL as `https://master-ip:3000` for SSL
- Choose whether to verify SSL certificate (y for production, n for self-signed)
- Enable payload encryption when prompted
- Enter the encryption key copied from Master node

### Option 2: Manual Setup

#### Master Node with SSL + Encryption

1. **Generate SSL certificate:**
```bash
mkdir -p /opt/mservercontroller/ssl
openssl req -x509 -newkey rsa:4096 -nodes \
    -keyout /opt/mservercontroller/ssl/key.pem \
    -out /opt/mservercontroller/ssl/cert.pem \
    -days 365 \
    -subj "/C=US/ST=State/L=City/O=MServerController/CN=your-hostname"
```

2. **Generate encryption key:**
```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" > /opt/mservercontroller/encryption.key
chmod 600 /opt/mservercontroller/encryption.key
```

3. **Start Master with SSL and encryption:**
```bash
export ENCRYPTION_KEY=$(cat /opt/mservercontroller/encryption.key)

python server.py --mode central \
  --ssl-cert /opt/mservercontroller/ssl/cert.pem \
  --ssl-key /opt/mservercontroller/ssl/key.pem \
  --port 3000
```

#### Slave Node with SSL + Encryption

```bash
python server.py --mode client \
  --controller https://192.168.1.100:3000 \
  --node-id slave-01 \
  --encryption-key "YOUR_ENCRYPTION_KEY_FROM_MASTER"
```

**Note:** For self-signed certificates, add `--no-verify-ssl` flag (not recommended for production).

## Security Levels

### Level 1: No Encryption (Default)
- ⚠️ **HTTP only** - Data transmitted in plain text
- ❌ No transport encryption
- ❌ No payload encryption
- Use case: Testing, development, trusted internal networks

```bash
# Master
python server.py --mode central

# Slave
python server.py --mode client \
  --controller http://192.168.1.100:3000 \
  --node-id slave-01
```

### Level 2: SSL/TLS Only
- ✅ **HTTPS** - Transport layer encryption
- ✅ Certificate-based authentication
- ❌ No payload encryption
- Use case: Production environments with trusted network

```bash
# Master
python server.py --mode central \
  --ssl-cert /path/to/cert.pem \
  --ssl-key /path/to/key.pem

# Slave
python server.py --mode client \
  --controller https://192.168.1.100:3000 \
  --node-id slave-01
```

### Level 3: SSL/TLS + Payload Encryption (Recommended)
- ✅ **HTTPS** - Transport layer encryption
- ✅ Certificate-based authentication
- ✅ Payload encryption (Fernet)
- ✅ Message authentication
- Use case: Production, sensitive data, multi-tenant environments

```bash
# Master
export ENCRYPTION_KEY="your-fernet-key-here"
python server.py --mode central \
  --ssl-cert /path/to/cert.pem \
  --ssl-key /path/to/key.pem

# Slave
python server.py --mode client \
  --controller https://192.168.1.100:3000 \
  --node-id slave-01 \
  --encryption-key "your-fernet-key-here"
```

## Encryption Key Management

### Generating a New Encryption Key

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Storing the Encryption Key

**Master Node:**
- Store in `/opt/mservercontroller/encryption.key`
- Set environment variable: `ENCRYPTION_KEY=your-key`
- File permissions: `chmod 600 encryption.key`

**Slave Nodes:**
- Pass via command line: `--encryption-key "key"`
- Or store in deployment config: `/opt/mservercontroller/deployment.conf`

### Rotating Encryption Keys

1. Generate new key on Master
2. Update Master's environment variable or config
3. Restart Master node
4. Update all Slave nodes with new key
5. Restart Slave nodes

**Important:** All nodes must use the same encryption key.

## SSL Certificate Options

### Self-Signed Certificates (Development/Internal)

**Pros:**
- Free
- Quick to generate
- Works for internal networks

**Cons:**
- Browser warnings
- Requires `--no-verify-ssl` on Slave nodes
- Not suitable for production

**Generate:**
```bash
openssl req -x509 -newkey rsa:4096 -nodes \
    -keyout key.pem -out cert.pem -days 365 \
    -subj "/C=US/ST=State/L=City/O=MServerController/CN=$(hostname)"
```

### Let's Encrypt (Production)

**Pros:**
- Free trusted certificates
- Automatic renewal
- Works with public domains

**Cons:**
- Requires public domain name
- Requires ports 80/443 accessible

**Setup with Certbot:**
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

Then update nginx.conf to use Let's Encrypt certificates.

### Commercial CA Certificates (Enterprise)

Purchase from trusted Certificate Authority (DigiCert, GlobalSign, etc.)

## Network Configuration

### Firewall Rules

**Master Node:**
```bash
# Allow HTTPS (if using SSL)
sudo ufw allow 443/tcp

# Or allow HTTP (if not using SSL)
sudo ufw allow 3000/tcp
```

**Slave Nodes:**
- No incoming ports required (slave connects to master)
- Ensure outbound HTTPS/HTTP to master is allowed

### Nginx Configuration with SSL

Update `/opt/mservercontroller/nginx.conf`:

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /opt/mservercontroller/ssl/cert.pem;
    ssl_certificate_key /opt/mservercontroller/ssl/key.pem;
    
    # Strong SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}
```

## API Key Authentication

In addition to encryption, all Slave nodes authenticate using API keys:

- Generated automatically during registration
- Stored in Master's `clients.json`
- Sent in `X-Client-API-Key` header
- Unique per Slave node

## Troubleshooting

### SSL Certificate Errors

**Problem:** `SSL: CERTIFICATE_VERIFY_FAILED`

**Solution:**
- For self-signed certificates: Add `--no-verify-ssl` flag
- For production: Ensure certificate is valid and not expired
- Check certificate hostname matches controller URL

### Encryption Errors

**Problem:** `Decryption error` or `Invalid token`

**Solution:**
- Ensure Master and Slave use the same encryption key
- Check encryption key format (must be valid Fernet key)
- Verify encryption key hasn't been corrupted

### Connection Refused

**Problem:** Slave cannot connect to Master

**Solution:**
- Check firewall rules
- Verify Master is running
- Ensure correct protocol (http vs https)
- Test with curl: `curl -k https://master-ip:3000/api/health`

## Best Practices

1. **Always use SSL/TLS in production**
2. **Enable payload encryption for sensitive data**
3. **Use valid certificates from trusted CA for production**
4. **Rotate encryption keys periodically**
5. **Store encryption keys securely**
6. **Use strong firewall rules**
7. **Monitor failed authentication attempts**
8. **Keep certificates up to date**
9. **Use separate encryption keys per environment (dev/staging/prod)**
10. **Document your encryption setup for disaster recovery**

## Security Checklist

- [ ] SSL/TLS enabled on Master
- [ ] Valid SSL certificates (not self-signed for production)
- [ ] Payload encryption enabled
- [ ] Encryption key stored securely
- [ ] Firewall configured
- [ ] Nginx configured for HTTPS
- [ ] SSL certificate auto-renewal configured
- [ ] All Slave nodes using encryption
- [ ] Regular security audits scheduled
- [ ] Encryption keys backed up securely

## Additional Resources

- [Cryptography Library Documentation](https://cryptography.io/)
- [Fernet Specification](https://github.com/fernet/spec/)
- [SSL/TLS Best Practices](https://wiki.mozilla.org/Security/Server_Side_TLS)
- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)
