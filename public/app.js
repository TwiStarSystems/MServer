// WebSocket connection
let ws = null;
let currentPath = '';
let currentEditingFile = '';

// Initialize WebSocket
function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${protocol}//${window.location.host}`);
  
  ws.onopen = () => {
    console.log('WebSocket connected');
  };
  
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    if (data.type === 'output' || data.type === 'error' || data.type === 'info') {
      appendTerminalOutput(data.data);
    }
  };
  
  ws.onclose = () => {
    console.log('WebSocket disconnected');
    setTimeout(connectWebSocket, 3000);
  };
  
  ws.onerror = (error) => {
    console.error('WebSocket error:', error);
  };
}

// Terminal functions
function appendTerminalOutput(text) {
  const terminal = document.getElementById('terminal-output');
  terminal.textContent += text;
  terminal.scrollTop = terminal.scrollHeight;
}

function sendCommand(command) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'command', command }));
    appendTerminalOutput(`> ${command}\n`);
  }
}

// API functions
async function apiRequest(url, options = {}) {
  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers
      }
    });
    return await response.json();
  } catch (error) {
    console.error('API request failed:', error);
    alert('Request failed: ' + error.message);
    throw error;
  }
}

async function updateStatus() {
  const status = await apiRequest('/api/status');
  const indicator = document.getElementById('status-indicator');
  const text = document.getElementById('status-text');
  const startBtn = document.getElementById('start-btn');
  const stopBtn = document.getElementById('stop-btn');
  const terminalInput = document.getElementById('terminal-input');
  const sendBtn = document.getElementById('send-btn');
  
  if (status.running) {
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
}

async function startServer() {
  const result = await apiRequest('/api/server/start', { method: 'POST' });
  if (result.success) {
    appendTerminalOutput('Starting server...\n');
    updateStatus();
  }
}

async function stopServer() {
  const result = await apiRequest('/api/server/stop', { method: 'POST' });
  if (result.success) {
    appendTerminalOutput('Stopping server...\n');
    setTimeout(updateStatus, 1000);
  }
}

// File Explorer functions
async function loadFiles(path = '') {
  currentPath = path;
  const data = await apiRequest(`/api/files?path=${encodeURIComponent(path)}`);
  
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
    const row = createFileRow({
      name: '..',
      isDirectory: true
    }, parentPath);
    fileList.appendChild(row);
  }
  
  // Add files and directories
  data.files.forEach(file => {
    const filePath = path ? `${path}/${file.name}` : file.name;
    const row = createFileRow(file, filePath);
    fileList.appendChild(row);
  });
}

