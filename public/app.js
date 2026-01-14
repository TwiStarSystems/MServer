// MServerController - Multi-Server Frontend Application

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
        <button class="btn-icon" onclick="openProfileSettings()" title="Profile">👤</button>
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


// ==================== Socket.IO Connection ====================

function connectWebSocket() {
  socket = io();
  
  socket.on('connect', () => {
    console.log('Socket.IO connected');
    // Subscribe to current server if selected
    if (currentServerId) {
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
        updateServerStatus(data.running);
      }
    }
    // Update server list status
    if (data.type === 'status') {
      updateServerInList(data.serverId, data.running);
    }
  });
  
  socket.on('disconnect', () => {
    console.log('Socket.IO disconnected');
  });
  
  socket.on('connect_error', (error) => {
    console.error('Socket.IO error:', error);
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
  
  container.innerHTML = servers.map(server => `
    <div class="server-item ${server.id === currentServerId ? 'active' : ''}" 
         data-server-id="${server.id}" 
         onclick="selectServer('${server.id}')">
      <div class="server-item-status ${server.running ? 'status-running' : 'status-stopped'}">●</div>
      <div class="server-item-info">
        <div class="server-item-name">${escapeHtml(server.name)}</div>
        <div class="server-item-state">${server.running ? 'Running' : 'Stopped'}</div>
      </div>
    </div>
  `).join('');
}

function updateServerInList(serverId, isRunning) {
  const server = servers.find(s => s.id === serverId);
  if (server) {
    server.running = isRunning;
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
  document.getElementById('terminal-output').textContent = '';
  
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
    updateServerStatus(server.running);
  } catch (error) {
    console.error('Failed to load server details:', error);
  }
}

function updateServerStatus(isRunning) {
  const indicator = document.getElementById('status-indicator');
  const text = document.getElementById('status-text');
  const startBtn = document.getElementById('start-btn');
  const stopBtn = document.getElementById('stop-btn');
  const terminalInput = document.getElementById('terminal-input');
  const sendBtn = document.getElementById('send-btn');
  
  if (isRunning) {
    indicator.className = 'status-running';
    text.textContent = 'Running';
    startBtn.disabled = true;
    stopBtn.disabled = false;
    terminalInput.disabled = false;
    sendBtn.disabled = false;
  } else {
    indicator.className = 'status-stopped';
    text.textContent = 'Stopped';
    startBtn.disabled = false;
    stopBtn.disabled = true;
    terminalInput.disabled = true;
    sendBtn.disabled = true;
  }
  
  // Update server in list
  updateServerInList(currentServerId, isRunning);
}

// ==================== Server Actions ====================

async function startServer() {
  if (!currentServerId) return;
  
  try {
    const result = await apiRequest(`/api/servers/${currentServerId}/start`, { method: 'POST' });
    if (result.success) {
      appendTerminalOutput('Starting server...\n');
      updateServerStatus(true);
    }
  } catch (error) {
    // Error already shown by apiRequest
  }
}

async function stopServer() {
  if (!currentServerId) return;
  
  try {
    const result = await apiRequest(`/api/servers/${currentServerId}/stop`, { method: 'POST' });
    if (result.success) {
      appendTerminalOutput('Stopping server...\n');
      setTimeout(() => loadServerDetails(), 2000);
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
  document.getElementById('fresh-type').value = '';
  document.getElementById('fresh-version').value = '';
  document.getElementById('fresh-version').disabled = true;
  document.getElementById('fresh-jar-name').value = 'server.jar';
  document.getElementById('fresh-java-args').value = '-Xmx2G -Xms1G';
  document.getElementById('fresh-upload-jar').checked = false;
  document.getElementById('custom-jar-upload').style.display = 'none';
  
  // Reset import form
  document.getElementById('import-name').value = '';
  document.getElementById('import-file').value = '';
  document.getElementById('import-java-args').value = '-Xmx2G -Xms1G';
  
  // Reset manual form with default path placeholder
  document.getElementById('input-name').value = '';
  document.getElementById('input-path').value = '';
  document.getElementById('input-path').placeholder = defaultServerPath ? `${defaultServerPath}/<server-id>` : '/path/to/minecraft/server';
  document.getElementById('input-executable').value = 'server.jar';
  document.getElementById('input-java-args').value = '-Xmx2G -Xms1G';
  
  // Update path hint with actual default path
  const pathHint = document.getElementById('path-hint');
  if (pathHint && defaultServerPath) {
    pathHint.innerHTML = `Leave empty to auto-create in <code>${defaultServerPath}/</code>`;
  }
  
  // Load server types for fresh server option
  loadServerTypes();
  
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

async function loadServerTypes() {
  try {
    const result = await apiRequest('/api/server-types');
    serverTypes = result.types || [];
    
    const typeSelect = document.getElementById('fresh-type');
    typeSelect.innerHTML = '<option value="">Select server type...</option>';
    
    serverTypes.forEach(type => {
      const option = document.createElement('option');
      option.value = type.id;
      option.textContent = type.name;
      option.dataset.description = type.description || '';
      typeSelect.appendChild(option);
    });
  } catch (error) {
    console.error('Failed to load server types:', error);
  }
}

async function loadVersions() {
  const typeSelect = document.getElementById('fresh-type');
  const versionSelect = document.getElementById('fresh-version');
  const typeDesc = document.getElementById('type-description');
  
  const serverType = typeSelect.value;
  
  if (!serverType) {
    versionSelect.innerHTML = '<option value="">Select server type first...</option>';
    versionSelect.disabled = true;
    typeDesc.textContent = '';
    return;
  }
  
  // Show type description
  const selectedOption = typeSelect.options[typeSelect.selectedIndex];
  typeDesc.textContent = selectedOption.dataset.description || '';
  
  try {
    versionSelect.innerHTML = '<option value="">Loading versions...</option>';
    versionSelect.disabled = true;
    
    const result = await apiRequest(`/api/server-types/${serverType}/versions`);
    const versions = result.versions || [];
    
    versionSelect.innerHTML = '<option value="">Select version...</option>';
    versions.forEach(version => {
      const option = document.createElement('option');
      option.value = version;
      option.textContent = version;
      versionSelect.appendChild(option);
    });
    versionSelect.disabled = false;
  } catch (error) {
    console.error('Failed to load versions:', error);
    versionSelect.innerHTML = '<option value="">Error loading versions</option>';
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
    document.getElementById('input-java-args').value = server.javaArgs || '-Xmx2G -Xms1G';
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
  
  const serverData = {
    name: document.getElementById('input-name').value,
    serverPath: document.getElementById('input-path').value,
    executable: document.getElementById('input-executable').value,
    javaArgs: document.getElementById('input-java-args').value
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
  const serverType = document.getElementById('fresh-type').value;
  const version = document.getElementById('fresh-version').value;
  const executable = document.getElementById('fresh-jar-name').value || 'server.jar';
  const javaArgs = document.getElementById('fresh-java-args').value || '-Xmx2G -Xms1G';
  const uploadCustom = document.getElementById('fresh-upload-jar').checked;
  
  if (!uploadCustom && (!serverType || !version)) {
    showNotification('Please select a server type and version', 'error');
    return;
  }
  
  try {
    // Show loading state
    const submitBtn = e.target.querySelector('button[type="submit"]');
    const originalText = submitBtn.textContent;
    submitBtn.textContent = 'Creating...';
    submitBtn.disabled = true;
    
    if (uploadCustom) {
      // Custom JAR upload flow
      const fileInput = document.getElementById('fresh-jar-file');
      if (!fileInput.files.length) {
        showNotification('Please select a JAR file to upload', 'error');
        submitBtn.textContent = originalText;
        submitBtn.disabled = false;
        return;
      }
      
      // First create the server
      const result = await apiRequest('/api/servers', {
        method: 'POST',
        body: JSON.stringify({
          name,
          executable,
          javaArgs,
          serverType: 'custom'
        })
      });
      
      if (result.pendingApproval) {
        showNotification('Server created and pending admin approval', 'info');
        closeServerModal();
        await loadServers();
        return;
      }
      
      // Then upload the JAR
      const formData = new FormData();
      formData.append('file', fileInput.files[0]);
      
      await fetch(`/api/servers/${result.serverId}/upload-jar`, {
        method: 'POST',
        body: formData
      });
      
      await loadServers();
      selectServer(result.serverId);
    } else {
      // Download server JAR from repository
      const result = await apiRequest('/api/servers', {
        method: 'POST',
        body: JSON.stringify({
          name,
          executable,
          javaArgs,
          serverType,
          version,
          downloadJar: true
        })
      });
      
      if (result.pendingApproval) {
        showNotification('Server created and pending admin approval', 'info');
      } else if (result.warning) {
        showNotification(result.warning, 'warning');
        await loadServers();
        selectServer(result.serverId);
      } else {
        await loadServers();
        selectServer(result.serverId);
      }
    }
    
    closeServerModal();
    submitBtn.textContent = originalText;
    submitBtn.disabled = false;
  } catch (error) {
    console.error('Failed to create server:', error);
    showNotification('Failed to create server: ' + error.message, 'error');
    // Reset button state
    const submitBtn = e.target.querySelector('button[type="submit"]');
    submitBtn.textContent = 'Create Server';
    submitBtn.disabled = false;
  }
}

// Import server from ZIP
async function importServer(e) {
  e.preventDefault();
  
  const name = document.getElementById('import-name').value;
  const fileInput = document.getElementById('import-file');
  const javaArgs = document.getElementById('import-java-args').value || '-Xmx2G -Xms1G';
  
  if (!fileInput.files.length) {
    showNotification('Please select a ZIP file to import', 'error');
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
    formData.append('javaArgs', javaArgs);
    
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
  const typeGroup = document.getElementById('fresh-type').closest('.form-group');
  const versionGroup = document.getElementById('fresh-version').closest('.form-group');
  
  if (checkbox.checked) {
    customSection.style.display = 'block';
    typeGroup.style.display = 'none';
    versionGroup.style.display = 'none';
  } else {
    customSection.style.display = 'none';
    typeGroup.style.display = 'block';
    versionGroup.style.display = 'block';
  }
}

async function deleteServer() {
  if (!currentServerId) return;
  
  const server = servers.find(s => s.id === currentServerId);
  if (!confirm(`Are you sure you want to delete "${server?.name}"?\n\nThis will only remove the configuration, not the server files.`)) {
    return;
  }
  
  try {
    await apiRequest(`/api/servers/${currentServerId}`, { method: 'DELETE' });
    
    currentServerId = null;
    document.getElementById('no-server-view').style.display = 'flex';
    document.getElementById('server-view').style.display = 'none';
    
    await loadServers();
  } catch (error) {
    console.error('Failed to delete server:', error);
  }
}

// ==================== Terminal Functions ====================

function appendTerminalOutput(text) {
  const terminal = document.getElementById('terminal-output');
  terminal.textContent += text;
  terminal.scrollTop = terminal.scrollHeight;
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
      row.innerHTML = `
        <td>${escapeHtml(backup.name)}</td>
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
  }
}

// ==================== Utility Functions ====================

function formatBytes(bytes) {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ==================== Event Listeners ====================

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
  
  // Version loading when type changes
  document.getElementById('fresh-type').onchange = loadVersions;
  
  // Server actions
  document.getElementById('start-btn').onclick = startServer;
  document.getElementById('stop-btn').onclick = stopServer;
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
  
  // File editor
  document.getElementById('save-file-btn').onclick = saveFile;
  
  // Backup controls
  document.getElementById('create-backup-btn').onclick = createBackup;
  document.getElementById('refresh-backups-btn').onclick = loadBackups;
  
  // Close modals on background click
  document.getElementById('server-modal').onclick = (e) => {
    if (e.target.id === 'server-modal') closeServerModal();
  };
  
  document.getElementById('file-editor-modal').onclick = (e) => {
    if (e.target.id === 'file-editor-modal') closeFileEditor();
  };
});

// ==================== Admin Panel ====================

function openAdminPanel() {
  // Create admin panel modal
  const modal = document.createElement('div');
  modal.id = 'admin-modal';
  modal.className = 'modal';
  modal.innerHTML = `
    <div class="modal-content modal-large">
      <div class="modal-header">
        <h2>Admin Panel</h2>
        <button class="close-btn" onclick="closeAdminPanel()">&times;</button>
      </div>
      <div class="admin-tabs">
        <button class="admin-tab-btn active" data-tab="users" onclick="switchAdminTab('users')">Users</button>
        <button class="admin-tab-btn" data-tab="pending" onclick="switchAdminTab('pending')">Pending Approval</button>
      </div>
      <div id="admin-users-tab" class="admin-tab-content active">
        <div class="admin-loading">Loading users...</div>
      </div>
      <div id="admin-pending-tab" class="admin-tab-content">
        <div class="admin-loading">Loading pending users...</div>
      </div>
    </div>
  `;
  modal.style.display = 'flex';
  document.body.appendChild(modal);
  
  modal.onclick = (e) => {
    if (e.target.id === 'admin-modal') closeAdminPanel();
  };
  
  loadAdminUsers();
}

function closeAdminPanel() {
  const modal = document.getElementById('admin-modal');
  if (modal) modal.remove();
}

function switchAdminTab(tabName) {
  document.querySelectorAll('.admin-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });
  document.querySelectorAll('.admin-tab-content').forEach(content => {
    content.classList.toggle('active', content.id === `admin-${tabName}-tab`);
  });
}

async function loadAdminUsers() {
  try {
    const data = await apiRequest('/api/admin/users');
    const users = data.users || [];
    
    const approvedUsers = users.filter(u => u.approved);
    const pendingUsers = users.filter(u => !u.approved);
    
    // Render approved users
    const usersTab = document.getElementById('admin-users-tab');
    if (approvedUsers.length === 0) {
      usersTab.innerHTML = '<p class="admin-empty">No approved users</p>';
    } else {
      usersTab.innerHTML = `
        <table class="admin-table">
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
                <td class="admin-actions">
                  <select onchange="changeUserRole('${u.id}', this.value)">
                    <option value="public" ${u.role === 'public' ? 'selected' : ''}>Public</option>
                    <option value="user" ${u.role === 'user' ? 'selected' : ''}>User</option>
                    <option value="admin" ${u.role === 'admin' ? 'selected' : ''}>Admin</option>
                  </select>
                  <button class="btn-small" onclick="resetUserPassword('${u.id}')">Reset PW</button>
                  <button class="btn-small btn-danger" onclick="deleteUser('${u.id}', '${escapeHtml(u.username)}')">Delete</button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    }
    
    // Render pending users
    const pendingTab = document.getElementById('admin-pending-tab');
    if (pendingUsers.length === 0) {
      pendingTab.innerHTML = '<p class="admin-empty">No pending approval requests</p>';
    } else {
      pendingTab.innerHTML = `
        <table class="admin-table">
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
                <td class="admin-actions">
                  <button class="btn-small btn-success" onclick="approveUser('${u.id}')">Approve</button>
                  <button class="btn-small btn-danger" onclick="deleteUser('${u.id}', '${escapeHtml(u.username)}')">Reject</button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    }
  } catch (err) {
    console.error('Failed to load users:', err);
  }
}

async function approveUser(userId) {
  try {
    await apiRequest(`/api/admin/users/${userId}/approve`, { method: 'POST' });
    loadAdminUsers();
  } catch (err) {
    console.error('Failed to approve user:', err);
  }
}

async function changeUserRole(userId, role) {
  try {
    await apiRequest(`/api/admin/users/${userId}/role`, {
      method: 'PUT',
      body: JSON.stringify({ role })
    });
    loadAdminUsers();
  } catch (err) {
    console.error('Failed to change role:', err);
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
    await apiRequest(`/api/admin/users/${userId}/password`, {
      method: 'PUT',
      body: JSON.stringify({ password: newPassword })
    });
    alert('Password reset successfully');
  } catch (err) {
    console.error('Failed to reset password:', err);
  }
}

async function deleteUser(userId, username) {
  if (!confirm(`Are you sure you want to delete user "${username}"?`)) return;
  
  try {
    await apiRequest(`/api/admin/users/${userId}`, { method: 'DELETE' });
    loadAdminUsers();
  } catch (err) {
    console.error('Failed to delete user:', err);
  }
}

// ==================== Profile Settings ====================

function openProfileSettings() {
  const modal = document.createElement('div');
  modal.id = 'profile-modal';
  modal.className = 'modal';
  modal.innerHTML = `
    <div class="modal-content">
      <div class="modal-header">
        <h2>Profile Settings</h2>
        <button class="close-btn" onclick="closeProfileSettings()">&times;</button>
      </div>
      <div class="profile-info">
        <p><strong>Username:</strong> ${escapeHtml(currentUser.username)}</p>
        <p><strong>Role:</strong> <span class="role-badge ${currentUser.role}">${currentUser.role}</span></p>
      </div>
      <form id="password-form" onsubmit="changePassword(event)">
        <h3>Change Password</h3>
        <div class="form-group">
          <label for="current-password">Current Password</label>
          <input type="password" id="current-password" required>
        </div>
        <div class="form-group">
          <label for="new-password">New Password</label>
          <input type="password" id="new-password" required minlength="8">
        </div>
        <div class="form-group">
          <label for="confirm-password">Confirm New Password</label>
          <input type="password" id="confirm-password" required>
        </div>
        <button type="submit" class="btn btn-primary">Update Password</button>
      </form>
    </div>
  `;
  modal.style.display = 'flex';
  document.body.appendChild(modal);
  
  modal.onclick = (e) => {
    if (e.target.id === 'profile-modal') closeProfileSettings();
  };
}

function closeProfileSettings() {
  const modal = document.getElementById('profile-modal');
  if (modal) modal.remove();
}

async function changePassword(event) {
  event.preventDefault();
  
  const currentPassword = document.getElementById('current-password').value;
  const newPassword = document.getElementById('new-password').value;
  const confirmPassword = document.getElementById('confirm-password').value;
  
  if (newPassword !== confirmPassword) {
    alert('New passwords do not match');
    return;
  }
  
  try {
    await apiRequest('/api/auth/password', {
      method: 'PUT',
      body: JSON.stringify({ currentPassword, newPassword })
    });
    alert('Password updated successfully');
    closeProfileSettings();
  } catch (err) {
    console.error('Failed to change password:', err);
  }
}
