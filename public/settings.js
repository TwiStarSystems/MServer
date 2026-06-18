// Settings page JavaScript

// Note: CSRF token management is in utils.js (window.csrfToken and fetchCSRFToken)

let socket = null;
let statsChart = null;
let currentUser = null;

// Global fetch wrapper to handle authentication errors and CSRF
// Store original fetch for utils.js to use when fetching CSRF token
window.originalFetch = window.fetch;
const originalFetch = window.fetch;
window.fetch = async function(...args) {
  // Ensure options object exists before mutating
  if (!args[1]) args[1] = {};

  // Add CSRF token to state-changing requests
  const method = args[1]?.method?.toUpperCase();
  if (method && ['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
    if (!args[1].headers) {
      args[1].headers = {};
    }
    if (window.csrfToken && !args[1].headers['X-CSRF-Token']) {
      args[1].headers['X-CSRF-Token'] = window.csrfToken;
    }
  }

  let response = await originalFetch.apply(this, args);

  // If CSRF token expired/invalid, refresh and retry once
  if (response.status === 403) {
    const clone = response.clone();
    try {
      const data = await clone.json();
      if (data.error && data.error.includes('CSRF')) {
        await fetchCSRFToken();
        if (args[1].headers) {
          args[1].headers['X-CSRF-Token'] = window.csrfToken;
        }
        response = await originalFetch.apply(this, args);
      }
    } catch (_) { /* not JSON — leave original 403 response */ }
  }

  // Redirect to login if authentication fails
  if (response.status === 401) {
    window.location.href = '/login.html';
  }

  return response;
};

document.addEventListener('DOMContentLoaded', async () => {
  // Fetch CSRF token first
  await fetchCSRFToken();
  
  // Set up tab switching FIRST before any async operations
  document.querySelectorAll('.settings-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      
      document.querySelectorAll('.settings-tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      
      document.querySelectorAll('.settings-section').forEach(s => s.classList.remove('active'));
      document.getElementById(`${tab}-section`).classList.add('active');
      
      // Load users when User Management tab is clicked
      if (tab === 'users') {
        loadUsers();
      }
      // Load approvals when Approvals tab is clicked
      if (tab === 'approvals') {
        loadPendingApprovals();
      }
      // Load API manager when API Manager tab is clicked
      if (tab === 'api') {
        loadApiManager();
      }
      // Load app settings when Server Settings tab is clicked
      if (tab === 'appsettings') {
        loadAppSettings();
      }
      // Load external backup settings when that tab is clicked
      if (tab === 'external-backup') {
        loadExternalBackupSettings();
      }
      // Load version info and JAR bucket when Tools tab is clicked
      if (tab === 'tools') {
        loadVersionInfo();
        loadJarBucketTypes();
        loadJarBucketDownloaded();
      }
    });
  });
  
  // Check authentication
  try {
    const response = await fetch('/api/auth/me');
    if (!response.ok) {
      window.location.href = '/login.html';
      return;
    }
    currentUser = await response.json();
    if (currentUser.role !== 'admin') {
      window.location.href = '/';
      return;
    }
    // Update user UI in top bar
    updateUserUI();
  } catch (err) {
    console.error('Auth error:', err);
    window.location.href = '/login.html';
    return;
  }
  
  // Load branding for page
  loadPageBranding();
  
  // Initialize Socket.IO for real-time stats
  try {
    socket = io();
    socket.on('stats_update', updateCurrentStats);
  } catch (err) {
    console.error('Socket.IO error:', err);
  }
  
  // Load initial data
  loadCurrentStats();
  loadStatsHistory();
  loadBranding();
  loadTools();
  loadJarBucketTypes();
  loadJarBucketDownloaded();
  
  // Time range change handler
  document.getElementById('time-range').addEventListener('change', loadStatsHistory);
  
  // Branding form
  document.getElementById('branding-form').addEventListener('submit', saveBranding);
  
  // Live preview for branding
  document.getElementById('branding-site-title').addEventListener('input', updateBrandingPreview);
  document.getElementById('site-icon').addEventListener('change', handleFaviconSelect);
  document.getElementById('footer-addition').addEventListener('input', updateBrandingPreview);
  
  // Favicon upload button
  document.getElementById('upload-favicon-btn').addEventListener('click', (e) => {
    e.preventDefault();
    document.getElementById('site-icon').click();
  });
  
  // Initialize chart
  initChart();
});

// ==================== User UI Functions ====================

function updateUserUI() {
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
}

async function loadPageBranding() {
  try {
    const response = await fetch('/api/settings/branding');
    if (response.ok) {
      const branding = await response.json();
      
      // Update page title
      const siteTitle = branding.siteTitle || '🎮 MServerController';
      document.getElementById('site-title').textContent = siteTitle;
      document.title = `Settings - ${siteTitle.replace(/^🎮\s*/, '')}`;
      
      // Update favicon
      if (branding.siteIcon) {
        let favicon = document.querySelector("link[rel~='icon']");
        if (!favicon) {
          favicon = document.createElement('link');
          favicon.rel = 'icon';
          document.head.appendChild(favicon);
        }
        // siteIcon is now a filename stored on the server
        favicon.href = `/public/favicons/${branding.siteIcon}`;
      }
    }
  } catch (err) {
    console.error('Failed to load page branding:', err);
  }
}

async function logout() {
  try {
    await fetch('/api/auth/logout', { method: 'POST' });
  } catch (err) {
    console.error('Logout error:', err);
  }
  window.location.href = '/login.html';
}

// ==================== Profile Settings ====================

let currentMFASecret = null;
let currentRecoveryCode = null;

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
    
    // Load notification preferences
    loadNotificationPrefs();
    
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
    
    // Save notification preferences
    await saveNotificationPrefs(true);  // silent — profile save message covers it
    
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

// ==================== Stats Functions ====================

function initChart() {
  const ctx = document.getElementById('stats-chart').getContext('2d');
  
  statsChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        {
          label: 'CPU %',
          data: [],
          borderColor: '#ff6384',
          backgroundColor: 'rgba(255, 99, 132, 0.1)',
          tension: 0.4,
          fill: true
        },
        {
          label: 'Memory %',
          data: [],
          borderColor: '#36a2eb',
          backgroundColor: 'rgba(54, 162, 235, 0.1)',
          tension: 0.4,
          fill: true
        },
        {
          label: 'Disk %',
          data: [],
          borderColor: '#ffce56',
          backgroundColor: 'rgba(255, 206, 86, 0.1)',
          tension: 0.4,
          fill: true
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        intersect: false,
        mode: 'index'
      },
      plugins: {
        legend: {
          position: 'top',
          labels: {
            color: '#888',
            usePointStyle: true
          }
        }
      },
      scales: {
        x: {
          grid: {
            color: '#333'
          },
          ticks: {
            color: '#888',
            maxTicksLimit: 12
          }
        },
        y: {
          min: 0,
          max: 100,
          grid: {
            color: '#333'
          },
          ticks: {
            color: '#888',
            callback: value => value + '%'
          }
        }
      }
    }
  });
}

async function loadCurrentStats() {
  try {
    const response = await fetch('/api/stats/current');
    if (response.ok) {
      const stats = await response.json();
      updateCurrentStats(stats);
    }
  } catch (err) {
    console.error('Failed to load current stats:', err);
  }
}

function updateCurrentStats(stats) {
  // CPU
  const cpuPercent = Math.round(stats.cpu || 0);
  document.getElementById('cpu-value').textContent = cpuPercent + '%';
  document.getElementById('cpu-bar').style.width = cpuPercent + '%';
  
  // Memory
  const memPercent = Math.round(stats.memory?.percent || 0);
  const memUsed = formatBytes(stats.memory?.used || 0);
  const memTotal = formatBytes(stats.memory?.total || 0);
  document.getElementById('memory-value').textContent = memPercent + '%';
  document.getElementById('memory-bar').style.width = memPercent + '%';
  document.getElementById('memory-details').textContent = `${memUsed} / ${memTotal}`;
  
  // Disk
  const diskPercent = Math.round(stats.disk?.percent || 0);
  const diskUsed = formatBytes(stats.disk?.used || 0);
  const diskTotal = formatBytes(stats.disk?.total || 0);
  document.getElementById('disk-value').textContent = diskPercent + '%';
  document.getElementById('disk-bar').style.width = diskPercent + '%';
  document.getElementById('disk-details').textContent = `${diskUsed} / ${diskTotal}`;
}

async function loadStatsHistory() {
  const hours = parseInt(document.getElementById('time-range').value);
  
  try {
    const response = await fetch(`/api/stats/history?hours=${hours}`);
    if (response.ok) {
      const data = await response.json();
      updateChart(data.history, hours);
    }
  } catch (err) {
    console.error('Failed to load stats history:', err);
  }
}

