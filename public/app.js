// MServerController - Multi-Server Frontend Application

// Global fetch wrapper to handle authentication errors
const originalFetch = window.fetch;
window.fetch = async function(...args) {
  const response = await originalFetch.apply(this, args);
  
  // Redirect to login if authentication fails (except for auth endpoints)
  if (response.status === 401 && !args[0].includes('/api/auth/')) {
    window.location.href = '/login.html';
  }
  
  return response;
};

// Global state
let socket = null;
let currentServerId = null;
let currentPath = '';
let currentEditingFile = '';
let editingServerId = null;
let servers = [];
let currentUser = null;

// ==================== Notifications ====================

function showNotification(message, type = 'info') {
  // Remove existing notification
  const existing = document.querySelector('.notification');
  if (existing) existing.remove();
  
  const notification = document.createElement('div');
  notification.className = `notification notification-${type}`;
  notification.innerHTML = `
    <span class="notification-message">${escapeHtml(message)}</span>
    <button class="notification-close" onclick="this.parentElement.remove()">&times;</button>
  `;
  
  document.body.appendChild(notification);
  
  // Auto-remove after 5 seconds
  setTimeout(() => {
    if (notification.parentElement) {
      notification.remove();
    }
  }, 5000);
}

// ==================== Authentication ====================

async function checkAuth() {
  try {
    const response = await fetch('/api/auth/me');
    if (response.ok) {
      currentUser = await response.json();
      updateUserUI();
      return true;
    } else {
      // Not authenticated, redirect to login
      window.location.href = '/login.html';
      return false;
    }
  } catch (err) {
    window.location.href = '/login.html';
    return false;
  }
}

function updateUserUI() {
  // Update user info in top bar
  const userInfo = document.getElementById('user-info');
  if (userInfo && currentUser) {
    userInfo.innerHTML = `
      <div class="user-display">
        <span class="user-name">${escapeHtml(currentUser.username)}</span>
        <span class="user-role ${currentUser.role}">${currentUser.role}</span>
      </div>
      <div class="user-actions">
        <button class="btn-icon" onclick="openProfileSettings()" title="Profile Settings">⚙️</button>
        <button class="btn-icon" onclick="logout()" title="Logout">🚪</button>
      </div>
    `;
  }
  
  // Show/hide settings link based on admin role
  const settingsLink = document.getElementById('settings-link');
  if (settingsLink && currentUser) {
    settingsLink.style.display = currentUser.role === 'admin' ? 'inline-block' : 'none';
  }
}

async function loadBranding() {
  try {
    const response = await fetch('/api/settings/branding');
    if (response.ok) {
      const branding = await response.json();
      
      // Update page title
      if (branding.siteTitle) {
        document.title = branding.siteTitle;
        const siteTitle = document.getElementById('site-title');
        if (siteTitle) {
          siteTitle.textContent = '🎮 ' + branding.siteTitle;
        }
      }
      
      // Update favicon if provided
      if (branding.siteIcon) {
        let favicon = document.querySelector('link[rel="icon"]');
        if (!favicon) {
          favicon = document.createElement('link');
          favicon.rel = 'icon';
          document.head.appendChild(favicon);
        }
        favicon.href = branding.siteIcon;
      }
      
      // Update footer
      const footer = document.getElementById('app-footer');
      if (footer) {
        let footerContent = '';
        if (branding.footerAddition) {
          footerContent = branding.footerAddition + ' | ';
        }
        footerContent += 'Made By TwiStarSystems © All Rights Reserved';
        footer.innerHTML = footerContent;
      }
    }
  } catch (err) {
    console.log('Failed to load branding:', err);
  }
}

async function logout() {
  if (!confirm('Are you sure you want to logout?')) return;
  
  try {
    await fetch('/api/auth/logout', { method: 'POST' });
  } catch (err) {
    // Ignore errors
  }
  window.location.href = '/login.html';
}

// ==================== Profile Settings ====================

function openProfileSettings() {
  try {
    // Populate profile display section (read-only)
    document.getElementById('profile-display-username').textContent = currentUser.username;
    const roleDisplay = document.getElementById('profile-display-role');
    roleDisplay.textContent = currentUser.role.toUpperCase();
    roleDisplay.className = 'profile-info-value profile-role-badge ' + currentUser.role;
    
    // Populate editable fields
    document.getElementById('profile-username').value = currentUser.username;
    document.getElementById('profile-name').value = currentUser.name || '';
    document.getElementById('profile-email').value = currentUser.email || '';
    
    // Clear password fields
    document.getElementById('profile-old-password').value = '';
    document.getElementById('profile-new-password').value = '';
    document.getElementById('profile-confirm-password').value = '';
    
    // Update MFA status
    updateMFAStatus();
    
    // Show modal
    document.getElementById('profile-modal').style.display = 'flex';
  } catch (err) {
    console.error('Error opening profile settings:', err);
    // Still show the modal even if there's an error
    document.getElementById('profile-modal').style.display = 'flex';
  }
}

function closeProfileModal() {
  document.getElementById('profile-modal').style.display = 'none';
}

async function saveProfileSettings() {
  const username = document.getElementById('profile-username').value.trim();
  const name = document.getElementById('profile-name').value.trim();
  const email = document.getElementById('profile-email').value.trim();
  
  if (!username) {
    showNotification('Username is required', 'error');
    return;
  }
  
  try {
    // Update username if changed
    if (username !== currentUser.username) {
      const usernameResponse = await fetch('/api/auth/profile/username', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username })
      });
      
      const usernameData = await usernameResponse.json();
      
      if (!usernameResponse.ok) {
        showNotification(usernameData.error || 'Failed to update username', 'error');
        return;
      }
      
      currentUser.username = username;
    }
    
    // Update name if changed
    if (name !== (currentUser.name || '')) {
      const nameResponse = await fetch('/api/auth/profile/name', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
      });
      
      const nameData = await nameResponse.json();
      
      if (!nameResponse.ok) {
        showNotification(nameData.error || 'Failed to update name', 'error');
        return;
      }
      
      currentUser.name = name;
    }
    
    // Update email if changed
    if (email !== (currentUser.email || '')) {
      const emailResponse = await fetch('/api/auth/profile/email', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email })
      });
      
      const emailData = await emailResponse.json();
      
      if (!emailResponse.ok) {
        showNotification(emailData.error || 'Failed to update email', 'error');
        return;
      }
      
      currentUser.email = email;
    }
    
    showNotification('Profile updated successfully', 'success');
    updateUserUI();
    closeProfileModal();
  } catch (err) {
    showNotification('Failed to update profile: ' + err.message, 'error');
  }
}

async function changePassword() {
  const oldPassword = document.getElementById('profile-old-password').value;
  const newPassword = document.getElementById('profile-new-password').value;
  const confirmPassword = document.getElementById('profile-confirm-password').value;
  
  // Validation
  if (!oldPassword || !newPassword || !confirmPassword) {
    showNotification('All password fields are required', 'error');
    return;
  }
  
  if (newPassword !== confirmPassword) {
    showNotification('New passwords do not match', 'error');
    return;
  }
  
  if (newPassword.length < 6) {
    showNotification('New password must be at least 6 characters', 'error');
    return;
  }
  
  try {
    const response = await fetch('/api/auth/password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        oldPassword,
        newPassword
      })
    });
    
    const data = await response.json();
    
    if (!response.ok) {
      showNotification(data.error || 'Failed to change password', 'error');
      return;
    }
    
    showNotification('Password changed successfully', 'success');
    
    // Clear password fields
    document.getElementById('profile-old-password').value = '';
    document.getElementById('profile-new-password').value = '';
    document.getElementById('profile-confirm-password').value = '';
  } catch (err) {
    showNotification('Failed to change password: ' + err.message, 'error');
  }
}

// ==================== MFA Functions ====================

let currentMFASecret = null;
let currentRecoveryCode = null;

console.log('MFA Functions loaded - v2.0'); // Debug marker

function updateMFAStatus() {
  if (!currentUser) {
    console.warn('currentUser not defined yet');
    return;
  }
  
  const mfaEnabled = currentUser.mfaEnabled === true;
  
  const mfaDisabledView = document.getElementById('mfa-disabled-view');
  const mfaEnabledView = document.getElementById('mfa-enabled-view');
  const mfaSetupSection = document.getElementById('mfa-setup-section');
  const mfaRecoverySection = document.getElementById('mfa-recovery-section');
  
  if (mfaDisabledView) mfaDisabledView.style.display = mfaEnabled ? 'none' : 'block';
  if (mfaEnabledView) mfaEnabledView.style.display = mfaEnabled ? 'block' : 'none';
  if (mfaSetupSection) mfaSetupSection.style.display = 'none';
  if (mfaRecoverySection) mfaRecoverySection.style.display = 'none';
}

async function setupMFA() {
  try {
    const response = await fetch('/api/auth/mfa/setup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    
    const data = await response.json();
    
    if (!response.ok) {
      showNotification(data.error || 'Failed to setup MFA', 'error');
      return;
    }
    
    currentMFASecret = data.secret;
    
    // Display QR code
    document.getElementById('mfa-qr-code').src = data.qrCode;
    document.getElementById('mfa-secret-text').value = data.manualEntry;
    
    // Show setup section
    document.getElementById('mfa-status-section').style.display = 'none';
    document.getElementById('mfa-setup-section').style.display = 'block';
    document.getElementById('mfa-verify-code').value = '';
  } catch (err) {
    showNotification('Failed to setup MFA: ' + err.message, 'error');
  }
}

function copyMFASecret() {
  const secretInput = document.getElementById('mfa-secret-text');
  secretInput.select();
  document.execCommand('copy');
  showNotification('Secret copied to clipboard', 'success');
}

async function verifyMFACode() {
  const code = document.getElementById('mfa-verify-code').value.trim();
  
  if (!code || code.length !== 6) {
    showNotification('Please enter a 6-digit code', 'error');
    return;
  }
  
  try {
    const response = await fetch('/api/auth/mfa/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        secret: currentMFASecret,
        code: code
      })
    });
    
    const data = await response.json();
    
    if (!response.ok) {
      showNotification(data.error || 'Invalid verification code', 'error');
      return;
    }
    
    currentRecoveryCode = data.recoveryCode;
    
    // Show recovery code
    document.getElementById('mfa-recovery-code').textContent = currentRecoveryCode;
    document.getElementById('mfa-setup-section').style.display = 'none';
    document.getElementById('mfa-recovery-section').style.display = 'block';
    
    // Enable complete button when checkbox is checked
    document.getElementById('mfa-recovery-confirm').addEventListener('change', (e) => {
      document.getElementById('mfa-complete-btn').disabled = !e.target.checked;
    });
  } catch (err) {
    showNotification('Failed to verify code: ' + err.message, 'error');
  }
}

function copyRecoveryCode() {
  const code = document.getElementById('mfa-recovery-code').textContent;
  navigator.clipboard.writeText(code).then(() => {
    showNotification('Recovery code copied to clipboard', 'success');
  }).catch(() => {
    // Fallback for older browsers
    const textarea = document.createElement('textarea');
    textarea.value = code;
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
    showNotification('Recovery code copied to clipboard', 'success');
  });
}

function completeMFASetup() {
  showNotification('MFA has been enabled successfully!', 'success');
  currentUser.mfaEnabled = true;
  
  // Reset view
  document.getElementById('mfa-recovery-section').style.display = 'none';
  document.getElementById('mfa-status-section').style.display = 'block';
  document.getElementById('mfa-recovery-confirm').checked = false;
  updateMFAStatus();
  
  currentMFASecret = null;
  currentRecoveryCode = null;
}

function cancelMFASetup() {
  document.getElementById('mfa-setup-section').style.display = 'none';
  document.getElementById('mfa-status-section').style.display = 'block';
  currentMFASecret = null;
}

async function disableMFA() {
  const password = prompt('Enter your password to disable MFA:');
  
  if (!password) return;
  
  try {
    const response = await fetch('/api/auth/mfa/disable', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password })
    });
    
    const data = await response.json();
    
    if (!response.ok) {
      showNotification(data.error || 'Failed to disable MFA', 'error');
      return;
    }
    
    showNotification('MFA has been disabled', 'success');
    currentUser.mfaEnabled = false;
    updateMFAStatus();
  } catch (err) {
    showNotification('Failed to disable MFA: ' + err.message, 'error');
  }
}


// ==================== Socket.IO Connection ====================

function connectWebSocket() {
  socket = io();
  
  socket.on('connect', () => {
    console.log('Socket.IO connected');
    // Subscribe to current server if selected
    if (currentServerId) {
      // Clear terminal before re-subscribing to avoid duplicate logs
      clearTerminal();
      socket.emit('subscribe', { serverId: currentServerId });
    }
  });
  
  socket.on('message', (data) => {
    // Only process messages for the currently selected server
    if (data.serverId === currentServerId) {
      if (data.type === 'output' || data.type === 'error' || data.type === 'info') {
        appendTerminalOutput(data.data);
      }
      if (data.type === 'status') {
        const status = data.status || (data.running ? 'running' : 'stopped');
        updateServerStatus(status, data.running);
      }
    }
    // Update server list status
    if (data.type === 'status') {
      const status = data.status || (data.running ? 'running' : 'stopped');
      updateServerInList(data.serverId, data.running, status);
    }
  });
  
  socket.on('disconnect', () => {
    console.log('Socket.IO disconnected');
  });
  
  socket.on('connect_error', (error) => {
    console.error('Socket.IO error:', error);
  });
  
  // Listen for scheduled backup events
  socket.on('backup_completed', (data) => {
    if (data.scheduled) {
      showNotification(`📅 Scheduled backup completed for server: ${data.backup}`, 'success');
      // Refresh backup list if we're on that server
      if (data.serverId === currentServerId) {
        loadBackups();
      }
    }
  });
  
  socket.on('backup_failed', (data) => {
    if (data.scheduled) {
      showNotification(`❌ Scheduled backup failed: ${data.error}`, 'error');
    }
  });
}

// ==================== API Functions ====================

async function apiRequest(url, options = {}) {
  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers
      }
    });
    
    // Handle authentication errors
    if (response.status === 401) {
      window.location.href = '/login.html';
      throw new Error('Session expired. Please login again.');
    }
    
    const data = await response.json();
    if (!response.ok && data.error) {
      throw new Error(data.error);
    }
    return data;
  } catch (error) {
    console.error('API request failed:', error);
    alert('Error: ' + error.message);
    throw error;
  }
}

// ==================== Server List Management ====================

async function loadServers() {
  try {
    const data = await apiRequest('/api/servers');
    servers = data.servers || [];
    renderServerList();
  } catch (error) {
    console.error('Failed to load servers:', error);
  }
}

