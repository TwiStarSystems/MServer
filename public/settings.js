// Settings page JavaScript

let socket = null;
let statsChart = null;
let currentUser = null;

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
  loadJarFetcherTypes();
  loadJarConfig();
  loadApiUrls();
  
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

// ==================== JAR URL Fetcher Functions ====================

let currentJarType = '';
let currentJarVersion = '';
let currentJarUrl = '';

async function loadJarFetcherTypes() {
  const select = document.getElementById('jar-server-type');
  
  try {
    const response = await fetch('/api/tools/jarfetcher/types');
    if (response.ok) {
      const data = await response.json();
      
      select.innerHTML = '<option value="">Select server type...</option>';
      data.types.forEach(type => {
        const option = document.createElement('option');
        option.value = type.id;
        option.textContent = `${type.name} - ${type.description}`;
        select.appendChild(option);
      });
    }
  } catch (err) {
    console.error('Failed to load JAR types:', err);
  }
}

async function loadJarVersions() {
  const typeSelect = document.getElementById('jar-server-type');
  const versionSelect = document.getElementById('jar-version');
  const fetchBtn = document.getElementById('fetch-url-btn');
  const resultDiv = document.getElementById('jar-result');
  const statusDiv = document.getElementById('jar-status');
  
  currentJarType = typeSelect.value;
  currentJarVersion = '';
  currentJarUrl = '';
  
  // Reset
  versionSelect.innerHTML = '<option value="">Select version...</option>';
  fetchBtn.disabled = true;
  resultDiv.style.display = 'none';
  statusDiv.textContent = '';
  
  if (!currentJarType) return;
  
  statusDiv.innerHTML = '<span class="loading-text">Loading versions...</span>';
  
  try {
    const response = await fetch(`/api/tools/jarfetcher/versions/${currentJarType}`);
    if (response.ok) {
      const data = await response.json();
      
      versionSelect.innerHTML = '<option value="">Select version...</option>';
      data.versions.forEach(v => {
        const option = document.createElement('option');
        option.value = v.version;
        option.textContent = v.version;
        versionSelect.appendChild(option);
      });
      
      statusDiv.innerHTML = `<span class="success-text">✓ Loaded ${data.versions.length} versions</span>`;
    } else {
      const error = await response.json();
      statusDiv.innerHTML = `<span class="error-text">✗ ${error.error}</span>`;
    }
  } catch (err) {
    statusDiv.innerHTML = `<span class="error-text">✗ Failed to load versions: ${err.message}</span>`;
  }
}



async function fetchJarUrl() {
  const versionSelect = document.getElementById('jar-version');
  const fetchBtn = document.getElementById('fetch-url-btn');
  const resultDiv = document.getElementById('jar-result');
  const urlOutput = document.getElementById('jar-url-output');
  const buildInfo = document.getElementById('jar-build-info');
  const noteDiv = document.getElementById('jar-note');
  const statusDiv = document.getElementById('jar-status');
  
  currentJarVersion = versionSelect.value;
  
  // Enable/disable fetch button based on selection
  fetchBtn.disabled = !currentJarType || !currentJarVersion;
  
  if (!currentJarType || !currentJarVersion) {
    resultDiv.style.display = 'none';
    return;
  }
  
  statusDiv.innerHTML = '<span class="loading-text">Fetching download URL...</span>';
  fetchBtn.disabled = true;
  
  try {
    const requestBody = { type: currentJarType, version: currentJarVersion };
    
    const response = await fetch('/api/tools/jarfetcher/download-url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody)
    });
    
    const data = await response.json();
    
    if (response.ok && data.url) {
      currentJarUrl = data.url;
      urlOutput.textContent = data.url;
      resultDiv.style.display = 'block';
      
      if (data.build) {
        buildInfo.textContent = `Build: ${data.build}`;
        buildInfo.style.display = 'block';
      } else {
        buildInfo.style.display = 'none';
      }
      
      // Show note for Bedrock (.zip file)
      if (noteDiv) {
        if (currentJarType === 'bedrock') {
          noteDiv.innerHTML = '<strong>Note:</strong> Bedrock Dedicated Server is a .zip archive, not a .jar file. Extract the contents to your server directory.';
          noteDiv.style.display = 'block';
        } else {
          noteDiv.style.display = 'none';
        }
      }
      
      statusDiv.innerHTML = '<span class="success-text">✓ URL fetched successfully</span>';
    } else {
      statusDiv.innerHTML = `<span class="error-text">✗ ${data.error || 'Failed to fetch URL'}</span>`;
      resultDiv.style.display = 'none';
    }
  } catch (err) {
    statusDiv.innerHTML = `<span class="error-text">✗ Error: ${err.message}</span>`;
    resultDiv.style.display = 'none';
  } finally {
    fetchBtn.disabled = false;
  }
}