function updateChart(history, hours) {
  if (!statsChart || !history || history.length === 0) return;
  
  // Determine how many points to show based on time range
  const maxPoints = hours <= 6 ? 100 : hours <= 24 ? 150 : 200;
  const step = Math.max(1, Math.floor(history.length / maxPoints));
  
  const filteredHistory = history.filter((_, i) => i % step === 0);
  
  // Format labels based on time range
  const labels = filteredHistory.map(s => {
    const date = new Date(s.timestamp);
    if (hours <= 24) {
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } else {
      return date.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + 
             date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
  });
  
  statsChart.data.labels = labels;
  statsChart.data.datasets[0].data = filteredHistory.map(s => s.cpu || 0);
  statsChart.data.datasets[1].data = filteredHistory.map(s => s.memory?.percent || 0);
  statsChart.data.datasets[2].data = filteredHistory.map(s => s.disk?.percent || 0);
  statsChart.update();
}

// ==================== Branding Functions ====================

async function loadBranding() {
  try {
    const response = await fetch('/api/settings/branding');
    if (response.ok) {
      const branding = await response.json();
      
      document.getElementById('branding-site-title').value = branding.siteTitle || '';
      document.getElementById('footer-addition').value = branding.footerAddition || '';
      
      // Handle favicon
      if (branding.siteIcon) {
        // siteIcon is a filename, update the display
        document.getElementById('favicon-filename').textContent = branding.siteIcon;
        const previewContainer = document.getElementById('favicon-preview');
        previewContainer.style.display = 'block';
        document.getElementById('favicon-preview-img').src = `/public/favicons/${branding.siteIcon}`;
      }
      
      updateBrandingPreview();
    }
  } catch (err) {
    console.error('Failed to load branding:', err);
  }
}

function handleFaviconSelect(e) {
  const file = e.target.files[0];
  
  if (!file) {
    document.getElementById('favicon-filename').textContent = 'No file selected';
    document.getElementById('favicon-preview').style.display = 'none';
    return;
  }
  
  // Validate file type
  const validTypes = ['image/png', 'image/jpeg', 'image/gif', 'image/x-icon'];
  if (!validTypes.includes(file.type)) {
    alert('Invalid file type. Please upload a PNG, JPEG, GIF, or ICO image.');
    e.target.value = '';
    document.getElementById('favicon-filename').textContent = 'No file selected';
    document.getElementById('favicon-preview').style.display = 'none';
    return;
  }
  
  // Update filename display
  document.getElementById('favicon-filename').textContent = file.name;
  
  // Show preview
  const reader = new FileReader();
  reader.onload = (event) => {
    document.getElementById('favicon-preview-img').src = event.target.result;
    document.getElementById('favicon-preview').style.display = 'block';
  };
  reader.readAsDataURL(file);
  
  updateBrandingPreview();
}

function updateBrandingPreview() {
  const title = document.getElementById('branding-site-title').value || 'MServerController';
  const footerAddition = document.getElementById('footer-addition').value;
  const faviconFile = document.getElementById('site-icon').files[0];
  
  document.getElementById('preview-title').textContent = title;
  
  const iconEl = document.getElementById('preview-icon');
  if (faviconFile) {
    const reader = new FileReader();
    reader.onload = (event) => {
      iconEl.innerHTML = `<img src="${event.target.result}" alt="icon" onerror="this.parentElement.innerHTML='🎮'" style="max-width: 100%; max-height: 100%;">`;
    };
    reader.readAsDataURL(faviconFile);
  } else {
    // Check if there's an existing favicon from the server
    const existingFaviconSrc = document.getElementById('favicon-preview-img').src;
    if (existingFaviconSrc && document.getElementById('favicon-preview').style.display !== 'none') {
      iconEl.innerHTML = `<img src="${existingFaviconSrc}" alt="icon" onerror="this.parentElement.innerHTML='🎮'" style="max-width: 100%; max-height: 100%;">`;
    } else {
      iconEl.innerHTML = '🎮';
    }
  }
  
  const footerEl = document.getElementById('preview-footer-addition');
  if (footerAddition) {
    footerEl.innerHTML = footerAddition + ' | ';
  } else {
    footerEl.innerHTML = '';
  }
}

async function saveBranding(e) {
  e.preventDefault();
  
  const faviconFile = document.getElementById('site-icon').files[0];
  const siteTitle = document.getElementById('branding-site-title').value;
  const footerAddition = document.getElementById('footer-addition').value;
  
  try {
    const formData = new FormData();
    formData.append('siteTitle', siteTitle);
    formData.append('footerAddition', footerAddition);
    if (faviconFile) {
      formData.append('favicon', faviconFile);
    }
    
    const response = await fetch('/api/settings/branding', {
      method: 'PUT',
      body: formData
    });
    
    if (response.ok) {
      const result = await response.json();
      alert('Branding saved successfully!');
      
      // Reload branding to get the updated favicon filename from server
      await loadBranding();
      
      // Update page title and header
      const displayTitle = siteTitle || '🎮 MServerController';
      document.getElementById('site-title').textContent = displayTitle;
      document.title = `Settings - ${displayTitle.replace(/^🎮\s*/, '')}`;
    } else {
      const err = await response.json();
      alert('Failed to save branding: ' + (err.error || 'Unknown error'));
    }
  } catch (err) {
    alert('Failed to save branding: ' + err.message);
  }
}

// ==================== Tools Functions ====================

// ---- Server Backup / Restore ----

async function backupAllServers() {
  const btn = document.getElementById('backup-all-btn');
  const status = document.getElementById('backup-all-status');

  btn.disabled = true;
  btn.textContent = '⏳ Creating archive…';
  status.textContent = '';
  status.className = 'jar-status';

  try {
    const response = await fetch('/api/tools/servers/backup-all', { method: 'POST' });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || `Server error ${response.status}`);
    }

    // Trigger browser download
    const blob = await response.blob();
    const disposition = response.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="([^"]+)"/);
    const filename = match ? match[1] : 'mserver_backup_all.zip';

    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);

    status.textContent = `✅ Archive downloaded: ${filename}`;
    status.classList.add('status-success');
  } catch (err) {
    status.textContent = `❌ Backup failed: ${err.message}`;
    status.classList.add('status-error');
  } finally {
    btn.disabled = false;
    btn.textContent = '📥 Download All Servers';
  }
}

function onRestoreFileSelected(input) {
  const label = document.getElementById('restore-filename');
  const restoreBtn = document.getElementById('restore-all-btn');
  if (input.files && input.files.length > 0) {
    label.textContent = input.files[0].name;
    restoreBtn.disabled = false;
  } else {
    label.textContent = 'No file selected';
    restoreBtn.disabled = true;
  }
}

async function restoreAllServers() {
  const fileInput = document.getElementById('restore-file-input');
  const mode = document.getElementById('restore-mode').value;
  const btn = document.getElementById('restore-all-btn');
  const status = document.getElementById('restore-all-status');

  if (!fileInput.files || fileInput.files.length === 0) {
    alert('Please select a backup ZIP file first.');
    return;
  }

  const warningMsg = mode === 'replace'
    ? 'REPLACE mode will DELETE ALL existing servers before restoring.\n\nAre you absolutely sure? This cannot be undone.'
    : `Merge mode will overwrite servers found in the archive.\n\nContinue?`;

  if (!confirm(warningMsg)) return;

  btn.disabled = true;
  btn.textContent = '⏳ Restoring…';
  status.textContent = '';
  status.className = 'jar-status';

  try {
    const formData = new FormData();
    formData.append('backup', fileInput.files[0]);

    // Use originalFetch so the global wrapper's header injection doesn't
    // interfere with FormData (multipart) boundary — CSRF is still sent via
    // the X-CSRF-Token header added on POST by the wrapper.
    const response = await fetch(`/api/tools/servers/restore-all?mode=${encodeURIComponent(mode)}`, {
      method: 'POST',
      body: formData
    });

    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Server error ${response.status}`);

    const serverList = data.serversRestored.length > 0
      ? data.serversRestored.join(', ')
      : 'none';
    status.textContent = `✅ Restored ${data.serversRestored.length} server(s): ${serverList}  (${data.filesRestored} files)`;
    status.classList.add('status-success');

    // Reset file input
    fileInput.value = '';
    document.getElementById('restore-filename').textContent = 'No file selected';
    btn.disabled = true;
    btn.textContent = '🔄 Restore Servers';
  } catch (err) {
    status.textContent = `❌ Restore failed: ${err.message}`;
    status.classList.add('status-error');
    btn.disabled = false;
    btn.textContent = '🔄 Restore Servers';
  }
}

// ---- End Server Backup / Restore ----

async function loadTools() {
  const container = document.getElementById('tools-container');
  
  try {
    const response = await fetch('/api/tools');
    const responseText = await response.text();
    
    // Try to parse as JSON
    let data;
    try {
      data = JSON.parse(responseText);
    } catch (parseErr) {
      throw new Error(`Invalid JSON response: ${responseText.substring(0, 200)}`);
    }
    
    if (!response.ok) {
      throw new Error(`Server returned ${response.status}: ${data.error || response.statusText}`);
    }
    
    if (data.tools && data.tools.length > 0) {
      container.innerHTML = data.tools.map(tool => `
        <div class="tool-item" data-tool="${tool.name}">
          <div class="tool-item-header">
            <div class="tool-info">
              <h4 class="tool-name">📜 ${escapeHtml(tool.filename)}</h4>
              <p class="tool-desc">${escapeHtml(tool.description)}</p>
            </div>
            <div class="tool-header-btns">
              <button class="btn btn-small tool-toggle" onclick="toggleToolExpand('${tool.name}')" title="Expand/Collapse">▼</button>
              <button class="btn btn-small btn-danger" onclick="deleteTool('${tool.name}')" title="Delete Tool">🗑️</button>
            </div>
          </div>
          <div class="tool-details" id="details-${tool.name}" style="display: none;">
            <div class="tool-args-section">
              <label>Arguments (optional):</label>
              <input type="text" class="form-control tool-args-input" id="args-${tool.name}" 
                     placeholder="e.g., --download-latest=10 --quiet" />
              <small class="tool-args-hint">Enter command-line arguments separated by spaces</small>
            </div>
            <div class="tool-actions">
              <button class="btn btn-primary" onclick="runTool('${tool.name}')">▶️ Run Tool</button>
              <span class="tool-status" id="status-${tool.name}"></span>
            </div>
            <div class="tool-output" id="output-${tool.name}"></div>
          </div>
        </div>
      `).join('');
    } else {
      container.innerHTML = `
        <div class="no-tools">
          <h3>No Tools Available</h3>
          <p>Add Python scripts to the <code>./tools</code> folder to see them here.</p>
          <p>Each script should have a comment at the top describing its purpose.</p>
          <p><small>API returned: ${data.tools ? data.tools.length : 0} tools</small></p>
        </div>
      `;
    }
  } catch (err) {
    container.innerHTML = `
      <div class="no-tools">
        <h3>Failed to Load Tools</h3>
        <p>${err.message}</p>
      </div>
    `;
  }
}

function toggleToolExpand(toolName) {
  const details = document.getElementById(`details-${toolName}`);
  const toggle = document.querySelector(`[data-tool="${toolName}"] .tool-toggle`);
  
  if (details.style.display === 'none') {
    details.style.display = 'block';
    toggle.textContent = '▲';
  } else {
    details.style.display = 'none';
    toggle.textContent = '▼';
  }
}

async function uploadTool(input) {
  const file = input.files[0];
  if (!file) return;
  
  const statusDiv = document.getElementById('tool-upload-status');
  
  // Validate file extension
  if (!file.name.toLowerCase().endsWith('.py')) {
    statusDiv.style.display = 'block';
    statusDiv.className = 'upload-status error';
    statusDiv.innerHTML = '❌ Only Python (.py) files are allowed';
    input.value = ''; // Clear the input
    return;
  }
  
  // Show uploading status
  statusDiv.style.display = 'block';
  statusDiv.className = 'upload-status loading';
  statusDiv.innerHTML = '⏳ Uploading...';
  
  const formData = new FormData();
  formData.append('file', file);
  
  try {
    const response = await fetch('/api/tools/upload', {
      method: 'POST',
      body: formData
    });
    
    const result = await response.json();
    
    if (response.ok && result.success) {
      statusDiv.className = 'upload-status success';
      statusDiv.innerHTML = `✅ ${result.message}`;
      
      // Reload tools list
      loadTools();
      
      // Hide status after 3 seconds
      setTimeout(() => {
        statusDiv.style.display = 'none';
      }, 3000);
    } else {
      statusDiv.className = 'upload-status error';
      statusDiv.innerHTML = `❌ ${result.error || 'Upload failed'}`;
    }
  } catch (err) {
    statusDiv.className = 'upload-status error';
    statusDiv.innerHTML = `❌ Error: ${err.message}`;
  }
  
  // Clear the input so the same file can be selected again
  input.value = '';
}

async function deleteTool(toolName) {
  if (!confirm(`Are you sure you want to delete "${toolName}.py"?`)) return;
  
  try {
    const response = await fetch(`/api/tools/${toolName}/delete`, {
      method: 'DELETE'
    });
    
    const result = await response.json();
    
    if (response.ok && result.success) {
      alert(result.message);
      loadTools();
    } else {
      alert(`Failed to delete tool: ${result.error || 'Unknown error'}`);
    }
  } catch (err) {
    alert(`Error deleting tool: ${err.message}`);
  }
}

async function runTool(toolName) {
  const outputEl = document.getElementById(`output-${toolName}`);
  const statusEl = document.getElementById(`status-${toolName}`);
  const argsInput = document.getElementById(`args-${toolName}`);
  const card = document.querySelector(`[data-tool="${toolName}"]`);
  const btn = card.querySelector('.btn-primary');
  
  const args = argsInput ? argsInput.value.trim() : '';
  
  btn.disabled = true;
  btn.textContent = '⏳ Running...';
  statusEl.textContent = '';
  outputEl.classList.add('show');
  outputEl.classList.remove('success', 'error');
  outputEl.innerHTML = '<span class="loading-text">Executing tool...</span>';
  
  try {
    const response = await fetch(`/api/tools/${toolName}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ args: args, timeout: 300 })
    });
    
    const result = await response.json();
    
    if (result.success) {
      outputEl.classList.add('success');
      statusEl.innerHTML = '<span class="success-text">✅ Completed</span>';
      outputEl.textContent = result.output || 'Tool completed successfully (no output)';
    } else {
      outputEl.classList.add('error');
      statusEl.innerHTML = '<span class="error-text">❌ Failed</span>';
      const errorOutput = result.error || result.output || 'Tool failed';
      outputEl.textContent = errorOutput;
    }
  } catch (err) {
    outputEl.classList.add('error');
    statusEl.innerHTML = '<span class="error-text">❌ Error</span>';
    outputEl.textContent = 'Error: ' + err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = '▶️ Run Tool';
  }
}