function renderServerList() {
  const container = document.getElementById('server-list');
  
  if (servers.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <p>No servers configured</p>
        <small>Click "Add" to create one</small>
      </div>
    `;
    return;
  }
  
  container.innerHTML = servers.map(server => {
    const status = server.status || 'stopped';
    const statusClasses = {
      'stopped': 'status-stopped',
      'starting': 'status-starting',
      'running': 'status-running',
      'stopping': 'status-stopping',
      'unresponsive': 'status-unresponsive'
    };
    
    const statusTexts = {
      'stopped': 'Stopped',
      'starting': 'Starting...',
      'running': server.port ? `Running - ${server.port}` : 'Running',
      'stopping': 'Stopping...',
      'unresponsive': 'Unresponsive'
    };
    
    return `
      <div class="server-item ${server.id === currentServerId ? 'active' : ''}" 
           data-server-id="${server.id}" 
           onclick="selectServer('${server.id}')">
        <div class="server-item-status ${statusClasses[status] || 'status-stopped'}">●</div>
        <div class="server-item-info">
          <div class="server-item-name">${escapeHtml(server.name)}</div>
          <div class="server-item-state">${statusTexts[status] || 'Unknown'}</div>
        </div>
      </div>
    `;
  }).join('');
}

function updateServerInList(serverId, isRunning, status) {
  const server = servers.find(s => s.id === serverId);
  if (server) {
    server.running = isRunning;
    server.status = status || (isRunning ? 'running' : 'stopped');
    renderServerList();
  }
}

// ==================== Server Selection ====================

async function selectServer(serverId) {
  currentServerId = serverId;
  currentPath = '';
  
  // Update UI
  document.getElementById('no-server-view').style.display = 'none';
  document.getElementById('server-view').style.display = 'flex';
  
  // Update server list selection
  renderServerList();
  
  // Clear terminal
  clearTerminal();
  
  // Subscribe to server output
  if (socket && socket.connected) {
    socket.emit('subscribe', { serverId: currentServerId });
  }
  
  // Load server details
  await loadServerDetails();
  
  // Switch to terminal tab
  switchTab('terminal');
}

async function loadServerDetails() {
  if (!currentServerId) return;
  
  try {
    const server = await apiRequest(`/api/servers/${currentServerId}`);
    
    // Update header
    document.getElementById('server-name').textContent = server.name;
    const status = server.status || (server.running ? 'running' : 'stopped');
    updateServerStatus(status, server.running);
    
    // Show/hide Mods tab based on server category
    const modsTabBtn = document.getElementById('mods-tab-btn');
    if (server.category === 'modded') {
      modsTabBtn.style.display = '';
    } else {
      modsTabBtn.style.display = 'none';
      // If currently on mods tab, switch to terminal
      if (document.querySelector('.tab-button.active[data-tab="mods"]')) {
        switchTab('terminal');
      }
    }
    
    // Check if server.properties exists and show/hide Properties tab
    const propertiesTabBtn = document.getElementById('properties-tab-btn');
    try {
      const propsCheck = await apiRequest(`/api/servers/${currentServerId}/properties/exists`);
      if (propsCheck.exists) {
        propertiesTabBtn.style.display = '';
      } else {
        propertiesTabBtn.style.display = 'none';
        if (document.querySelector('.tab-button.active[data-tab="properties"]')) {
          switchTab('terminal');
        }
      }
    } catch (err) {
      propertiesTabBtn.style.display = 'none';
    }
  } catch (error) {
    console.error('Failed to load server details:', error);
  }
}

function updateServerStatus(status, isRunning) {
  const indicator = document.getElementById('status-indicator');
  const text = document.getElementById('status-text');
  const startBtn = document.getElementById('start-btn');
  const stopBtn = document.getElementById('stop-btn');
  const killBtn = document.getElementById('kill-btn');
  const terminalInput = document.getElementById('terminal-input');
  const sendBtn = document.getElementById('send-btn');
  
  // Fallback to 'stopped' if status is undefined
  status = status || 'stopped';
  
  // Update status indicator and text
  const statusClasses = {
    'stopped': 'status-stopped',
    'starting': 'status-starting',
    'running': 'status-running',
    'stopping': 'status-stopping',
    'unresponsive': 'status-unresponsive'
  };
  
  const statusTexts = {
    'stopped': 'Stopped',
    'starting': 'Starting...',
    'running': 'Running',
    'stopping': 'Stopping...',
    'unresponsive': 'Unresponsive'
  };
  
  indicator.className = statusClasses[status] || 'status-stopped';
  text.textContent = statusTexts[status] || 'Unknown';
  
  // Button states based on status
  const canStart = status === 'stopped';
  const canStop = status === 'running' || status === 'unresponsive';
  const canKill = status === 'starting' || status === 'running' || status === 'stopping' || status === 'unresponsive';
  const canCommand = status === 'running';
  
  startBtn.disabled = !canStart;
  stopBtn.disabled = !canStop;
  killBtn.disabled = !canKill;
  terminalInput.disabled = !canCommand;
  sendBtn.disabled = !canCommand;
  
  // Update server in list
  updateServerInList(currentServerId, isRunning, status);
}

// ==================== Server Actions ====================

async function startServer() {
  if (!currentServerId) return;
  
  try {
    // First check if server is managed (has managed.conf) and validate fields
    const managedCheck = await apiRequest(`/api/servers/${currentServerId}/managed`);
    
    if (!managedCheck.managed) {
      // Show management modal
      showManagementModal();
      return;
    }
    
    // Check if managed.conf has all required fields
    if (!managedCheck.valid && managedCheck.missingFields && managedCheck.missingFields.length > 0) {
      showMissingFieldsModal(managedCheck.missingFields, managedCheck.data);
      return;
    }
    
    // Check if EULA has been accepted
    const eulaCheck = await apiRequest(`/api/servers/${currentServerId}/eula`);
    
    if (!eulaCheck.accepted) {
      // Show EULA acceptance modal
      showEulaModal();
      return;
    }
    
    // All checks passed, start the server
    // Clear terminal before starting
    clearTerminal();
    
    const result = await apiRequest(`/api/servers/${currentServerId}/start`, { method: 'POST' });
    if (result.success) {
      appendTerminalOutput('Starting server...\n');
      updateServerStatus('starting', false);
    }
  } catch (error) {
    // Error already shown by apiRequest
  }
}

function showMissingFieldsModal(missingFields, currentData) {
  // Remove existing modal if any
  const existing = document.getElementById('missing-fields-modal');
  if (existing) existing.remove();
  
  const server = servers.find(s => s.id === currentServerId);
  
  // Build form fields for missing items
  let fieldsHtml = '';
  
  for (const field of missingFields) {
    let inputHtml = '';
    
    switch(field) {
      case 'Engine':
        inputHtml = `
          <select id="missing-${field}" class="form-control" required>
            <option value="">Select engine...</option>
            <option value="Vanilla">Vanilla</option>
            <option value="Paper">Paper</option>
            <option value="Folia">Folia</option>
            <option value="Purpur">Purpur</option>
            <option value="Spigot">Spigot</option>
            <option value="Forge">Forge</option>
            <option value="NeoForge">NeoForge</option>
            <option value="Fabric">Fabric</option>
          </select>
        `;
        break;
      case 'Modded':
        inputHtml = `
          <select id="missing-${field}" class="form-control" required>
            <option value="">Select...</option>
            <option value="false">No (Vanilla)</option>
            <option value="true">Yes (Modded/Plugins)</option>
          </select>
        `;
        break;
      case 'EULAAccepted':
        inputHtml = `
          <select id="missing-${field}" class="form-control" required>
            <option value="false">Not Accepted</option>
            <option value="true">Accepted</option>
          </select>
        `;
        break;
      case 'Owner':
        inputHtml = `<input type="text" id="missing-${field}" class="form-control" placeholder="Username" value="${currentUser?.username || 'admin'}" required>`;
        break;
      case 'ServerName':
        inputHtml = `<input type="text" id="missing-${field}" class="form-control" placeholder="Server name" value="${escapeHtml(server?.name || '')}" required>`;
        break;
      default:
        inputHtml = `<input type="text" id="missing-${field}" class="form-control" placeholder="Enter value..." required>`;
    }
    
    fieldsHtml += `
      <div class="form-group">
        <label for="missing-${field}">${field}:</label>
        ${inputHtml}
      </div>
    `;
  }
  
  const modal = document.createElement('div');
  modal.id = 'missing-fields-modal';
  modal.className = 'modal active';
  modal.innerHTML = `
    <div class="modal-content modal-medium">
      <div class="modal-header">
        <h2>⚠️ Configuration Incomplete</h2>
        <button class="close-btn" onclick="closeMissingFieldsModal()">&times;</button>
      </div>
      <div class="missing-fields-content">
        <p>The <code>managed.conf</code> file for <strong>"${escapeHtml(server?.name || 'this server')}"</strong> is missing some required fields.</p>
        <p class="missing-fields-info">Please provide the following information:</p>
        <form id="missing-fields-form" onsubmit="submitMissingFields(event)">
          ${fieldsHtml}
          <div class="modal-footer">
            <button type="button" class="btn" onclick="closeMissingFieldsModal()">Cancel</button>
            <button type="submit" class="btn btn-success">Save & Continue</button>
          </div>
        </form>
      </div>
    </div>
  `;
  
  document.body.appendChild(modal);
  
  // Close on background click
  modal.onclick = (e) => {
    if (e.target.id === 'missing-fields-modal') closeMissingFieldsModal();
  };
}

function closeMissingFieldsModal() {
  const modal = document.getElementById('missing-fields-modal');
  if (modal) modal.remove();
}

async function submitMissingFields(e) {
  e.preventDefault();
  
  const form = document.getElementById('missing-fields-form');
  const inputs = form.querySelectorAll('input, select');
  
  const data = {};
  for (const input of inputs) {
    const field = input.id.replace('missing-', '');
    data[field] = input.value;
  }
  
  try {
    await apiRequest(`/api/servers/${currentServerId}/managed/update`, {
      method: 'POST',
      body: JSON.stringify(data)
    });
    
    closeMissingFieldsModal();
    showNotification('Configuration updated successfully', 'success');
    
    // Try starting the server again
    startServer();
  } catch (error) {
    console.error('Failed to update managed.conf:', error);
  }
}

function showManagementModal() {
  // Remove existing modal if any
  const existing = document.getElementById('management-modal');
  if (existing) existing.remove();
  
  const server = servers.find(s => s.id === currentServerId);
  
  const modal = document.createElement('div');
  modal.id = 'management-modal';
  modal.className = 'modal active';
  modal.innerHTML = `
    <div class="modal-content modal-medium">
      <div class="modal-header">
        <h2>📋 Enable Server Management</h2>
        <button class="close-btn" onclick="closeManagementModal()">&times;</button>
      </div>
      <div class="management-content">
        <p>The server <strong>"${escapeHtml(server?.name || 'this server')}"</strong> is not yet fully managed by MServerController.</p>
        <div class="management-notice">
          <p>Enabling management will:</p>
          <ul>
            <li>Create a <code>managed.conf</code> file in the server directory</li>
            <li>Allow MServerController to track server settings and status</li>
            <li>Enable EULA acceptance and other management features</li>
          </ul>
        </div>
        <p class="management-info">ℹ️ This is required for servers imported before management tracking was added, or after app updates.</p>
      </div>
      <div class="modal-footer">
        <button class="btn" onclick="closeManagementModal()">Cancel</button>
        <button class="btn btn-success" onclick="enableManagementAndContinue()">Enable Management</button>
      </div>
    </div>
  `;
  
  document.body.appendChild(modal);
  
  // Close on background click
  modal.onclick = (e) => {
    if (e.target.id === 'management-modal') closeManagementModal();
  };
}

function closeManagementModal() {
  const modal = document.getElementById('management-modal');
  if (modal) modal.remove();
}

async function enableManagementAndContinue() {
  if (!currentServerId) return;
  
  try {
    // Enable management
    const result = await apiRequest(`/api/servers/${currentServerId}/managed/enable`, { method: 'POST' });
    
    if (result.success) {
      closeManagementModal();
      showNotification('Server management enabled', 'success');
      
      // Continue with the start process (will check EULA next)
      await startServer();
    }
  } catch (error) {
    showNotification('Failed to enable management: ' + error.message, 'error');
  }
}

function showEulaModal() {
  // Remove existing modal if any
  const existing = document.getElementById('eula-modal');
  if (existing) existing.remove();
  
  const modal = document.createElement('div');
  modal.id = 'eula-modal';
  modal.className = 'modal active';
  modal.innerHTML = `
    <div class="modal-content modal-medium">
      <div class="modal-header">
        <h2>⚠️ Minecraft EULA</h2>
        <button class="close-btn" onclick="closeEulaModal()">&times;</button>
      </div>
      <div class="eula-content">
        <p>Before starting this Minecraft server, you must accept the <strong>Minecraft End User License Agreement (EULA)</strong>.</p>
        <div class="eula-notice">
          <p>By clicking "Accept EULA", you agree that:</p>
          <ul>
            <li>You have read and agree to the <a href="https://aka.ms/MinecraftEULA" target="_blank">Minecraft EULA</a></li>
            <li>You understand the terms and conditions set by Mojang/Microsoft</li>
            <li>This will create an <code>eula.txt</code> file with <code>eula=true</code></li>
          </ul>
        </div>
        <p class="eula-warning">⚠️ You must accept the EULA to run a Minecraft server.</p>
      </div>
      <div class="modal-footer">
        <button class="btn" onclick="closeEulaModal()">Cancel</button>
        <button class="btn btn-success" onclick="acceptEulaAndStart()">Accept EULA & Start Server</button>
      </div>
    </div>
  `;
  
  document.body.appendChild(modal);
  
  // Close on background click
  modal.onclick = (e) => {
    if (e.target.id === 'eula-modal') closeEulaModal();
  };
}

function closeEulaModal() {
  const modal = document.getElementById('eula-modal');
  if (modal) modal.remove();
}

async function acceptEulaAndStart() {
  if (!currentServerId) return;
  
  try {
    // Accept EULA
    const acceptResult = await apiRequest(`/api/servers/${currentServerId}/eula/accept`, { method: 'POST' });
    
    if (acceptResult.success) {
      closeEulaModal();
      showNotification('EULA accepted successfully', 'success');
      
      // Now start the server
      const result = await apiRequest(`/api/servers/${currentServerId}/start`, { method: 'POST' });
      if (result.success) {
        appendTerminalOutput('EULA accepted. Starting server...\n');
        updateServerStatus(true);
      }
    }
  } catch (error) {
    showNotification('Failed to accept EULA: ' + error.message, 'error');
  }
}

async function stopServer() {
  if (!currentServerId) return;
  
  try {
    const result = await apiRequest(`/api/servers/${currentServerId}/stop`, { method: 'POST' });
    if (result.success) {
      appendTerminalOutput('Stopping server gracefully...\n');
      setTimeout(() => loadServerDetails(), 2000);
    }
  } catch (error) {
    // Error already shown by apiRequest
  }
}

async function killServer() {
  if (!currentServerId) return;
  
  if (!confirm('Are you sure you want to forcefully kill the server?\n\nThis will immediately terminate the process without saving. Use only if the server is unresponsive.')) {
    return;
  }
  
  try {
    const result = await apiRequest(`/api/servers/${currentServerId}/kill`, { method: 'POST' });
    if (result.success) {
      appendTerminalOutput('Server process killed.\n');
      updateServerStatus(false);
    }
  } catch (error) {
    // Error already shown by apiRequest
  }
}

// ==================== Server CRUD ====================

let serverTypes = [];
let currentCreationType = null;
let defaultServerPath = '';

async function openAddServerModal() {
  editingServerId = null;
  currentCreationType = null;
  
  document.getElementById('modal-title').textContent = 'Add Server';
  
  // Show creation type selection, hide all forms
  document.getElementById('creation-type-section').style.display = 'block';
  document.getElementById('fresh-server-form').style.display = 'none';
  document.getElementById('import-server-form').style.display = 'none';
  document.getElementById('manual-server-form').style.display = 'none';
  
  // Fetch the default server path
  try {
    const result = await apiRequest('/api/default-server-path');
    defaultServerPath = result.path || '';
  } catch (err) {
    console.error('Failed to get default server path:', err);
    defaultServerPath = '';
  }
  
  // Reset fresh server form
  document.getElementById('fresh-name').value = '';
  document.getElementById('fresh-category').value = '';
  document.getElementById('fresh-version').value = '';
  document.getElementById('fresh-version').disabled = true;
  document.getElementById('fresh-jar-name').value = 'server.jar';
  document.getElementById('fresh-min-ram').value = '1G';
  document.getElementById('fresh-max-ram').value = '2G';
  document.getElementById('fresh-jvm-args').value = '';
  document.getElementById('fresh-upload-jar').checked = false;
  document.getElementById('custom-jar-upload').style.display = 'none';
  
  // Hide conditional fields
  document.getElementById('engine-group').style.display = 'none';
  document.getElementById('version-group').style.display = 'none';
  document.getElementById('jar-name-group').style.display = 'none';
  document.getElementById('ram-fields-group').style.display = 'none';
  document.getElementById('upload-jar-group').style.display = 'none';
  
  // Reset download status UI
  const downloadStatusGroup = document.getElementById('download-status-group');
  const versionStatus = document.getElementById('version-status');
  const progressFill = document.querySelector('#jar-download-status .progress-fill');
  const progressText = document.querySelector('#jar-download-status .progress-text');
  const downloadProgress = document.querySelector('#jar-download-status .download-progress');
  const downloadInfo = document.querySelector('#jar-download-status .download-info');
  
  if (downloadStatusGroup) downloadStatusGroup.style.display = 'none';
  if (versionStatus) versionStatus.textContent = '';
  if (progressFill) progressFill.style.width = '0%';
  if (progressText) progressText.textContent = '0%';
  if (downloadProgress) downloadProgress.style.display = 'none';
  if (downloadInfo) {
    downloadInfo.innerHTML = '';
    downloadInfo.classList.remove('error');
  }
  versionAvailability = {};
  
  // Reset import form
  document.getElementById('import-name').value = '';
  document.getElementById('import-file').value = '';
  document.getElementById('import-category').value = 'unmodded';
  document.getElementById('import-jar-name').value = 'server.jar';
  document.getElementById('import-min-ram').value = '1G';
  document.getElementById('import-max-ram').value = '2G';
  document.getElementById('import-jvm-args').value = '';
  
  // Reset manual form with default path placeholder
  document.getElementById('input-name').value = '';
  document.getElementById('input-category').value = 'unmodded';
  document.getElementById('input-path').value = '';
  document.getElementById('input-path').placeholder = defaultServerPath ? `${defaultServerPath}/<server-id>` : '/path/to/minecraft/server';
  document.getElementById('input-executable').value = 'server.jar';
  document.getElementById('input-min-ram').value = '1G';
  document.getElementById('input-max-ram').value = '2G';
  document.getElementById('input-jvm-args').value = '';
  
  // Update path hint with actual default path
  const pathHint = document.getElementById('path-hint');
  if (pathHint && defaultServerPath) {
    pathHint.innerHTML = `Leave empty to auto-create in <code>${defaultServerPath}/</code>`;
  }
  
  // Load server engines for fresh server option
  loadServerEngines();
  
  document.getElementById('server-modal').classList.add('active');
}

function selectCreationType(type) {
  currentCreationType = type;
  
  // Hide creation type section
  document.getElementById('creation-type-section').style.display = 'none';
  
  // Show the appropriate form
  if (type === 'fresh') {
    document.getElementById('fresh-server-form').style.display = 'block';
  } else if (type === 'import') {
    document.getElementById('import-server-form').style.display = 'block';
  } else if (type === 'manual') {
    document.getElementById('manual-server-form').style.display = 'block';
    // Show the back button in manual mode
    document.querySelector('#manual-server-form .back-btn').style.display = 'inline-block';
  }
}

function backToCreationType() {
  currentCreationType = null;
  
  // Hide all forms
  document.getElementById('fresh-server-form').style.display = 'none';
  document.getElementById('import-server-form').style.display = 'none';
  document.getElementById('manual-server-form').style.display = 'none';
  
  // Show creation type selection
  document.getElementById('creation-type-section').style.display = 'block';
}

// Track JAR availability for versions
let versionAvailability = {};  // {version: {downloaded: bool}}

// Handle category change for fresh server form
function onCategoryChange() {
  const category = document.getElementById('fresh-category').value;
  const engineGroup = document.getElementById('engine-group');
  const versionGroup = document.getElementById('version-group');
  const jarNameGroup = document.getElementById('jar-name-group');
  const ramFieldsGroup = document.getElementById('ram-fields-group');
  const uploadJarGroup = document.getElementById('upload-jar-group');
  const downloadStatusGroup = document.getElementById('download-status-group');
  const versionSelect = document.getElementById('fresh-version');
  const categoryDesc = document.getElementById('category-description');
  
  // Reset version availability
  versionAvailability = {};
  
  // Hide download status
  if (downloadStatusGroup) downloadStatusGroup.style.display = 'none';
  
  if (!category) {
    // Hide all conditional fields
    engineGroup.style.display = 'none';
    versionGroup.style.display = 'none';
    jarNameGroup.style.display = 'none';
    ramFieldsGroup.style.display = 'none';
    uploadJarGroup.style.display = 'none';
    categoryDesc.textContent = 'Choose whether you want a vanilla or modded server';
    return;
  }
  
  if (category === 'unmodded') {
    // Unmodded: Hide engine, show version directly
    engineGroup.style.display = 'none';
    versionGroup.style.display = 'block';
    jarNameGroup.style.display = 'block';
    ramFieldsGroup.style.display = 'block';
    uploadJarGroup.style.display = 'block';
    categoryDesc.textContent = 'Official Minecraft server - no mods or plugins';
    
    // Load vanilla versions from JAR Bucket
    loadVersionsForEngine('vanilla');
  } else if (category === 'modded') {
    // Modded: Show engine selector
    engineGroup.style.display = 'block';
    versionGroup.style.display = 'none';
    jarNameGroup.style.display = 'none';
    ramFieldsGroup.style.display = 'none';
    uploadJarGroup.style.display = 'none';
    categoryDesc.textContent = 'Supports plugins and/or mods';
    
    // Reset engine and version
    document.getElementById('fresh-engine').value = '';
    versionSelect.innerHTML = '<option value="">Select server engine first...</option>';
    versionSelect.disabled = true;
  }
}

async function loadServerEngines() {
  try {
    // Load all available server types from JAR Bucket (not just local)
    const result = await apiRequest('/api/jar-bucket/all-types');
    const allTypes = result.types || [];
    
    // Filter to server types (not proxies)
    const serverTypes = allTypes.filter(t => t.category === 'servers' || t.category === 'modded');
    
    // Filter to only modded engines (exclude vanilla)
    const moddedEngines = serverTypes.filter(e => e.id !== 'vanilla');
    
    const engineSelect = document.getElementById('fresh-engine');
    
    if (moddedEngines.length === 0) {
      engineSelect.innerHTML = '<option value="">No server types available</option>';
      engineSelect.disabled = true;
      document.getElementById('engine-description').textContent = 
        'No server types found.';
      return;
    }
    
    engineSelect.innerHTML = '<option value="">Select server engine...</option>';
    engineSelect.disabled = false;
    
    moddedEngines.forEach(engine => {
      const option = document.createElement('option');
      option.value = engine.id;
      option.textContent = `${engine.icon || '📦'} ${engine.name}`;
      option.dataset.description = engine.description || '';
      engineSelect.appendChild(option);
    });
  } catch (error) {
    console.error('Failed to load server engines:', error);
    const engineSelect = document.getElementById('fresh-engine');
    engineSelect.innerHTML = '<option value="">Error loading server engines</option>';
  }
}

async function loadVersions() {
  const engineSelect = document.getElementById('fresh-engine');
  const versionSelect = document.getElementById('fresh-version');
  const engineDesc = document.getElementById('engine-description');
  const versionGroup = document.getElementById('version-group');
  const jarNameGroup = document.getElementById('jar-name-group');
  const ramFieldsGroup = document.getElementById('ram-fields-group');
  const uploadJarGroup = document.getElementById('upload-jar-group');
  const downloadStatusGroup = document.getElementById('download-status-group');
  
  const serverEngine = engineSelect.value;
  
  // Reset version availability
  versionAvailability = {};
  
  // Hide download status
  if (downloadStatusGroup) downloadStatusGroup.style.display = 'none';
  
  if (!serverEngine) {
    versionSelect.innerHTML = '<option value="">Select server engine first...</option>';
    versionSelect.disabled = true;
    versionGroup.style.display = 'none';
    jarNameGroup.style.display = 'none';
    ramFieldsGroup.style.display = 'none';
    uploadJarGroup.style.display = 'none';
    engineDesc.textContent = '';
    return;
  }
  
  // Show engine description
  const selectedOption = engineSelect.options[engineSelect.selectedIndex];
  engineDesc.textContent = selectedOption.dataset.description || '';
  
  // Show remaining fields
  versionGroup.style.display = 'block';
  jarNameGroup.style.display = 'block';
  ramFieldsGroup.style.display = 'block';
  uploadJarGroup.style.display = 'block';
  
  await loadVersionsForEngine(serverEngine);
}

async function loadVersionsForEngine(serverEngine) {
  const versionSelect = document.getElementById('fresh-version');
  const versionStatus = document.getElementById('version-status');
  
  try {
    versionSelect.innerHTML = '<option value="">Loading versions...</option>';
    versionSelect.disabled = true;
    if (versionStatus) versionStatus.textContent = '';
    
    // Use JAR Bucket API to get all available versions (not just local)
    const result = await apiRequest(`/api/jar-bucket/all-versions/${serverEngine}`);
    const versions = result.versions || [];
    
    if (versions.length === 0) {
      versionSelect.innerHTML = '<option value="">No versions available</option>';
      return;
    }
    
    // Store availability info
    versionAvailability = {};
    versions.forEach(v => {
      versionAvailability[v.version] = { downloaded: v.downloaded };
    });
    
    versionSelect.innerHTML = '<option value="">Select version...</option>';
    versions.forEach(v => {
      const option = document.createElement('option');
      option.value = v.version;
      option.textContent = v.downloaded 
        ? `${v.version} ✓ (Downloaded)` 
        : v.version;
      option.dataset.downloaded = v.downloaded;
      versionSelect.appendChild(option);
    });
    versionSelect.disabled = false;
  } catch (error) {
    console.error('Failed to load versions:', error);
    versionSelect.innerHTML = '<option value="">Error loading versions</option>';
  }
}

// Handle version selection change
function onVersionChange() {
  const version = document.getElementById('fresh-version').value;
  const downloadStatusGroup = document.getElementById('download-status-group');
  const versionStatus = document.getElementById('version-status');
  const versionDesc = document.getElementById('version-description');
  
  // Always hide download status until Create Server is clicked
  if (downloadStatusGroup) downloadStatusGroup.style.display = 'none';
  
  if (!version) {
    if (versionStatus) versionStatus.textContent = '';
    if (versionDesc) versionDesc.textContent = 'Select the Minecraft version';
    return;
  }
  
  const info = versionAvailability[version] || {};
  
  if (info.downloaded) {
    // JAR is available locally
    if (versionStatus) {
      versionStatus.textContent = '✓ Downloaded';
      versionStatus.className = 'version-status downloaded';
    }
    if (versionDesc) versionDesc.textContent = 'JAR file is already downloaded and ready to use';
  } else {
    // JAR needs to be downloaded
    if (versionStatus) {
      versionStatus.textContent = '⬇ Will Download';
      versionStatus.className = 'version-status not-downloaded';
    }
    if (versionDesc) versionDesc.textContent = 'JAR will be automatically downloaded when server is created';
  }
}

async function openEditServerModal() {
  if (!currentServerId) return;
  
  try {
    const server = await apiRequest(`/api/servers/${currentServerId}`);
    
    editingServerId = currentServerId;
    currentCreationType = 'manual';
    
    document.getElementById('modal-title').textContent = 'Edit Server';
    
    // Hide creation type section and other forms
    document.getElementById('creation-type-section').style.display = 'none';
    document.getElementById('fresh-server-form').style.display = 'none';
    document.getElementById('import-server-form').style.display = 'none';
    document.getElementById('manual-server-form').style.display = 'block';
    
    // Hide the back button in edit mode
    document.querySelector('#manual-server-form .back-btn').style.display = 'none';
    
    document.getElementById('input-name').value = server.name || '';
    document.getElementById('input-path').value = server.serverPath || '';
    document.getElementById('input-executable').value = server.executable || 'server.jar';
    document.getElementById('input-category').value = server.category || 'unmodded';
    
    // Parse RAM values and extra JVM args from javaArgs
    const javaArgs = server.javaArgs || '-Xms1G -Xmx2G';
    const minRamMatch = javaArgs.match(/-Xms(\d+[GMK])/i);
    const maxRamMatch = javaArgs.match(/-Xmx(\d+[GMK])/i);
    
    // Extract extra JVM args (everything except -Xms and -Xmx)
    const extraArgs = javaArgs
      .replace(/-Xms\d+[GMK]/gi, '')
      .replace(/-Xmx\d+[GMK]/gi, '')
      .trim();
    
    document.getElementById('input-min-ram').value = minRamMatch ? minRamMatch[1] : '1G';
    document.getElementById('input-max-ram').value = maxRamMatch ? maxRamMatch[1] : '2G';
    document.getElementById('input-jvm-args').value = extraArgs;
    
    document.getElementById('server-modal').classList.add('active');
  } catch (error) {
    console.error('Failed to load server for editing:', error);
  }
}

function closeServerModal() {
  document.getElementById('server-modal').classList.remove('active');
  editingServerId = null;
  currentCreationType = null;
}

// Save server (manual configuration / edit mode)
async function saveServer(e) {
  e.preventDefault();
  
  const category = document.getElementById('input-category').value;
  const minRam = document.getElementById('input-min-ram').value;
  const maxRam = document.getElementById('input-max-ram').value;
  const extraJvmArgs = document.getElementById('input-jvm-args').value.trim();
  const javaArgs = `-Xms${minRam} -Xmx${maxRam}${extraJvmArgs ? ' ' + extraJvmArgs : ''}`;
  
  const serverData = {
    name: document.getElementById('input-name').value,
    serverPath: document.getElementById('input-path').value,
    executable: document.getElementById('input-executable').value,
    javaArgs: javaArgs,
    category: category
  };
  
  try {
    if (editingServerId) {
      // Update existing server
      await apiRequest(`/api/servers/${editingServerId}`, {
        method: 'PUT',
        body: JSON.stringify(serverData)
      });
    } else {
      // Create new server (manual)
      const result = await apiRequest('/api/servers', {
        method: 'POST',
        body: JSON.stringify(serverData)
      });
      
      if (result.pendingApproval) {
        showNotification('Server created and pending admin approval', 'info');
      }
      
      // Select the new server if approved
      await loadServers();
      if (!result.pendingApproval && result.serverId) {
        selectServer(result.serverId);
      }
    }
    
    closeServerModal();
    await loadServers();
    
    if (currentServerId) {
      await loadServerDetails();
    }
  } catch (error) {
    console.error('Failed to save server:', error);
  }
}

// Create fresh server with JAR download
async function createFreshServer(e) {
  e.preventDefault();
  
  const name = document.getElementById('fresh-name').value;
  const category = document.getElementById('fresh-category').value;
  const serverEngine = category === 'modded' 
    ? document.getElementById('fresh-engine').value 
    : 'vanilla';
  const version = document.getElementById('fresh-version').value;
  const executable = document.getElementById('fresh-jar-name').value || 'server.jar';
  const minRam = document.getElementById('fresh-min-ram').value;
  const maxRam = document.getElementById('fresh-max-ram').value;
  const extraJvmArgs = document.getElementById('fresh-jvm-args').value.trim();
  const javaArgs = `-Xms${minRam} -Xmx${maxRam}${extraJvmArgs ? ' ' + extraJvmArgs : ''}`;
  const uploadCustom = document.getElementById('fresh-upload-jar').checked;
  
  // Check JAR availability - automatically download if not available
  const versionInfo = versionAvailability[version] || {};
  const needsDownload = !versionInfo.downloaded;
  
  if (!category) {
    showNotification('Please select a category', 'error');
    return;
  }
  
  if (category === 'modded' && !serverEngine) {
    showNotification('Please select a server engine', 'error');
    return;
  }
  
  if (!uploadCustom && !version) {
    showNotification('Please select a version', 'error');
    return;
  }
  
  // Get UI elements
  const submitBtn = e.target.querySelector('button[type="submit"]');
  const backBtn = e.target.querySelector('.btn:not([type="submit"])');
  const originalText = submitBtn.textContent;
  const downloadStatusGroup = document.getElementById('download-status-group');
  const downloadProgress = document.querySelector('#jar-download-status .download-progress');
  const progressFill = document.querySelector('#jar-download-status .progress-fill');
  const progressText = document.querySelector('#jar-download-status .progress-text');
  const downloadInfo = document.querySelector('#jar-download-status .download-info');
  
  // Reset progress bar to 0
  if (progressFill) progressFill.style.width = '0%';
  if (progressText) progressText.textContent = '0%';
  if (downloadProgress) downloadProgress.style.display = 'none';
  if (downloadStatusGroup) downloadStatusGroup.style.display = 'none';
  
  // Helper to update progress UI
  const updateProgress = (message, percent = null, isError = false) => {
    if (downloadStatusGroup) downloadStatusGroup.style.display = 'block';
    if (downloadInfo) {
      const icon = isError ? '❌' : (percent === 100 ? '✓' : '⏳');
      downloadInfo.innerHTML = `<span class="info-icon">${icon}</span> ${message}`;
      if (isError) downloadInfo.classList.add('error');
      else downloadInfo.classList.remove('error');
    }
    if (percent !== null && downloadProgress) {
      downloadProgress.style.display = 'flex';
      if (progressFill) progressFill.style.width = `${percent}%`;
      if (progressText) progressText.textContent = `${Math.round(percent)}%`;
    }
  };
  
  // Helper to reset UI on error
  const resetOnError = (errorMsg) => {
    submitBtn.textContent = originalText;
    submitBtn.disabled = false;
    if (backBtn) backBtn.disabled = false;
    updateProgress(errorMsg, null, true);
    showNotification(errorMsg, 'error');
  };
  
  try {
    // Disable form controls during creation
    submitBtn.textContent = 'Creating...';
    submitBtn.disabled = true;
    if (backBtn) backBtn.disabled = true;
    
    if (uploadCustom) {
      // Custom JAR upload flow
      const fileInput = document.getElementById('fresh-jar-file');
      if (!fileInput.files.length) {
        resetOnError('Please select a JAR file to upload');
        return;
      }
      
      updateProgress('Creating server...', 10);
      
      // First create the server
      const result = await apiRequest('/api/servers', {
        method: 'POST',
        body: JSON.stringify({
          name,
          executable,
          javaArgs,
          category,
          serverEngine: 'custom'
        })
      });
      
      if (result.pendingApproval) {
        showNotification('Server created and pending admin approval', 'info');
        closeServerModal();
        await loadServers();
        return;
      }
      
      updateProgress('Uploading JAR file...', 50);
      
      // Then upload the JAR
      const formData = new FormData();
      formData.append('file', fileInput.files[0]);
      
      const uploadResponse = await fetch(`/api/servers/${result.serverId}/upload-jar`, {
        method: 'POST',
        body: formData
      });
      
      if (!uploadResponse.ok) {
        const errorData = await uploadResponse.json().catch(() => ({}));
        throw new Error(errorData.error || 'Failed to upload JAR file');
      }
      
      updateProgress('Server created successfully!', 100);
      await new Promise(r => setTimeout(r, 1000)); // Brief pause to show completion
      
      await loadServers();
      selectServer(result.serverId);
      closeServerModal();
      
    } else if (needsDownload) {
      // Need to download from JAR Bucket first
      updateProgress(`Downloading ${serverEngine} ${version}...`, 0);
      submitBtn.textContent = 'Downloading JAR...';
      
      // Start the download
      let downloadResult;
      try {
        downloadResult = await apiRequest('/api/jar-bucket/download', {
          method: 'POST',
          body: JSON.stringify({ type: serverEngine, version })
        });
      } catch (downloadErr) {
        resetOnError(`Failed to start download: ${downloadErr.message}`);
        return;
      }
      
      if (!downloadResult.progress_id) {
        resetOnError('Failed to start download - no progress ID returned');
        return;
      }
      
      // Poll for progress with timeout
      const progressId = downloadResult.progress_id;
      let downloadComplete = false;
      let downloadError = null;
      let pollCount = 0;
      const maxPolls = 600; // 5 minutes timeout (600 * 500ms)
      
      while (!downloadComplete && pollCount < maxPolls) {
        await new Promise(r => setTimeout(r, 500));
        pollCount++;
        
        try {
          const progress = await apiRequest(`/api/jar-bucket/progress/${progressId}`);
          
          if (progress.status === 'downloading') {
            const pct = progress.progress || 0;
            const downloaded = formatBytes(progress.downloaded || 0);
            const total = formatBytes(progress.total || 0);
            updateProgress(`Downloading ${serverEngine} ${version}... (${downloaded} / ${total})`, pct);
          } else if (progress.status === 'complete') {
            downloadComplete = true;
            if (progress.success === false) {
              downloadError = progress.error || 'Download failed';
            } else {
              updateProgress('Download complete!', 100);
            }
          } else if (progress.status === 'error') {
            downloadComplete = true;
            downloadError = progress.error || 'Download failed';
          }
        } catch (pollErr) {
          console.error('Error polling download progress:', pollErr);
          // Don't fail immediately, keep trying
        }
      }
      
      if (!downloadComplete) {
        resetOnError('Download timed out. Please try again.');
        return;
      }
      
      if (downloadError) {
        resetOnError(`Download failed: ${downloadError}`);
        return;
      }
      
      // Now create the server with the downloaded JAR
      submitBtn.textContent = 'Creating Server...';
      updateProgress('Creating server files...', 0);
      
      let result;
      try {
        result = await apiRequest('/api/servers', {
          method: 'POST',
          body: JSON.stringify({
            name,
            executable,
            javaArgs,
            category,
            serverEngine,
            version,
            downloadJar: true  // Copy from local repo
          })
        });
      } catch (createErr) {
        resetOnError(`Failed to create server: ${createErr.message}`);
        return;
      }
      
      if (result.pendingApproval) {
        updateProgress('Server created and pending admin approval', 100);
        showNotification('Server created and pending admin approval', 'info');
        await new Promise(r => setTimeout(r, 1500));
        closeServerModal();
        await loadServers();
      } else if (result.warning) {
        updateProgress(`Server created with warning: ${result.warning}`, 100);
        showNotification(result.warning, 'warning');
        await new Promise(r => setTimeout(r, 1500));
        await loadServers();
        selectServer(result.serverId);
        closeServerModal();
      } else {
        updateProgress('Server created successfully!', 100);
        showNotification('Server created successfully!', 'success');
        await new Promise(r => setTimeout(r, 1000));
        await loadServers();
        selectServer(result.serverId);
        closeServerModal();
      }
      
    } else {
      // Use existing local JAR
      updateProgress('Creating server files...', 20);
      
      let result;
      try {
        result = await apiRequest('/api/servers', {
          method: 'POST',
          body: JSON.stringify({
            name,
            executable,
            javaArgs,
            category,
            serverEngine,
            version,
            downloadJar: true
          })
        });
      } catch (createErr) {
        resetOnError(`Failed to create server: ${createErr.message}`);
        return;
      }
      
      if (result.pendingApproval) {
        updateProgress('Server created and pending admin approval', 100);
        showNotification('Server created and pending admin approval', 'info');
        await new Promise(r => setTimeout(r, 1500));
        closeServerModal();
        await loadServers();
      } else if (result.warning) {
        updateProgress(`Server created with warning: ${result.warning}`, 100);
        showNotification(result.warning, 'warning');
        await new Promise(r => setTimeout(r, 1500));
        await loadServers();
        selectServer(result.serverId);
        closeServerModal();
      } else {
        updateProgress('Server created successfully!', 100);
        showNotification('Server created successfully!', 'success');
        await new Promise(r => setTimeout(r, 1000));
        await loadServers();
        selectServer(result.serverId);
        closeServerModal();
      }
    }
    
    // Reset button state (in case modal wasn't closed)
    submitBtn.textContent = originalText;
    submitBtn.disabled = false;
    if (backBtn) backBtn.disabled = false;
    
  } catch (error) {
    console.error('Failed to create server:', error);
    resetOnError(`Failed to create server: ${error.message}`);
  }
}

// Helper function to format bytes
function formatBytes(bytes, decimals = 2) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

// Import server from ZIP
async function importServer(e) {
  e.preventDefault();
  
  const name = document.getElementById('import-name').value;
  const fileInput = document.getElementById('import-file');
  const jarName = document.getElementById('import-jar-name').value || 'server.jar';
  const category = document.getElementById('import-category').value;
  const minRam = document.getElementById('import-min-ram').value;
  const maxRam = document.getElementById('import-max-ram').value;
  const extraJvmArgs = document.getElementById('import-jvm-args').value.trim();
  const javaArgs = `-Xms${minRam} -Xmx${maxRam}${extraJvmArgs ? ' ' + extraJvmArgs : ''}`;
  
  if (!fileInput.files.length) {
    showNotification('Please select a ZIP file to import', 'error');
    return;
  }
  
  if (!category) {
    showNotification('Please select a category', 'error');
    return;
  }
  
  try {
    // Show loading state
    const submitBtn = e.target.querySelector('button[type="submit"]');
    const originalText = submitBtn.textContent;
    submitBtn.textContent = 'Importing...';
    submitBtn.disabled = true;
    
    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    formData.append('name', name);
    formData.append('jarName', jarName);
    formData.append('javaArgs', javaArgs);
    formData.append('category', category);
    
    const response = await fetch('/api/servers/import', {
      method: 'POST',
      body: formData
    });
    
    const result = await response.json();
    
    if (!response.ok) {
      throw new Error(result.error || 'Import failed');
    }
    
    if (result.pendingApproval) {
      showNotification('Server imported and pending admin approval', 'info');
    } else {
      await loadServers();
      selectServer(result.serverId);
    }
    
    closeServerModal();
    submitBtn.textContent = originalText;
    submitBtn.disabled = false;
  } catch (error) {
    console.error('Failed to import server:', error);
    showNotification('Failed to import server: ' + error.message, 'error');
    // Reset button state
    const submitBtn = e.target.querySelector('button[type="submit"]');
    submitBtn.textContent = 'Import Server';
    submitBtn.disabled = false;
  }
}

// Toggle custom JAR upload section
function toggleCustomJarUpload() {
  const checkbox = document.getElementById('fresh-upload-jar');
  const customSection = document.getElementById('custom-jar-upload');
  const categoryGroup = document.getElementById('fresh-category').closest('.form-group');
  const engineGroup = document.getElementById('fresh-engine').closest('.form-group');
  const versionGroup = document.getElementById('fresh-version').closest('.form-group');
  
  if (checkbox.checked) {
    customSection.style.display = 'block';
    categoryGroup.style.display = 'none';
    engineGroup.style.display = 'none';
    versionGroup.style.display = 'none';
  } else {
    customSection.style.display = 'none';
    categoryGroup.style.display = 'block';
    // Engine visibility depends on category selection
    const category = document.getElementById('fresh-category').value;
    engineGroup.style.display = category === 'modded' ? 'block' : 'none';
    versionGroup.style.display = 'block';
  }
}

function deleteServer() {
  if (!currentServerId) return;
  
  const server = servers.find(s => s.id === currentServerId);
  showDeleteServerModal(server);
}

function showDeleteServerModal(server) {
  // Remove existing modal if any
  const existing = document.getElementById('delete-server-modal');
  if (existing) existing.remove();
  
  const modal = document.createElement('div');
  modal.id = 'delete-server-modal';
  modal.className = 'modal active';
  modal.innerHTML = `
    <div class="modal-content modal-medium">
      <div class="modal-header">
        <h2>🗑️ Delete Server</h2>
        <button class="close-btn" onclick="closeDeleteServerModal()">&times;</button>
      </div>
      <div class="delete-server-content">
        <p>What would you like to do with <strong>"${escapeHtml(server?.name || 'this server')}"</strong>?</p>
        
        <div class="delete-options">
          <button class="delete-option-btn" onclick="confirmDeleteServer(false)">
            <span class="delete-option-icon">📤</span>
            <div class="delete-option-info">
              <span class="delete-option-title">Remove from Management</span>
              <span class="delete-option-desc">Remove server from console only. Server files will be kept and can be re-imported later.</span>
            </div>
          </button>
          
          <button class="delete-option-btn delete-option-danger" onclick="confirmDeleteServer(true)">
            <span class="delete-option-icon">⚠️</span>
            <div class="delete-option-info">
              <span class="delete-option-title">Delete Everything</span>
              <span class="delete-option-desc">Permanently delete the server and ALL its files including worlds, plugins, and configurations.</span>
            </div>
          </button>
        </div>
        
        <p class="delete-warning">⚠️ Deleting everything cannot be undone!</p>
      </div>
      <div class="modal-footer">
        <button class="btn" onclick="closeDeleteServerModal()">Cancel</button>
      </div>
    </div>
  `;
  
  document.body.appendChild(modal);
  
  // Close on background click
  modal.onclick = (e) => {
    if (e.target.id === 'delete-server-modal') closeDeleteServerModal();
  };
}

function closeDeleteServerModal() {
  const modal = document.getElementById('delete-server-modal');
  if (modal) modal.remove();
}

async function confirmDeleteServer(deleteFiles) {
  if (!currentServerId) return;
  
  const server = servers.find(s => s.id === currentServerId);
  
  // Extra confirmation for full delete
  if (deleteFiles) {
    if (!confirm(`⚠️ FINAL WARNING ⚠️\n\nYou are about to PERMANENTLY DELETE "${server?.name}" and ALL its files!\n\nThis includes:\n• World data\n• Plugins\n• Configurations\n• Backups in server folder\n\nThis action CANNOT be undone!\n\nAre you absolutely sure?`)) {
      return;
    }
  }
  
  try {
    const url = deleteFiles 
      ? `/api/servers/${currentServerId}?deleteFiles=true`
      : `/api/servers/${currentServerId}`;
    
    await apiRequest(url, { method: 'DELETE' });
    
    closeDeleteServerModal();
    
    if (deleteFiles) {
      showNotification('Server and all files deleted permanently', 'success');
    } else {
      showNotification('Server removed from management. Files preserved.', 'success');
    }
    
    currentServerId = null;
    document.getElementById('no-server-view').style.display = 'flex';
    document.getElementById('server-view').style.display = 'none';
    
    await loadServers();
  } catch (error) {
    console.error('Failed to delete server:', error);
    showNotification('Failed to delete server: ' + error.message, 'error');
  }
}

// ==================== Terminal Functions ====================

// Use requestAnimationFrame to batch DOM updates and prevent flickering
let terminalBuffer = '';
let terminalUpdatePending = false;

function appendTerminalOutput(text) {
  terminalBuffer += text;
  
  if (!terminalUpdatePending) {
    terminalUpdatePending = true;
    requestAnimationFrame(() => {
      const terminal = document.getElementById('terminal-output');
      // Append text directly without re-rendering entire content
      terminal.textContent += terminalBuffer;
      terminal.scrollTop = terminal.scrollHeight;
      terminalBuffer = '';
      terminalUpdatePending = false;
    });
  }
}

function clearTerminal() {
  const terminal = document.getElementById('terminal-output');
  terminal.textContent = '';
  terminalBuffer = '';
  terminalUpdatePending = false;
}

// ==================== Logs Functions ====================

async function loadLogs() {
  if (!currentServerId) return;
  
  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/logs`);
    const logsOutput = document.getElementById('logs-output');
    logsOutput.textContent = data.content || 'No logs available';
    logsOutput.scrollTop = logsOutput.scrollHeight;
  } catch (error) {
    console.error('Failed to load logs:', error);
    const logsOutput = document.getElementById('logs-output');
    logsOutput.textContent = 'Failed to load logs: ' + error.message;
  }
}