function copyJarUrl() {
  if (currentJarUrl) {
    navigator.clipboard.writeText(currentJarUrl).then(() => {
      const statusDiv = document.getElementById('jar-status');
      statusDiv.innerHTML = '<span class="success-text">✓ URL copied to clipboard!</span>';
    }).catch(err => {
      console.error('Failed to copy:', err);
    });
  }
}

async function addToConfig() {
  if (!currentJarType || !currentJarVersion || !currentJarUrl) {
    return;
  }
  
  const statusDiv = document.getElementById('jar-status');
  statusDiv.innerHTML = '<span class="loading-text">Adding to config...</span>';
  
  try {
    const response = await fetch('/api/tools/jarfetcher/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: currentJarType,
        version: currentJarVersion,
        url: currentJarUrl
      })
    });
    
    const data = await response.json();
    
    if (response.ok && data.success) {
      statusDiv.innerHTML = `<span class="success-text">✓ ${data.message}</span>`;
      loadJarConfig(); // Refresh config display
    } else {
      statusDiv.innerHTML = `<span class="error-text">✗ ${data.error || 'Failed to update config'}</span>`;
    }
  } catch (err) {
    statusDiv.innerHTML = `<span class="error-text">✗ Error: ${err.message}</span>`;
  }
}

async function loadJarConfig() {
  const configDisplay = document.getElementById('jar-config-content');
  
  try {
    const response = await fetch('/api/tools/jarfetcher/config');
    if (response.ok) {
      const data = await response.json();
      configDisplay.textContent = data.content || '# No configuration yet';
    } else {
      configDisplay.textContent = '# Failed to load configuration';
    }
  } catch (err) {
    configDisplay.textContent = `# Error loading config: ${err.message}`;
  }
}

// ==================== URL Testing Functions ====================

async function testAllJarUrls() {
  const resultsDiv = document.getElementById('url-test-results');
  const summaryDiv = document.getElementById('url-test-summary');
  const detailsDiv = document.getElementById('url-test-details');
  
  // Show results area with loading state
  resultsDiv.style.display = 'block';
  summaryDiv.innerHTML = '<div class="loading-text">🔍 Testing URLs... This may take a moment.</div>';
  detailsDiv.innerHTML = '';
  
  try {
    const response = await fetch('/api/tools/jarfetcher/test-urls', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ testAll: true })
    });
    
    const data = await response.json();
    
    if (response.ok && data.success) {
      renderUrlTestResults(data);
    } else {
      summaryDiv.innerHTML = `<div class="error-text">❌ ${data.error || 'Failed to test URLs'}</div>`;
    }
  } catch (err) {
    summaryDiv.innerHTML = `<div class="error-text">❌ Error: ${err.message}</div>`;
  }
}

function renderUrlTestResults(data) {
  const summaryDiv = document.getElementById('url-test-summary');
  const detailsDiv = document.getElementById('url-test-details');
  const summary = data.summary;
  const results = data.results;
  
  // Summary
  summaryDiv.innerHTML = `
    <div class="test-summary-stats">
      <div class="test-stat valid">
        <span class="stat-icon">✅</span>
        <span class="stat-value">${summary.valid}</span>
        <span class="stat-label">Valid</span>
      </div>
      <div class="test-stat invalid">
        <span class="stat-icon">❌</span>
        <span class="stat-value">${summary.invalid}</span>
        <span class="stat-label">Invalid</span>
      </div>
      <div class="test-stat api">
        <span class="stat-icon">🔄</span>
        <span class="stat-value">${summary.api}</span>
        <span class="stat-label">API</span>
      </div>
      <div class="test-stat total">
        <span class="stat-icon">📊</span>
        <span class="stat-value">${summary.total}</span>
        <span class="stat-label">Total</span>
      </div>
    </div>
  `;
  
  // Details
  let detailsHtml = '';
  
  // Invalid URLs first (most important)
  if (results.invalid.length > 0) {
    detailsHtml += `
      <div class="test-section invalid-section">
        <h5>❌ Invalid URLs (${results.invalid.length})</h5>
        <div class="test-list">
          ${results.invalid.map(item => `
            <div class="test-item invalid">
              <div class="test-item-header">
                <span class="test-key">${item.key}</span>
                <span class="test-error">${item.error || 'Unknown error'}</span>
              </div>
              <div class="test-item-url">${escapeHtml(item.url)}</div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }
  
  // Valid URLs
  if (results.valid.length > 0) {
    detailsHtml += `
      <div class="test-section valid-section">
        <h5>✅ Valid URLs (${results.valid.length})</h5>
        <div class="test-list collapsed" id="valid-urls-list">
          ${results.valid.map(item => `
            <div class="test-item valid">
              <div class="test-item-header">
                <span class="test-key">${item.key}</span>
                <span class="test-status">HTTP ${item.status_code}</span>
                ${item.size && item.size !== 'unknown' ? `<span class="test-size">${formatBytes(parseInt(item.size))}</span>` : ''}
              </div>
            </div>
          `).join('')}
        </div>
        <button class="btn btn-small btn-link" onclick="toggleTestList('valid-urls-list')">Show/Hide Valid URLs</button>
      </div>
    `;
  }
  
  // API entries
  if (results.api.length > 0) {
    detailsHtml += `
      <div class="test-section api-section">
        <h5>🔄 API Entries (${results.api.length})</h5>
        <p class="test-note">These entries use dynamic API resolution at download time.</p>
        <div class="test-list collapsed" id="api-urls-list">
          ${results.api.map(item => `
            <div class="test-item api">
              <span class="test-key">${item.key}</span>
            </div>
          `).join('')}
        </div>
        <button class="btn btn-small btn-link" onclick="toggleTestList('api-urls-list')">Show/Hide API Entries</button>
      </div>
    `;
  }
  
  detailsDiv.innerHTML = detailsHtml || '<p>No entries to test.</p>';
}

