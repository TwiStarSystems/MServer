// Settings page JavaScript

let socket = null;
let statsChart = null;
let currentUser = null;

document.addEventListener('DOMContentLoaded', async () => {
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
    window.location.href = '/login.html';
    return;
  }
  
  // Load branding for page
  loadPageBranding();
  
  // Initialize Socket.IO for real-time stats
  socket = io();
  socket.on('stats_update', updateCurrentStats);
  
  // Tab switching
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
    });
  });
  
  // Load initial data
  loadCurrentStats();
  loadStatsHistory();
  loadBranding();
  loadTools();
  
  // Time range change handler
  document.getElementById('time-range').addEventListener('change', loadStatsHistory);
  
  // Branding form
  document.getElementById('branding-form').addEventListener('submit', saveBranding);
  
  // Live preview for branding
  document.getElementById('branding-site-title').addEventListener('input', updateBrandingPreview);
  document.getElementById('site-icon').addEventListener('input', updateBrandingPreview);
  document.getElementById('footer-addition').addEventListener('input', updateBrandingPreview);
  
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
        favicon.href = branding.siteIcon;
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
      document.getElementById('site-icon').value = branding.siteIcon || '';
      document.getElementById('footer-addition').value = branding.footerAddition || '';
      
      updateBrandingPreview();
    }
  } catch (err) {
    console.error('Failed to load branding:', err);
  }
}