// ==================== Version Info Functions ====================

// Load version info
async function loadVersionInfo() {
  try {
    const response = await fetch('/api/system/version');
    if (!response.ok) throw new Error('Failed to load version info');
    
    const data = await response.json();
    
    document.getElementById('current-version').textContent = data.version || 'Unknown';
    document.getElementById('current-date').textContent = data.commit_date ? new Date(data.commit_date).toLocaleString() : '--';
  } catch (error) {
    console.error('Error loading version:', error);
    document.getElementById('current-version').textContent = 'Error';
  }
}

// ==================== JAR Bucket Functions ====================

let jarBucketTypes = {};
let selectedServerType = null;
let selectedServerTypeInfo = null;
let allVersions = [];
let activeDownloads = {};
let downloadedVersions = {};  // Track which versions are already downloaded

async function loadJarBucketTypes() {
  try {
    const response = await fetch('/api/jar-bucket/types');
    if (!response.ok) throw new Error('Failed to load server types');
    
    jarBucketTypes = await response.json();
    renderJarBucketTypes();
  } catch (err) {
    console.error('Error loading JAR bucket types:', err);
  }
}

function refreshJarBucketTypes() {
  loadJarBucketTypes();
  loadJarBucketDownloaded();
}

function renderJarBucketTypes() {
  // Render Java servers category
  const serversContainer = document.getElementById('jar-bucket-servers');
  if (serversContainer && jarBucketTypes.java) {
    serversContainer.innerHTML = jarBucketTypes.java.map(type => `
      <div class="server-type-card" onclick="selectServerType('${type.id}', ${JSON.stringify(type).replace(/"/g, '&quot;')})">
        <span class="type-icon">${type.icon || '📦'}</span>
        <span class="type-name">${escapeHtml(type.name)}</span>
        <small class="type-desc">${escapeHtml(type.description)}</small>
      </div>
    `).join('') || '<div class="no-data">No Java servers available</div>';
  }
  
  // Render Bedrock category
  const bedrockContainer = document.getElementById('jar-bucket-bedrock');
  if (bedrockContainer && jarBucketTypes.bedrock) {
    bedrockContainer.innerHTML = jarBucketTypes.bedrock.map(type => `
      <div class="server-type-card" onclick="selectServerType('${type.id}', ${JSON.stringify(type).replace(/"/g, '&quot;')})">
        <span class="type-icon">${type.icon || '📦'}</span>
        <span class="type-name">${escapeHtml(type.name)}</span>
        <small class="type-desc">${escapeHtml(type.description)}</small>
      </div>
    `).join('') || '<div class="no-data">No Bedrock servers available</div>';
  }
  
  // Render modded category
  const moddedContainer = document.getElementById('jar-bucket-modded');
  if (moddedContainer && jarBucketTypes.modded) {
    moddedContainer.innerHTML = jarBucketTypes.modded.map(type => `
      <div class="server-type-card" onclick="selectServerType('${type.id}', ${JSON.stringify(type).replace(/"/g, '&quot;')})">
        <span class="type-icon">${type.icon || '📦'}</span>
        <span class="type-name">${escapeHtml(type.name)}</span>
        <small class="type-desc">${escapeHtml(type.description)}</small>
      </div>
    `).join('') || '<div class="no-data">No modded servers available</div>';
  }
}

async function selectServerType(typeId, typeInfo) {
  selectedServerType = typeId;
  selectedServerTypeInfo = typeInfo;
  
  // Update header
  document.getElementById('selected-type-icon').textContent = typeInfo.icon || '📦';
  document.getElementById('selected-type-name').textContent = typeInfo.name;
  
  // Show versions panel
  const versionsPanel = document.getElementById('jar-bucket-versions-panel');
  versionsPanel.style.display = 'block';
  
  // Clear search
  document.getElementById('version-search-input').value = '';
  
  // Load versions
  const versionsList = document.getElementById('jar-bucket-versions-list');
  versionsList.innerHTML = '<div class="loading-text">Loading versions...</div>';
  
  try {
    // Fetch both versions and downloaded files in parallel
    const [versionsResponse, downloadedResponse] = await Promise.all([
      fetch(`/api/jar-bucket/versions/${typeId}`),
      fetch('/api/jar-bucket/list')
    ]);
    
    if (!versionsResponse.ok) throw new Error('Failed to load versions');
    
    const versionsData = await versionsResponse.json();
    allVersions = versionsData.versions || [];
    
    // Build set of downloaded versions for this type
    downloadedVersions = {};
    if (downloadedResponse.ok) {
      const downloadedData = await downloadedResponse.json();
      const typeJars = downloadedData.jars?.[typeId];
      if (typeJars && typeJars.files) {
        for (const file of typeJars.files) {
          if (file.version) {
            downloadedVersions[file.version] = file;
          }
        }
      }
    }
    
    // Update version count
    const countEl = document.getElementById('selected-type-count');
    if (countEl) {
      const downloadedCount = Object.keys(downloadedVersions).length;
      countEl.textContent = `(${allVersions.length} available, ${downloadedCount} downloaded)`;
    }
    
    renderVersions(allVersions);
  } catch (err) {
    versionsList.innerHTML = `<div class="error-text">Failed to load versions: ${err.message}</div>`;
  }
}

function renderVersions(versions) {
  const versionsList = document.getElementById('jar-bucket-versions-list');
  
  if (!versions || versions.length === 0) {
    versionsList.innerHTML = '<div class="no-data">No versions available</div>';
    return;
  }
  
  versionsList.innerHTML = versions.map(version => {
    const isDownloaded = downloadedVersions[version];
    const downloadedFile = isDownloaded ? downloadedVersions[version] : null;
    
    return `
      <div class="version-item ${isDownloaded ? 'downloaded' : ''}">
        <div class="version-info">
          <span class="version-number">${escapeHtml(version)}</span>
          ${isDownloaded ? `<span class="downloaded-badge" title="${escapeHtml(downloadedFile?.filename || '')}">✓ Downloaded</span>` : ''}
        </div>
        <button class="btn btn-small ${isDownloaded ? 'btn-secondary' : 'btn-success'}" onclick="downloadJarVersion('${selectedServerType}', '${escapeHtml(version)}')">
          ${isDownloaded ? '🔄 Re-download' : '📥 Download'}
        </button>
      </div>
    `;
  }).join('');
}

function filterVersions() {
  const searchTerm = document.getElementById('version-search-input').value.toLowerCase();
  const filtered = allVersions.filter(v => v.toLowerCase().includes(searchTerm));
  renderVersions(filtered);
}

function closeVersionsPanel() {
  document.getElementById('jar-bucket-versions-panel').style.display = 'none';
  selectedServerType = null;
  selectedServerTypeInfo = null;
  allVersions = [];
  downloadedVersions = {};
}

async function downloadAllVersions() {
  if (!selectedServerType || !allVersions.length) {
    alert('No versions to download');
    return;
  }
  
  // Filter to only non-downloaded versions
  const toDownload = allVersions.filter(v => !downloadedVersions[v]);
  
  if (toDownload.length === 0) {
    alert('All versions are already downloaded!');
    return;
  }
  
  const confirmMsg = `Download ${toDownload.length} version(s) of ${selectedServerTypeInfo?.name || selectedServerType}?\n\nThis may take a while and use significant disk space.`;
  if (!confirm(confirmMsg)) return;
  
  const progressPanel = document.getElementById('jar-download-progress-panel');
  const progressContent = document.getElementById('jar-download-progress-content');
  
  progressPanel.style.display = 'block';
  progressContent.innerHTML = `
    <div class="bulk-download-status">
      <div class="bulk-progress-header">
        <span>Downloading ${selectedServerTypeInfo?.name || selectedServerType}</span>
        <span id="bulk-progress-count">0 / ${toDownload.length}</span>
      </div>
      <div class="progress-bar">
        <div id="bulk-progress-bar" class="progress-bar-fill" style="width: 0%"></div>
      </div>
      <div id="bulk-progress-current" class="bulk-current">Starting...</div>
      <div id="bulk-progress-log" class="bulk-log"></div>
    </div>
  `;
  
  let completed = 0;
  let failed = 0;
  const logEl = document.getElementById('bulk-progress-log');
  
  for (const version of toDownload) {
    document.getElementById('bulk-progress-current').textContent = `Downloading: ${version}`;
    
    try {
      const response = await fetch('/api/jar-bucket/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: selectedServerType, version })
      });
      
      const data = await response.json();
      
      if (response.ok && data.progress_id) {
        // Wait for download to complete
        await waitForDownload(data.progress_id);
        completed++;
        logEl.innerHTML = `<div class="log-success">✅ ${version}</div>` + logEl.innerHTML;
      } else {
        failed++;
        logEl.innerHTML = `<div class="log-error">❌ ${version}: ${data.error || 'Failed'}</div>` + logEl.innerHTML;
      }
    } catch (err) {
      failed++;
      logEl.innerHTML = `<div class="log-error">❌ ${version}: ${err.message}</div>` + logEl.innerHTML;
    }
    
    // Update progress
    const total = completed + failed;
    const percent = Math.round((total / toDownload.length) * 100);
    document.getElementById('bulk-progress-count').textContent = `${total} / ${toDownload.length}`;
    document.getElementById('bulk-progress-bar').style.width = `${percent}%`;
  }
  
  document.getElementById('bulk-progress-current').textContent = `Complete! ${completed} succeeded, ${failed} failed.`;
  
  // Refresh the downloaded list
  loadJarBucketDownloaded();
  
  // Refresh the versions panel to update downloaded status
  if (selectedServerType && selectedServerTypeInfo) {
    selectServerType(selectedServerType, selectedServerTypeInfo);
  }
}

async function waitForDownload(progressId, maxWaitMs = 300000) {
  const startTime = Date.now();
  
  while (Date.now() - startTime < maxWaitMs) {
    try {
      const response = await fetch(`/api/jar-bucket/progress/${progressId}`);
      const data = await response.json();
      
      if (data.status === 'complete') {
        if (data.success) return true;
        throw new Error(data.error || 'Download failed');
      } else if (data.status === 'error') {
        throw new Error(data.error || 'Download failed');
      }
      
      // Still downloading, wait and check again
      await new Promise(resolve => setTimeout(resolve, 1000));
    } catch (err) {
      console.error('Progress check error:', err);
      throw err;
    }
  }
  
  throw new Error('Download timeout');
}

