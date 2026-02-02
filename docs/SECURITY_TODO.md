# 🔧 Remaining Security Tasks for Production

This document outlines security improvements that should be implemented before or shortly after production deployment.

---

## 🔴 HIGH PRIORITY (Implement Before Production)

### 1. CSRF Protection
**Status:** Not Implemented  
**Risk Level:** Medium  
**Estimated Time:** 2-3 hours

**Implementation Steps:**

1. **Install Flask-WTF:**
   ```bash
   pip install Flask-WTF
   pip freeze > requirements.txt
   ```

2. **Add to server.py:**
   ```python
   from flask_wtf.csrf import CSRFProtect, generate_csrf
   
   csrf = CSRFProtect(app)
   
   # Exempt API endpoints if they use API keys
   csrf.exempt('api_v1')  # Blueprint exemption
   ```

3. **Add CSRF token endpoint:**
   ```python
   @app.route('/api/csrf-token', methods=['GET'])
   def get_csrf_token():
       token = generate_csrf()
       return jsonify({'csrf_token': token})
   ```

4. **Update frontend (app.js, login.js, settings.js):**
   ```javascript
   // Get CSRF token
   let csrfToken = null;
   async function getCSRFToken() {
       const response = await fetch('/api/csrf-token');
       const data = await response.json();
       csrfToken = data.csrf_token;
   }
   
   // Add to all POST/PUT/DELETE requests
   const response = await fetch('/api/endpoint', {
       method: 'POST',
       headers: {
           'Content-Type': 'application/json',
           'X-CSRF-Token': csrfToken
       },
       body: JSON.stringify(data)
   });
   ```

5. **Test thoroughly:**
   - All forms still work
   - AJAX requests succeed
   - API endpoints (if exempted) still work

**Files to Modify:**
- `server.py` (add CSRF protection)
- `public/app.js` (add CSRF token to requests)
- `public/login.js` (add CSRF token)
- `public/settings.js` (add CSRF token)
- `requirements.txt` (add Flask-WTF)

---

### 2. Change Default Admin Credentials
**Status:** Uses Default  
**Risk Level:** High  
**Estimated Time:** 30 minutes

**Options:**

**Option A: Force Password Change on First Login**
```python
# In server.py
def requires_password_change(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id, user = get_current_user()
        if user and user.get('forcePasswordChange', False):
            if request.endpoint != 'api_change_password':
                return jsonify({
                    'error': 'Password change required',
                    'forcePasswordChange': True
                }), 403
        return f(*args, **kwargs)
    return decorated_function

# Mark default admin for password change
if username == 'admin' and not user.get('passwordChanged', False):
    user['forcePasswordChange'] = True
```

**Option B: Generate Random Initial Password**
```python
# In UserManager._ensure_admin_exists()
import secrets
import string
random_password = ''.join(secrets.choice(string.ascii_letters + string.digits + string.punctuation) for _ in range(16))
self.users['users'][admin_id]['password'] = generate_password_hash(random_password)
print(f"Default admin password: {random_password}")
# Write to secure file
with open('admin_initial_password.txt', 'w') as f:
    f.write(f"Username: admin\nPassword: {random_password}\n")
os.chmod('admin_initial_password.txt', 0o600)
```

**Recommended:** Option A (forced password change)

---

## 🟡 MEDIUM PRIORITY (Implement Soon After Launch)

### 3. Hash MFA Recovery Codes
**Status:** Plaintext Storage  
**Risk Level:** Medium  
**Estimated Time:** 1 hour

**Implementation:**

1. **Update UserManager.enable_mfa():**
   ```python
   def enable_mfa(self, user_id, secret, recovery_code):
       with self.lock:
           user = self.users.get('users', {}).get(user_id)
           if not user:
               return False, "User not found"
           
           # Hash recovery code before storage
           recovery_hash = generate_password_hash(recovery_code)
           
           self.users['users'][user_id]['mfaEnabled'] = True
           self.users['users'][user_id]['mfaSecret'] = secret
           self.users['users'][user_id]['mfaRecoveryCode'] = recovery_hash  # Hashed
           self._save_users()
           return True, "MFA enabled successfully"
   ```

2. **Update UserManager.verify_recovery_code():**
   ```python
   def verify_recovery_code(self, user_id, recovery_code):
       with self.lock:
           user = self.users.get('users', {}).get(user_id)
           if not user:
               return False
           
           stored_hash = user.get('mfaRecoveryCode')
           if not stored_hash:
               return False
           
           # Verify hashed recovery code
           if check_password_hash(stored_hash, recovery_code):
               # Disable MFA after recovery code use
               self.disable_mfa(user_id)
               return True
           return False
   ```

**Testing:**
- Generate new recovery code
- Verify it's hashed in users.json
- Test recovery process still works
- Confirm MFA disabled after recovery

---

### 4. Restrict CORS for SocketIO
**Status:** Wide Open (`*`)  
**Risk Level:** Medium  
**Estimated Time:** 30 minutes

**Implementation:**

1. **Update server.py:**
   ```python
   # Get allowed origins from environment
   ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', 'http://localhost:3000').split(',')
   
   # In production, set ALLOWED_ORIGINS to your domain
   if os.environ.get('FLASK_ENV') == 'production':
       socketio = SocketIO(app, cors_allowed_origins=ALLOWED_ORIGINS, manage_session=False)
   else:
       # Allow all in development
       socketio = SocketIO(app, cors_allowed_origins="*", manage_session=False)
   ```

2. **Set environment variable:**
   ```bash
   export ALLOWED_ORIGINS="https://yourdomain.com,https://www.yourdomain.com"
   ```