function clearLogsView() {
  const logsOutput = document.getElementById('logs-output');
  logsOutput.textContent = '';
}

function sendCommand(command) {
  if (!currentServerId || !socket || !socket.connected) return;
  
  socket.emit('command', { serverId: currentServerId, command });
  appendTerminalOutput(`> ${command}\n`);
}

// ==================== File Explorer ====================

async function loadFiles(path = '') {
  if (!currentServerId) return;
  
  currentPath = path;
  
  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/files?path=${encodeURIComponent(path)}`);
    
    if (data.isFile) {
      await openFileEditor(path);
      return;
    }
    
    document.getElementById('current-path').textContent = '/' + path;
    const fileList = document.getElementById('file-list');
    fileList.innerHTML = '';
    
    // Add parent directory link if not at root
    if (path) {
      const parentPath = path.split('/').slice(0, -1).join('/');
      fileList.appendChild(createFileRow({ name: '..', isDirectory: true }, parentPath));
    }
    
    // Sort: directories first, then files
    const sortedFiles = data.files.sort((a, b) => {
      if (a.isDirectory && !b.isDirectory) return -1;
      if (!a.isDirectory && b.isDirectory) return 1;
      return a.name.localeCompare(b.name);
    });
    
    sortedFiles.forEach(file => {
      const filePath = path ? `${path}/${file.name}` : file.name;
      fileList.appendChild(createFileRow(file, filePath));
    });
  } catch (error) {
    console.error('Failed to load files:', error);
  }
}

function createFileRow(file, filePath) {
  const row = document.createElement('tr');
  
  const nameCell = document.createElement('td');
  const nameDiv = document.createElement('div');
  nameDiv.className = 'file-name';
  nameDiv.innerHTML = `
    <span class="file-icon">${file.isDirectory ? '📁' : '📄'}</span>
    <span>${escapeHtml(file.name)}</span>
  `;
  nameDiv.onclick = () => {
    if (file.isDirectory) {
      loadFiles(filePath);
    } else {
      openFileEditor(filePath);
    }
  };
  nameCell.appendChild(nameDiv);
  
  const sizeCell = document.createElement('td');
  sizeCell.textContent = file.isDirectory ? '-' : formatBytes(file.size);
  
  const modifiedCell = document.createElement('td');
  modifiedCell.textContent = file.modified ? new Date(file.modified).toLocaleString() : '-';
  
  const actionsCell = document.createElement('td');
  const actionsDiv = document.createElement('div');
  actionsDiv.className = 'file-actions-cell';
  
  if (file.name !== '..') {
    if (!file.isDirectory) {
      const downloadBtn = document.createElement('button');
      downloadBtn.textContent = 'Download';
      downloadBtn.className = 'btn btn-small action-btn';
      downloadBtn.onclick = (e) => {
        e.stopPropagation();
        downloadFile(filePath);
      };
      actionsDiv.appendChild(downloadBtn);
    }
    
    const deleteBtn = document.createElement('button');
    deleteBtn.textContent = 'Delete';
    deleteBtn.className = 'btn btn-danger btn-small action-btn';
    deleteBtn.onclick = (e) => {
      e.stopPropagation();
      deleteFile(filePath);
    };
    actionsDiv.appendChild(deleteBtn);
  }
  
  actionsCell.appendChild(actionsDiv);
  
  row.appendChild(nameCell);
  row.appendChild(sizeCell);
  row.appendChild(modifiedCell);
  row.appendChild(actionsCell);
  
  return row;
}

async function openFileEditor(filePath) {
  if (!currentServerId) return;
  
  // Check if this is an NBT file
  if (isNbtFile(filePath)) {
    await openNbtEditor(filePath);
    return;
  }
  
  try {
    currentEditingFile = filePath;
    const data = await apiRequest(`/api/servers/${currentServerId}/files/read?path=${encodeURIComponent(filePath)}`);
    
    document.getElementById('editor-title').textContent = `Edit: ${filePath}`;
    document.getElementById('file-content').value = data.content;
    document.getElementById('file-editor-modal').classList.add('active');
  } catch (error) {
    console.error('Failed to open file:', error);
  }
}

async function saveFile() {
  if (!currentServerId || !currentEditingFile) return;
  
  try {
    const content = document.getElementById('file-content').value;
    await apiRequest(`/api/servers/${currentServerId}/files/write`, {
      method: 'POST',
      body: JSON.stringify({ path: currentEditingFile, content })
    });
    
    closeFileEditor();
    alert('File saved successfully');
  } catch (error) {
    console.error('Failed to save file:', error);
  }
}

function closeFileEditor() {
  document.getElementById('file-editor-modal').classList.remove('active');
  currentEditingFile = '';
}

// ==================== NBT Editor ====================

let currentNbtFile = '';
let currentNbtData = null;
let currentNbtCompression = 'gzip';
let currentNbtEditPath = [];
let currentNbtAddParentPath = [];

const NBT_TYPE_NAMES = {
  0: 'End', 1: 'Byte', 2: 'Short', 3: 'Int', 4: 'Long',
  5: 'Float', 6: 'Double', 7: 'ByteArray', 8: 'String',
  9: 'List', 10: 'Compound', 11: 'IntArray', 12: 'LongArray'
};

const NBT_TYPE_ICONS = {
  1: '🔢', 2: '🔢', 3: '🔢', 4: '🔢', 5: '🔢', 6: '🔢',
  7: '📊', 8: '📝', 9: '📋', 10: '📦', 11: '📊', 12: '📊'
};

function isNbtFile(filename) {
  const ext = filename.toLowerCase().split('.').pop();
  return ['dat', 'dat_old', 'dat_mcr', 'nbt', 'schematic'].includes(ext);
}

async function openNbtEditor(filePath) {
  if (!currentServerId) return;
  
  try {
    currentNbtFile = filePath;
    const response = await apiRequest(`/api/servers/${currentServerId}/nbt/read?path=${encodeURIComponent(filePath)}`);
    
    if (response.success) {
      currentNbtData = response.data;
      currentNbtCompression = response.compression || 'gzip';
      
      document.getElementById('nbt-editor-title').textContent = `NBT Editor: ${filePath}`;
      document.getElementById('nbt-compression-info').textContent = `Compression: ${currentNbtCompression || 'none'}`;
      
      renderNbtTree();
      document.getElementById('nbt-editor-modal').classList.add('active');
    }
  } catch (error) {
    console.error('Failed to open NBT file:', error);
    showNotification('Failed to open NBT file: ' + error.message, 'error');
  }
}

function renderNbtTree() {
  const container = document.getElementById('nbt-tree');
  container.innerHTML = '';
  
  if (currentNbtData) {
    container.appendChild(createNbtNode(currentNbtData, []));
  }
}

function createNbtNode(tag, path) {
  const node = document.createElement('div');
  node.className = 'nbt-node';
  
  const header = document.createElement('div');
  header.className = 'nbt-node-header';
  
  const isExpandable = tag.type === 10 || tag.type === 9; // Compound or List
  
  if (isExpandable) {
    const toggle = document.createElement('span');
    toggle.className = 'nbt-toggle';
    toggle.textContent = '▶';
    toggle.onclick = (e) => {
      e.stopPropagation();
      const children = node.querySelector('.nbt-children');
      if (children) {
        children.classList.toggle('collapsed');
        toggle.textContent = children.classList.contains('collapsed') ? '▶' : '▼';
        toggle.classList.toggle('expanded', !children.classList.contains('collapsed'));
      }
    };
    header.appendChild(toggle);
  } else {
    const spacer = document.createElement('span');
    spacer.className = 'nbt-toggle-spacer';
    header.appendChild(spacer);
  }
  
  const icon = document.createElement('span');
  icon.className = 'nbt-icon';
  icon.textContent = NBT_TYPE_ICONS[tag.type] || '❓';
  header.appendChild(icon);
  
  const name = document.createElement('span');
  name.className = 'nbt-name';
  name.textContent = tag.name || '(unnamed)';
  header.appendChild(name);
  
  const type = document.createElement('span');
  type.className = 'nbt-type';
  type.textContent = `[${NBT_TYPE_NAMES[tag.type] || 'Unknown'}]`;
  header.appendChild(type);
  
  // Show value preview for simple types
  if (!isExpandable && tag.type !== 7 && tag.type !== 11 && tag.type !== 12) {
    const value = document.createElement('span');
    value.className = 'nbt-value';
    value.textContent = `: ${formatNbtValue(tag.value, tag.type)}`;
    header.appendChild(value);
    
    // Make editable
    header.classList.add('nbt-editable');
    header.onclick = () => openNbtValueEditor(tag, path);
  } else if (tag.type === 7 || tag.type === 11 || tag.type === 12) {
    // Array types - show count
    const value = document.createElement('span');
    value.className = 'nbt-value nbt-array-info';
    const arrLen = Array.isArray(tag.value) ? tag.value.length : 0;
    value.textContent = `: [${arrLen} entries]`;
    header.appendChild(value);
  }
  
  // Action buttons
  const actions = document.createElement('div');
  actions.className = 'nbt-actions';
  
  if (isExpandable) {
    const addBtn = document.createElement('button');
    addBtn.className = 'btn btn-small nbt-action-btn';
    addBtn.textContent = '+';
    addBtn.title = 'Add child tag';
    addBtn.onclick = (e) => {
      e.stopPropagation();
      openNbtAddModal(path);
    };
    actions.appendChild(addBtn);
  }
  
  if (path.length > 0) {
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'btn btn-danger btn-small nbt-action-btn';
    deleteBtn.textContent = '×';
    deleteBtn.title = 'Delete tag';
    deleteBtn.onclick = (e) => {
      e.stopPropagation();
      deleteNbtTag(path);
    };
    actions.appendChild(deleteBtn);
  }
  
  header.appendChild(actions);
  node.appendChild(header);
  
  // Render children for compound and list
  if (tag.type === 10 && Array.isArray(tag.value)) {
    const children = document.createElement('div');
    children.className = 'nbt-children collapsed';
    tag.value.forEach((child, index) => {
      children.appendChild(createNbtNode(child, [...path, child.name]));
    });
    node.appendChild(children);
  } else if (tag.type === 9 && tag.value && tag.value.items) {
    const children = document.createElement('div');
    children.className = 'nbt-children collapsed';
    tag.value.items.forEach((item, index) => {
      const listItem = {
        type: item.type,
        name: `[${index}]`,
        value: item.value
      };
      children.appendChild(createNbtNode(listItem, [...path, index.toString()]));
    });
    node.appendChild(children);
  }
  
  return node;
}

function formatNbtValue(value, type) {
  if (type === 8) return `"${value}"`;
  if (type === 5 || type === 6) return value.toFixed(4);
  return String(value);
}

function openNbtValueEditor(tag, path) {
  currentNbtEditPath = path;
  
  document.getElementById('nbt-value-label').textContent = tag.name || 'Value';
  document.getElementById('nbt-value-type').textContent = `Type: ${NBT_TYPE_NAMES[tag.type]}`;
  document.getElementById('nbt-value-input').value = tag.value;
  document.getElementById('nbt-value-input').dataset.type = tag.type;
  
  document.getElementById('nbt-value-modal').classList.add('active');
}

function closeNbtValueModal() {
  document.getElementById('nbt-value-modal').classList.remove('active');
  currentNbtEditPath = [];
}

function saveNbtValue() {
  const input = document.getElementById('nbt-value-input');
  let value = input.value;
  const type = parseInt(input.dataset.type);
  
  // Convert value based on type
  switch (type) {
    case 1: value = parseInt(value); break; // Byte
    case 2: value = parseInt(value); break; // Short
    case 3: value = parseInt(value); break; // Int
    case 4: value = parseInt(value); break; // Long (may lose precision)
    case 5: value = parseFloat(value); break; // Float
    case 6: value = parseFloat(value); break; // Double
    case 8: value = String(value); break; // String
  }
  
  // Update the value in the data structure
  updateNbtDataValue(currentNbtData, currentNbtEditPath, value);
  
  // Re-render and close modal
  renderNbtTree();
  closeNbtValueModal();
  showNotification('Value updated (save to apply)', 'info');
}

function updateNbtDataValue(data, path, newValue) {
  if (path.length === 0) return;
  
  let current = data;
  for (let i = 0; i < path.length - 1; i++) {
    const key = path[i];
    if (current.type === 10) { // Compound
      current = current.value.find(c => c.name === key);
    } else if (current.type === 9) { // List
      current = current.value.items[parseInt(key)];
    }
  }
  
  const finalKey = path[path.length - 1];
  if (current.type === 10) {
    const target = current.value.find(c => c.name === finalKey);
    if (target) target.value = newValue;
  } else if (current.type === 9) {
    current.value.items[parseInt(finalKey)].value = newValue;
  } else {
    current.value = newValue;
  }
}

function openNbtAddModal(parentPath) {
  currentNbtAddParentPath = parentPath;
  document.getElementById('nbt-add-name').value = '';
  document.getElementById('nbt-add-value').value = '';
  document.getElementById('nbt-add-type').value = '8'; // Default to String
  updateNbtAddValue();
  document.getElementById('nbt-add-modal').classList.add('active');
}

function closeNbtAddModal() {
  document.getElementById('nbt-add-modal').classList.remove('active');
  currentNbtAddParentPath = [];
}

function updateNbtAddValue() {
  const type = parseInt(document.getElementById('nbt-add-type').value);
  const valueGroup = document.getElementById('nbt-add-value-group');
  
  // Hide value input for compound type
  valueGroup.style.display = type === 10 ? 'none' : 'block';
}

function confirmAddNbtTag() {
  const name = document.getElementById('nbt-add-name').value.trim();
  const type = parseInt(document.getElementById('nbt-add-type').value);
  let value = document.getElementById('nbt-add-value').value;
  
  if (!name) {
    alert('Please enter a tag name');
    return;
  }
  
  // Create the new tag
  let newTag = { type, name };
  
  switch (type) {
    case 1: case 2: case 3: case 4: newTag.value = parseInt(value) || 0; break;
    case 5: case 6: newTag.value = parseFloat(value) || 0.0; break;
    case 8: newTag.value = value || ''; break;
    case 10: newTag.value = []; break; // Empty compound
  }
  
  // Find parent and add tag
  addNbtTagToData(currentNbtData, currentNbtAddParentPath, newTag);
  
  renderNbtTree();
  closeNbtAddModal();
  showNotification('Tag added (save to apply)', 'info');
}

function addNbtTagToData(data, parentPath, newTag) {
  let current = data;
  
  for (const key of parentPath) {
    if (current.type === 10) {
      current = current.value.find(c => c.name === key);
    } else if (current.type === 9) {
      current = current.value.items[parseInt(key)];
    }
  }
  
  if (current.type === 10) {
    current.value.push(newTag);
  } else if (current.type === 9) {
    current.value.items.push({ type: newTag.type, value: newTag.value });
  }
}

function deleteNbtTag(path) {
  if (!confirm('Are you sure you want to delete this tag?')) return;
  
  deleteNbtTagFromData(currentNbtData, path);
  renderNbtTree();
  showNotification('Tag deleted (save to apply)', 'info');
}

function deleteNbtTagFromData(data, path) {
  if (path.length === 0) return;
  
  let current = data;
  for (let i = 0; i < path.length - 1; i++) {
    const key = path[i];
    if (current.type === 10) {
      current = current.value.find(c => c.name === key);
    } else if (current.type === 9) {
      current = current.value.items[parseInt(key)];
    }
  }
  
  const finalKey = path[path.length - 1];
  if (current.type === 10) {
    current.value = current.value.filter(c => c.name !== finalKey);
  } else if (current.type === 9) {
    current.value.items.splice(parseInt(finalKey), 1);
  }
}

async function saveNbtFile() {
  if (!currentServerId || !currentNbtFile || !currentNbtData) return;
  
  try {
    await apiRequest(`/api/servers/${currentServerId}/nbt/write`, {
      method: 'POST',
      body: JSON.stringify({
        path: currentNbtFile,
        data: currentNbtData,
        compression: currentNbtCompression
      })
    });
    
    closeNbtEditor();
    showNotification('NBT file saved successfully', 'success');
  } catch (error) {
    console.error('Failed to save NBT file:', error);
    showNotification('Failed to save NBT file: ' + error.message, 'error');
  }
}

function closeNbtEditor() {
  document.getElementById('nbt-editor-modal').classList.remove('active');
  currentNbtFile = '';
  currentNbtData = null;
}

function expandAllNbt() {
  document.querySelectorAll('.nbt-children').forEach(el => {
    el.classList.remove('collapsed');
  });
  document.querySelectorAll('.nbt-toggle').forEach(el => {
    el.textContent = '▼';
    el.classList.add('expanded');
  });
}

function collapseAllNbt() {
  document.querySelectorAll('.nbt-children').forEach(el => {
    el.classList.add('collapsed');
  });
  document.querySelectorAll('.nbt-toggle').forEach(el => {
    el.textContent = '▶';
    el.classList.remove('expanded');
  });
}

function addNbtTag() {
  openNbtAddModal([]);
}

async function createNewFile() {
  if (!currentServerId) return;
  
  const name = prompt('Enter file name:');
  if (!name) return;
  
  try {
    const filePath = currentPath ? `${currentPath}/${name}` : name;
    await apiRequest(`/api/servers/${currentServerId}/files/create`, {
      method: 'POST',
      body: JSON.stringify({ path: filePath, type: 'file' })
    });
    
    loadFiles(currentPath);
  } catch (error) {
    console.error('Failed to create file:', error);
  }
}

async function createNewFolder() {
  if (!currentServerId) return;
  
  const name = prompt('Enter folder name:');
  if (!name) return;
  
  try {
    const filePath = currentPath ? `${currentPath}/${name}` : name;
    await apiRequest(`/api/servers/${currentServerId}/files/create`, {
      method: 'POST',
      body: JSON.stringify({ path: filePath, type: 'directory' })
    });
    
    loadFiles(currentPath);
  } catch (error) {
    console.error('Failed to create folder:', error);
  }
}

async function deleteFile(filePath) {
  if (!currentServerId) return;
  if (!confirm(`Are you sure you want to delete ${filePath}?`)) return;
  
  try {
    await apiRequest(`/api/servers/${currentServerId}/files/delete`, {
      method: 'DELETE',
      body: JSON.stringify({ path: filePath })
    });
    
    loadFiles(currentPath);
  } catch (error) {
    console.error('Failed to delete file:', error);
  }
}

function downloadFile(filePath) {
  if (!currentServerId) return;
  window.location.href = `/api/servers/${currentServerId}/files/download?path=${encodeURIComponent(filePath)}`;
}

async function uploadFile(file) {
  if (!currentServerId) return;
  
  const formData = new FormData();
  formData.append('file', file);
  formData.append('path', currentPath);
  
  try {
    const response = await fetch(`/api/servers/${currentServerId}/files/upload`, {
      method: 'POST',
      body: formData
    });
    
    const result = await response.json();
    if (result.success) {
      alert('File uploaded successfully');
      loadFiles(currentPath);
    } else {
      throw new Error(result.error || 'Upload failed');
    }
  } catch (error) {
    console.error('Failed to upload file:', error);
    alert('Upload failed: ' + error.message);
  }
}

// ==================== Backup Functions ====================

async function loadBackups() {
  if (!currentServerId) return;
  
  // Load schedule status
  loadBackupSchedule();
  
  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/backups`);
    const backupList = document.getElementById('backup-list');
    backupList.innerHTML = '';
    
    if (data.backups.length === 0) {
      backupList.innerHTML = '<tr><td colspan="4" class="empty-state"><h3>No backups yet</h3><p>Create your first backup to protect your server</p></td></tr>';
      return;
    }
    
    data.backups.forEach(backup => {
      const row = document.createElement('tr');
      const isScheduled = backup.name.startsWith('scheduled-backup-');
      row.innerHTML = `
        <td>${isScheduled ? '📅 ' : ''}${escapeHtml(backup.name)}</td>
        <td>${formatBytes(backup.size)}</td>
        <td>${new Date(backup.created).toLocaleString()}</td>
        <td>
          <div class="file-actions-cell">
            <button class="btn btn-small action-btn" onclick="downloadBackup('${escapeHtml(backup.name)}')">Download</button>
            <button class="btn btn-success btn-small action-btn" onclick="restoreBackup('${escapeHtml(backup.name)}')">Restore</button>
            <button class="btn btn-danger btn-small action-btn" onclick="deleteBackup('${escapeHtml(backup.name)}')">Delete</button>
          </div>
        </td>
      `;
      backupList.appendChild(row);
    });
  } catch (error) {
    console.error('Failed to load backups:', error);
  }
}