async function downloadJarVersion(serverType, version) {
  const progressPanel = document.getElementById('jar-download-progress-panel');
  const progressContent = document.getElementById('jar-download-progress-content');
  
  progressPanel.style.display = 'block';
  progressContent.innerHTML = `
    <div class="download-item">
      <div class="download-info">
        <span class="download-name">${escapeHtml(serverType)} ${escapeHtml(version)}</span>
        <span class="download-status">Starting download...</span>
      </div>
      <div class="progress-bar">
        <div class="progress-bar-fill" style="width: 0%"></div>
      </div>
    </div>
  `;
  
  try {
    const response = await fetch('/api/jar-bucket/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: serverType, version })
    });
    
    const data = await response.json();
    
    if (!response.ok) {
      progressContent.innerHTML = `
        <div class="download-item error">
          <div class="download-info">
            <span class="download-name">${escapeHtml(serverType)} ${escapeHtml(version)}</span>
            <span class="download-status error">❌ ${data.error || 'Failed to start download'}</span>
          </div>
          <div class="download-actions">
            <button class="btn btn-small btn-secondary" onclick="downloadJarVersion('${escapeHtml(serverType)}', '${escapeHtml(version)}')">🔄 Retry</button>
            <button class="btn btn-small" onclick="document.getElementById('jar-download-progress-panel').style.display='none'">Dismiss</button>
          </div>
        </div>
      `;
      return;
    }
    
    if (!data.progress_id) {
      progressContent.innerHTML = `
        <div class="download-item error">
          <div class="download-info">
            <span class="download-name">${escapeHtml(serverType)} ${escapeHtml(version)}</span>
            <span class="download-status error">❌ Failed to start download - no progress ID</span>
          </div>
          <div class="download-actions">
            <button class="btn btn-small btn-secondary" onclick="downloadJarVersion('${escapeHtml(serverType)}', '${escapeHtml(version)}')">🔄 Retry</button>
            <button class="btn btn-small" onclick="document.getElementById('jar-download-progress-panel').style.display='none'">Dismiss</button>
          </div>
        </div>
      `;
      return;
    }
    
    // Poll for progress
    const progressId = data.progress_id;
    pollDownloadProgress(progressId, serverType, version);
    
  } catch (err) {
    progressContent.innerHTML = `
      <div class="download-item error">
        <div class="download-info">
          <span class="download-name">${escapeHtml(serverType)} ${escapeHtml(version)}</span>
          <span class="download-status error">❌ Network error: ${err.message}</span>
        </div>
        <div class="download-actions">
          <button class="btn btn-small btn-secondary" onclick="downloadJarVersion('${escapeHtml(serverType)}', '${escapeHtml(version)}')">🔄 Retry</button>
          <button class="btn btn-small" onclick="document.getElementById('jar-download-progress-panel').style.display='none'">Dismiss</button>
        </div>
      </div>
    `;
  }
}

async function pollDownloadProgress(progressId, serverType, version) {
  const progressContent = document.getElementById('jar-download-progress-content');
  let pollCount = 0;
  const maxPolls = 600; // 5 minute timeout
  let consecutiveErrors = 0;
  const maxConsecutiveErrors = 5;
  
  const checkProgress = async () => {
    pollCount++;
    
    if (pollCount > maxPolls) {
      progressContent.innerHTML = `
        <div class="download-item error">
          <div class="download-info">
            <span class="download-name">${escapeHtml(serverType)} ${escapeHtml(version)}</span>
            <span class="download-status error">❌ Download timed out</span>
          </div>
          <div class="download-actions">
            <button class="btn btn-small btn-secondary" onclick="downloadJarVersion('${escapeHtml(serverType)}', '${escapeHtml(version)}')">🔄 Retry</button>
            <button class="btn btn-small" onclick="document.getElementById('jar-download-progress-panel').style.display='none'">Dismiss</button>
          </div>
        </div>
      `;
      return;
    }
    
    try {
      const response = await fetch(`/api/jar-bucket/progress/${progressId}`);
      
      // Check if response is valid before parsing
      if (!response.ok) {
        // If 404, the progress ID doesn't exist yet (still initializing)
        if (response.status === 404) {
          consecutiveErrors++;
          if (consecutiveErrors >= maxConsecutiveErrors) {
            progressContent.innerHTML = `
              <div class="download-item error">
                <div class="download-info">
                  <span class="download-name">${escapeHtml(serverType)} ${escapeHtml(version)}</span>
                  <span class="download-status error">❌ Download initialization failed</span>
                </div>
                <div class="download-actions">
                  <button class="btn btn-small btn-secondary" onclick="downloadJarVersion('${escapeHtml(serverType)}', '${escapeHtml(version)}')">🔄 Retry</button>
                  <button class="btn btn-small" onclick="document.getElementById('jar-download-progress-panel').style.display='none'">Dismiss</button>
                </div>
              </div>
            `;
            return;
          } else {
            // Keep trying for 404s (initialization delay)
            setTimeout(checkProgress, 1000);
            return;
          }
        }
        throw new Error(`Server returned ${response.status}: ${response.statusText}`);
      }
      
      // Check content type before parsing
      const contentType = response.headers.get('content-type');
      if (!contentType || !contentType.includes('application/json')) {
        throw new Error('Server response is not JSON');
      }
      
      const data = await response.json();
      
      consecutiveErrors = 0; // Reset on successful poll
      
      if (data.status === 'initializing') {
        // Still initializing, keep polling
        progressContent.innerHTML = `
          <div class="download-item">
            <div class="download-info">
              <span class="download-name">${escapeHtml(serverType)} ${escapeHtml(version)}</span>
              <span class="download-status">${data.message || 'Initializing...'}</span>
            </div>
            <div class="progress-bar">
              <div class="progress-bar-fill" style="width: 0%"></div>
            </div>
          </div>
        `;
        setTimeout(checkProgress, 500);
      } else if (data.status === 'downloading') {
        const percent = data.progress || 0;
        const downloaded = formatBytes(data.downloaded || 0);
        const total = formatBytes(data.total || 0);
        
        progressContent.innerHTML = `
          <div class="download-item">
            <div class="download-info">
              <span class="download-name">${escapeHtml(serverType)} ${escapeHtml(version)}</span>
              <span class="download-status">${downloaded} / ${total}</span>
            </div>
            <div class="progress-bar">
              <div class="progress-bar-fill" style="width: ${percent}%"></div>
            </div>
          </div>
        `;
        setTimeout(checkProgress, 500);
      } else if (data.status === 'complete') {
        if (data.success !== false) {
          progressContent.innerHTML = `
            <div class="download-item success">
              <div class="download-info">
                <span class="download-name">${escapeHtml(serverType)} ${escapeHtml(version)}</span>
                <span class="download-status success">✅ ${data.message || 'Download complete!'}</span>
              </div>
              <small class="download-path">📁 ${data.path || ''}</small>
              <div class="download-actions">
                <button class="btn btn-small btn-success" onclick="document.getElementById('jar-download-progress-panel').style.display='none'; selectServerType('${escapeHtml(serverType)}', selectedServerTypeInfo);">View Downloads</button>
              </div>
            </div>
          `;
          // Refresh the downloaded list and version panel
          loadJarBucketDownloaded();
          if (selectedServerType === serverType) {
            // Update the version panel to show new downloaded status
            downloadedVersions[version] = true;
            renderVersions(allVersions || []);
          }
        } else {
          progressContent.innerHTML = `
            <div class="download-item error">
              <div class="download-info">
                <span class="download-name">${escapeHtml(serverType)} ${escapeHtml(version)}</span>
                <span class="download-status error">❌ ${data.error || 'Download failed'}</span>
              </div>
              <div class="download-actions">
                <button class="btn btn-small btn-secondary" onclick="downloadJarVersion('${escapeHtml(serverType)}', '${escapeHtml(version)}')">🔄 Retry</button>
                <button class="btn btn-small" onclick="document.getElementById('jar-download-progress-panel').style.display='none'">Dismiss</button>
              </div>
            </div>
          `;
        }
      } else if (data.status === 'error') {
        progressContent.innerHTML = `
          <div class="download-item error">
            <div class="download-info">
              <span class="download-name">${escapeHtml(serverType)} ${escapeHtml(version)}</span>
              <span class="download-status error">❌ ${data.error || 'Download failed'}</span>
            </div>
            <div class="download-actions">
              <button class="btn btn-small btn-secondary" onclick="downloadJarVersion('${escapeHtml(serverType)}', '${escapeHtml(version)}')">🔄 Retry</button>
              <button class="btn btn-small" onclick="document.getElementById('jar-download-progress-panel').style.display='none'">Dismiss</button>
            </div>
          </div>
        `;
      } else {
        // Unknown status, keep polling
        setTimeout(checkProgress, 500);
      }
    } catch (err) {
      consecutiveErrors++;
      if (consecutiveErrors >= maxConsecutiveErrors) {
        progressContent.innerHTML = `
          <div class="download-item error">
            <div class="download-info">
              <span class="download-name">${escapeHtml(serverType)} ${escapeHtml(version)}</span>
              <span class="download-status error">❌ Lost connection to server</span>
            </div>
            <div class="download-actions">
              <button class="btn btn-small btn-secondary" onclick="downloadJarVersion('${escapeHtml(serverType)}', '${escapeHtml(version)}')">🔄 Retry</button>
              <button class="btn btn-small" onclick="document.getElementById('jar-download-progress-panel').style.display='none'">Dismiss</button>
            </div>
          </div>
        `;
      } else {
        // Keep trying
        setTimeout(checkProgress, 1000);
      }
    }
  };
  
  checkProgress();
}

async function loadJarBucketDownloaded() {
  const container = document.getElementById('jar-bucket-downloaded-list');
  if (!container) return;
  
  try {
    const response = await fetch('/api/jar-bucket/list');
    const data = await response.json();
    
    if (!data.jars || Object.keys(data.jars).length === 0) {
      container.innerHTML = '<div class="no-jars-text">No downloaded JARs yet. Use the browser above to download server files.</div>';
      return;
    }
    
    let html = '';
    
    for (const [serverType, typeData] of Object.entries(data.jars)) {
      if (!typeData.files || typeData.files.length === 0) continue;
      
      html += `
        <div class="jar-type-group">
          <div class="jar-type-header">
            <span class="jar-type-icon">${typeData.icon || '📦'}</span>
            <span class="jar-type-name">${escapeHtml(typeData.name || serverType)}</span>
            <span class="jar-type-count">${typeData.files.length} file(s)</span>
          </div>
          <div class="jar-type-files">
      `;
      
      for (const file of typeData.files) {
        html += `
          <div class="jar-file-item">
            <div class="jar-file-info">
              <span class="jar-filename">${escapeHtml(file.filename)}</span>
              <span class="jar-version">${escapeHtml(file.version || 'Unknown')}</span>
              <span class="jar-size">${formatBytes(file.size)}</span>
            </div>
            <div class="jar-file-actions">
              <button class="btn btn-small btn-danger" onclick="deleteJarBucket('${serverType}', '${escapeHtml(file.filename)}')" title="Delete">🗑️</button>
            </div>
          </div>
        `;
      }
      
      html += '</div></div>';
    }
    
    container.innerHTML = html || '<div class="no-jars-text">No downloaded JARs yet</div>';
    
  } catch (err) {
    container.innerHTML = `<div class="error-text">Failed to load files: ${err.message}</div>`;
  }
}

async function deleteJarBucket(serverType, filename) {
  if (!confirm(`Delete ${filename}?`)) return;
  
  try {
    const response = await fetch('/api/jar-bucket/delete', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: serverType, filename })
    });
    
    const data = await response.json();
    
    if (response.ok && data.success) {
      loadJarBucketDownloaded();
    } else {
      alert('Failed to delete: ' + (data.error || 'Unknown error'));
    }
  } catch (err) {
    alert('Error: ' + err.message);
  }
}

