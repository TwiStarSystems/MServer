# 🔒 Security Quick Reference - MServerController

## Password Requirements (NEW - Strengthened)
- **Minimum length:** 12 characters (was 6)
- **Required:** At least one uppercase letter
- **Required:** At least one lowercase letter  
- **Required:** At least one number
- **Applies to:** Registration, password changes, admin resets

Example valid passwords:
- ✅ `MySecure2026Pass`
- ✅ `AdminPassword123`
- ❌ `admin` (too short, no uppercase, no numbers)
- ❌ `password123` (no uppercase)

---

## Session Security (NEW - Enhanced)
- **HTTPS-only cookies:** Enabled in production (auto-detects environment)
- **HttpOnly:** Prevents JavaScript access to session cookies
- **SameSite=Lax:** Protects against CSRF attacks
- **Lifetime:** 7 days (configurable)

**Environment Detection:**
- Development (`FLASK_ENV=development`): HTTPS-only disabled for testing
- Production (default): HTTPS-only enforced

---

## MFA System Status
✅ **Production Ready**

### Features:
- TOTP-based authentication (Google Authenticator, Authy compatible)
- QR code provisioning for easy setup
- Recovery codes for account recovery
- **5-minute timeout** for verification (NEW)
- Policy enforcement (all users or admins only)

### MFA Flow:
1. User logs in with username/password
2. If MFA enabled → temp session created with timestamp
3. User has 5 minutes to enter TOTP code
4. After timeout → must re-login
5. On success → full session established

### Recovery Process:
1. Click "Lost your authenticator?"
2. Enter recovery code
3. MFA automatically disabled
4. User can re-enable MFA in settings

---

## Security Headers (NEW - Implemented)

All responses now include these headers:

```
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block
Strict-Transport-Security: max-age=31536000; includeSubDomains
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; ...
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
```

**What this protects against:**
- ✓ Clickjacking attacks
- ✓ MIME-sniffing vulnerabilities
- ✓ Cross-site scripting (XSS)
- ✓ Protocol downgrade attacks
- ✓ Information leakage via referrer
- ✓ Unauthorized feature access

---

## Brute-Force Protection

### Account Lockout:
- **Trigger:** 5 failed login attempts
- **Action:** Account automatically disabled
- **Reset:** Admin must manually enable account

### Anti-Lockout System:
- **Trigger:** All admin accounts disabled
- **Action:** Emergency admin account auto-created
- **Credentials:** Logged to console and `anti_lockout_credentials.log`
- **Format:** `emergency_admin_####` with 16-character random password
- **Auto-removal:** When regular admin re-enabled

### Rate Limits:
```
Login attempts:    10 per minute
Registration:      5 per hour  
MFA verification:  10 per minute
File uploads:      10-20 per 15 minutes
Backup creation:   5 per 15 minutes
Global default:    100 per 15 minutes
```

---

## API Key Security

### Key Storage:
- Keys hashed with SHA-256 before storage
- Only prefix shown in management interface
- Full key shown ONCE on creation

### Permissions:
- `read` - View server status and info
- `write` - Modify server settings
- `servers` - Create/delete servers
- `console` - Send console commands
- `players` - Query player data
- `admin` - Full administrative access

### Usage:
```bash
# Header method (recommended)
curl -H "X-API-Key: msc_..." https://your-server.com/api/v1/status

# Query parameter method
curl https://your-server.com/api/v1/status?api_key=msc_...
```

---

## Environment Variables for Production

### Required:
```bash
export SECRET_KEY="<generate-with-secrets.token_hex(32)>"
export FLASK_ENV="production"
```

### Recommended:
```bash
export ALLOWED_ORIGINS="https://yourdomain.com"
export SESSION_COOKIE_DOMAIN="yourdomain.com"
export PORT="3000"
```

