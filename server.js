const express = require('express');
const http = require('http');
const WebSocket = require('ws');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const multer = require('multer');
const archiver = require('archiver');

const app = express();
const server = http.createServer(app);
const wss = new WebSocket.Server({ server });

const PORT = process.env.PORT || 3000;
const SERVERS_DIR = path.join(__dirname, 'servers');
const BACKUPS_DIR = path.join(__dirname, 'backups');
const UPLOADS_DIR = path.join(__dirname, 'uploads');

// Ensure directories exist
[SERVERS_DIR, BACKUPS_DIR, UPLOADS_DIR].forEach(dir => {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
});

// Middleware
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// Store active Minecraft server process
let minecraftProcess = null;
let serverConfig = {
  serverPath: '',
  executable: 'server.jar',
  memory: '2G',
  javaArgs: '-Xmx2G -Xms1G'
};

// Load config if exists
const configPath = path.join(__dirname, 'config.json');
if (fs.existsSync(configPath)) {
  serverConfig = JSON.parse(fs.readFileSync(configPath, 'utf8'));
}

// Save config
function saveConfig() {
  fs.writeFileSync(configPath, JSON.stringify(serverConfig, null, 2));
}

// Configure multer for file uploads
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    cb(null, UPLOADS_DIR);
  },
  filename: (req, file, cb) => {
    cb(null, file.originalname);
  }
});
const upload = multer({ storage });

// WebSocket connection for terminal
wss.on('connection', (ws) => {
  console.log('Client connected to WebSocket');
  
  ws.on('message', (message) => {
    try {
      const data = JSON.parse(message);
      
      if (data.type === 'command' && minecraftProcess) {
        minecraftProcess.stdin.write(data.command + '\n');
      }
    } catch (err) {
      console.error('WebSocket message error:', err);
    }
  });
  
  ws.on('close', () => {
    console.log('Client disconnected from WebSocket');
  });
});

// Broadcast to all WebSocket clients
function broadcast(data) {
  wss.clients.forEach(client => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(JSON.stringify(data));
    }
  });
}

// API Routes

// Get server status
app.get('/api/status', (req, res) => {
  res.json({
    running: minecraftProcess !== null,
    config: serverConfig
  });
});

// Get server config
app.get('/api/config', (req, res) => {
  res.json(serverConfig);
});

// Update server config
app.post('/api/config', (req, res) => {
  serverConfig = { ...serverConfig, ...req.body };
  saveConfig();
  res.json({ success: true, config: serverConfig });
});

// Start server
app.post('/api/server/start', (req, res) => {
  if (minecraftProcess) {
    return res.status(400).json({ error: 'Server is already running' });
  }
  
  const serverPath = serverConfig.serverPath || SERVERS_DIR;
  const executablePath = path.join(serverPath, serverConfig.executable);
  
  if (!fs.existsSync(executablePath)) {
    return res.status(400).json({ error: 'Server executable not found' });
  }
  
  const args = serverConfig.javaArgs.split(' ').concat(['-jar', serverConfig.executable, 'nogui']);
  
  minecraftProcess = spawn('java', args, {
    cwd: serverPath
  });
  
  minecraftProcess.stdout.on('data', (data) => {
    broadcast({ type: 'output', data: data.toString() });
  });
  
  minecraftProcess.stderr.on('data', (data) => {
    broadcast({ type: 'error', data: data.toString() });
  });
  
  minecraftProcess.on('close', (code) => {
    broadcast({ type: 'info', data: `Server stopped with code ${code}` });
    minecraftProcess = null;
  });
  
  res.json({ success: true, message: 'Server started' });
});

// Stop server
app.post('/api/server/stop', (req, res) => {
  if (!minecraftProcess) {
    return res.status(400).json({ error: 'Server is not running' });
  }
  
  minecraftProcess.stdin.write('stop\n');
  
  setTimeout(() => {
    if (minecraftProcess) {
      minecraftProcess.kill();
      minecraftProcess = null;
    }
  }, 10000);
  
  res.json({ success: true, message: 'Server stopping...' });
});

// File Explorer API

// List files
app.get('/api/files', (req, res) => {
  const requestedPath = req.query.path || '';
  const serverPath = serverConfig.serverPath || SERVERS_DIR;
  const fullPath = path.join(serverPath, requestedPath);
  
  // Security: prevent directory traversal
  if (!fullPath.startsWith(serverPath)) {
    return res.status(403).json({ error: 'Access denied' });
  }
  
  if (!fs.existsSync(fullPath)) {
    return res.status(404).json({ error: 'Path not found' });
  }
  
  const stat = fs.statSync(fullPath);
  
  if (stat.isDirectory()) {
    const files = fs.readdirSync(fullPath).map(name => {
      const itemPath = path.join(fullPath, name);
      const itemStat = fs.statSync(itemPath);
      return {
        name,
        isDirectory: itemStat.isDirectory(),
        size: itemStat.size,
        modified: itemStat.mtime
      };
    });
    res.json({ files, currentPath: requestedPath });
  } else {
    res.json({ isFile: true, path: requestedPath });
  }
});