async function createBackup() {
  if (!currentServerId) return;
  if (!confirm('Create a backup of the server? This may take a few minutes.')) return;
  
  const btn = document.getElementById('create-backup-btn');
  btn.disabled = true;
  btn.textContent = 'Creating...';
  
  try {
    const result = await apiRequest(`/api/servers/${currentServerId}/backups/create`, { method: 'POST' });
    if (result.success) {
      alert(`Backup created: ${result.backup} (${formatBytes(result.size)})`);
      loadBackups();
    }
  } catch (error) {
    console.error('Failed to create backup:', error);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Create Backup';
  }
}

function downloadBackup(name) {
  if (!currentServerId) return;
  window.location.href = `/api/servers/${currentServerId}/backups/download?name=${encodeURIComponent(name)}`;
}

async function restoreBackup(name) {
  if (!currentServerId) return;
  if (!confirm(`Restore backup "${name}"?\n\nWARNING: This will replace all current server files!\nMake sure the server is stopped.`)) return;
  
  try {
    const result = await apiRequest(`/api/servers/${currentServerId}/backups/restore`, {
      method: 'POST',
      body: JSON.stringify({ name })
    });
    
    if (result.success) {
      alert('Backup restored successfully!');
      loadFiles('');
    }
  } catch (error) {
    console.error('Failed to restore backup:', error);
  }
}