// Toggle collapsible tool panels
function toggleToolPanel(header) {
  const panel = header.closest('.tool-panel');
  const body = panel.querySelector('.tool-panel-body');
  const indicator = header.querySelector('.collapse-indicator');
  
  if (body.style.display === 'none') {
    body.style.display = 'block';
    panel.classList.remove('collapsed');
    if (indicator) indicator.textContent = '▼';
  } else {
    body.style.display = 'none';
    panel.classList.add('collapsed');
    if (indicator) indicator.textContent = '▶';
  }
}

// ==================== Legacy JAR Downloader Functions ====================

async function downloadJarManual() {
  const typeInput = document.getElementById('download-type');
  const versionInput = document.getElementById('download-version');
  const urlInput = document.getElementById('download-url');
  const btn = document.getElementById('download-jar-btn');
  const statusDiv = document.getElementById('download-status');
  
  const serverType = typeInput.value.trim().toLowerCase();
  const version = versionInput.value.trim();
  const url = urlInput.value.trim();
  
  if (!serverType || !version || !url) {
    statusDiv.innerHTML = '<span class="error-text">⚠️ Please fill in all fields</span>';
    return;
  }
  
  btn.disabled = true;
  btn.innerHTML = '⏳ Downloading...';
  statusDiv.innerHTML = '<span class="loading-text">📥 Downloading file...</span>';
  
  try {
    const response = await fetch('/api/tools/jar-downloader/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: serverType, version, url })
    });
    
    const data = await response.json();
    
    if (response.ok && data.success) {
      statusDiv.innerHTML = `<span class="success-text">✅ ${data.message}</span>
        <div class="download-details">
          <small>📁 Saved to: ${data.path}</small>
          ${data.size ? `<small>📦 Size: ${formatBytes(data.size)}</small>` : ''}
        </div>`;
      
      // Clear form
      typeInput.value = '';
      versionInput.value = '';
      urlInput.value = '';
      
      // Reload both lists
      loadDownloadedJars();
      loadJarBucketDownloaded();
    } else {
      statusDiv.innerHTML = `<span class="error-text">❌ ${data.error || 'Download failed'}</span>`;
    }
  } catch (err) {
    statusDiv.innerHTML = `<span class="error-text">❌ Error: ${err.message}</span>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '📥 Download JAR';
  }
}

async function loadDownloadedJars() {
  const container = document.getElementById('downloaded-jars-list');
  if (!container) return;
  
  try {
    const response = await fetch('/api/tools/jar-downloader/list');
    const data = await response.json();
    
    if (!data.jars || Object.keys(data.jars).length === 0) {
      container.innerHTML = '<div class="no-jars-text">No downloaded files yet</div>';
      return;
    }
    
    // Build table HTML
    let html = '<table class="jars-table"><thead><tr>';
    html += '<th>Type</th><th>Filename</th><th>Size</th><th>Actions</th>';
    html += '</tr></thead><tbody>';
    
    let hasFiles = false;
    for (const [serverType, files] of Object.entries(data.jars)) {
      if (files.length === 0) continue;
      
      for (const file of files) {
        hasFiles = true;
        html += `
          <tr>
            <td><span class="jar-type-badge">${escapeHtml(serverType)}</span></td>
            <td class="jar-filename-cell">${escapeHtml(file.filename)}</td>
            <td class="jar-size-cell">${formatBytes(file.size)}</td>
            <td class="jar-actions-cell">
              <button class="btn btn-small btn-danger" onclick="deleteJar('${serverType}', '${escapeHtml(file.filename)}')" title="Delete">🗑️</button>
            </td>
          </tr>`;
      }
    }
    
    html += '</tbody></table>';
    container.innerHTML = hasFiles ? html : '<div class="no-jars-text">No downloaded files yet</div>';
  } catch (err) {
    container.innerHTML = `<div class="error-text">Failed to load files: ${err.message}</div>`;
  }
}

async function deleteJar(serverType, filename) {
  if (!confirm(`Delete ${filename}?`)) return;
  
  try {
    const response = await fetch('/api/tools/jar-downloader/delete', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: serverType, filename })
    });
    
    const data = await response.json();
    
    if (response.ok && data.success) {
      loadDownloadedJars();
    } else {
      alert('Failed to delete: ' + (data.error || 'Unknown error'));
    }
  } catch (err) {
    alert('Error: ' + err.message);
  }
}

// ==================== User Management Functions ====================
// Note: Utility functions (formatBytes, escapeHtml) are in utils.js

async function loadUsers() {
  try {
    const response = await fetch('/api/admin/users');
    if (!response.ok) throw new Error('Failed to load users');
    
    const data = await response.json();
    const users = data.users || [];
    const approvedUsers = users.filter(u => u.approved);
    
    const usersList = document.getElementById('users-list');
    if (approvedUsers.length === 0) {
      usersList.innerHTML = `
        <div class="user-mgmt-empty">
          <h3>No Users</h3>
          <p>No registered users found</p>
        </div>
      `;
    } else {
      usersList.innerHTML = `
        <table class="user-mgmt-table">
          <thead>
            <tr>
              <th>Username</th>
              <th>Display Name</th>
              <th>Email</th>
              <th>Role</th>
              <th>MFA</th>
              <th>Created</th>
              <th>Last Login</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            ${approvedUsers.map(u => `
              <tr>
                <td>${escapeHtml(u.username)}</td>
                <td>${u.name ? escapeHtml(u.name) : '<span class="text-muted">Not set</span>'}</td>
                <td>${u.email ? escapeHtml(u.email) : '<span class="text-muted">Not set</span>'}</td>
                <td><span class="role-badge ${u.role}">${u.role}</span></td>
                <td>${u.mfaEnabled ? '<span class="badge badge-success">Enabled</span>' : '<span class="badge badge-secondary">Disabled</span>'}</td>
                <td>${new Date(u.created).toLocaleDateString()}</td>
                <td>${u.lastLogin ? new Date(u.lastLogin).toLocaleDateString() : 'Never'}</td>
                <td class="user-mgmt-actions">
                  <button class="btn btn-small btn-primary" onclick="openEditUserModal('${u.id}')">✏️ Edit</button>
                  <button class="btn btn-small btn-danger" onclick="deleteUser('${u.id}', '${escapeHtml(u.username)}')">🗑️</button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    }
  } catch (err) {
    console.error('Failed to load users:', err);
    document.getElementById('users-list').innerHTML = `
      <div class="user-mgmt-empty">
        <h3>Error Loading Users</h3>
        <p>${err.message}</p>
      </div>
    `;
  }
}

// ==================== Approvals Functions ====================

async function loadPendingApprovals() {
  await Promise.all([loadPendingUsers(), loadPendingServers()]);
}

async function loadPendingUsers() {
  try {
    const response = await fetch('/api/admin/users');
    if (!response.ok) throw new Error('Failed to load users');
    
    const data = await response.json();
    const users = data.users || [];
    const pendingUsers = users.filter(u => !u.approved);
    
    // Update count badge
    document.getElementById('pending-users-count').textContent = pendingUsers.length;
    
    const pendingList = document.getElementById('pending-users-list');
    if (pendingUsers.length === 0) {
      pendingList.innerHTML = `
        <div class="approval-empty">
          <p>No pending user registrations</p>
        </div>
      `;
    } else {
      pendingList.innerHTML = `
        <div class="approval-items">
          ${pendingUsers.map(u => `
            <div class="approval-item">
              <div class="approval-item-info">
                <span class="approval-item-name">${escapeHtml(u.username)}</span>
                <span class="approval-item-date">Registered ${new Date(u.created).toLocaleDateString()}</span>
              </div>
              <div class="approval-item-actions">
                <button class="btn btn-small btn-success" onclick="approveUser('${u.id}')">Approve</button>
                <button class="btn btn-small btn-danger" onclick="deleteUser('${u.id}', '${escapeHtml(u.username)}')">Reject</button>
              </div>
            </div>
          `).join('')}
        </div>
      `;
    }
  } catch (err) {
    console.error('Failed to load pending users:', err);
    document.getElementById('pending-users-list').innerHTML = `
      <div class="approval-empty">
        <p>Error loading pending users</p>
      </div>
    `;
  }
}

async function loadPendingServers() {
  try {
    const response = await fetch('/api/admin/servers/pending');
    if (!response.ok) {
      // Endpoint may not exist yet - show empty state
      document.getElementById('pending-servers-count').textContent = '0';
      document.getElementById('pending-servers-list').innerHTML = `
        <div class="approval-empty">
          <p>No pending server requests</p>
        </div>
      `;
      return;
    }
    
    const data = await response.json();
    const pendingServers = data.servers || [];
    
    // Update count badge
    document.getElementById('pending-servers-count').textContent = pendingServers.length;
    
    const pendingList = document.getElementById('pending-servers-list');
    if (pendingServers.length === 0) {
      pendingList.innerHTML = `
        <div class="approval-empty">
          <p>No pending server requests</p>
        </div>
      `;
    } else {
      pendingList.innerHTML = `
        <div class="approval-items">
          ${pendingServers.map(s => `
            <div class="approval-item">
              <div class="approval-item-info">
                <span class="approval-item-name">${escapeHtml(s.name)}</span>
                <span class="approval-item-meta">Requested by ${escapeHtml(s.owner || 'Unknown')} • ${s.type || 'Server'}</span>
                <span class="approval-item-date">Requested ${new Date(s.created).toLocaleDateString()}</span>
              </div>
              <div class="approval-item-actions">
                <button class="btn btn-small btn-success" onclick="approveServer('${s.id}')">Approve</button>
                <button class="btn btn-small btn-danger" onclick="rejectServer('${s.id}', '${escapeHtml(s.name)}')">Reject</button>
              </div>
            </div>
          `).join('')}
        </div>
      `;
    }
  } catch (err) {
    console.error('Failed to load pending servers:', err);
    document.getElementById('pending-servers-count').textContent = '0';
    document.getElementById('pending-servers-list').innerHTML = `
      <div class="approval-empty">
        <p>No pending server requests</p>
      </div>
    `;
  }
}

async function approveServer(serverId) {
  try {
    const response = await fetch(`/api/admin/servers/${serverId}/approve`, { method: 'POST' });
    if (!response.ok) throw new Error('Failed to approve server');
    loadPendingServers();
  } catch (err) {
    console.error('Failed to approve server:', err);
    alert('Failed to approve server: ' + err.message);
  }
}

async function rejectServer(serverId, serverName) {
  if (!confirm(`Are you sure you want to reject the server request "${serverName}"? This will delete the request.`)) return;
  
  try {
    const response = await fetch(`/api/admin/servers/${serverId}/reject`, { method: 'DELETE' });
    if (!response.ok) throw new Error('Failed to reject server');
    loadPendingServers();
  } catch (err) {
    console.error('Failed to reject server:', err);
    alert('Failed to reject server: ' + err.message);
  }
}

async function approveUser(userId) {
  try {
    const response = await fetch(`/api/admin/users/${userId}/approve`, { method: 'POST' });
    if (!response.ok) throw new Error('Failed to approve user');
    loadUsers();
  } catch (err) {
    console.error('Failed to approve user:', err);
    alert('Failed to approve user: ' + err.message);
  }
}

async function deleteUser(userId, username) {
  if (!confirm(`Are you sure you want to delete user "${username}"?`)) return;
  
  try {
    const response = await fetch(`/api/admin/users/${userId}`, { method: 'DELETE' });
    if (!response.ok) throw new Error('Failed to delete user');
    loadUsers();
  } catch (err) {
    console.error('Failed to delete user:', err);
    alert('Failed to delete user: ' + err.message);
  }
}

// ==================== Edit User Functions ====================

let editingUserId = null;

async function openEditUserModal(userId) {
  try {
    const response = await fetch(`/api/admin/users/${userId}`);
    if (!response.ok) throw new Error('Failed to load user');
    
    const data = await response.json();
    const user = data.user;
    
    editingUserId = userId;
    
    // Populate the modal fields
    document.getElementById('edit-user-display-username').textContent = user.username;
    const roleDisplay = document.getElementById('edit-user-display-role');
    roleDisplay.textContent = user.role.toUpperCase();
    roleDisplay.className = 'profile-info-value profile-role-badge ' + user.role;
    
    document.getElementById('edit-user-username').value = user.username;
    document.getElementById('edit-user-name').value = user.name || '';
    document.getElementById('edit-user-email').value = user.email || '';
    document.getElementById('edit-user-role').value = user.role;
    
    // Update MFA status display
    const mfaStatusContainer = document.getElementById('edit-user-mfa-status');
    if (user.mfaEnabled) {
      mfaStatusContainer.innerHTML = `
        <p class="mfa-info success-text">✓ Two-factor authentication is enabled on this account.</p>
        <button class="btn btn-danger" onclick="clearUserMFA('${userId}')">Clear MFA</button>
      `;
    } else {
      mfaStatusContainer.innerHTML = `
        <p class="mfa-info">Two-factor authentication is not enabled on this account.</p>
      `;
    }
    
    // Clear password field
    document.getElementById('edit-user-new-password').value = '';
    
    // Show modal
    document.getElementById('edit-user-modal').style.display = 'flex';
  } catch (err) {
    console.error('Failed to load user:', err);
    alert('Failed to load user: ' + err.message);
  }
}

function closeEditUserModal() {
  document.getElementById('edit-user-modal').style.display = 'none';
  editingUserId = null;
}

async function saveEditUser() {
  if (!editingUserId) return;
  
  const username = document.getElementById('edit-user-username').value.trim();
  const name = document.getElementById('edit-user-name').value.trim();
  const email = document.getElementById('edit-user-email').value.trim();
  const role = document.getElementById('edit-user-role').value;
  const newPassword = document.getElementById('edit-user-new-password').value;
  
  if (!username) {
    showNotification('Username is required', 'error');
    return;
  }
  
  try {
    // Update username
    const usernameResponse = await fetch(`/api/admin/users/${editingUserId}/username`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username })
    });
    
    if (!usernameResponse.ok) {
      const data = await usernameResponse.json();
      showNotification(data.error || 'Failed to update username', 'error');
      return;
    }
    
    // Update name
    const nameResponse = await fetch(`/api/admin/users/${editingUserId}/name`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    });
    
    if (!nameResponse.ok) {
      const data = await nameResponse.json();
      showNotification(data.error || 'Failed to update display name', 'error');
      return;
    }
    
    // Update email
    const emailResponse = await fetch(`/api/admin/users/${editingUserId}/email`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email })
    });
    
    if (!emailResponse.ok) {
      const data = await emailResponse.json();
      showNotification(data.error || 'Failed to update email', 'error');
      return;
    }
    
    // Update role
    const roleResponse = await fetch(`/api/admin/users/${editingUserId}/role`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role })
    });
    
    if (!roleResponse.ok) {
      const data = await roleResponse.json();
      showNotification(data.error || 'Failed to update role', 'error');
      return;
    }
    
    // Update password if provided
    if (newPassword) {
      if (newPassword.length < 6) {
        showNotification('Password must be at least 6 characters', 'error');
        return;
      }
      
      const passwordResponse = await fetch(`/api/admin/users/${editingUserId}/password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: newPassword })
      });
      
      if (!passwordResponse.ok) {
        const data = await passwordResponse.json();
        showNotification(data.error || 'Failed to reset password', 'error');
        return;
      }
    }
    
    showNotification('User updated successfully', 'success');
    closeEditUserModal();
    loadUsers();
  } catch (err) {
    console.error('Failed to update user:', err);
    showNotification('Failed to update user: ' + err.message, 'error');
  }
}