// Read file content
app.get('/api/files/read', (req, res) => {
  const requestedPath = req.query.path || '';
  const serverPath = serverConfig.serverPath || SERVERS_DIR;
  const fullPath = path.join(serverPath, requestedPath);
  
  if (!fullPath.startsWith(serverPath)) {
    return res.status(403).json({ error: 'Access denied' });
  }
  
  if (!fs.existsSync(fullPath)) {
    return res.status(404).json({ error: 'File not found' });
  }
  
  const content = fs.readFileSync(fullPath, 'utf8');
  res.json({ content });
});

// Write file content
app.post('/api/files/write', (req, res) => {
  const { path: filePath, content } = req.body;
  const serverPath = serverConfig.serverPath || SERVERS_DIR;
  const fullPath = path.join(serverPath, filePath);
  
  if (!fullPath.startsWith(serverPath)) {
    return res.status(403).json({ error: 'Access denied' });
  }
  
  fs.writeFileSync(fullPath, content, 'utf8');
  res.json({ success: true });
});

// Create file or directory
app.post('/api/files/create', (req, res) => {
  const { path: filePath, type } = req.body;
  const serverPath = serverConfig.serverPath || SERVERS_DIR;
  const fullPath = path.join(serverPath, filePath);
  
  if (!fullPath.startsWith(serverPath)) {
    return res.status(403).json({ error: 'Access denied' });
  }
  
  if (type === 'directory') {
    fs.mkdirSync(fullPath, { recursive: true });
  } else {
    fs.writeFileSync(fullPath, '', 'utf8');
  }
  
  res.json({ success: true });
});

// Delete file or directory
app.delete('/api/files/delete', (req, res) => {
  const { path: filePath } = req.body;
  const serverPath = serverConfig.serverPath || SERVERS_DIR;
  const fullPath = path.join(serverPath, filePath);
  
  if (!fullPath.startsWith(serverPath)) {
    return res.status(403).json({ error: 'Access denied' });
  }
  
  if (!fs.existsSync(fullPath)) {
    return res.status(404).json({ error: 'File not found' });
  }
  
  const stat = fs.statSync(fullPath);
  if (stat.isDirectory()) {
    fs.rmSync(fullPath, { recursive: true });
  } else {
    fs.unlinkSync(fullPath);
  }
  
  res.json({ success: true });
});

// Download file
app.get('/api/files/download', (req, res) => {
  const requestedPath = req.query.path || '';
  const serverPath = serverConfig.serverPath || SERVERS_DIR;
  const fullPath = path.join(serverPath, requestedPath);
  
  if (!fullPath.startsWith(serverPath)) {
    return res.status(403).json({ error: 'Access denied' });
  }
  
  if (!fs.existsSync(fullPath)) {
    return res.status(404).json({ error: 'File not found' });
  }
  
  res.download(fullPath);
});

// Upload file
app.post('/api/files/upload', upload.single('file'), (req, res) => {
  const targetPath = req.body.path || '';
  const serverPath = serverConfig.serverPath || SERVERS_DIR;
  const uploadedFile = req.file;
  
  if (!uploadedFile) {
    return res.status(400).json({ error: 'No file uploaded' });
  }
  
  const destPath = path.join(serverPath, targetPath, uploadedFile.originalname);
  
  if (!destPath.startsWith(serverPath)) {
    fs.unlinkSync(uploadedFile.path);
    return res.status(403).json({ error: 'Access denied' });
  }
  
  fs.renameSync(uploadedFile.path, destPath);
  res.json({ success: true });
});

// Backup API

// List backups
app.get('/api/backups', (req, res) => {
  if (!fs.existsSync(BACKUPS_DIR)) {
    return res.json({ backups: [] });
  }
  
  const backups = fs.readdirSync(BACKUPS_DIR)
    .filter(name => name.endsWith('.zip'))
    .map(name => {
      const stat = fs.statSync(path.join(BACKUPS_DIR, name));
      return {
        name,
        size: stat.size,
        created: stat.mtime
      };
    });
  
  res.json({ backups });
});

// Create backup
app.post('/api/backups/create', (req, res) => {
  const serverPath = serverConfig.serverPath || SERVERS_DIR;
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const backupName = `backup-${timestamp}.zip`;
  const backupPath = path.join(BACKUPS_DIR, backupName);
  
  const output = fs.createWriteStream(backupPath);
  const archive = archiver('zip', { zlib: { level: 9 } });
  
  output.on('close', () => {
    res.json({ success: true, backup: backupName, size: archive.pointer() });
  });
  
  archive.on('error', (err) => {
    res.status(500).json({ error: err.message });
  });
  
  archive.pipe(output);
  archive.directory(serverPath, false);
  archive.finalize();
});

// Download backup
app.get('/api/backups/download', (req, res) => {
  const backupName = req.query.name;
  const backupPath = path.join(BACKUPS_DIR, backupName);
  
  if (!fs.existsSync(backupPath)) {
    return res.status(404).json({ error: 'Backup not found' });
  }
  
  res.download(backupPath);
});

// Delete backup
app.delete('/api/backups/delete', (req, res) => {
  const { name } = req.body;
  const backupPath = path.join(BACKUPS_DIR, name);
  
  if (!fs.existsSync(backupPath)) {
    return res.status(404).json({ error: 'Backup not found' });
  }
  
  fs.unlinkSync(backupPath);
  res.json({ success: true });
});

// Start server
server.listen(PORT, () => {
  console.log(`MServerController running on http://localhost:${PORT}`);
});