async function deleteBackup(name) {
  if (!currentServerId) return;
  if (!confirm(`Delete backup ${name}?`)) return;
  
  try {
    await apiRequest(`/api/servers/${currentServerId}/backups/delete`, {
      method: 'DELETE',
      body: JSON.stringify({ name })
    });
    loadBackups();
  } catch (error) {
    console.error('Failed to delete backup:', error);
  }
}

// ==================== Backup Scheduling ====================

async function loadBackupSchedule() {
  if (!currentServerId) return;
  
  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/backups/schedule`);
    const statusBanner = document.getElementById('schedule-status');
    
    if (data.schedule && data.schedule.enabled) {
      const schedule = data.schedule;
      let scheduleText = '';
      
      switch (schedule.type) {
        case 'hourly':
          scheduleText = `Every hour at :${String(schedule.minute).padStart(2, '0')}`;
          break;
        case 'daily':
          scheduleText = `Daily at ${String(schedule.hour).padStart(2, '0')}:${String(schedule.minute).padStart(2, '0')}`;
          break;
        case 'weekly':
          const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
          scheduleText = `Every ${days[schedule.dayOfWeek]} at ${String(schedule.hour).padStart(2, '0')}:${String(schedule.minute).padStart(2, '0')}`;
          break;
        case 'custom':
          scheduleText = `Custom: ${schedule.cron}`;
          break;
      }
      
      document.getElementById('schedule-text').textContent = `Scheduled: ${scheduleText}`;
      
      if (schedule.nextRun) {
        const nextRun = new Date(schedule.nextRun);
        document.getElementById('next-backup-text').textContent = `Next: ${nextRun.toLocaleString()}`;
      } else {
        document.getElementById('next-backup-text').textContent = '';
      }
      
      statusBanner.style.display = 'flex';
    } else {
      statusBanner.style.display = 'none';
    }
  } catch (error) {
    console.error('Failed to load backup schedule:', error);
    document.getElementById('schedule-status').style.display = 'none';
  }
}

function openScheduleModal() {
  const modal = document.getElementById('schedule-modal');
  modal.classList.add('active');
  
  // Load current schedule if exists
  loadScheduleIntoModal();
}

function closeScheduleModal() {
  document.getElementById('schedule-modal').classList.remove('active');
}

async function loadScheduleIntoModal() {
  if (!currentServerId) return;
  
  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/backups/schedule`);
    
    if (data.schedule) {
      const s = data.schedule;
      document.getElementById('schedule-type').value = s.type || 'daily';
      document.getElementById('schedule-hour').value = s.hour || 3;
      document.getElementById('schedule-minute').value = s.minute || 0;
      document.getElementById('schedule-day').value = s.dayOfWeek || 0;
      document.getElementById('schedule-cron').value = s.cron || '';
      document.getElementById('schedule-max-backups').value = s.maxBackups || 7;
      document.getElementById('schedule-stop-server').checked = s.stopServer !== false;
      document.getElementById('schedule-restart-after').checked = s.restartAfter !== false;
      
      updateScheduleOptions();
    }
  } catch (error) {
    console.error('Failed to load schedule into modal:', error);
  }
}

function updateScheduleOptions() {
  const type = document.getElementById('schedule-type').value;
  const dayGroup = document.getElementById('schedule-day-group');
  const hourGroup = document.getElementById('schedule-hour-group');
  const timeOptions = document.getElementById('schedule-time-options');
  const cronGroup = document.getElementById('schedule-cron-group');
  
  // Reset visibility
  dayGroup.style.display = 'none';
  hourGroup.style.display = 'block';
  timeOptions.style.display = 'block';
  cronGroup.style.display = 'none';
  
  switch (type) {
    case 'hourly':
      hourGroup.style.display = 'none';
      break;
    case 'daily':
      // Default - hour and minute shown
      break;
    case 'weekly':
      dayGroup.style.display = 'block';
      break;
    case 'custom':
      timeOptions.style.display = 'none';
      cronGroup.style.display = 'block';
      break;
  }
}

