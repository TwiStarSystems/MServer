// Login page JavaScript

// Prevent multiple auth checks
let authCheckDone = false;

document.addEventListener('DOMContentLoaded', () => {
    // Check if already logged in (only once)
    if (!authCheckDone) {
        authCheckDone = true;
        checkAuthStatus();
    }
    
    // Tab switching
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            
            // Update active tab button
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Show corresponding content
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.getElementById(`${tab}-tab`).classList.add('active');
            
            // Clear messages
            hideMessages();
        });
    });
    
    // Login form
    document.getElementById('login-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        hideMessages();
        
        const username = document.getElementById('login-username').value.trim();
        const password = document.getElementById('login-password').value;
        const submitBtn = e.target.querySelector('button[type="submit"]');
        
        submitBtn.disabled = true;
        submitBtn.textContent = 'Signing in...';
        
        try {
            const response = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                if (data.mfaRequired) {
                    // Show MFA verification modal/screen
                    showMFAVerification();
                    submitBtn.disabled = false;
                    submitBtn.textContent = 'Sign In';
                } else {
                    showSuccess('Login successful! Redirecting...');
                    setTimeout(() => {
                        window.location.href = '/';
                    }, 1000);
                }
            } else {
                showError(data.error || 'Login failed');
                submitBtn.disabled = false;
                submitBtn.textContent = 'Sign In';
            }
        } catch (err) {
            showError('Network error. Please try again.');
            submitBtn.disabled = false;
            submitBtn.textContent = 'Sign In';
        }
    });
    
    // Register form
    document.getElementById('register-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        hideMessages();
        
        const username = document.getElementById('register-username').value.trim();
        const password = document.getElementById('register-password').value;
        const confirm = document.getElementById('register-confirm').value;
        const submitBtn = e.target.querySelector('button[type="submit"]');
        
        // Validate password match
        if (password !== confirm) {
            showError('Passwords do not match');
            return;
        }
        
        // Validate username
        if (!/^[a-zA-Z0-9_-]+$/.test(username)) {
            showError('Username can only contain letters, numbers, underscores, and hyphens');
            return;
        }
        
        submitBtn.disabled = true;
        submitBtn.textContent = 'Creating account...';
        
        try {
            const response = await fetch('/api/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                showSuccess('Account created! Please wait for admin approval before logging in.');
                document.getElementById('register-form').reset();
                
                // Switch to login tab after 2 seconds
                setTimeout(() => {
                    document.querySelector('[data-tab="login"]').click();
                }, 2000);
            } else {
                showError(data.error || 'Registration failed');
            }
        } catch (err) {
            showError('Network error. Please try again.');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Create Account';
        }
    });
});

async function checkAuthStatus() {
    try {
        const response = await fetch('/api/auth/me');
        if (response.ok) {
            const data = await response.json();
            if (data && data.username) {
                // Already logged in, redirect to main app
                window.location.replace('/');
            }
        }
        // If not ok (401, etc.), just stay on login page - no action needed
    } catch (err) {
        // Network error - stay on login page, don't do anything
        console.log('Auth check failed, staying on login page');
    }
}

function showError(message) {
    const el = document.getElementById('error-message');
    el.textContent = message;
    el.classList.add('show');
}

function showSuccess(message) {
    const el = document.getElementById('success-message');
    el.textContent = message;
    el.classList.add('show');
}

function hideMessages() {
    document.getElementById('error-message').classList.remove('show');
    document.getElementById('success-message').classList.remove('show');
}

// ==================== MFA Verification ====================

function showMFAVerification() {
    // Hide login/register forms
    document.querySelector('.auth-container').style.display = 'none';
    
    // Create MFA verification UI
    const mfaContainer = document.createElement('div');
    mfaContainer.id = 'mfa-container';
    mfaContainer.className = 'auth-container';
    mfaContainer.innerHTML = `
        <div class="auth-card">
            <h1>🔐 Two-Factor Authentication</h1>
            <p class="auth-subtitle">Enter the 6-digit code from your authenticator app</p>
            
            <div id="mfa-error-message" class="error-message"></div>
            
            <form id="mfa-verify-form">
                <div class="form-group">
                    <label for="mfa-code">Verification Code</label>
                    <input type="text" id="mfa-code" placeholder="123456" maxlength="6" pattern="[0-9]{6}" required autofocus>
                </div>
                
                <button type="submit" class="btn-primary">Verify</button>
                
                <div class="mfa-recovery-link">
                    <a href="#" onclick="showMFARecoveryInput(); return false;">Lost your authenticator? Use recovery code</a>
                </div>
                
                <div id="mfa-recovery-container" style="display: none;">
                    <div class="form-group">
                        <label for="mfa-recovery">Recovery Code</label>
                        <input type="text" id="mfa-recovery" placeholder="XXXXXXXX-XXXXXXXX-XXXXXXXX">
                        <small class="form-hint">Using your recovery code will disable MFA on your account.</small>
                    </div>
                    <button type="button" class="btn-secondary" onclick="verifyMFARecovery()">Use Recovery Code</button>
                </div>
                
                <button type="button" class="btn-text" onclick="cancelMFAVerification()">Back to Login</button>
            </form>
        </div>
    `;
    
    document.querySelector('.login-container').appendChild(mfaContainer);
    
    // Handle MFA form submission
    document.getElementById('mfa-verify-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        await verifyMFACode();
    });
}

function showMFARecoveryInput() {
    document.getElementById('mfa-recovery-container').style.display = 'block';
}

async function verifyMFACode() {
    const code = document.getElementById('mfa-code').value.trim();
    const submitBtn = document.querySelector('#mfa-verify-form button[type="submit"]');
    
    if (!code || code.length !== 6) {
        showMFAError('Please enter a 6-digit code');
        return;
    }
    
    submitBtn.disabled = true;
    submitBtn.textContent = 'Verifying...';
    
    try {
        const response = await fetch('/api/auth/mfa/verify-login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code, useRecovery: false })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showSuccess('Login successful! Redirecting...');
            setTimeout(() => {
                window.location.href = '/';
            }, 1000);
        } else {
            showMFAError(data.error || 'Invalid verification code');
            submitBtn.disabled = false;
            submitBtn.textContent = 'Verify';
        }
    } catch (err) {
        showMFAError('Network error. Please try again.');
        submitBtn.disabled = false;
        submitBtn.textContent = 'Verify';
    }
}

async function verifyMFARecovery() {
    const code = document.getElementById('mfa-recovery').value.trim();
    
    if (!code) {
        showMFAError('Please enter your recovery code');
        return;
    }
    
    try {
        const response = await fetch('/api/auth/mfa/verify-login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code, useRecovery: true })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showSuccess('Login successful! MFA has been disabled. Redirecting...');
            setTimeout(() => {
                window.location.href = '/';
            }, 1500);
        } else {
            showMFAError(data.error || 'Invalid recovery code');
        }
    } catch (err) {
        showMFAError('Network error. Please try again.');
    }
}

function showMFAError(message) {
    const el = document.getElementById('mfa-error-message');
    el.textContent = message;
    el.style.display = 'block';
}

function cancelMFAVerification() {
    const mfaContainer = document.getElementById('mfa-container');
    if (mfaContainer) {
        mfaContainer.remove();
    }
    document.querySelector('.auth-container').style.display = 'block';
}