async function clearUserMFA(userId) {
  if (!confirm('Are you sure you want to clear MFA for this user? They will need to set it up again.')) {
    return;
  }
  
  try {
    const response = await fetch(`/api/admin/users/${userId}/mfa`, {
      method: 'DELETE'
    });
    
    const data = await response.json();
    
    if (!response.ok) {
      showNotification(data.error || 'Failed to clear MFA', 'error');
      return;
    }
    
    showNotification('MFA cleared successfully', 'success');
    
    // Refresh the modal to show updated MFA status
    openEditUserModal(userId);
  } catch (err) {
    console.error('Failed to clear MFA:', err);
    showNotification('Failed to clear MFA: ' + err.message, 'error');
  }
}

// ==================== Add User Functions ====================

function openAddUserModal() {
  document.getElementById('add-user-modal').style.display = 'flex';
  document.getElementById('new-username').focus();
}

function closeAddUserModal() {
  document.getElementById('add-user-modal').style.display = 'none';
  document.getElementById('add-user-form').reset();
}

async function createUser(event) {
  event.preventDefault();
  
  const username = document.getElementById('new-username').value.trim();
  const email = document.getElementById('new-email').value.trim();
  const password = document.getElementById('new-password').value;
  const role = document.getElementById('new-role').value;
  
  if (!username || !password) {
    alert('Please fill in all fields');
    return;
  }
  
  try {
    const response = await fetch('/api/admin/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, email, password, role })
    });
    
    const data = await response.json();
    
    if (!response.ok) {
      throw new Error(data.error || 'Failed to create user');
    }
    
    alert('User created successfully!');
    closeAddUserModal();
    loadUsers();
    
    // Clear the form
    document.getElementById('new-username').value = '';
    document.getElementById('new-email').value = '';
    document.getElementById('new-password').value = '';
    document.getElementById('new-role').value = 'user';
  } catch (err) {
    console.error('Failed to create user:', err);
    alert('Failed to create user: ' + err.message);
  }
}

// ==================== App Settings Functions ====================

async function loadAppSettings() {
  try {
    const response = await fetch('/api/settings/app');
    if (response.ok) {
      const settings = await response.json();
      
      document.getElementById('enable-registration').checked = settings.enableRegistration ?? true;
      document.getElementById('require-approval').checked = settings.requireApproval ?? true;
      document.getElementById('require-server-approval').checked = settings.requireServerApproval ?? false;
      document.getElementById('global-max-backups').value = settings.globalMaxBackups ?? 10;
      document.getElementById('auto-delete-expired-backups').checked = settings.autoDeleteExpiredBackups ?? false;
    }
    
    // Load MFA settings
    const mfaResponse = await fetch('/api/settings/mfa');
    if (mfaResponse.ok) {
      const mfaSettings = await mfaResponse.json();
      document.getElementById('require-mfa-admins').checked = mfaSettings.requireMfaForAdmins ?? false;
      document.getElementById('require-mfa-all').checked = mfaSettings.requireMfaForAllUsers ?? false;
    }
    
    // Load SMTP settings
    await loadSmtpSettings();
    // Load Webhook settings
    await loadWebhookSettings();
    // Load Email Templates
    await loadEmailTemplates();
    // Load Network & Connectivity settings
    await loadNetworkSettings();
  } catch (err) {
    console.error('Failed to load app settings:', err);
  }
}

async function loadNetworkSettings() {
  try {
    const response = await fetch('/api/settings/network');
    if (response.ok) {
      const net = await response.json();
      document.getElementById('base-url').value = (await fetch('/api/settings/branding').then(r => r.json())).baseUrl || '';
      document.getElementById('cors-origins').value = net.corsOrigins || '';
      document.getElementById('session-cookie-secure').checked = net.sessionCookieSecure ?? false;
      document.getElementById('session-cookie-domain').value = net.sessionCookieDomain || '';
      document.getElementById('session-lifetime').value = net.permanentSessionLifetime ?? 604800;
      document.getElementById('network-port').value = net.port ?? 3000;
    }
  } catch (err) {
    console.error('Failed to load network settings:', err);
  }
}

async function saveNetworkSettings() {
  try {
    // Save baseUrl via branding endpoint
    const baseUrl = document.getElementById('base-url').value;
    const brandingFd = new FormData();
    brandingFd.append('baseUrl', baseUrl);
    // Preserve current branding values
    const currentBranding = await fetch('/api/settings/branding').then(r => r.json());
    brandingFd.append('siteTitle', currentBranding.siteTitle || '');
    brandingFd.append('footerAddition', currentBranding.footerAddition || '');
    await fetch('/api/settings/branding', { method: 'PUT', body: brandingFd });

    // Save network/.env settings
    const payload = {
      corsOrigins: document.getElementById('cors-origins').value,
      sessionCookieSecure: document.getElementById('session-cookie-secure').checked,
      sessionCookieDomain: document.getElementById('session-cookie-domain').value,
      permanentSessionLifetime: parseInt(document.getElementById('session-lifetime').value, 10) || 604800,
    };

    const response = await fetch('/api/settings/network', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (response.ok) {
      const result = await response.json();
      showNotification(result.message || 'Network settings saved.', 'success');
    } else {
      const err = await response.json();
      showNotification('Failed to save network settings: ' + (err.error || 'Unknown error'), 'error');
    }
  } catch (err) {
    showNotification('Failed to save network settings: ' + err.message, 'error');
  }
}

async function deleteAllExpiredBackups() {
  if (!await confirmAction('Delete all expired backups across every server? This cannot be undone.', { title: 'Delete All Expired Backups', icon: '🗑️', okText: 'Delete All Expired', okClass: 'btn-danger' })) return;
  try {
    const response = await fetch('/api/backups/delete-expired', { method: 'POST' });
    const result = await response.json();
    if (!response.ok) {
      showNotification(result.error || 'Failed to delete expired backups', 'error');
      return;
    }
    showNotification(`Deleted ${result.deleted} expired backup(s) across all servers`, 'success');
  } catch (err) {
    console.error('Failed to delete expired backups:', err);
    showNotification('Failed to delete expired backups', 'error');
  }
}

async function loadSmtpSettings() {
  try {
    const response = await fetch('/api/settings/smtp');
    if (response.ok) {
      const smtp = await response.json();
      
      document.getElementById('smtp-enabled').checked = smtp.enabled ?? false;
      document.getElementById('smtp-host').value = smtp.host ?? '';
      document.getElementById('smtp-port').value = smtp.port ?? 587;
      document.getElementById('smtp-secure').checked = smtp.secure ?? true;
      document.getElementById('smtp-username').value = smtp.username ?? '';
      // Password is not returned from API for security, only show placeholder if configured
      document.getElementById('smtp-password').value = '';
      document.getElementById('smtp-password').placeholder = smtp.host ? '••••••••' : 'Password';
      document.getElementById('smtp-from-email').value = smtp.fromEmail ?? '';
      document.getElementById('smtp-from-name').value = smtp.fromName ?? '';
      
      toggleSmtpFields();
    }
  } catch (err) {
    console.error('Failed to load SMTP settings:', err);
  }
}

function toggleSmtpFields() {
  const enabled = document.getElementById('smtp-enabled').checked;
  const smtpConfigSection = document.getElementById('smtp-config-section');
  
  if (smtpConfigSection) {
    smtpConfigSection.style.display = enabled ? 'block' : 'none';
  }
}

async function saveAppSettings() {
  const settings = {
    enableRegistration: document.getElementById('enable-registration').checked,
    requireApproval: document.getElementById('require-approval').checked,
    requireServerApproval: document.getElementById('require-server-approval').checked,
    globalMaxBackups: parseInt(document.getElementById('global-max-backups').value) || 0,
    autoDeleteExpiredBackups: document.getElementById('auto-delete-expired-backups').checked
  };
  
  const mfaSettings = {
    requireMfaForAdmins: document.getElementById('require-mfa-admins').checked,
    requireMfaForAllUsers: document.getElementById('require-mfa-all').checked
  };
  
  try {
    const response = await fetch('/api/settings/app', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings)
    });
    
    if (!response.ok) {
      throw new Error('Failed to save app settings');
    }
    
    // Save MFA settings
    const mfaResponse = await fetch('/api/settings/mfa', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(mfaSettings)
    });
    
    if (!mfaResponse.ok) {
      throw new Error('Failed to save MFA settings');
    }
  } catch (err) {
    console.error('Failed to save app settings:', err);
    alert('Failed to save settings: ' + err.message);
  }
}