async function saveSchedule() {
  if (!currentServerId) return;
  
  const type = document.getElementById('schedule-type').value;
  const scheduleData = {
    enabled: true,
    type: type,
    hour: parseInt(document.getElementById('schedule-hour').value) || 3,
    minute: parseInt(document.getElementById('schedule-minute').value) || 0,
    dayOfWeek: parseInt(document.getElementById('schedule-day').value) || 0,
    cron: document.getElementById('schedule-cron').value,
    maxBackups: parseInt(document.getElementById('schedule-max-backups').value) || 7,
    stopServer: document.getElementById('schedule-stop-server').checked,
    restartAfter: document.getElementById('schedule-restart-after').checked
  };
  
  try {
    const result = await apiRequest(`/api/servers/${currentServerId}/backups/schedule`, {
      method: 'POST',
      body: JSON.stringify(scheduleData)
    });
    
    if (result.success) {
      showNotification('Backup schedule saved successfully!', 'success');
      closeScheduleModal();
      loadBackupSchedule();
    }
  } catch (error) {
    console.error('Failed to save schedule:', error);
    showNotification('Failed to save backup schedule', 'error');
  }
}

async function deleteSchedule() {
  if (!currentServerId) return;
  if (!confirm('Are you sure you want to disable the backup schedule?')) return;
  
  try {
    await apiRequest(`/api/servers/${currentServerId}/backups/schedule`, {
      method: 'DELETE'
    });
    
    showNotification('Backup schedule disabled', 'info');
    loadBackupSchedule();
  } catch (error) {
    console.error('Failed to delete schedule:', error);
    showNotification('Failed to disable backup schedule', 'error');
  }
}

// ==================== Task Scheduler ====================

let editingTaskId = null;

async function loadTasks() {
  if (!currentServerId) return;
  
  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/tasks`);
    const taskList = document.getElementById('task-list');
    taskList.innerHTML = '';
    
    if (!data.tasks || data.tasks.length === 0) {
      taskList.innerHTML = '<tr><td colspan="8" class="empty-message">No tasks configured. Create one to get started!</td></tr>';
      return;
    }
    
    data.tasks.forEach(task => {
      const row = document.createElement('tr');
      
      const statusCell = document.createElement('td');
      const statusBadge = document.createElement('span');
      statusBadge.className = task.enabled ? 'badge badge-success' : 'badge badge-secondary';
      statusBadge.textContent = task.enabled ? 'Enabled' : 'Disabled';
      statusCell.appendChild(statusBadge);
      
      const nameCell = document.createElement('td');
      nameCell.textContent = task.name;
      
      const actionCell = document.createElement('td');
      const actionBadge = document.createElement('span');
      actionBadge.className = 'badge';
      switch (task.action) {
        case 'START':
          actionBadge.classList.add('badge-success');
          actionBadge.textContent = '▶️ Start';
          break;
        case 'STOP':
          actionBadge.classList.add('badge-danger');
          actionBadge.textContent = '⏹️ Stop';
          break;
        case 'REBOOT':
          actionBadge.classList.add('badge-warning');
          actionBadge.textContent = '🔄 Reboot';
          break;
        case 'COMMAND':
          actionBadge.classList.add('badge-info');
          actionBadge.textContent = '⌨️ Command';
          break;
      }
      actionCell.appendChild(actionBadge);
      
      const intervalCell = document.createElement('td');
      intervalCell.textContent = task.interval;
      intervalCell.style.fontFamily = 'monospace';
      intervalCell.style.fontSize = '12px';
      
      const runsCell = document.createElement('td');
      if (task.runs > 0) {
        runsCell.textContent = `${task.runCount || 0}/${task.runs}`;
      } else {
        runsCell.textContent = task.runCount || 0;
      }
      
      const lastRunCell = document.createElement('td');
      lastRunCell.textContent = task.lastRun ? new Date(task.lastRun).toLocaleString() : 'Never';
      
      const nextRunCell = document.createElement('td');
      nextRunCell.textContent = task.nextRun ? new Date(task.nextRun).toLocaleString() : '-';
      
      const actionsCell = document.createElement('td');
      const editBtn = document.createElement('button');
      editBtn.textContent = 'Edit';
      editBtn.className = 'btn btn-small action-btn';
      editBtn.onclick = () => openEditTaskModal(task);
      
      const deleteBtn = document.createElement('button');
      deleteBtn.textContent = 'Delete';
      deleteBtn.className = 'btn btn-danger btn-small action-btn';
      deleteBtn.onclick = () => deleteTask(task.id);
      
      actionsCell.appendChild(editBtn);
      actionsCell.appendChild(deleteBtn);
      
      row.appendChild(statusCell);
      row.appendChild(nameCell);
      row.appendChild(actionCell);
      row.appendChild(intervalCell);
      row.appendChild(runsCell);
      row.appendChild(lastRunCell);
      row.appendChild(nextRunCell);
      row.appendChild(actionsCell);
      
      taskList.appendChild(row);
    });
  } catch (error) {
    console.error('Failed to load tasks:', error);
    showNotification('Failed to load tasks', 'error');
  }
}

function openCreateTaskModal() {
  editingTaskId = null;
  document.getElementById('task-modal-title').textContent = 'Create Task';
  document.getElementById('task-name').value = '';
  document.getElementById('task-action').value = 'START';
  document.getElementById('task-interval').value = '0 3 * * *';
  document.getElementById('task-command').value = '';
  document.getElementById('task-runs').value = '0';
  document.getElementById('task-enabled').checked = true;
  document.getElementById('task-delete-after').checked = false;
  document.getElementById('task-delete-after-runs').checked = false;
  
  updateTaskActionOptions();
  document.getElementById('task-modal').classList.add('active');
}

function openEditTaskModal(task) {
  editingTaskId = task.id;
  document.getElementById('task-modal-title').textContent = 'Edit Task';
  document.getElementById('task-name').value = task.name;
  document.getElementById('task-action').value = task.action;
  document.getElementById('task-interval').value = task.interval;
  document.getElementById('task-command').value = task.command || '';
  document.getElementById('task-runs').value = task.runs || 0;
  document.getElementById('task-enabled').checked = task.enabled;
  document.getElementById('task-delete-after').checked = task.deleteAfterExecution;
  document.getElementById('task-delete-after-runs').checked = task.deleteAfterRunsCount;
  
  updateTaskActionOptions();
  document.getElementById('task-modal').classList.add('active');
}

function closeTaskModal() {
  document.getElementById('task-modal').classList.remove('active');
  editingTaskId = null;
}

function updateTaskActionOptions() {
  const action = document.getElementById('task-action').value;
  const commandGroup = document.getElementById('task-command-group');
  
  if (action === 'COMMAND') {
    commandGroup.style.display = 'block';
  } else {
    commandGroup.style.display = 'none';
  }
}

function updateTaskRunsRequired() {
  const deleteAfterRuns = document.getElementById('task-delete-after-runs').checked;
  const runsInput = document.getElementById('task-runs');
  
  if (deleteAfterRuns && runsInput.value === '0') {
    runsInput.value = '1';
  }
}

async function saveTask() {
  if (!currentServerId) return;
  
  const name = document.getElementById('task-name').value.trim();
  const action = document.getElementById('task-action').value;
  const interval = document.getElementById('task-interval').value.trim();
  const command = document.getElementById('task-command').value.trim();
  const runs = parseInt(document.getElementById('task-runs').value) || 0;
  const enabled = document.getElementById('task-enabled').checked;
  const deleteAfterExecution = document.getElementById('task-delete-after').checked;
  const deleteAfterRunsCount = document.getElementById('task-delete-after-runs').checked;
  
  if (!name) {
    showNotification('Please enter a task name', 'error');
    return;
  }
  
  if (action === 'COMMAND' && !command) {
    showNotification('Please enter a command', 'error');
    return;
  }
  
  if (deleteAfterRunsCount && runs === 0) {
    showNotification('Please set a run limit when using "Delete after runs"', 'error');
    return;
  }
  
  try {
    const taskData = {
      name,
      action,
      interval,
      command,
      runs,
      enabled,
      deleteAfterExecution,
      deleteAfterRunsCount
    };
    
    if (editingTaskId) {
      await apiRequest(`/api/servers/${currentServerId}/tasks/${editingTaskId}`, {
        method: 'PUT',
        body: JSON.stringify(taskData)
      });
      showNotification('Task updated successfully', 'success');
    } else {
      await apiRequest(`/api/servers/${currentServerId}/tasks`, {
        method: 'POST',
        body: JSON.stringify(taskData)
      });
      showNotification('Task created successfully', 'success');
    }
    
    closeTaskModal();
    loadTasks();
  } catch (error) {
    console.error('Failed to save task:', error);
    showNotification('Failed to save task: ' + error.message, 'error');
  }
}

async function deleteTask(taskId) {
  if (!currentServerId || !taskId) return;
  
  if (!confirm('Are you sure you want to delete this task?')) {
    return;
  }
  
  try {
    await apiRequest(`/api/servers/${currentServerId}/tasks/${taskId}`, {
      method: 'DELETE'
    });
    
    showNotification('Task deleted successfully', 'success');
    loadTasks();
  } catch (error) {
    console.error('Failed to delete task:', error);
    showNotification('Failed to delete task', 'error');
  }
}

// ==================== Tab Switching ====================

function switchTab(tabName) {
  document.querySelectorAll('.tab-button').forEach(btn => {
    btn.classList.remove('active');
  });
  document.querySelectorAll('.tab-content').forEach(content => {
    content.classList.remove('active');
  });
  
  document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
  document.getElementById(`${tabName}-tab`).classList.add('active');
  
  // Load data when switching tabs
  if (tabName === 'files') {
    loadFiles(currentPath);
  } else if (tabName === 'backups') {
    loadBackups();
  } else if (tabName === 'players') {
    loadAllPlayerData();
  } else if (tabName === 'mods') {
    loadMods();
  } else if (tabName === 'properties') {
    loadProperties();
  } else if (tabName === 'logs') {
    loadLogs();
  } else if (tabName === 'tasks') {
    loadTasks();
  } else if (tabName === 'resourcepack') {
    loadResourcePack();
  }
}

// ==================== Mods Management ====================

async function loadMods() {
  if (!currentServerId) return;
  
  const pluginsList = document.getElementById('plugins-list');
  const modsList = document.getElementById('mods-list');
  
  pluginsList.innerHTML = '<tr><td colspan="4" class="empty-message">Loading plugins...</td></tr>';
  modsList.innerHTML = '<tr><td colspan="4" class="empty-message">Loading mods...</td></tr>';
  
  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/mods`);
    
    // Render plugins
    if (data.plugins && data.plugins.length > 0) {
      pluginsList.innerHTML = '';
      data.plugins.forEach(plugin => {
        pluginsList.appendChild(createModRow(plugin, 'plugins'));
      });
    } else {
      pluginsList.innerHTML = '<tr><td colspan="4" class="empty-message">No plugins installed</td></tr>';
    }
    
    // Render mods
    if (data.mods && data.mods.length > 0) {
      modsList.innerHTML = '';
      data.mods.forEach(mod => {
        modsList.appendChild(createModRow(mod, 'mods'));
      });
    } else {
      modsList.innerHTML = '<tr><td colspan="4" class="empty-message">No mods installed</td></tr>';
    }
  } catch (error) {
    console.error('Failed to load mods:', error);
    pluginsList.innerHTML = '<tr><td colspan="4" class="empty-message error">Failed to load plugins</td></tr>';
    modsList.innerHTML = '<tr><td colspan="4" class="empty-message error">Failed to load mods</td></tr>';
  }
}

function createModRow(mod, type) {
  const row = document.createElement('tr');
  
  const nameCell = document.createElement('td');
  nameCell.innerHTML = `<span class="file-icon">📦</span> ${escapeHtml(mod.name)}`;
  
  const sizeCell = document.createElement('td');
  sizeCell.textContent = formatBytes(mod.size);
  
  const modifiedCell = document.createElement('td');
  modifiedCell.textContent = mod.modified ? new Date(mod.modified).toLocaleString() : '-';
  
  const actionsCell = document.createElement('td');
  const actionsDiv = document.createElement('div');
  actionsDiv.className = 'file-actions-cell';
  
  const toggleBtn = document.createElement('button');
  const isEnabled = !mod.name.endsWith('.disabled');
  toggleBtn.textContent = isEnabled ? 'Disable' : 'Enable';
  toggleBtn.className = `btn btn-small action-btn ${isEnabled ? '' : 'btn-success'}`;
  toggleBtn.onclick = () => toggleMod(mod.name, type, isEnabled);
  actionsDiv.appendChild(toggleBtn);
  
  const deleteBtn = document.createElement('button');
  deleteBtn.textContent = 'Delete';
  deleteBtn.className = 'btn btn-danger btn-small action-btn';
  deleteBtn.onclick = () => deleteMod(mod.name, type);
  actionsDiv.appendChild(deleteBtn);
  
  actionsCell.appendChild(actionsDiv);
  
  row.appendChild(nameCell);
  row.appendChild(sizeCell);
  row.appendChild(modifiedCell);
  row.appendChild(actionsCell);
  
  return row;
}

async function toggleMod(filename, type, isEnabled) {
  if (!currentServerId) return;
  
  const action = isEnabled ? 'disable' : 'enable';
  
  try {
    await apiRequest(`/api/servers/${currentServerId}/mods/${type}/${encodeURIComponent(filename)}/${action}`, {
      method: 'POST'
    });
    showNotification(`Mod ${action}d successfully`, 'success');
    loadMods();
  } catch (error) {
    console.error('Failed to toggle mod:', error);
  }
}

async function deleteMod(filename, type) {
  if (!currentServerId) return;
  
  if (!confirm(`Are you sure you want to delete "${filename}"? This cannot be undone.`)) {
    return;
  }
  
  try {
    await apiRequest(`/api/servers/${currentServerId}/mods/${type}/${encodeURIComponent(filename)}`, {
      method: 'DELETE'
    });
    showNotification('Mod deleted successfully', 'success');
    loadMods();
  } catch (error) {
    console.error('Failed to delete mod:', error);
  }
}

async function uploadMod(file, type) {
  if (!currentServerId || !file) return;
  
  const formData = new FormData();
  formData.append('file', file);
  formData.append('type', type);
  
  try {
    const response = await fetch(`/api/servers/${currentServerId}/mods/upload`, {
      method: 'POST',
      body: formData
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'Upload failed');
    }
    
    showNotification('Mod uploaded successfully', 'success');
    loadMods();
  } catch (error) {
    console.error('Failed to upload mod:', error);
    showNotification('Failed to upload mod: ' + error.message, 'error');
  }
}

function showModUploadDialog() {
  return new Promise((resolve) => {
    // Remove existing modal if any
    const existing = document.getElementById('mod-upload-dialog');
    if (existing) existing.remove();
    
    const modal = document.createElement('div');
    modal.id = 'mod-upload-dialog';
    modal.className = 'modal active';
    modal.innerHTML = `
      <div class="modal-content modal-small">
        <div class="modal-header">
          <h2>📦 Upload Mod/Plugin</h2>
          <button class="close-btn" onclick="this.closest('.modal').remove()">&times;</button>
        </div>
        <div class="modal-body">
          <p>Where would you like to upload the file(s)?</p>
          <div class="mod-upload-choices">
            <button class="btn btn-primary" id="upload-to-plugins">
              🔌 Plugins Folder
              <small>For Bukkit/Spigot/Paper plugins</small>
            </button>
            <button class="btn btn-primary" id="upload-to-mods">
              🔧 Mods Folder
              <small>For Forge/NeoForge/Fabric mods</small>
            </button>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn" onclick="this.closest('.modal').remove()">Cancel</button>
        </div>
      </div>
    `;
    
    document.body.appendChild(modal);
    
    document.getElementById('upload-to-plugins').onclick = () => {
      modal.remove();
      resolve('plugins');
    };
    
    document.getElementById('upload-to-mods').onclick = () => {
      modal.remove();
      resolve('mods');
    };
    
    // Cancel on backdrop click
    modal.onclick = (e) => {
      if (e.target === modal) {
        modal.remove();
        resolve(null);
      }
    };
  });
}

// ==================== Player Management ====================

let currentEditingOpUuid = null;

async function loadAllPlayerData() {
  if (!currentServerId) return;
  
  await Promise.all([
    loadOperators(),
    loadPlayerData(),
    loadWhitelist(),
    loadBannedPlayers()
  ]);
}

async function loadOperators() {
  if (!currentServerId) return;
  
  const tbody = document.getElementById('ops-list');
  tbody.innerHTML = '<tr><td colspan="5" class="empty-message">Loading...</td></tr>';
  
  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/players/ops`);
    const ops = data.operators || [];
    
    if (ops.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-message">No operators configured</td></tr>';
      return;
    }
    
    tbody.innerHTML = ops.map(op => `
      <tr>
        <td><strong>${escapeHtml(op.name)}</strong></td>
        <td class="uuid-cell">${escapeHtml(op.uuid)}</td>
        <td>
          <span class="level-badge level-${op.level}">Level ${op.level}</span>
        </td>
        <td>${op.bypassesPlayerLimit ? '✅' : '❌'}</td>
        <td class="actions-cell">
          <button class="btn btn-small" onclick="editOperator('${op.uuid}', '${escapeHtml(op.name)}', ${op.level}, ${op.bypassesPlayerLimit})">Edit</button>
          <button class="btn btn-danger btn-small" onclick="removeOperator('${op.uuid}', '${escapeHtml(op.name)}')">Remove</button>
        </td>
      </tr>
    `).join('');
  } catch (error) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-message error">Failed to load operators</td></tr>';
  }
}

async function loadPlayerData() {
  if (!currentServerId) return;
  
  const tbody = document.getElementById('playerdata-list');
  tbody.innerHTML = '<tr><td colspan="4" class="empty-message">Loading...</td></tr>';
  
  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/players/playerdata`);
    const players = data.players || [];
    
    if (players.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty-message">No player data found</td></tr>';
      return;
    }
    
    tbody.innerHTML = players.map(player => `
      <tr>
        <td class="uuid-cell">${escapeHtml(player.uuid)}</td>
        <td>${new Date(player.modified).toLocaleString()}</td>
        <td>${formatBytes(player.size)}</td>
        <td class="actions-cell">
          <button class="btn btn-small" onclick="openPlayerNbtEditor('${player.uuid}')">Edit NBT</button>
          <button class="btn btn-small btn-success" onclick="makePlayerOp('${player.uuid}')">Make OP</button>
        </td>
      </tr>
    `).join('');
  } catch (error) {
    tbody.innerHTML = '<tr><td colspan="4" class="empty-message error">Failed to load player data</td></tr>';
  }
}