function toggleTestList(listId) {
  const list = document.getElementById(listId);
  if (list) {
    list.classList.toggle('collapsed');
  }
}

function hideUrlTestResults() {
  const resultsDiv = document.getElementById('url-test-results');
  if (resultsDiv) {
    resultsDiv.style.display = 'none';
  }
}

// ==================== API URL Configuration Functions ====================

const SERVER_TYPE_NAMES = {
  'vanilla': 'Vanilla (Java)',
  'bedrock': 'Vanilla (Bedrock)',
  'paper': 'Paper',
  'purpur': 'Purpur',
  'fabric': 'Fabric',
  'folia': 'Folia',
  'forge': 'Forge',
  'waterfall': 'Waterfall'
};

async function loadApiUrls() {
  const container = document.getElementById('api-urls-container');
  if (!container) return;
  
  try {
    const response = await fetch('/api/tools/jarfetcher/api-urls');
    if (response.ok) {
      const data = await response.json();
      renderApiUrls(data.urls, data.defaults);
    } else {
      container.innerHTML = '<div class="error-text">Failed to load API URLs</div>';
    }
  } catch (err) {
    container.innerHTML = `<div class="error-text">Error: ${err.message}</div>`;
  }
}

function renderApiUrls(urls, defaults) {
  const container = document.getElementById('api-urls-container');
  if (!container) return;
  
  let html = '';
  
  for (const [type, url] of Object.entries(urls)) {
    const isDefault = url === defaults[type];
    const name = SERVER_TYPE_NAMES[type] || type;
    
    html += `
      <div class="api-url-item" data-type="${type}">
        <div class="api-url-header">
          <span class="api-url-name">${name}</span>
          ${isDefault ? '<span class="api-url-badge default">Default</span>' : '<span class="api-url-badge custom">Custom</span>'}
        </div>
        <div class="api-url-input-group">
          <input type="text" 
                 class="form-control api-url-input" 
                 id="api-url-${type}" 
                 value="${url}" 
                 placeholder="${defaults[type]}"
                 data-default="${defaults[type]}">
          <button class="btn btn-small" onclick="saveApiUrl('${type}')" title="Save URL">💾</button>
          <button class="btn btn-small btn-secondary" onclick="resetApiUrl('${type}')" title="Reset to Default">↩️</button>
        </div>
      </div>
    `;
  }
  
  container.innerHTML = html;
}

async function saveApiUrl(type) {
  const input = document.getElementById(`api-url-${type}`);
  const url = input.value.trim();
  const item = input.closest('.api-url-item');
  
  try {
    const response = await fetch('/api/tools/jarfetcher/api-urls', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, url })
    });
    
    const data = await response.json();
    
    if (response.ok && data.success) {
      // Update badge
      const badge = item.querySelector('.api-url-badge');
      if (data.isDefault) {
        badge.className = 'api-url-badge default';
        badge.textContent = 'Default';
      } else {
        badge.className = 'api-url-badge custom';
        badge.textContent = 'Custom';
      }
      
      // Flash success
      item.classList.add('save-success');
      setTimeout(() => item.classList.remove('save-success'), 1500);
    } else {
      alert('Failed to save: ' + (data.error || 'Unknown error'));
    }
  } catch (err) {
    alert('Error saving URL: ' + err.message);
  }
}