### Generate Secure SECRET_KEY:
```python
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## First-Time Setup Security Checklist

1. **Change Default Admin Password**
   - Default: `admin` / `admin`
   - Change immediately on first login
   - New password must meet strength requirements

2. **Configure Environment**
   ```bash
   cp .env.example .env
   nano .env  # Add SECRET_KEY and other vars
   ```

3. **Enable HTTPS**
   - Use reverse proxy (Nginx) with SSL/TLS
   - Or run with `--ssl-cert` and `--ssl-key` flags
   - Let's Encrypt recommended for free certificates

4. **Review Settings**
   - Enable registration approval if needed
   - Configure MFA policies
   - Set up SMTP for email notifications

5. **Test Security Features**
   - Verify login lockout works (try 5 wrong passwords)
   - Test MFA setup and verification
   - Confirm rate limiting blocks excessive requests
   - Check security headers with browser dev tools

---

## Security Incident Response

### If You Suspect Compromise:

1. **Immediate Actions:**
   ```bash
   # Rotate SECRET_KEY
   export SECRET_KEY="<new-random-key>"
   
   # Restart application
   systemctl restart mservercontroller
   ```

2. **Audit Logs:**
   - Check `anti_lockout_credentials.log`
   - Review `api_stats.json` for unusual patterns
   - Check user accounts in `users.json`

3. **Reset Everything:**
   - Force password reset for all users
   - Revoke all API keys
   - Review server configurations for changes

4. **Notify Users:**
   - Inform users of potential compromise
   - Require password changes
   - Recommend MFA enabling

---

## Testing Security Features

### Test Brute-Force Protection:
1. Attempt login with wrong password 5 times
2. Verify account is disabled
3. Check console for lockout message
4. Admin must enable account in user management

### Test MFA:
1. User Settings → Enable MFA
2. Scan QR code with authenticator app
3. Enter 6-digit code to verify
4. Save recovery code securely
5. Logout and login again
6. Verify TOTP code required

### Test Rate Limiting:
```bash
# Should block after 10 attempts
for i in {1..15}; do 
  curl -X POST http://localhost:3000/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username":"test","password":"test"}'
  echo "Attempt $i"
done
```

### Test Security Headers:
```bash
curl -I http://localhost:3000/
# Look for: X-Frame-Options, X-Content-Type-Options, etc.
```

---

## Common Security Questions

### Q: Why is HTTPS-only cookie disabled in development?
**A:** To allow testing over HTTP. In production (FLASK_ENV != 'development'), it's automatically enabled.

### Q: Can users choose weaker passwords?
**A:** No, the strengthened requirements are enforced server-side. Frontend validation should match.

### Q: What happens if I forget my recovery code?
**A:** Admin must disable MFA for your account. You can then re-enable it with a new code.

### Q: How do I rotate API keys?
**A:** Delete old key in admin panel, create new key, update applications using the API.

### Q: What's the difference between anti-lockout and regular admin?
**A:** Anti-lockout accounts are temporary emergency accounts that auto-remove when regular admins are re-enabled.

---

## Security Best Practices

### For Administrators:
- ✓ Use strong, unique passwords
- ✓ Enable MFA on your account
- ✓ Regularly review user accounts
- ✓ Monitor failed login attempts
- ✓ Keep API key list up-to-date
- ✓ Review server access logs
- ✓ Update application regularly

### For Users:
- ✓ Enable MFA for extra security
- ✓ Use unique password (not reused)
- ✓ Keep recovery code safe
- ✓ Logout when finished
- ✓ Report suspicious activity
- ✓ Don't share accounts

### For Server Operators:
- ✓ Run behind reverse proxy (Nginx)
- ✓ Enable HTTPS/TLS
- ✓ Regular security updates
- ✓ Backup user database
- ✓ Monitor resource usage
- ✓ Review logs periodically
- ✓ Test disaster recovery

---

## Additional Resources

- **Full Audit Report:** [docs/SECURITY_AUDIT_REPORT.md](./SECURITY_AUDIT_REPORT.md)
- **Security Documentation:** [docs/SECURITY.md](./SECURITY.md)
- **Development Guide:** [docs/DEVELOPMENT_GUIDE.md](./DEVELOPMENT_GUIDE.md)
- **Flask Security:** https://flask.palletsprojects.com/en/latest/security/
- **OWASP Top 10:** https://owasp.org/www-project-top-ten/

---

*Last Updated: February 2, 2026*