3. **Test:**
   - Verify WebSocket connections work from allowed origins
   - Verify connections blocked from other origins

---

### 5. Input Sanitization in Error Messages
**Status:** Some Direct Reflection  
**Risk Level:** Low-Medium  
**Estimated Time:** 2-3 hours

**Areas to Review:**

1. **Username in error messages:**
   ```python
   # Before
   return jsonify({'error': f'User {username} not found'}), 404
   
   # After
   return jsonify({'error': 'User not found'}), 404
   ```

2. **File paths in errors:**
   ```python
   # Before
   return jsonify({'error': f'File {filepath} not found'}), 404
   
   # After
   return jsonify({'error': 'Requested file not found'}), 404
   ```

3. **Add HTML escaping utility:**
   ```python
   from markupsafe import escape
   
   def safe_error(message, user_input=None):
       if user_input:
           return f"{message}: {escape(user_input)}"
       return message
   ```

**Files to Review:**
- All `return jsonify({'error': ...})` statements
- Error messages containing user input
- Logged error messages

---

### 6. Enhanced API Rate Limiting with Redis
**Status:** Memory-based  
**Risk Level:** Low  
**Estimated Time:** 1-2 hours

**Implementation:**

1. **Install Redis:**
   ```bash
   pip install redis
   apt-get install redis-server  # or brew install redis
   ```

2. **Update server.py:**
   ```python
   # Configure Limiter with Redis
   limiter = Limiter(
       key_func=get_remote_address,
       app=app,
       default_limits=["100 per 15 minutes"],
       storage_uri="redis://localhost:6379"
   )
   ```

3. **Add per-API-key rate limiting:**
   ```python
   def get_api_key_for_limit():
       api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
       if api_key:
           # Use key ID instead of full key
           key_data = validate_api_key(api_key)
           if key_data:
               return key_data['id']
       return get_remote_address()
   
   # Apply to API endpoints
   @api_v1.route('/endpoint')
   @limiter.limit("60 per minute", key_func=get_api_key_for_limit)
   def api_endpoint():
       pass
   ```

**Benefits:**
- Persistent rate limit tracking across restarts
- Better performance under load
- Distributed rate limiting support

---

## 🟢 LOW PRIORITY (Nice to Have)

### 7. Comprehensive Audit Logging
**Estimated Time:** 4-6 hours

**Features to Log:**
- All authentication events (success/failure)
- User account changes (password, role, MFA)
- Server creation/deletion/modification
- Admin actions (user management, settings)
- API key usage
- File uploads/deletions
- Backup operations

**Implementation:**
```python
import logging
from logging.handlers import RotatingFileHandler

audit_logger = logging.getLogger('audit')
audit_logger.setLevel(logging.INFO)
handler = RotatingFileHandler('logs/audit.log', maxBytes=10000000, backupCount=10)
handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
audit_logger.addHandler(handler)

def log_audit(action, user_id, details):
    audit_logger.info(f"USER:{user_id} ACTION:{action} DETAILS:{details}")
```

---

### 8. Database Migration from JSON to PostgreSQL
**Estimated Time:** 8-12 hours

**Benefits:**
- Better concurrency handling
- Transaction support
- Improved performance
- Better backup/restore
- Query capabilities

**Considerations:**
- Overkill for small deployments
- Adds infrastructure complexity
- Current JSON system works fine for <1000 users

**Recommendation:** Only if scaling beyond 500 users

---

### 9. Two-Factor Backup Methods
**Estimated Time:** 6-8 hours

**Features:**
- SMS/Email as backup 2FA
- U2F/WebAuthn security keys
- Multiple TOTP devices

**Dependencies:**
- SMTP configuration for email
- SMS provider (Twilio, etc.)
- WebAuthn library

---

### 10. Session Management Improvements
**Estimated Time:** 3-4 hours

**Features:**
- View active sessions
- Force logout from other devices
- Session IP tracking
- Session device fingerprinting

**Implementation:**
```python
# Store sessions in database
sessions = {
    'session_id': {
        'user_id': 'user_id',
        'ip': 'ip_address',
        'user_agent': 'user_agent',
        'created': 'timestamp',
        'last_active': 'timestamp'
    }
}
```

---

## 📋 Implementation Priority Order

### Phase 1 (Before Production):
1. CSRF Protection ⭐⭐⭐
2. Change Default Admin Credentials ⭐⭐⭐

### Phase 2 (Within 2 Weeks):
3. Hash MFA Recovery Codes ⭐⭐
4. Restrict CORS Origins ⭐⭐
5. Input Sanitization Review ⭐⭐

### Phase 3 (Within 1 Month):
6. Enhanced API Rate Limiting ⭐
7. Comprehensive Audit Logging ⭐

### Phase 4 (Future Enhancements):
8. Database Migration (if needed)
9. Two-Factor Backup Methods
10. Advanced Session Management

---

## 🧪 Testing Checklist

After each implementation, verify:

- [ ] Existing functionality still works
- [ ] New security feature effective
- [ ] No performance degradation
- [ ] Error handling correct
- [ ] Documentation updated
- [ ] Frontend updated if needed
- [ ] Environment variables documented
- [ ] Deployment process updated

---

## 📚 Documentation to Update

After implementing tasks:

1. **README.md** - Installation and setup steps
2. **SECURITY.md** - Security features and best practices
3. **docs/SECURITY_QUICK_REFERENCE.md** - Quick reference guide
4. **requirements.txt** - Python dependencies
5. **.env.example** - Environment variable examples

---

*Document Created: February 2, 2026*  
*Keep this updated as tasks are completed*