function createFileRow(file, filePath) {
  const row = document.createElement('tr');
  
  const nameCell = document.createElement('td');
  const nameDiv = document.createElement('div');
  nameDiv.className = 'file-name';
  nameDiv.innerHTML = `
    <span class="file-icon">${file.isDirectory ? '📁' : '📄'}</span>
    <span>${file.name}</span>
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

function formatBytes(bytes) {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

async function openFileEditor(filePath) {
  currentEditingFile = filePath;
  const data = await apiRequest(`/api/files/read?path=${encodeURIComponent(filePath)}`);
  
  document.getElementById('editor-title').textContent = `Edit: ${filePath}`;
  document.getElementById('file-content').value = data.content;
  document.getElementById('file-editor-modal').classList.add('active');
}

async function saveFile() {
  const content = document.getElementById('file-content').value;
  await apiRequest('/api/files/write', {
    method: 'POST',
    body: JSON.stringify({ path: currentEditingFile, content })
  });
  
  closeModal();
  alert('File saved successfully');
}

function closeModal() {
  document.getElementById('file-editor-modal').classList.remove('active');
}

async function createNewFile() {
  const name = prompt('Enter file name:');
  if (!name) return;
  
  const filePath = currentPath ? `${currentPath}/${name}` : name;
  await apiRequest('/api/files/create', {
    method: 'POST',
    body: JSON.stringify({ path: filePath, type: 'file' })
  });
  
  loadFiles(currentPath);
}

async function createNewFolder() {
  const name = prompt('Enter folder name:');
  if (!name) return;
  
  const filePath = currentPath ? `${currentPath}/${name}` : name;
  await apiRequest('/api/files/create', {
    method: 'POST',
    body: JSON.stringify({ path: filePath, type: 'directory' })
  });
  
  loadFiles(currentPath);
}

async function deleteFile(filePath) {
  if (!confirm(`Are you sure you want to delete ${filePath}?`)) return;
  
  await apiRequest('/api/files/delete', {
    method: 'DELETE',
    body: JSON.stringify({ path: filePath })
  });
  
  loadFiles(currentPath);
}

function downloadFile(filePath) {
  window.location.href = `/api/files/download?path=${encodeURIComponent(filePath)}`;
}

async function uploadFile(file) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('path', currentPath);
  
  const response = await fetch('/api/files/upload', {
    method: 'POST',
    body: formData
  });
  
  const result = await response.json();
  if (result.success) {
    alert('File uploaded successfully');
    loadFiles(currentPath);
  }
}

// Backup functions
async function loadBackups() {
  const data = await apiRequest('/api/backups');
  const backupList = document.getElementById('backup-list');
  backupList.innerHTML = '';
  
  if (data.backups.length === 0) {
    backupList.innerHTML = '<tr><td colspan="4" class="empty-state"><h3>No backups yet</h3><p>Create your first backup to get started</p></td></tr>';
    return;
  }
  
  data.backups.forEach(backup => {
    const row = document.createElement('tr');
    
    row.innerHTML = `
      <td>${backup.name}</td>
      <td>${formatBytes(backup.size)}</td>
      <td>${new Date(backup.created).toLocaleString()}</td>
      <td>
        <div class="file-actions-cell">
          <button class="btn btn-small action-btn download-backup" data-name="${backup.name}">Download</button>
          <button class="btn btn-danger btn-small action-btn delete-backup" data-name="${backup.name}">Delete</button>
        </div>
      </td>
    `;
    
    backupList.appendChild(row);
  });
  
  // Add event listeners
  document.querySelectorAll('.download-backup').forEach(btn => {
    btn.onclick = () => downloadBackup(btn.dataset.name);
  });
  
  document.querySelectorAll('.delete-backup').forEach(btn => {
    btn.onclick = () => deleteBackup(btn.dataset.name);
  });
}

async function createBackup() {
  if (!confirm('Create a backup of the server? This may take a few minutes.')) return;
  
  document.getElementById('create-backup-btn').disabled = true;
  document.getElementById('create-backup-btn').textContent = 'Creating...';
  
  try {
    const result = await apiRequest('/api/backups/create', { method: 'POST' });
    if (result.success) {
      alert(`Backup created: ${result.backup} (${formatBytes(result.size)})`);
      loadBackups();
    }
  } finally {
    document.getElementById('create-backup-btn').disabled = false;
    document.getElementById('create-backup-btn').textContent = 'Create Backup';
  }
}

function downloadBackup(name) {
  window.location.href = `/api/backups/download?name=${encodeURIComponent(name)}`;
}

async function deleteBackup(name) {
  if (!confirm(`Delete backup ${name}?`)) return;
  
  await apiRequest('/api/backups/delete', {
    method: 'DELETE',
    body: JSON.stringify({ name })
  });
  
  loadBackups();
}

// Configuration functions
async function loadConfig() {
  const config = await apiRequest('/api/config');
  
  document.getElementById('server-path').value = config.serverPath || '';
  document.getElementById('executable').value = config.executable || 'server.jar';
  document.getElementById('java-args').value = config.javaArgs || '-Xmx2G -Xms1G';
}

async function saveConfig() {
  const config = {
    serverPath: document.getElementById('server-path').value,
    executable: document.getElementById('executable').value,
    javaArgs: document.getElementById('java-args').value
  };
  
  const result = await apiRequest('/api/config', {
    method: 'POST',
    body: JSON.stringify(config)
  });
  
  if (result.success) {
    alert('Configuration saved successfully');
  }
}

// Tab switching
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
    loadFiles();
  } else if (tabName === 'backups') {
    loadBackups();
  } else if (tabName === 'config') {
    loadConfig();
  }
}

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
  // Connect WebSocket
  connectWebSocket();
  
  // Update status
  updateStatus();
  setInterval(updateStatus, 5000);
  
  // Tab buttons
  document.querySelectorAll('.tab-button').forEach(btn => {
    btn.onclick = () => switchTab(btn.dataset.tab);
  });
  
  // Terminal controls
  document.getElementById('start-btn').onclick = startServer;
  document.getElementById('stop-btn').onclick = stopServer;
  
  document.getElementById('terminal-input').onkeypress = (e) => {
    if (e.key === 'Enter') {
      const input = e.target;
      sendCommand(input.value);
      input.value = '';
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
  document.querySelectorAll('.close-btn').forEach(btn => {
    btn.onclick = closeModal;
  });
  
  // Backup controls
  document.getElementById('create-backup-btn').onclick = createBackup;
  document.getElementById('refresh-backups-btn').onclick = loadBackups;
  
  // Config controls
  document.getElementById('save-config-btn').onclick = saveConfig;
  
  // Close modal on background click
  document.getElementById('file-editor-modal').onclick = (e) => {
    if (e.target.id === 'file-editor-modal') {
      closeModal();
    }
  };
});
