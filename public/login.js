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
                showSuccess('Login successful! Redirecting...');
                setTimeout(() => {
                    window.location.href = '/';
                }, 1000);
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
