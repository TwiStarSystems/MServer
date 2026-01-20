// Settings page JavaScript

let socket = null;
let statsChart = null;
let currentUser = null;

// Global fetch wrapper to handle authentication errors
const originalFetch = window.fetch;
window.fetch = async function(...args) {
  const response = await originalFetch.apply(this, args);
  
  // Redirect to login if authentication fails
  if (response.status === 401) {
    window.location.href = '/login.html';
  }
  
  return response;
};

document.addEventListener('DOMContentLoaded', async () => {
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
      // Load app settings when Server Settings tab is clicked
      if (tab === 'appsettings') {
        loadAppSettings();
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
  loadDownloadedJars();
  
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
      document.getElementById('base-url').value = branding.baseUrl || '';
      
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
    footerAddition: document.getElementById('footer-addition').value,
    baseUrl: document.getElementById('base-url').value
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
    
    console.log('Tools API response:', data);
    
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

// ==================== JAR Downloader Functions ====================

async function downloadJar() {
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
      
      // Reload the list
      loadDownloadedJars();
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
  openPasswordResetModal(userId);
}

function openPasswordResetModal(userId) {
  const modal = document.createElement('div');
  modal.id = 'password-reset-modal';
  modal.className = 'modal';
  modal.innerHTML = `
    <div class="modal-content modal-small">
      <div class="modal-header">
        <h2>Reset User Password</h2>
        <button class="close-btn" onclick="closePasswordResetModal()">&times;</button>
      </div>
      <form id="password-reset-form" onsubmit="submitPasswordReset(event, '${userId}')">
        <div class="form-group">
          <label for="reset-new-password">New Password</label>
          <input type="password" id="reset-new-password" class="form-control" required minlength="6" placeholder="Enter new password (min 6 characters)">
        </div>
        <div class="form-group">
          <label for="reset-confirm-password">Confirm Password</label>
          <input type="password" id="reset-confirm-password" class="form-control" required minlength="6" placeholder="Confirm new password">
        </div>
        <div class="modal-footer">
          <button type="button" class="btn" onclick="closePasswordResetModal()">Cancel</button>
          <button type="submit" class="btn btn-primary">Reset Password</button>
        </div>
      </form>
    </div>
  `;
  modal.style.display = 'flex';
  document.body.appendChild(modal);
  
  modal.onclick = (e) => {
    if (e.target.id === 'password-reset-modal') closePasswordResetModal();
  };
  
  // Focus on first input
  setTimeout(() => document.getElementById('reset-new-password').focus(), 100);
}

function closePasswordResetModal() {
  const modal = document.getElementById('password-reset-modal');
  if (modal) modal.remove();
}

async function submitPasswordReset(event, userId) {
  event.preventDefault();
  
  const newPassword = document.getElementById('reset-new-password').value;
  const confirmPassword = document.getElementById('reset-confirm-password').value;
  
  if (newPassword !== confirmPassword) {
    alert('Passwords do not match');
    return;
  }
  
  if (newPassword.length < 6) {
    alert('Password must be at least 6 characters');
    return;
  }
  
  try {
    const response = await fetch(`/api/admin/users/${userId}/password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: newPassword })
    });
    if (!response.ok) throw new Error('Failed to reset password');
    alert('Password reset successfully');
    closePasswordResetModal();
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
      body: JSON.stringify({ username, password, role })
    });
    
    const data = await response.json();
    
    if (!response.ok) {
      throw new Error(data.error || 'Failed to create user');
    }
    
    alert('User created successfully!');
    closeAddUserModal();
    loadUsers();
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
    }
    
    // Load MFA settings
    const mfaResponse = await fetch('/api/settings/mfa');
    if (mfaResponse.ok) {
      const mfaSettings = await mfaResponse.json();
      document.getElementById('require-mfa-admins').checked = mfaSettings.requireMfaForAdmins ?? false;
      document.getElementById('require-mfa-all').checked = mfaSettings.requireMfaForAllUsers ?? false;
    }
  } catch (err) {
    console.error('Failed to load app settings:', err);
  }
}

async function saveAppSettings() {
  const settings = {
    enableRegistration: document.getElementById('enable-registration').checked,
    requireApproval: document.getElementById('require-approval').checked,
    requireServerApproval: document.getElementById('require-server-approval').checked
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