async function loadWhitelist() {
  if (!currentServerId) return;
  
  const tbody = document.getElementById('whitelist-list');
  tbody.innerHTML = '<tr><td colspan="3" class="empty-message">Loading...</td></tr>';
  
  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/players/whitelist`);
    const whitelist = data.whitelist || [];
    
    if (whitelist.length === 0) {
      tbody.innerHTML = '<tr><td colspan="3" class="empty-message">Whitelist is empty</td></tr>';
      return;
    }
    
    tbody.innerHTML = whitelist.map(player => `
      <tr>
        <td><strong>${escapeHtml(player.name)}</strong></td>
        <td class="uuid-cell">${escapeHtml(player.uuid)}</td>
        <td class="actions-cell">
          <button class="btn btn-danger btn-small" onclick="removeFromWhitelist('${player.uuid}', '${escapeHtml(player.name)}')">Remove</button>
        </td>
      </tr>
    `).join('');
  } catch (error) {
    tbody.innerHTML = '<tr><td colspan="3" class="empty-message error">Failed to load whitelist</td></tr>';
  }
}

async function loadBannedPlayers() {
  if (!currentServerId) return;
  
  const tbody = document.getElementById('banned-list');
  tbody.innerHTML = '<tr><td colspan="5" class="empty-message">Loading...</td></tr>';
  
  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/players/banned`);
    const banned = data.banned || [];
    
    if (banned.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-message">No banned players</td></tr>';
      return;
    }
    
    tbody.innerHTML = banned.map(player => `
      <tr>
        <td><strong>${escapeHtml(player.name)}</strong></td>
        <td class="uuid-cell">${escapeHtml(player.uuid)}</td>
        <td>${escapeHtml(player.reason || 'No reason')}</td>
        <td>${escapeHtml(player.source || 'Unknown')}</td>
        <td class="actions-cell">
          <button class="btn btn-success btn-small" onclick="unbanPlayer('${player.uuid}', '${escapeHtml(player.name)}')">Unban</button>
        </td>
      </tr>
    `).join('');
  } catch (error) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-message error">Failed to load banned players</td></tr>';
  }
}

// Operator Functions
function openAddOpModal() {
  document.getElementById('op-player-name').value = '';
  document.getElementById('op-level').value = '4';
  document.getElementById('op-bypass-limit').checked = false;
  document.getElementById('add-op-modal').classList.add('active');
}

function closeAddOpModal() {
  document.getElementById('add-op-modal').classList.remove('active');
}

async function addOperator() {
  const name = document.getElementById('op-player-name').value.trim();
  const level = parseInt(document.getElementById('op-level').value);
  const bypassLimit = document.getElementById('op-bypass-limit').checked;
  
  if (!name) {
    alert('Please enter a player name');
    return;
  }
  
  try {
    await apiRequest(`/api/servers/${currentServerId}/players/ops`, {
      method: 'POST',
      body: JSON.stringify({ name, level, bypassesPlayerLimit: bypassLimit })
    });
    
    closeAddOpModal();
    showNotification(`${name} added as operator`, 'success');
    loadOperators();
  } catch (error) {
    // Error shown by apiRequest
  }
}

function editOperator(uuid, name, level, bypassLimit) {
  currentEditingOpUuid = uuid;
  document.getElementById('edit-op-name').value = name;
  document.getElementById('edit-op-level').value = level;
  document.getElementById('edit-op-bypass').checked = bypassLimit;
  document.getElementById('edit-op-modal').classList.add('active');
}

function closeEditOpModal() {
  document.getElementById('edit-op-modal').classList.remove('active');
  currentEditingOpUuid = null;
}

async function saveOperator() {
  if (!currentEditingOpUuid) return;
  
  const level = parseInt(document.getElementById('edit-op-level').value);
  const bypassLimit = document.getElementById('edit-op-bypass').checked;
  
  try {
    await apiRequest(`/api/servers/${currentServerId}/players/ops/${currentEditingOpUuid}`, {
      method: 'PUT',
      body: JSON.stringify({ level, bypassesPlayerLimit: bypassLimit })
    });
    
    closeEditOpModal();
    showNotification('Operator updated', 'success');
    loadOperators();
  } catch (error) {
    // Error shown by apiRequest
  }
}

async function removeOperator(uuid, name) {
  if (!confirm(`Remove ${name} from operators?`)) return;
  
  try {
    await apiRequest(`/api/servers/${currentServerId}/players/ops/${uuid}`, {
      method: 'DELETE'
    });
    
    showNotification(`${name} removed from operators`, 'success');
    loadOperators();
  } catch (error) {
    // Error shown by apiRequest
  }
}

async function makePlayerOp(uuid) {
  const name = prompt('Enter player name to make OP:');
  if (!name) return;
  
  try {
    await apiRequest(`/api/servers/${currentServerId}/players/ops`, {
      method: 'POST',
      body: JSON.stringify({ name, level: 4, bypassesPlayerLimit: false })
    });
    
    showNotification(`${name} added as operator`, 'success');
    loadOperators();
  } catch (error) {
    // Error shown by apiRequest
  }
}

// Whitelist Functions
function openAddWhitelistModal() {
  document.getElementById('whitelist-player-name').value = '';
  document.getElementById('add-whitelist-modal').classList.add('active');
}

function closeAddWhitelistModal() {
  document.getElementById('add-whitelist-modal').classList.remove('active');
}

async function addToWhitelist() {
  const name = document.getElementById('whitelist-player-name').value.trim();
  
  if (!name) {
    alert('Please enter a player name');
    return;
  }
  
  try {
    await apiRequest(`/api/servers/${currentServerId}/players/whitelist`, {
      method: 'POST',
      body: JSON.stringify({ name })
    });
    
    closeAddWhitelistModal();
    showNotification(`${name} added to whitelist`, 'success');
    loadWhitelist();
  } catch (error) {
    // Error shown by apiRequest
  }
}

async function removeFromWhitelist(uuid, name) {
  if (!confirm(`Remove ${name} from whitelist?`)) return;
  
  try {
    await apiRequest(`/api/servers/${currentServerId}/players/whitelist/${uuid}`, {
      method: 'DELETE'
    });
    
    showNotification(`${name} removed from whitelist`, 'success');
    loadWhitelist();
  } catch (error) {
    // Error shown by apiRequest
  }
}

// Ban Functions
function openBanPlayerModal() {
  document.getElementById('ban-player-name').value = '';
  document.getElementById('ban-reason').value = '';
  document.getElementById('ban-player-modal').classList.add('active');
}

function closeBanPlayerModal() {
  document.getElementById('ban-player-modal').classList.remove('active');
}

async function banPlayer() {
  const name = document.getElementById('ban-player-name').value.trim();
  const reason = document.getElementById('ban-reason').value.trim() || 'Banned by server administrator';
  
  if (!name) {
    alert('Please enter a player name');
    return;
  }
  
  try {
    await apiRequest(`/api/servers/${currentServerId}/players/banned`, {
      method: 'POST',
      body: JSON.stringify({ name, reason })
    });
    
    closeBanPlayerModal();
    showNotification(`${name} has been banned`, 'success');
    loadBannedPlayers();
  } catch (error) {
    // Error shown by apiRequest
  }
}

async function unbanPlayer(uuid, name) {
  if (!confirm(`Unban ${name}?`)) return;
  
  try {
    await apiRequest(`/api/servers/${currentServerId}/players/banned/${uuid}`, {
      method: 'DELETE'
    });
    
    showNotification(`${name} has been unbanned`, 'success');
    loadBannedPlayers();
  } catch (error) {
    // Error shown by apiRequest
  }
}

// Player NBT Editor
async function openPlayerNbtEditor(uuid) {
  // Find the world folder with playerdata
  const worldFolders = ['world', 'world_nether', 'world_the_end'];
  
  for (const world of worldFolders) {
    const path = `${world}/playerdata/${uuid}.dat`;
    try {
      await openNbtEditor(path);
      return;
    } catch (e) {
      // Try next folder
    }
  }
  
  showNotification('Could not find player data file', 'error');
}

// ==================== Event Listeners ====================
// Note: Utility functions (formatBytes, escapeHtml) are in utils.js

document.addEventListener('DOMContentLoaded', async () => {
  // Check authentication first
  const isAuthenticated = await checkAuth();
  if (!isAuthenticated) return;
  
  // Load branding settings
  loadBranding();
  
  // Connect WebSocket
  connectWebSocket();
  
  // Load servers
  loadServers();
  
  // Refresh servers periodically
  setInterval(loadServers, 10000);
  
  // Add server buttons
  document.getElementById('add-server-btn').onclick = openAddServerModal;
  document.getElementById('welcome-add-btn').onclick = openAddServerModal;
  
  // Server forms
  document.getElementById('fresh-server-form').onsubmit = createFreshServer;
  document.getElementById('import-server-form').onsubmit = importServer;
  document.getElementById('manual-server-form').onsubmit = saveServer;
  
  // Custom JAR upload toggle
  document.getElementById('fresh-upload-jar').onchange = toggleCustomJarUpload;
  
  // Server actions
  document.getElementById('start-btn').onclick = startServer;
  document.getElementById('stop-btn').onclick = stopServer;
  document.getElementById('kill-btn').onclick = killServer;
  document.getElementById('edit-server-btn').onclick = openEditServerModal;
  document.getElementById('delete-server-btn').onclick = deleteServer;
  
  // Tab buttons
  document.querySelectorAll('.tab-button').forEach(btn => {
    btn.onclick = () => switchTab(btn.dataset.tab);
  });
  
  // Terminal input
  document.getElementById('terminal-input').onkeypress = (e) => {
    if (e.key === 'Enter') {
      sendCommand(e.target.value);
      e.target.value = '';
    }
  };
  
  document.getElementById('send-btn').onclick = () => {
    const input = document.getElementById('terminal-input');
    sendCommand(input.value);
    input.value = '';
  };
  
  // Logs controls
  document.getElementById('refresh-logs-btn').onclick = loadLogs;
  document.getElementById('clear-logs-view-btn').onclick = clearLogsView;
  
  // File explorer controls
  document.getElementById('new-file-btn').onclick = createNewFile;
  document.getElementById('new-folder-btn').onclick = createNewFolder;
  document.getElementById('refresh-files-btn').onclick = () => loadFiles(currentPath);
  
  document.getElementById('file-upload').onchange = (e) => {
    if (e.target.files.length > 0) {
      uploadFile(e.target.files[0]);
      e.target.value = '';
    }
  };
  
  // Mods controls
  document.getElementById('refresh-mods-btn').onclick = loadMods;
  
  document.getElementById('mod-upload').onchange = async (e) => {
    if (e.target.files.length > 0) {
      // Ask user which folder to upload to
      const choice = await showModUploadDialog();
      if (choice) {
        for (const file of e.target.files) {
          await uploadMod(file, choice);
        }
      }
      e.target.value = '';
    }
  };
  
  // File editor
  document.getElementById('save-file-btn').onclick = saveFile;
  
  // Backup controls
  document.getElementById('create-backup-btn').onclick = createBackup;
  document.getElementById('schedule-backup-btn').onclick = openScheduleModal;
  document.getElementById('refresh-backups-btn').onclick = loadBackups;
  
  // Task controls
  document.getElementById('create-task-btn').onclick = openCreateTaskModal;
  document.getElementById('refresh-tasks-btn').onclick = loadTasks;
  
  // Close modals on background click
  document.getElementById('server-modal').onclick = (e) => {
    if (e.target.id === 'server-modal') closeServerModal();
  };
  
  document.getElementById('file-editor-modal').onclick = (e) => {
    if (e.target.id === 'file-editor-modal') closeFileEditor();
  };
  
  document.getElementById('schedule-modal').onclick = (e) => {
    if (e.target.id === 'schedule-modal') closeScheduleModal();
  };
  
  document.getElementById('task-modal').onclick = (e) => {
    if (e.target.id === 'task-modal') closeTaskModal();
  };
});

// ==================== Properties Management ====================

let currentProperties = {};