function updateBrandingPreview() {
  const title = document.getElementById('branding-site-title').value || 'MServerController';
  const icon = document.getElementById('site-icon').value;
  const footerAddition = document.getElementById('footer-addition').value;
  
  document.getElementById('preview-title').textContent = title;
  
  const iconEl = document.getElementById('preview-icon');
  if (icon) {
    iconEl.innerHTML = `<img src="${escapeHtml(icon)}" alt="icon" onerror="this.parentElement.innerHTML='🎮'">`;
  } else {
    iconEl.innerHTML = '🎮';
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
  
  const data = {
    siteTitle: document.getElementById('branding-site-title').value,
    siteIcon: document.getElementById('site-icon').value,
    footerAddition: document.getElementById('footer-addition').value
  };
  
  try {
    const response = await fetch('/api/settings/branding', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    
    if (response.ok) {
      alert('Branding saved successfully!');
      // Update page title and header
      const siteTitle = data.siteTitle || '🎮 MServerController';
      document.getElementById('site-title').textContent = siteTitle;
      document.title = `Settings - ${siteTitle.replace(/^🎮\s*/, '')}`;
    } else {
      const err = await response.json();
      alert('Failed to save branding: ' + (err.error || 'Unknown error'));
    }
  } catch (err) {
    alert('Failed to save branding: ' + err.message);
  }
}

// ==================== Tools Functions ====================

async function loadTools() {
  const container = document.getElementById('tools-container');
  
  try {
    const response = await fetch('/api/tools');
    if (response.ok) {
      const data = await response.json();
      
      if (data.tools && data.tools.length > 0) {
        container.innerHTML = data.tools.map(tool => `
          <div class="tool-card" data-tool="${tool.name}">
            <h4>${escapeHtml(tool.name)}</h4>
            <p>${escapeHtml(tool.description)}</p>
            <button class="btn btn-primary" onclick="runTool('${tool.name}')">Run Tool</button>
            <div class="tool-output" id="output-${tool.name}"></div>
          </div>
        `).join('');
      } else {
        container.innerHTML = `
          <div class="no-tools">
            <h3>No Tools Available</h3>
            <p>Add Python scripts to the <code>./tools</code> folder to see them here.</p>
            <p>Each script should have a comment at the top describing its purpose.</p>
          </div>
        `;
      }
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

async function runTool(toolName) {
  const outputEl = document.getElementById(`output-${toolName}`);
  const card = document.querySelector(`[data-tool="${toolName}"]`);
  const btn = card.querySelector('button');
  
  btn.disabled = true;
  btn.textContent = 'Running...';
  outputEl.classList.add('show');
  outputEl.classList.remove('success', 'error');
  outputEl.textContent = 'Executing tool...';
  
  try {
    const response = await fetch(`/api/tools/${toolName}/run`, {
      method: 'POST'
    });
    
    const result = await response.json();
    
    if (result.success) {
      outputEl.classList.add('success');
      outputEl.textContent = result.output || 'Tool completed successfully (no output)';
    } else {
      outputEl.classList.add('error');
      outputEl.textContent = result.error || result.output || 'Tool failed';
    }
  } catch (err) {
    outputEl.classList.add('error');
    outputEl.textContent = 'Error: ' + err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Run Tool';
  }
}

// ==================== Utility Functions ====================

function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ==================== User Management Functions ====================

function switchUserTab(subtab) {
  document.querySelectorAll('.user-mgmt-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.subtab === subtab);
  });
  document.querySelectorAll('.user-mgmt-content').forEach(content => {
    content.classList.toggle('active', content.id === `${subtab}-users-tab`);
  });
}

async function loadUsers() {
  try {
    const response = await fetch('/api/admin/users');
    if (!response.ok) throw new Error('Failed to load users');
    
    const data = await response.json();
    const users = data.users || [];
    
    const approvedUsers = users.filter(u => u.approved);
    const pendingUsers = users.filter(u => !u.approved);
    
    // Render approved users
    const approvedTab = document.getElementById('approved-users-tab');
    if (approvedUsers.length === 0) {
      approvedTab.innerHTML = `
        <div class="user-mgmt-empty">
          <h3>No Users</h3>
          <p>No approved users found</p>
        </div>
      `;
    } else {
      approvedTab.innerHTML = `
        <table class="user-mgmt-table">
          <thead>
            <tr>
              <th>Username</th>
              <th>Role</th>
              <th>Created</th>
              <th>Last Login</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            ${approvedUsers.map(u => `
              <tr>
                <td>${escapeHtml(u.username)}</td>
                <td><span class="role-badge ${u.role}">${u.role}</span></td>
                <td>${new Date(u.created).toLocaleDateString()}</td>
                <td>${u.lastLogin ? new Date(u.lastLogin).toLocaleDateString() : 'Never'}</td>
                <td class="user-mgmt-actions">
                  <select onchange="changeUserRole('${u.id}', this.value)">
                    <option value="public" ${u.role === 'public' ? 'selected' : ''}>Public</option>
                    <option value="user" ${u.role === 'user' ? 'selected' : ''}>User</option>
                    <option value="admin" ${u.role === 'admin' ? 'selected' : ''}>Admin</option>
                  </select>
                  <button class="btn btn-small" onclick="resetUserPassword('${u.id}')">Reset PW</button>
                  <button class="btn btn-small btn-danger" onclick="deleteUser('${u.id}', '${escapeHtml(u.username)}')">Delete</button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    }
    
    // Render pending users
    const pendingTab = document.getElementById('pending-users-tab');
    if (pendingUsers.length === 0) {
      pendingTab.innerHTML = `
        <div class="user-mgmt-empty">
          <h3>No Pending Requests</h3>
          <p>No users waiting for approval</p>
        </div>
      `;
    } else {
      pendingTab.innerHTML = `
        <table class="user-mgmt-table">
          <thead>
            <tr>
              <th>Username</th>
              <th>Registered</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            ${pendingUsers.map(u => `
              <tr>
                <td>${escapeHtml(u.username)}</td>
                <td>${new Date(u.created).toLocaleDateString()}</td>
                <td class="user-mgmt-actions">
                  <button class="btn btn-small btn-success" onclick="approveUser('${u.id}')">Approve</button>
                  <button class="btn btn-small btn-danger" onclick="deleteUser('${u.id}', '${escapeHtml(u.username)}')">Reject</button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    }
  } catch (err) {
    console.error('Failed to load users:', err);
    document.getElementById('approved-users-tab').innerHTML = `
      <div class="user-mgmt-empty">
        <h3>Error Loading Users</h3>
        <p>${err.message}</p>
      </div>
    `;
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

async function changeUserRole(userId, role) {
  try {
    const response = await fetch(`/api/admin/users/${userId}/role`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role })
    });
    if (!response.ok) throw new Error('Failed to change role');
    loadUsers();
  } catch (err) {
    console.error('Failed to change role:', err);
    alert('Failed to change role: ' + err.message);
  }
}

async function resetUserPassword(userId) {
  const newPassword = prompt('Enter new password (min 8 characters):');
  if (!newPassword) return;
  if (newPassword.length < 8) {
    alert('Password must be at least 8 characters');
    return;
  }
  
  try {
    const response = await fetch(`/api/admin/users/${userId}/password`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: newPassword })
    });
    if (!response.ok) throw new Error('Failed to reset password');
    alert('Password reset successfully');
  } catch (err) {
    console.error('Failed to reset password:', err);
    alert('Failed to reset password: ' + err.message);
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