async function saveSmtpSettings() {
  const smtpSettings = {
    enabled: document.getElementById('smtp-enabled').checked,
    host: document.getElementById('smtp-host').value.trim(),
    port: parseInt(document.getElementById('smtp-port').value) || 587,
    secure: document.getElementById('smtp-secure').checked,
    username: document.getElementById('smtp-username').value.trim(),
    fromEmail: document.getElementById('smtp-from-email').value.trim(),
    fromName: document.getElementById('smtp-from-name').value.trim()
  };
  
  // Only include password if it was changed (not empty)
  const password = document.getElementById('smtp-password').value;
  if (password) {
    smtpSettings.password = password;
  }
  
  // Validate required fields if SMTP is enabled
  if (smtpSettings.enabled) {
    if (!smtpSettings.host) {
      showNotification('SMTP host is required', 'error');
      return;
    }
    if (!smtpSettings.fromEmail) {
      showNotification('From email is required', 'error');
      return;
    }
  }
  
  try {
    const response = await fetch('/api/settings/smtp', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(smtpSettings)
    });
    
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.error || 'Failed to save SMTP settings');
    }
    
    showNotification('SMTP settings saved successfully', 'success');
    
    // Clear password field after save
    document.getElementById('smtp-password').value = '';
    document.getElementById('smtp-password').placeholder = smtpSettings.host ? '••••••••' : 'Password';
  } catch (err) {
    console.error('Failed to save SMTP settings:', err);
    showNotification('Failed to save SMTP settings: ' + err.message, 'error');
  }
}

async function testSmtpSettings() {
  const testEmail = document.getElementById('smtp-test-email')?.value.trim();
  
  if (!testEmail) {
    showNotification('Please enter a test email address', 'error');
    return;
  }
  
  // Basic email validation
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!emailRegex.test(testEmail)) {
    showNotification('Please enter a valid email address', 'error');
    return;
  }
  
  const testBtn = document.querySelector('.smtp-actions button');
  if (testBtn) {
    testBtn.disabled = true;
    testBtn.textContent = 'Sending...';
  }
  
  try {
    const response = await fetch('/api/settings/smtp/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: testEmail })
    });
    
    const data = await response.json();
    
    if (!response.ok) {
      throw new Error(data.error || 'Failed to send test email');
    }
    
    showNotification('Test email sent successfully! Check your inbox.', 'success');
  } catch (err) {
    console.error('Failed to send test email:', err);
    showNotification('Failed to send test email: ' + err.message, 'error');
  } finally {
    if (testBtn) {
      testBtn.disabled = false;
      testBtn.textContent = '📧 Send Test Email';
    }
  }
}

// ==================== API Manager Functions ====================

let apiKeysCache = [];

async function loadApiManager() {
  await loadApiKeys();
  await loadApiStats();
  updateApiEndpoint();
}

function updateApiEndpoint() {
  const endpoint = document.getElementById('api-endpoint');
  if (endpoint) {
    const baseUrl = window.location.origin;
    endpoint.textContent = `${baseUrl}/api/v1/`;
  }
}

async function loadApiKeys() {
  const listEl = document.getElementById('api-keys-list');
  
  try {
    const response = await fetch('/api/v1/keys');
    
    if (response.status === 401) {
      window.location.href = '/login.html';
      return;
    }
    
    if (response.status === 403) {
      listEl.innerHTML = '<div class="error-text">Admin access required to manage API keys</div>';
      return;
    }
    
    if (!response.ok) {
      listEl.innerHTML = '<div class="error-text">Failed to load API keys</div>';
      return;
    }
    
    const data = await response.json();
    apiKeysCache = data.keys || [];
    
    displayApiKeys(apiKeysCache);
    document.getElementById('api-active-keys').textContent = apiKeysCache.filter(k => k.active).length;
  } catch (err) {
    console.error('Failed to load API keys:', err);
    listEl.innerHTML = '<div class="error-text">Failed to load API keys: ' + escapeHtml(err.message) + '</div>';
  }
}

function displayApiKeys(keys) {
  const listEl = document.getElementById('api-keys-list');
  
  if (keys.length === 0) {
    listEl.innerHTML = '<div class="empty-state">No API keys created yet. Create one to allow external API access.</div>';
    return;
  }
  
  const keyCards = keys.map(key => {
    const statusClass = key.active ? 'online' : 'offline';
    const statusText = key.active ? 'Active' : 'Inactive';
    const createdAt = key.created_at ? new Date(key.created_at).toLocaleString() : 'Unknown';
    const lastUsed = key.last_used ? new Date(key.last_used).toLocaleString() : 'Never';
    const expiresAt = key.expires_at ? new Date(key.expires_at).toLocaleString() : 'Never';
    
    // Mask the key for display (show first 8 and last 4 characters)
    const maskedKey = key.key ? `${key.key.substring(0, 8)}...${key.key.substring(key.key.length - 4)}` : '••••••••';
    
    return `
      <div class="api-key-item">
        <div class="api-key-header">
          <div class="api-key-title">
            <h4>🔑 ${escapeHtml(key.name || 'Unnamed Key')}</h4>
            <span class="api-key-status ${statusClass}">${statusText}</span>
          </div>
          <div class="api-key-actions">
            <button class="btn btn-small" onclick="copyApiKey('${escapeHtml(key.id)}')" title="Copy Key">📋</button>
            <button class="btn btn-small ${key.active ? 'btn-warning' : 'btn-success'}" onclick="toggleApiKey('${escapeHtml(key.id)}')" title="${key.active ? 'Disable' : 'Enable'}">
              ${key.active ? '⏸️' : '▶️'}
            </button>
            <button class="btn btn-small btn-danger" onclick="deleteApiKey('${escapeHtml(key.id)}')" title="Delete">🗑️</button>
          </div>
        </div>
        
        <div class="api-key-details">
          <div class="api-key-info-grid">
            <div class="info-item">
              <span class="info-label">Key:</span>
              <code class="info-value api-key-masked">${maskedKey}</code>
            </div>
            <div class="info-item">
              <span class="info-label">Created:</span>
              <span class="info-value">${createdAt}</span>
            </div>
            <div class="info-item">
              <span class="info-label">Last Used:</span>
              <span class="info-value">${lastUsed}</span>
            </div>
            <div class="info-item">
              <span class="info-label">Expires:</span>
              <span class="info-value">${expiresAt}</span>
            </div>
            <div class="info-item">
              <span class="info-label">Requests:</span>
              <span class="info-value">${key.request_count || 0}</span>
            </div>
            <div class="info-item">
              <span class="info-label">Rate Limit:</span>
              <span class="info-value">${key.rate_limit || 'Default'}/min</span>
            </div>
          </div>
          
          <div class="api-key-permissions">
            <strong>Permissions:</strong>
            <div class="permissions-list">
              ${(key.permissions || ['read']).map(p => `<span class="permission-badge">${escapeHtml(p)}</span>`).join('')}
            </div>
          </div>
        </div>
      </div>
    `;
  }).join('');
  
  listEl.innerHTML = keyCards;
}

async function loadApiStats() {
  try {
    const response = await fetch('/api/v1/stats');
    
    if (!response.ok) {
      console.error('Failed to load API stats');
      return;
    }
    
    const data = await response.json();
    
    document.getElementById('api-total-requests').textContent = data.total_requests || 0;
    document.getElementById('api-successful-requests').textContent = data.successful_requests || 0;
    document.getElementById('api-failed-requests').textContent = data.failed_requests || 0;
  } catch (err) {
    console.error('Failed to load API stats:', err);
  }
}

function refreshApiStats() {
  loadApiStats();
  loadApiKeys();
}

function openCreateApiKeyModal() {
  // For now, use a simple prompt - can be enhanced with a proper modal later
  const keyName = prompt('Enter a name for this API key:');
  if (keyName && keyName.trim()) {
    createApiKey(keyName.trim());
  }
}

async function createApiKey(name) {
  try {
    const response = await fetch('/api/v1/keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, permissions: ['read'] })
    });
    
    if (!response.ok) {
      const error = await response.json();
      alert('Failed to create API key: ' + (error.error || 'Unknown error'));
      return;
    }
    
    const data = await response.json();
    
    // Show the full key to the user (only shown once)
    alert(`API Key created successfully!\n\nKey: ${data.key}\n\n⚠️ Copy this key now - it won't be shown again!`);
    
    loadApiKeys();
  } catch (err) {
    console.error('Failed to create API key:', err);
    alert('Failed to create API key: ' + err.message);
  }
}

async function copyApiKey(keyId) {
  const key = apiKeysCache.find(k => k.id === keyId);
  if (!key || !key.key) {
    alert('Cannot copy key - key data not available. For security, full keys are only shown when created.');
    return;
  }
  
  try {
    await navigator.clipboard.writeText(key.key);
    alert('API key copied to clipboard!');
  } catch (err) {
    console.error('Failed to copy:', err);
    alert('Failed to copy to clipboard');
  }
}