async function loadProperties() {
  if (!currentServerId) return;
  
  const editor = document.getElementById('properties-editor');
  const loading = document.getElementById('properties-loading');
  const empty = document.getElementById('properties-empty');
  
  loading.style.display = 'block';
  editor.innerHTML = '';
  empty.style.display = 'none';
  
  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/properties`);
    
    if (data.properties && Object.keys(data.properties).length > 0) {
      currentProperties = data.properties;
      renderPropertiesEditor(data.properties);
      loading.style.display = 'none';
      editor.style.display = 'block';
    } else {
      loading.style.display = 'none';
      empty.style.display = 'flex';
    }
  } catch (error) {
    console.error('Failed to load properties:', error);
    loading.style.display = 'none';
    empty.style.display = 'flex';
  }
}

function renderPropertiesEditor(properties) {
  const editor = document.getElementById('properties-editor');
  editor.innerHTML = '';
  
  // Group properties by category for better organization
  const groups = {
    'Server Settings': ['server-name', 'server-port', 'server-ip', 'max-players', 'white-list', 'enforce-whitelist', 'online-mode', 'motd'],
    'World Settings': ['level-name', 'level-type', 'level-seed', 'generator-settings', 'generate-structures', 'allow-nether', 'allow-flight', 'max-world-size', 'view-distance', 'simulation-distance'],
    'Gameplay': ['gamemode', 'difficulty', 'hardcore', 'pvp', 'spawn-protection', 'spawn-npcs', 'spawn-animals', 'spawn-monsters', 'max-tick-time'],
    'Performance': ['max-threads', 'rate-limit', 'network-compression-threshold', 'enable-jmx-monitoring', 'sync-chunk-writes'],
    'Advanced': []
  };
  
  // Create a set of all grouped properties
  const groupedProps = new Set();
  Object.values(groups).forEach(group => group.forEach(prop => groupedProps.add(prop)));
  
  // Add ungrouped properties to Advanced
  Object.keys(properties).forEach(key => {
    if (!groupedProps.has(key)) {
      groups['Advanced'].push(key);
    }
  });
  
  // Render each group
  Object.entries(groups).forEach(([groupName, propKeys]) => {
    const groupProps = propKeys.filter(key => properties.hasOwnProperty(key));
    if (groupProps.length === 0 && groupName !== 'Advanced') return;
    
    const groupDiv = document.createElement('div');
    groupDiv.className = 'property-group';
    
    const groupTitle = document.createElement('h3');
    groupTitle.textContent = groupName;
    groupDiv.appendChild(groupTitle);
    
    groupProps.forEach(key => {
      const value = properties[key];
      const propertyDiv = document.createElement('div');
      propertyDiv.className = 'property-item';
      
      const label = document.createElement('label');
      label.className = 'property-label';
      label.htmlFor = `prop-${key}`;
      
      const nameSpan = document.createElement('span');
      nameSpan.className = 'property-name';
      nameSpan.textContent = key;
      label.appendChild(nameSpan);
      
      // Get property metadata
      const metadata = getPropertyMetadata(key);
      
      // Add description if available
      if (metadata.description) {
        const descSpan = document.createElement('span');
        descSpan.className = 'property-description';
        descSpan.textContent = metadata.description;
        label.appendChild(descSpan);
      }
      
      // Add type and default info
      if (metadata.type || metadata.default) {
        const typeSpan = document.createElement('span');
        typeSpan.className = 'property-type-info';
        let typeText = '';
        if (metadata.type) {
          if (metadata.type === 'integer' && metadata.allowedValues) {
            typeText = `${metadata.type} [${metadata.allowedValues}]`;
          } else if (Array.isArray(metadata.allowedValues)) {
            typeText = `${metadata.type} (${metadata.allowedValues.join(', ')})`;
          } else {
            typeText = metadata.type;
          }
        }
        if (metadata.default) {
          typeText += typeText ? ` • default: ${metadata.default}` : `default: ${metadata.default}`;
        }
        typeSpan.textContent = typeText;
        label.appendChild(typeSpan);
      }
      
      propertyDiv.appendChild(label);
      
      // Create container for the value/input
      const valueContainer = document.createElement('div');
      valueContainer.className = 'property-value-container';
      
      // Determine input based on metadata type
      if (metadata.type === 'boolean' || (value === 'true' || value === 'false')) {
        // Create toggle switch container
        const toggleLabel = document.createElement('label');
        toggleLabel.className = 'toggle-switch';
        
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.id = `prop-${key}`;
        input.checked = value === 'true';
        input.dataset.key = key;
        
        const slider = document.createElement('span');
        slider.className = 'toggle-slider';
        
        toggleLabel.appendChild(input);
        toggleLabel.appendChild(slider);
        valueContainer.appendChild(toggleLabel);
      } else if (Array.isArray(metadata.allowedValues) && metadata.allowedValues.length <= 10) {
        // Use select dropdown for properties with limited choices
        const select = document.createElement('select');
        select.id = `prop-${key}`;
        select.className = 'property-select';
        select.dataset.key = key;
        
        metadata.allowedValues.forEach(option => {
          const optionElement = document.createElement('option');
          optionElement.value = option;
          optionElement.textContent = option;
          if (value === option) {
            optionElement.selected = true;
          }
          select.appendChild(optionElement);
        });
        
        valueContainer.appendChild(select);
      } else if (metadata.type === 'integer' || (!isNaN(value) && value !== '')) {
        const input = document.createElement('input');
        input.type = 'number';
        input.id = `prop-${key}`;
        input.className = 'property-input';
        input.value = value;
        input.dataset.key = key;
        
        // Set min/max if available in metadata
        if (metadata.allowedValues && typeof metadata.allowedValues === 'string') {
          const range = metadata.allowedValues.match(/(\d+)-(\d+)/);
          if (range) {
            input.min = range[1];
            input.max = range[2];
          }
        }
        
        valueContainer.appendChild(input);
      } else {
        // String input - use textarea for longer fields
        const isLongField = metadata.maxLength && metadata.maxLength > 50;
        
        if (isLongField) {
          const textarea = document.createElement('textarea');
          textarea.id = `prop-${key}`;
          textarea.className = 'property-textarea';
          textarea.value = value;
          textarea.dataset.key = key;
          textarea.rows = 2;
          if (metadata.maxLength) {
            textarea.maxLength = metadata.maxLength;
          }
          valueContainer.appendChild(textarea);
        } else {
          const input = document.createElement('input');
          input.type = 'text';
          input.id = `prop-${key}`;
          input.className = 'property-input';
          input.value = value;
          input.dataset.key = key;
          if (metadata.maxLength) {
            input.maxLength = metadata.maxLength;
          }
          valueContainer.appendChild(input);
        }
      }
      
      propertyDiv.appendChild(valueContainer);
      groupDiv.appendChild(propertyDiv);
    });
    
    editor.appendChild(groupDiv);
  });
}

function getPropertyMetadata(key) {
  const metadata = {
    'accepts-transfers': {
      type: 'boolean',
      default: 'false',
      description: 'Whether to accept incoming transfers via a transfer packet',
      allowedValues: ['true', 'false']
    },
    'allow-flight': {
      type: 'boolean',
      default: 'false',
      description: 'Allow players to fly in Survival mode. Enabling may make griefing easier',
      allowedValues: ['true', 'false']
    },
    'allow-nether': {
      type: 'boolean',
      default: 'true',
      description: 'Allow players to travel to the Nether dimension',
      allowedValues: ['true', 'false']
    },
    'broadcast-console-to-ops': {
      type: 'boolean',
      default: 'true',
      description: 'Send console command outputs to all online operators',
      allowedValues: ['true', 'false']
    },
    'broadcast-rcon-to-ops': {
      type: 'boolean',
      default: 'true',
      description: 'Send rcon console command outputs to all online operators',
      allowedValues: ['true', 'false']
    },
    'difficulty': {
      type: 'string',
      default: 'easy',
      description: 'Difficulty level of the server',
      allowedValues: ['peaceful', 'easy', 'normal', 'hard']
    },
    'enable-command-block': {
      type: 'boolean',
      default: 'false',
      description: 'Enable command blocks',
      allowedValues: ['true', 'false']
    },
    'enable-jmx-monitoring': {
      type: 'boolean',
      default: 'false',
      description: 'Expose MBean with server tick times in milliseconds',
      allowedValues: ['true', 'false']
    },
    'enable-query': {
      type: 'boolean',
      default: 'false',
      description: 'Enable GameSpy4 protocol server listener for server information',
      allowedValues: ['true', 'false']
    },
    'enable-rcon': {
      type: 'boolean',
      default: 'false',
      description: 'Enable remote access to the server console',
      allowedValues: ['true', 'false']
    },
    'enable-status': {
      type: 'boolean',
      default: 'true',
      description: 'Makes the server appear as "online" on the server list',
      allowedValues: ['true', 'false']
    },
    'enforce-secure-profile': {
      type: 'boolean',
      default: 'true',
      description: 'Only allow players with Mojang-signed public keys to join',
      allowedValues: ['true', 'false']
    },
    'enforce-whitelist': {
      type: 'boolean',
      default: 'false',
      description: 'Kick non-whitelisted players when whitelist is reloaded',
      allowedValues: ['true', 'false']
    },
    'entity-broadcast-range-percentage': {
      type: 'integer',
      default: '100',
      description: 'Controls how close entities need to be before being sent to clients (as percentage)',
      allowedValues: '10-1000'
    },
    'force-gamemode': {
      type: 'boolean',
      default: 'false',
      description: 'Force players to join in the default game mode',
      allowedValues: ['true', 'false']
    },
    'function-permission-level': {
      type: 'integer',
      default: '2',
      description: 'Default permission level for functions',
      allowedValues: '1-4'
    },
    'gamemode': {
      type: 'string',
      default: 'survival',
      description: 'Default game mode for new players',
      allowedValues: ['survival', 'creative', 'adventure', 'spectator']
    },
    'generate-structures': {
      type: 'boolean',
      default: 'true',
      description: 'Generate structures (villages, dungeons, etc.) in new chunks',
      allowedValues: ['true', 'false']
    },
    'generator-settings': {
      type: 'string',
      default: '{}',
      description: 'Settings for world generation customization',
      maxLength: 200
    },
    'hardcore': {
      type: 'boolean',
      default: 'false',
      description: 'Enable hardcore mode (permanent death)',
      allowedValues: ['true', 'false']
    },
    'hide-online-players': {
      type: 'boolean',
      default: 'false',
      description: 'Hide player list in server status requests',
      allowedValues: ['true', 'false']
    },
    'initial-disabled-packs': {
      type: 'string',
      default: '',
      description: 'Comma-separated list of datapacks to disable on world creation',
      maxLength: 200
    },
    'initial-enabled-packs': {
      type: 'string',
      default: 'vanilla',
      description: 'Comma-separated list of datapacks to enable on world creation',
      maxLength: 200
    },
    'level-name': {
      type: 'string',
      default: 'world',
      description: 'Name of the world folder',
      maxLength: 25
    },
    'level-seed': {
      type: 'string',
      default: '',
      description: 'Seed for world generation (leave blank for random)',
      maxLength: 100
    },
    'level-type': {
      type: 'string',
      default: 'normal',
      description: 'World preset for generation',
      allowedValues: ['normal', 'flat', 'large_biomes', 'amplified', 'single_biome_surface']
    },
    'log-ips': {
      type: 'boolean',
      default: 'true',
      description: 'Include client IP addresses in server logs',
      allowedValues: ['true', 'false']
    },
    'max-chained-neighbor-updates': {
      type: 'integer',
      default: '1000000',
      description: 'Limit consecutive neighbor updates before skipping additional ones',
      allowedValues: '1-10000000'
    },
    'max-players': {
      type: 'integer',
      default: '20',
      description: 'Maximum number of players that can join simultaneously',
      allowedValues: '0-2147483647'
    },
    'max-tick-time': {
      type: 'integer',
      default: '60000',
      description: 'Maximum milliseconds per tick before watchdog stops server (-1 to disable)',
      allowedValues: '-1 or 0-9223372036854775807'
    },
    'max-world-size': {
      type: 'integer',
      default: '29999984',
      description: 'Maximum radius of world border in blocks',
      allowedValues: '1-29999984'
    },
    'motd': {
      type: 'string',
      default: 'A Minecraft Server, Powered by MServer',
      description: 'Message shown in server list (59 character limit, supports formatting codes)',
      maxLength: 59
    },
    'network-compression-threshold': {
      type: 'integer',
      default: '256',
      description: 'Packet size threshold for compression in bytes (-1 to disable)',
      allowedValues: '-1 or 0-2147483647'
    },
    'online-mode': {
      type: 'boolean',
      default: 'true',
      description: 'Verify players with Mojang authentication. IMPORTANT: Disable only for offline/LAN servers',
      allowedValues: ['true', 'false']
    },
    'op-permission-level': {
      type: 'integer',
      default: '4',
      description: 'Default permission level for ops',
      allowedValues: '0-4'
    },
    'pause-when-empty-seconds': {
      type: 'integer',
      default: '60',
      description: 'Seconds to wait after no players online before pausing server',
      allowedValues: '0-2147483647'
    },
    'player-idle-timeout': {
      type: 'integer',
      default: '0',
      description: 'Minutes before idle players are kicked (0 to disable)',
      allowedValues: '0-2147483647'
    },
    'prevent-proxy-connections': {
      type: 'boolean',
      default: 'false',
      description: 'Kick players if ISP differs from Mojang authentication server',
      allowedValues: ['true', 'false']
    },
    'pvp': {
      type: 'boolean',
      default: 'true',
      description: 'Enable player versus player combat',
      allowedValues: ['true', 'false']
    },
    'query.port': {
      type: 'integer',
      default: '25565',
      description: 'UDP port for GameSpy4 query listener',
      allowedValues: '1-65535'
    },
    'rate-limit': {
      type: 'integer',
      default: '0',
      description: 'Maximum packets per player before kick (0 to disable)',
      allowedValues: '0-2147483647'
    },
    'rcon.password': {
      type: 'string',
      default: '',
      description: 'Password for RCON (required if RCON is enabled)',
      maxLength: 100
    },
    'rcon.port': {
      type: 'integer',
      default: '25575',
      description: 'TCP port for RCON connections',
      allowedValues: '1-65535'
    },
    'region-file-compression': {
      type: 'string',
      default: 'deflate',
      description: 'Compression algorithm for region files',
      allowedValues: ['deflate', 'lz4', 'none']
    },
    'require-resource-pack': {
      type: 'boolean',
      default: 'false',
      description: 'Disconnect players who decline the resource pack',
      allowedValues: ['true', 'false']
    },
    'resource-pack': {
      type: 'string',
      default: '',
      description: 'URL to optional resource pack (max 250 MiB)',
      maxLength: 300
    },
    'resource-pack-prompt': {
      type: 'string',
      default: '',
      description: 'Custom message for resource pack prompt (chat component syntax)',
      maxLength: 200
    },
    'resource-pack-sha1': {
      type: 'string',
      default: '',
      description: 'SHA-1 hash of resource pack for integrity verification',
      maxLength: 40
    },
    'server-ip': {
      type: 'string',
      default: '',
      description: 'IP address to bind to (leave blank for all interfaces)',
      maxLength: 45
    },
    'server-port': {
      type: 'integer',
      default: '25565',
      description: 'TCP port the server listens on. Must be forwarded if behind NAT',
      allowedValues: '1-65535'
    },
    'server-name': {
      type: 'string',
      default: '',
      description: 'Server name',
      maxLength: 100
    },
    'simulation-distance': {
      type: 'integer',
      default: '10',
      description: 'Maximum distance in chunks for mob spawning and entity updates',
      allowedValues: '3-32'
    },
    'spawn-animals': {
      type: 'boolean',
      default: 'true',
      description: 'Allow animals to spawn',
      allowedValues: ['true', 'false']
    },
    'spawn-monsters': {
      type: 'boolean',
      default: 'true',
      description: 'Allow hostile mobs to spawn',
      allowedValues: ['true', 'false']
    },
    'spawn-npcs': {
      type: 'boolean',
      default: 'true',
      description: 'Allow villagers to spawn',
      allowedValues: ['true', 'false']
    },
    'spawn-protection': {
      type: 'integer',
      default: '16',
      description: 'Radius around spawn where only ops can build (0 to disable)',
      allowedValues: '0-2147483647'
    },
    'sync-chunk-writes': {
      type: 'boolean',
      default: 'true',
      description: 'Enable synchronous chunk writes (prevents data loss after crashes)',
      allowedValues: ['true', 'false']
    },
    'use-native-transport': {
      type: 'boolean',
      default: 'true',
      description: 'Use optimized packet sending/receiving on Linux',
      allowedValues: ['true', 'false']
    },
    'view-distance': {
      type: 'integer',
      default: '10',
      description: 'Server-side view distance in chunks',
      allowedValues: '3-32'
    },
    'white-list': {
      type: 'boolean',
      default: 'false',
      description: 'Enable whitelist (only whitelisted players can join)',
      allowedValues: ['true', 'false']
    }
  };
  
  // Return metadata for known properties, or default to string for unknown
  return metadata[key] || {
    type: 'string',
    default: '',
    description: '',
    maxLength: 100
  };
}

async function saveProperties() {
  if (!currentServerId) return;
  
  const editor = document.getElementById('properties-editor');
  const inputs = editor.querySelectorAll('input[data-key], textarea[data-key], select[data-key]');
  
  const updatedProperties = {};
  inputs.forEach(input => {
    const key = input.dataset.key;
    if (input.type === 'checkbox') {
      updatedProperties[key] = input.checked ? 'true' : 'false';
    } else {
      updatedProperties[key] = input.value;
    }
  });
  
  try {
    await apiRequest(`/api/servers/${currentServerId}/properties`, {
      method: 'POST',
      body: JSON.stringify({ properties: updatedProperties })
    });
    
    showNotification('Properties saved successfully. Restart the server for changes to take effect.', 'success');
    loadProperties(); // Reload to show saved state
  } catch (error) {
    console.error('Failed to save properties:', error);
    showNotification('Failed to save properties: ' + error.message, 'error');
  }
}

function refreshProperties() {
  loadProperties();
}

// Add event listeners for properties buttons
document.addEventListener('DOMContentLoaded', () => {
  const savePropertiesBtn = document.getElementById('save-properties-btn');
  const refreshPropertiesBtn = document.getElementById('refresh-properties-btn');
  
  if (savePropertiesBtn) {
    savePropertiesBtn.addEventListener('click', saveProperties);
  }
  
  if (refreshPropertiesBtn) {
    refreshPropertiesBtn.addEventListener('click', refreshProperties);
  }
});

// ==================== Resource Pack Management ====================

async function loadResourcePack() {
  if (!currentServerId) return;
  
  const statusDiv = document.getElementById('resourcepack-status');
  const uploadSection = document.getElementById('resourcepack-upload-section');
  const detailsSection = document.getElementById('resourcepack-details');
  
  statusDiv.innerHTML = '<div class="loading">Loading resource pack information...</div>';
  uploadSection.style.display = 'block';
  detailsSection.style.display = 'none';
  
  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/resourcepack`);
    
    if (data.exists) {
      // Show resource pack details
      statusDiv.innerHTML = '<div class="success-message">✓ Resource pack is configured for this server</div>';
      uploadSection.style.display = 'none';
      detailsSection.style.display = 'block';
      
      document.getElementById('rp-filename').textContent = data.filename;
      document.getElementById('rp-size').textContent = formatBytes(data.size);
      document.getElementById('rp-uploaded').textContent = new Date(data.uploaded).toLocaleString();
      document.getElementById('rp-sha1').textContent = data.sha1;
      
      const urlLink = document.getElementById('rp-url');
      if (data.url) {
        urlLink.href = data.url;
        urlLink.textContent = data.url;
      } else {
        urlLink.href = '#';
        urlLink.textContent = 'No base URL configured';
      }
    } else {
      // No resource pack uploaded
      statusDiv.innerHTML = '<div class="info-message">ℹ No resource pack uploaded yet</div>';
      uploadSection.style.display = 'block';
      detailsSection.style.display = 'none';
    }
  } catch (error) {
    statusDiv.innerHTML = `<div class="error-message">Error loading resource pack: ${escapeHtml(error.message)}</div>`;
  }
}

async function uploadResourcePack(file) {
  if (!currentServerId) return;
  
  const statusDiv = document.getElementById('resourcepack-status');
  
  // Validate file
  if (!file.name.toLowerCase().endsWith('.zip')) {
    showNotification('File must be a .zip file', 'error');
    return;
  }
  
  // Check file size (100MB)
  const maxSize = 100 * 1024 * 1024;
  if (file.size > maxSize) {
    showNotification(`File size exceeds 100MB limit (${(file.size / (1024*1024)).toFixed(2)}MB)`, 'error');
    return;
  }
  
  statusDiv.innerHTML = '<div class="loading">Uploading resource pack...</div>';
  
  try {
    const formData = new FormData();
    formData.append('file', file);
    
    const response = await fetch(`/api/servers/${currentServerId}/resourcepack/upload`, {
      method: 'POST',
      body: formData
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'Upload failed');
    }
    
    const data = await response.json();
    
    showNotification('Resource pack uploaded successfully!', 'success');
    
    if (data.propertiesUpdated) {
      showNotification('server.properties updated with resource pack URL and SHA-1 hash', 'success');
    }
    
    // Reload the resource pack info
    loadResourcePack();
  } catch (error) {
    statusDiv.innerHTML = `<div class="error-message">Upload failed: ${escapeHtml(error.message)}</div>`;
    showNotification('Failed to upload resource pack: ' + error.message, 'error');
  }
}

async function deleteResourcePack() {
  if (!currentServerId) return;
  
  if (!confirm('Are you sure you want to delete this resource pack? This will also remove the resource pack configuration from server.properties.')) {
    return;
  }
  
  const statusDiv = document.getElementById('resourcepack-status');
  statusDiv.innerHTML = '<div class="loading">Deleting resource pack...</div>';
  
  try {
    await apiRequest(`/api/servers/${currentServerId}/resourcepack`, {
      method: 'DELETE'
    });
    
    showNotification('Resource pack deleted successfully', 'success');
    loadResourcePack();
  } catch (error) {
    statusDiv.innerHTML = `<div class="error-message">Delete failed: ${escapeHtml(error.message)}</div>`;
    showNotification('Failed to delete resource pack: ' + error.message, 'error');
  }
}

// Add event listeners for resource pack
document.addEventListener('DOMContentLoaded', () => {
  const uploadInput = document.getElementById('resourcepack-upload');
  const replaceBtn = document.getElementById('replace-resourcepack-btn');
  const deleteBtn = document.getElementById('delete-resourcepack-btn');
  
  if (uploadInput) {
    uploadInput.addEventListener('change', (e) => {
      const file = e.target.files[0];
      if (file) {
        uploadResourcePack(file);
      }
      // Reset input so same file can be selected again
      e.target.value = '';
    });
  }
  
  if (replaceBtn) {
    replaceBtn.addEventListener('click', () => {
      uploadInput.click();
    });
  }
  
  if (deleteBtn) {
    deleteBtn.addEventListener('click', deleteResourcePack);
  }
});