async function resetApiUrl(type) {
  const input = document.getElementById(`api-url-${type}`);
  const defaultUrl = input.dataset.default;
  
  try {
    const response = await fetch('/api/tools/jarfetcher/api-urls', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, url: '' }) // Empty URL resets to default
    });
    
    if (response.ok) {
      input.value = defaultUrl;
      
      // Update badge
      const item = input.closest('.api-url-item');
      const badge = item.querySelector('.api-url-badge');
      badge.className = 'api-url-badge default';
      badge.textContent = 'Default';
      
      // Flash success
      item.classList.add('save-success');
      setTimeout(() => item.classList.remove('save-success'), 1500);
    }
  } catch (err) {
    alert('Error resetting URL: ' + err.message);
  }
}

async function resetAllApiUrls() {
  if (!confirm('Are you sure you want to reset all API URLs to their defaults?')) {
    return;
  }
  
  try {
    const response = await fetch('/api/tools/jarfetcher/api-urls/reset', {
      method: 'POST'
    });
    
    if (response.ok) {
      loadApiUrls(); // Reload the display
    } else {
      alert('Failed to reset API URLs');
    }
  } catch (err) {
    alert('Error: ' + err.message);
  }
}

// ==================== Bulk URL Update Functions ====================

async function bulkUpdateJarUrls() {
  const btn = document.getElementById('bulk-update-btn');
  const progressDiv = document.getElementById('bulk-update-progress');
  const progressFill = document.getElementById('bulk-progress-fill');
  const progressText = document.getElementById('bulk-progress-text');
  const resultsDiv = document.getElementById('bulk-update-results');
  const summaryDiv = document.getElementById('bulk-results-summary');
  const detailsDiv = document.getElementById('bulk-results-details');
  
  // Get selected types
  const checkboxes = document.querySelectorAll('#bulk-update-types input[type="checkbox"]:checked');
  const selectedTypes = Array.from(checkboxes).map(cb => cb.value);
  
  if (selectedTypes.length === 0) {
    alert('Please select at least one server type to update.');
    return;
  }
  
  const maxVersions = parseInt(document.getElementById('bulk-max-versions').value);
  
  // Show progress, hide results
  btn.disabled = true;
  btn.innerHTML = '⏳ Updating...';
  progressDiv.style.display = 'block';
  resultsDiv.style.display = 'none';
  progressFill.style.width = '0%';
  progressText.textContent = 'Fetching URLs from APIs...';
  
  try {
    const response = await fetch('/api/tools/jarfetcher/bulk-update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        types: selectedTypes,
        maxVersions: maxVersions
      })
    });
    
    const data = await response.json();
    
    // Update progress to complete
    progressFill.style.width = '100%';
    progressText.textContent = 'Complete!';
    
    // Show results
    setTimeout(() => {
      progressDiv.style.display = 'none';
      resultsDiv.style.display = 'block';
      
      // Summary
      const summary = data.summary || { updated: 0, failed: 0, skipped: 0 };
      summaryDiv.innerHTML = `
        <div class="summary-stats">
          <div class="stat success-stat">
            <span class="stat-value">${summary.updated}</span>
            <span class="stat-label">Updated</span>
          </div>
          <div class="stat error-stat">
            <span class="stat-value">${summary.failed}</span>
            <span class="stat-label">Failed</span>
          </div>
        </div>
      `;
      
      // Details
      let detailsHtml = '';
      
      if (data.results.success.length > 0) {
        detailsHtml += '<div class="results-section"><h4>✅ Successfully Updated</h4><div class="results-list">';
        data.results.success.forEach(item => {
          detailsHtml += `
            <div class="result-item success">
              <span class="result-type">${item.type}:${item.version}</span>
              ${item.build ? `<span class="result-build">Build ${item.build}</span>` : ''}
            </div>
          `;
        });
        detailsHtml += '</div></div>';
      }
      
      if (data.results.failed.length > 0) {
        detailsHtml += '<div class="results-section"><h4>❌ Failed</h4><div class="results-list">';
        data.results.failed.forEach(item => {
          detailsHtml += `
            <div class="result-item failed">
              <span class="result-type">${item.type}${item.version ? ':' + item.version : ''}</span>
              <span class="result-error">${item.error}</span>
            </div>
          `;
        });
        detailsHtml += '</div></div>';
      }
      
      detailsDiv.innerHTML = detailsHtml || '<p>No detailed results available.</p>';
      
      // Reload config display
      loadJarConfig();
    }, 500);
    
  } catch (err) {
    progressDiv.style.display = 'none';
    resultsDiv.style.display = 'block';
    summaryDiv.innerHTML = `<div class="error-text">Error: ${err.message}</div>`;
    detailsDiv.innerHTML = '';
  } finally {
    btn.disabled = false;
    btn.innerHTML = '🔄 Update All URLs';
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
  
  try {
    const response = await fetch('/api/settings/app', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings)
    });
    
    if (!response.ok) {
      throw new Error('Failed to save settings');
    }
  } catch (err) {
    console.error('Failed to save app settings:', err);
    alert('Failed to save settings: ' + err.message);
  }
}