async function toggleApiKey(keyId) {
  const key = apiKeysCache.find(k => k.id === keyId);
  if (!key) return;
  
  try {
    const response = await fetch(`/api/v1/keys/${keyId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ active: !key.active })
    });
    
    if (!response.ok) {
      alert('Failed to update API key');
      return;
    }
    
    loadApiKeys();
  } catch (err) {
    console.error('Failed to toggle API key:', err);
    alert('Failed to update API key: ' + err.message);
  }
}

async function deleteApiKey(keyId) {
  if (!confirm('Are you sure you want to delete this API key? This cannot be undone.')) {
    return;
  }
  
  try {
    const response = await fetch(`/api/v1/keys/${keyId}`, {
      method: 'DELETE'
    });
    
    if (!response.ok) {
      alert('Failed to delete API key');
      return;
    }
    
    loadApiKeys();
  } catch (err) {
    console.error('Failed to delete API key:', err);
    alert('Failed to delete API key: ' + err.message);
  }
}


// ==================== External Backup Storage ====================

let _extBackupSaveTimer = null;

function debounceSaveExternal() {
  clearTimeout(_extBackupSaveTimer);
  _extBackupSaveTimer = setTimeout(saveExternalBackupSettings, 800);
}

function updateExternalBackupType() {
  const type = document.getElementById('ext-backup-type').value;
  document.getElementById('ext-ftp-config').style.display = type === 'ftp' ? '' : 'none';
  document.getElementById('ext-s3-config').style.display = type === 's3' ? '' : 'none';
}

async function loadExternalBackupSettings() {
  try {
    const response = await fetch('/api/settings/external-backup');
    if (!response.ok) return;
    const data = await response.json();

    document.getElementById('ext-backup-enabled').checked = !!data.enabled;
    document.getElementById('ext-backup-config').style.display = data.enabled ? '' : 'none';

    const type = data.type || 'ftp';
    document.getElementById('ext-backup-type').value = type;
    updateExternalBackupType();

    // FTP
    const ftp = data.ftp || {};
    document.getElementById('ext-ftp-host').value = ftp.host || '';
    document.getElementById('ext-ftp-port').value = ftp.port || 21;
    document.getElementById('ext-ftp-username').value = ftp.username || '';
    document.getElementById('ext-ftp-password').value = '';  // never pre-fill passwords
    document.getElementById('ext-ftp-path').value = ftp.remotePath || '/backups/';
    document.getElementById('ext-ftp-passive').checked = ftp.passive !== false;

    // S3
    const s3 = data.s3 || {};
    document.getElementById('ext-s3-bucket').value = s3.bucket || '';
    document.getElementById('ext-s3-region').value = s3.region || 'us-east-1';
    document.getElementById('ext-s3-access-key').value = s3.accessKey || '';
    document.getElementById('ext-s3-secret-key').value = '';  // never pre-fill secrets
    document.getElementById('ext-s3-prefix').value = s3.prefix || 'backups/';
  } catch (err) {
    console.error('Failed to load external backup settings:', err);
  }
}

async function saveExternalBackupSettings() {
  const enabled = document.getElementById('ext-backup-enabled').checked;
  document.getElementById('ext-backup-config').style.display = enabled ? '' : 'none';

  const type = document.getElementById('ext-backup-type').value;

  const payload = {
    enabled,
    type,
    ftp: {
      host: document.getElementById('ext-ftp-host').value,
      port: parseInt(document.getElementById('ext-ftp-port').value) || 21,
      username: document.getElementById('ext-ftp-username').value,
      password: document.getElementById('ext-ftp-password').value,
      remotePath: document.getElementById('ext-ftp-path').value,
      passive: document.getElementById('ext-ftp-passive').checked
    },
    s3: {
      bucket: document.getElementById('ext-s3-bucket').value,
      region: document.getElementById('ext-s3-region').value,
      accessKey: document.getElementById('ext-s3-access-key').value,
      secretKey: document.getElementById('ext-s3-secret-key').value,
      prefix: document.getElementById('ext-s3-prefix').value
    }
  };

  try {
    const response = await fetch('/api/settings/external-backup', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (result.success) {
      showNotification('External backup settings saved', 'success');
    }
  } catch (err) {
    console.error('Failed to save external backup settings:', err);
    showNotification('Failed to save external backup settings', 'error');
  }
}

async function testExternalBackupSettings() {
  try {
    showNotification('Testing external backup connection…', 'info');
    const response = await fetch('/api/settings/external-backup/test', { method: 'POST' });
    const result = await response.json();
    if (result.success) {
      showNotification(`✅ Connection successful: ${result.message}`, 'success');
    } else {
      showNotification(`❌ Connection failed: ${result.error}`, 'error');
    }
  } catch (err) {
    showNotification(`❌ Connection failed: ${err.message}`, 'error');
  }
}

// ==================== Notification Preferences (Profile Modal) ====================

async function loadNotificationPrefs() {
  try {
    const resp = await fetch('/api/auth/profile/notifications');
    if (!resp.ok) return;
    const prefs = await resp.json();
    const keys = ['backupComplete', 'backupFailure', 'serverStart', 'serverStop',
                   'playerJoin', 'playerLeave', 'criticalAlerts'];
    for (const key of keys) {
      const el = document.getElementById(`notif-${key}`);
      if (el) el.checked = prefs[key] ?? false;
    }
  } catch (err) {
    console.error('Failed to load notification prefs:', err);
  }
}

async function saveNotificationPrefs(silent = false) {
  const keys = ['backupComplete', 'backupFailure', 'serverStart', 'serverStop',
                 'playerJoin', 'playerLeave', 'criticalAlerts'];
  const prefs = {};
  for (const key of keys) {
    const el = document.getElementById(`notif-${key}`);
    if (el) prefs[key] = el.checked;
  }
  try {
    const resp = await fetch('/api/auth/profile/notifications', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(prefs)
    });
    if (resp.ok) {
      if (!silent) showNotification('Notification preferences saved', 'success');
      return true;
    } else {
      const d = await resp.json();
      showNotification(d.error || 'Failed to save notification preferences', 'error');
      return false;
    }
  } catch (err) {
    showNotification('Failed to save notification preferences', 'error');
    return false;
  }
}

// ==================== Webhook Settings ====================

let _webhookSaveTimer = null;
function debounceWebhookSave() {
  clearTimeout(_webhookSaveTimer);
  _webhookSaveTimer = setTimeout(saveWebhookSettings, 800);
}

function toggleWebhookFields() {
  const enabled = document.getElementById('webhook-enabled').checked;
  const section = document.getElementById('webhook-config-section');
  if (section) section.style.display = enabled ? 'block' : 'none';
}

async function loadWebhookSettings() {
  try {
    const resp = await fetch('/api/settings/webhook');
    if (!resp.ok) return;
    const s = await resp.json();
    document.getElementById('webhook-enabled').checked = s.enabled ?? false;
    document.getElementById('webhook-url').value = s.url ?? '';
    document.getElementById('webhook-secret').value = '';
    document.getElementById('webhook-secret').placeholder = s.url ? '••••••••' : 'Optional HMAC secret';
    toggleWebhookFields();
  } catch (err) {
    console.error('Failed to load webhook settings:', err);
  }
}

async function saveWebhookSettings() {
  const settings = {
    enabled: document.getElementById('webhook-enabled').checked,
    url: document.getElementById('webhook-url').value.trim(),
  };
  const secret = document.getElementById('webhook-secret').value;
  if (secret) settings.secret = secret;

  try {
    const resp = await fetch('/api/settings/webhook', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings)
    });
    const d = await resp.json();
    if (d.success) {
      showNotification('Webhook settings saved', 'success');
      document.getElementById('webhook-secret').value = '';
      document.getElementById('webhook-secret').placeholder = settings.url ? '••••••••' : 'Optional HMAC secret';
    } else {
      showNotification(d.error || 'Failed to save webhook settings', 'error');
    }
  } catch (err) {
    showNotification('Failed to save webhook settings', 'error');
  }
}

async function testWebhookSettings() {
  try {
    showNotification('Sending test webhook…', 'info');
    const resp = await fetch('/api/settings/webhook/test', { method: 'POST' });
    const d = await resp.json();
    if (d.success) {
      showNotification(`✅ Webhook delivered: ${d.message}`, 'success');
    } else {
      showNotification(`❌ Webhook failed: ${d.error}`, 'error');
    }
  } catch (err) {
    showNotification(`❌ Webhook test failed: ${err.message}`, 'error');
  }
}

// ==================== Email Templates ====================

const _TEMPLATE_LABELS = {
  backup_complete: { label: 'Backup Completed', vars: 'server_name, backup_name, size, timestamp, site_title' },
  backup_failure:  { label: 'Backup Failed',    vars: 'server_name, error, timestamp, site_title' },
  server_start:    { label: 'Server Started',   vars: 'server_name, server_id, timestamp, site_title' },
  server_stop:     { label: 'Server Stopped',   vars: 'server_name, server_id, timestamp, site_title' },
  player_join:     { label: 'Player Joined',    vars: 'player, server_name, server_id, timestamp, site_title' },
  player_leave:    { label: 'Player Left',      vars: 'player, server_name, server_id, timestamp, site_title' },
  critical_alert:  { label: 'Critical Alert',   vars: 'alert_type, details, timestamp, site_title' },
};

let _emailTemplates = {};

async function loadEmailTemplates() {
  try {
    const resp = await fetch('/api/settings/email-templates');
    if (!resp.ok) return;
    _emailTemplates = await resp.json();
    renderEmailTemplates();
  } catch (err) {
    console.error('Failed to load email templates:', err);
  }
}

function renderEmailTemplates() {
  const container = document.getElementById('email-templates-container');
  if (!container) return;

  const entries = Object.entries(_TEMPLATE_LABELS);
  container.innerHTML = entries.map(([key, meta]) => {
    const tmpl = _emailTemplates[key] || {};
    return `
      <div class="email-tmpl-accordion" id="tmpl-block-${key}">
        <div class="email-tmpl-header" onclick="toggleTemplateEditor('${key}')">
          <span class="email-tmpl-name">${meta.label}</span>
          <small class="email-tmpl-vars">Variables: <code>${meta.vars}</code></small>
          <span class="email-tmpl-chevron" id="tmpl-chevron-${key}">▼</span>
        </div>
        <div class="email-tmpl-body" id="tmpl-body-${key}" style="display:none;">
          <div class="form-group">
            <label for="tmpl-subject-${key}">Subject</label>
            <input type="text" id="tmpl-subject-${key}" class="form-control"
                   value="${escapeHtml(tmpl.subject || '')}" placeholder="Subject template…">
          </div>
          <div class="form-group">
            <label for="tmpl-html-${key}">HTML Body</label>
            <textarea id="tmpl-html-${key}" class="form-control tmpl-textarea"
                      rows="8" placeholder="HTML body template…">${escapeHtml(tmpl.html || '')}</textarea>
          </div>
          <div class="form-group">
            <label for="tmpl-text-${key}">Plain-text Body <span class="optional-label">(Optional)</span></label>
            <textarea id="tmpl-text-${key}" class="form-control tmpl-textarea"
                      rows="3" placeholder="Plain text fallback…">${escapeHtml(tmpl.text || '')}</textarea>
          </div>
          <div class="smtp-actions">
            <button type="button" class="btn btn-primary btn-small" onclick="saveEmailTemplate('${key}')">💾 Save</button>
            <button type="button" class="btn btn-secondary btn-small" onclick="resetEmailTemplate('${key}')">↩ Reset to Default</button>
          </div>
        </div>
      </div>`;
  }).join('');
}

function toggleTemplateEditor(key) {
  const body = document.getElementById(`tmpl-body-${key}`);
  const chevron = document.getElementById(`tmpl-chevron-${key}`);
  if (!body) return;
  const isOpen = body.style.display !== 'none';
  body.style.display = isOpen ? 'none' : 'block';
  if (chevron) chevron.textContent = isOpen ? '▼' : '▲';
}

async function saveEmailTemplate(key) {
  const subject = document.getElementById(`tmpl-subject-${key}`)?.value || '';
  const html    = document.getElementById(`tmpl-html-${key}`)?.value || '';
  const text    = document.getElementById(`tmpl-text-${key}`)?.value || '';

  try {
    const resp = await fetch(`/api/settings/email-template/${key}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subject, html, text })
    });
    const d = await resp.json();
    if (d.success) {
      showNotification(`Template "${_TEMPLATE_LABELS[key]?.label}" saved`, 'success');
      _emailTemplates[key] = { subject, html, text };
    } else {
      showNotification(d.error || 'Failed to save template', 'error');
    }
  } catch (err) {
    showNotification('Failed to save template', 'error');
  }
}

async function resetEmailTemplate(key) {
  const confirmed = await confirmAction(
    `Reset the "${_TEMPLATE_LABELS[key]?.label}" template to its built-in default?`
  );
  if (!confirmed) return;
  try {
    await fetch(`/api/settings/email-template/${key}/reset`, { method: 'POST' });
    showNotification('Template reset to default', 'success');
    await loadEmailTemplates();
  } catch (err) {
    showNotification('Failed to reset template', 'error');
  }
}
