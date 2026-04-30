/**
 * MSMCeditor - World Editor Frontend Controller
 * Handles Leaflet map, block inspection, editing panels, and Socket.IO events.
 */

// ==================== State ====================
let _msmcMap = null;
let _msmcTileLayer = null;
let _msmcSession = null;  // {platform, version, dimensions, bounds, readOnly}
let _msmcDimension = 'minecraft:overworld';
let _msmcInitialized = false;
let _msmcTasks = {};  // taskId -> {done, total, label}

// ==================== Initialization ====================

function initMSMCEditor() {
  if (!currentServerId) return;

  // Load available worlds
  msmcLoadWorlds();

  // Set up dimension tab clicks
  document.querySelectorAll('.msmceditor-dim-btn').forEach(btn => {
    btn.addEventListener('click', function () {
      document.querySelectorAll('.msmceditor-dim-btn').forEach(b => b.classList.remove('active'));
      this.classList.add('active');
      _msmcDimension = this.dataset.dim;
      if (_msmcSession) {
        msmcRefreshMap();
      }
    });
  });

  // Set up panel tab clicks
  document.querySelectorAll('.msmceditor-panel-tab').forEach(btn => {
    btn.addEventListener('click', function () {
      document.querySelectorAll('.msmceditor-panel-tab').forEach(b => b.classList.remove('active'));
      this.classList.add('active');
      document.querySelectorAll('.msmceditor-panel-content').forEach(p => p.classList.remove('active'));
      const panel = document.getElementById('msmceditor-panel-' + this.dataset.panel);
      if (panel) panel.classList.add('active');
    });
  });

  // Initialize map if not done
  if (!_msmcMap) {
    _msmcInitMap();
  }

  // Register Socket.IO listeners (once)
  if (!_msmcInitialized) {
    _msmcInitSocketListeners();
    _msmcInitialized = true;
  }
}

function _msmcInitMap() {
  const container = document.getElementById('msmceditor-map');
  if (!container || !window.L) return;

  _msmcMap = L.map(container, {
    crs: L.CRS.Simple,
    minZoom: -3,
    maxZoom: 2,
    zoomControl: true,
    attributionControl: false,
  });

  _msmcMap.setView([0, 0], 0);

  // Coordinate display on mousemove
  _msmcMap.on('mousemove', function (e) {
    const coordsEl = document.getElementById('msmceditor-coords');
    if (coordsEl) {
      // Convert Leaflet coords to MC coords (each tile = 1 chunk = 16 blocks)
      const mcX = Math.floor(e.latlng.lng * 16);
      const mcZ = Math.floor(-e.latlng.lat * 16);
      coordsEl.textContent = `X: ${mcX}  Z: ${mcZ}`;
    }
  });

  // Click to inspect block
  _msmcMap.on('click', function (e) {
    if (!_msmcSession) return;
    const mcX = Math.floor(e.latlng.lng * 16);
    const mcZ = Math.floor(-e.latlng.lat * 16);
    const yInput = document.getElementById('msmceditor-set-block-y');
    const y = yInput ? parseInt(yInput.value) || 64 : 64;
    msmcInspectBlock(mcX, y, mcZ);
  });
}

function _msmcInitSocketListeners() {
  if (typeof socket === 'undefined') return;

  socket.on('msmceditor:progress', function (data) {
    _msmcTasks[data.taskId] = data;
    _msmcRenderTasks();
  });

  socket.on('msmceditor:tile-invalidate', function (data) {
    if (_msmcTileLayer && data.dim === _msmcDimension) {
      _msmcTileLayer.redraw();
    }
  });

  socket.on('msmceditor:session-state', function (data) {
    if (data.serverId === currentServerId) {
      _msmcUpdateSessionUI(data);
    }
  });

  socket.on('msmceditor:error', function (data) {
    showNotification(data.message || 'Editor error', 'error');
  });
}

// ==================== World Management ====================

async function msmcLoadWorlds() {
  if (!currentServerId) return;
  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/msmceditor/worlds`);
    const select = document.getElementById('msmceditor-world-select');
    select.innerHTML = '<option value="">— Select World —</option>';
    if (data.worlds) {
      data.worlds.forEach(w => {
        const opt = document.createElement('option');
        opt.value = w.path;
        opt.textContent = `${w.name} (${w.platform})`;
        select.appendChild(opt);
      });
    }
    // If session is already open, update UI
    if (data.session) {
      _msmcSession = data.session;
      _msmcShowSessionUI(true);
    }
  } catch (err) {
    // Editor deps might not be installed
    if (err && err.message && err.message.includes('not installed')) {
      showNotification('World Editor dependencies not installed. See docs.', 'error');
    }
  }
}

async function msmcOpenSession() {
  const select = document.getElementById('msmceditor-world-select');
  const worldPath = select.value;
  if (!worldPath) {
    showNotification('Select a world first', 'warning');
    return;
  }

  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/msmceditor/open`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ worldPath })
    });

    if (data.error) {
      showNotification(data.error, 'error');
      return;
    }

    _msmcSession = data;
    _msmcShowSessionUI(true);
    msmcRefreshMap();
    showNotification('World opened successfully', 'success');
  } catch (err) {
    showNotification('Failed to open world: ' + (err.message || err), 'error');
  }
}

async function msmcCloseSession() {
  if (!currentServerId) return;
  try {
    await apiRequest(`/api/servers/${currentServerId}/msmceditor/close`, { method: 'POST' });
    _msmcSession = null;
    _msmcShowSessionUI(false);
    if (_msmcTileLayer) {
      _msmcMap.removeLayer(_msmcTileLayer);
      _msmcTileLayer = null;
    }
    showNotification('Session closed', 'success');
  } catch (err) {
    showNotification('Failed to close session: ' + (err.message || err), 'error');
  }
}

function _msmcShowSessionUI(open) {
  const openBtn = document.getElementById('msmceditor-open-btn');
  const closeBtn = document.getElementById('msmceditor-close-btn');
  const statusEl = document.getElementById('msmceditor-session-status');
  const saveControls = document.querySelector('.msmceditor-save-controls');
  const readOnlyBanner = document.getElementById('msmceditor-readonly-banner');
  const blockEdit = document.getElementById('msmceditor-block-edit');

  if (open && _msmcSession) {
    openBtn.style.display = 'none';
    closeBtn.style.display = '';
    statusEl.style.display = '';
    statusEl.textContent = `${_msmcSession.platform} — ${_msmcSession.readOnly ? 'Read-Only' : 'Editable'}`;
    statusEl.className = 'msmceditor-status-badge ' + (_msmcSession.readOnly ? 'readonly' : 'editable');

    if (_msmcSession.readOnly) {
      readOnlyBanner.style.display = '';
      saveControls.style.display = 'none';
      if (blockEdit) blockEdit.style.display = 'none';
    } else {
      readOnlyBanner.style.display = 'none';
      saveControls.style.display = '';
      if (blockEdit) blockEdit.style.display = '';
    }
  } else {
    openBtn.style.display = '';
    closeBtn.style.display = 'none';
    statusEl.style.display = 'none';
    saveControls.style.display = 'none';
    readOnlyBanner.style.display = 'none';
    if (blockEdit) blockEdit.style.display = 'none';
  }
}

function _msmcUpdateSessionUI(data) {
  if (data.open) {
    _msmcSession = Object.assign(_msmcSession || {}, data);
    _msmcShowSessionUI(true);
  }
}

// ==================== Map ====================

function msmcRefreshMap() {
  if (!_msmcMap || !_msmcSession || !currentServerId) return;

  if (_msmcTileLayer) {
    _msmcMap.removeLayer(_msmcTileLayer);
  }

  const dimEncoded = _msmcDimension.replace(':', '_').replace('/', '_');
  const tileUrl = `/api/servers/${currentServerId}/msmceditor/tile/${dimEncoded}/{y}/{x}.png`;

  _msmcTileLayer = L.tileLayer(tileUrl, {
    tileSize: 16,
    noWrap: true,
    maxNativeZoom: 0,
    minNativeZoom: 0,
    errorTileUrl: '',
  });

  _msmcTileLayer.addTo(_msmcMap);
  _msmcMap.setView([0, 0], 0);
}

// ==================== Block Inspector ====================

async function msmcInspectBlock(x, y, z) {
  if (!_msmcSession || !currentServerId) return;

  try {
    const data = await apiRequest(
      `/api/servers/${currentServerId}/msmceditor/block?dim=${encodeURIComponent(_msmcDimension)}&x=${x}&y=${y}&z=${z}`
    );

    const infoEl = document.getElementById('msmceditor-block-info');
    infoEl.style.display = '';

    document.getElementById('msmceditor-block-coords').textContent = `X:${data.x} Y:${data.y} Z:${data.z}`;
    document.getElementById('msmceditor-block-id').textContent = data.block || data.error || 'Unknown';
    document.getElementById('msmceditor-block-props').textContent =
      data.properties ? JSON.stringify(data.properties, null, 2) : '—';
    document.getElementById('msmceditor-block-nbt').textContent =
      data.blockEntity || '—';

    // Pre-fill edit form
    const editId = document.getElementById('msmceditor-set-block-id');
    if (editId && data.block) editId.value = data.block;
  } catch (err) {
    showNotification('Failed to inspect block: ' + (err.message || err), 'error');
  }
}

async function msmcSetBlock() {
  if (!_msmcSession || _msmcSession.readOnly) {
    showNotification('Read-only mode — stop the server to edit', 'warning');
    return;
  }

  const blockId = document.getElementById('msmceditor-set-block-id').value.trim();
  const y = parseInt(document.getElementById('msmceditor-set-block-y').value) || 64;

  // Get last inspected coords from display
  const coordsText = document.getElementById('msmceditor-block-coords').textContent;
  const match = coordsText.match(/X:(-?\d+)\s+Y:(-?\d+)\s+Z:(-?\d+)/);
  if (!match) {
    showNotification('Click the map first to select coordinates', 'warning');
    return;
  }

  const x = parseInt(match[1]);
  const z = parseInt(match[3]);

  if (!blockId) {
    showNotification('Enter a block ID', 'warning');
    return;
  }

  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/msmceditor/block`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dim: _msmcDimension, x, y, z, block: blockId })
    });

    if (data.error) {
      showNotification(data.error, 'error');
    } else {
      showNotification(`Block set: ${data.block}`, 'success');
      if (_msmcTileLayer) _msmcTileLayer.redraw();
    }
  } catch (err) {
    showNotification('Failed to set block: ' + (err.message || err), 'error');
  }
}

// ==================== Replace ====================

async function msmcReplace() {
  if (!_msmcSession || _msmcSession.readOnly) {
    showNotification('Read-only mode — stop the server to edit', 'warning');
    return;
  }

  const from = document.getElementById('msmceditor-replace-from').value.trim();
  const to = document.getElementById('msmceditor-replace-to').value.trim();
  const x1 = parseInt(document.getElementById('msmceditor-replace-x1').value);
  const y1 = parseInt(document.getElementById('msmceditor-replace-y1').value);
  const z1 = parseInt(document.getElementById('msmceditor-replace-z1').value);
  const x2 = parseInt(document.getElementById('msmceditor-replace-x2').value);
  const y2 = parseInt(document.getElementById('msmceditor-replace-y2').value);
  const z2 = parseInt(document.getElementById('msmceditor-replace-z2').value);
  const dryRun = document.getElementById('msmceditor-replace-dryrun').checked;

  if (!from || !to) {
    showNotification('Enter both block IDs', 'warning');
    return;
  }
  if ([x1, y1, z1, x2, y2, z2].some(isNaN)) {
    showNotification('Enter all bounding box coordinates', 'warning');
    return;
  }

  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/msmceditor/replace`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dim: _msmcDimension,
        box: { x1, y1, z1, x2, y2, z2 },
        from: from,
        to: to,
        dryRun
      })
    });

    if (data.error) {
      showNotification(data.error, 'error');
    } else {
      showNotification(`Replace task started (${data.taskId})`, 'success');
    }
  } catch (err) {
    showNotification('Failed to start replace: ' + (err.message || err), 'error');
  }
}

// ==================== Level.dat ====================

async function msmcLoadLevelDat() {
  if (!_msmcSession || !currentServerId) return;

  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/msmceditor/levelinfo`);
    const form = document.getElementById('msmceditor-leveldat-form');
    if (!data || data.error) {
      form.innerHTML = '<p class="msmceditor-hint">Could not load level.dat</p>';
      return;
    }

    let html = '';
    const fields = [
      { key: 'levelName', label: 'Level Name', type: 'text' },
      { key: 'seed', label: 'Seed', type: 'text' },
      { key: 'spawnX', label: 'Spawn X', type: 'number' },
      { key: 'spawnY', label: 'Spawn Y', type: 'number' },
      { key: 'spawnZ', label: 'Spawn Z', type: 'number' },
      { key: 'dayTime', label: 'Day Time', type: 'number' },
      { key: 'difficulty', label: 'Difficulty (0-3)', type: 'number' },
      { key: 'hardcore', label: 'Hardcore', type: 'checkbox' },
      { key: 'raining', label: 'Raining', type: 'checkbox' },
      { key: 'thundering', label: 'Thundering', type: 'checkbox' },
    ];

    fields.forEach(f => {
      const val = data[f.key];
      if (val === undefined && f.type !== 'checkbox') return;
      if (f.type === 'checkbox') {
        html += `<div class="form-group"><label class="msmceditor-checkbox"><input type="checkbox" id="msmceditor-ld-${f.key}" ${val ? 'checked' : ''}> ${f.label}</label></div>`;
      } else {
        html += `<div class="form-group"><label>${f.label}</label><input type="${f.type}" class="form-control" id="msmceditor-ld-${f.key}" value="${escapeHtml(String(val || ''))}"></div>`;
      }
    });

    // Game rules
    if (data.gameRules) {
      html += '<h6 style="margin-top:12px;">Game Rules</h6>';
      Object.entries(data.gameRules).forEach(([k, v]) => {
        html += `<div class="form-group form-group-inline"><label>${k}</label><input type="text" class="form-control" id="msmceditor-gr-${k}" value="${escapeHtml(v)}"></div>`;
      });
    }

    form.innerHTML = html;
  } catch (err) {
    showNotification('Failed to load level.dat: ' + (err.message || err), 'error');
  }
}

async function msmcSaveLevelDat() {
  if (!_msmcSession || _msmcSession.readOnly) {
    showNotification('Read-only mode', 'warning');
    return;
  }

  const updates = {};
  const fields = ['levelName', 'seed', 'spawnX', 'spawnY', 'spawnZ', 'dayTime', 'difficulty', 'hardcore', 'raining', 'thundering'];

  fields.forEach(key => {
    const el = document.getElementById(`msmceditor-ld-${key}`);
    if (!el) return;
    if (el.type === 'checkbox') {
      updates[key] = el.checked;
    } else if (el.type === 'number') {
      updates[key] = parseInt(el.value) || 0;
    } else {
      updates[key] = el.value;
    }
  });

  // Game rules
  const grInputs = document.querySelectorAll('[id^="msmceditor-gr-"]');
  if (grInputs.length > 0) {
    updates.gameRules = {};
    grInputs.forEach(el => {
      const ruleKey = el.id.replace('msmceditor-gr-', '');
      updates.gameRules[ruleKey] = el.value;
    });
  }

  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/msmceditor/levelinfo`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    });
    if (data.success) {
      showNotification('Level.dat saved', 'success');
    } else {
      showNotification(data.error || 'Failed to save', 'error');
    }
  } catch (err) {
    showNotification('Failed to save level.dat: ' + (err.message || err), 'error');
  }
}

// ==================== Players ====================

async function msmcLoadPlayers() {
  if (!_msmcSession || !currentServerId) return;

  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/msmceditor/players`);
    const listEl = document.getElementById('msmceditor-players-list');
    if (!data.players || data.players.length === 0) {
      listEl.innerHTML = '<p class="msmceditor-hint">No player data found</p>';
      return;
    }

    let html = '<ul class="msmceditor-player-list">';
    data.players.forEach(p => {
      html += `<li><a href="#" onclick="msmcLoadPlayer('${escapeHtml(p.uuid)}'); return false;">${escapeHtml(p.uuid)}</a></li>`;
    });
    html += '</ul>';
    listEl.innerHTML = html;
  } catch (err) {
    showNotification('Failed to load players', 'error');
  }
}

async function msmcLoadPlayer(uuid) {
  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/msmceditor/player/${uuid}`);
    const detailEl = document.getElementById('msmceditor-player-detail');
    if (!data || data.error) {
      detailEl.innerHTML = `<p class="msmceditor-hint">${data.error || 'Not found'}</p>`;
      detailEl.style.display = '';
      return;
    }

    let html = `<h6>${uuid}</h6>`;
    if (data.position) {
      html += `<div class="form-group"><label>Position</label><div>X:${data.position.x.toFixed(1)} Y:${data.position.y.toFixed(1)} Z:${data.position.z.toFixed(1)}</div></div>`;
    }
    if (data.gamemode !== undefined) {
      html += `<div class="form-group"><label>Gamemode</label><select id="msmceditor-player-gm" class="form-control"><option value="0" ${data.gamemode === 0 ? 'selected' : ''}>Survival</option><option value="1" ${data.gamemode === 1 ? 'selected' : ''}>Creative</option><option value="2" ${data.gamemode === 2 ? 'selected' : ''}>Adventure</option><option value="3" ${data.gamemode === 3 ? 'selected' : ''}>Spectator</option></select></div>`;
    }
    if (data.health !== undefined) {
      html += `<div class="form-group"><label>Health</label><input type="number" id="msmceditor-player-health" class="form-control" value="${data.health}" step="0.5"></div>`;
    }
    if (data.food !== undefined) {
      html += `<div class="form-group"><label>Food</label><input type="number" id="msmceditor-player-food" class="form-control" value="${data.food}"></div>`;
    }

    if (!_msmcSession.readOnly) {
      html += `<button class="btn btn-primary" onclick="msmcSavePlayer('${escapeHtml(uuid)}')" style="width:100%;margin-top:8px;">Save Player</button>`;
    }

    detailEl.innerHTML = html;
    detailEl.style.display = '';
  } catch (err) {
    showNotification('Failed to load player', 'error');
  }
}

async function msmcSavePlayer(uuid) {
  if (!_msmcSession || _msmcSession.readOnly) return;

  const updates = {};
  const gmEl = document.getElementById('msmceditor-player-gm');
  if (gmEl) updates.gamemode = parseInt(gmEl.value);
  const healthEl = document.getElementById('msmceditor-player-health');
  if (healthEl) updates.health = parseFloat(healthEl.value);
  const foodEl = document.getElementById('msmceditor-player-food');
  if (foodEl) updates.food = parseInt(foodEl.value);

  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/msmceditor/player/${uuid}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    });
    if (data.success) {
      showNotification('Player saved', 'success');
    } else {
      showNotification(data.error || 'Failed', 'error');
    }
  } catch (err) {
    showNotification('Failed to save player', 'error');
  }
}

// ==================== Chunks ====================

async function msmcDeleteChunks() {
  if (!_msmcSession || _msmcSession.readOnly) {
    showNotification('Read-only mode', 'warning');
    return;
  }

  const coords = _msmcGetChunkRange();
  if (!coords) return;

  if (!confirm(`Delete ${coords.length} chunks? This cannot be undone without the auto-backup.`)) return;

  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/msmceditor/chunk/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dim: _msmcDimension, coords })
    });
    if (data.error) {
      showNotification(data.error, 'error');
    } else {
      showNotification(`Chunk delete task started (${data.taskId})`, 'success');
    }
  } catch (err) {
    showNotification('Failed: ' + (err.message || err), 'error');
  }
}

async function msmcPruneChunks() {
  if (!_msmcSession || _msmcSession.readOnly) {
    showNotification('Read-only mode', 'warning');
    return;
  }

  const cx1 = parseInt(document.getElementById('msmceditor-chunk-x1').value);
  const cz1 = parseInt(document.getElementById('msmceditor-chunk-z1').value);
  const cx2 = parseInt(document.getElementById('msmceditor-chunk-x2').value);
  const cz2 = parseInt(document.getElementById('msmceditor-chunk-z2').value);

  if ([cx1, cz1, cx2, cz2].some(isNaN)) {
    showNotification('Enter chunk coordinates', 'warning');
    return;
  }

  if (!confirm('Prune will DELETE all chunks OUTSIDE the selected range. Continue?')) return;

  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/msmceditor/chunk/prune`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dim: _msmcDimension, keepBox: { x1: cx1, z1: cz1, x2: cx2, z2: cz2 } })
    });
    if (data.error) {
      showNotification(data.error, 'error');
    } else {
      showNotification(`Prune task started (${data.taskId})`, 'success');
    }
  } catch (err) {
    showNotification('Failed: ' + (err.message || err), 'error');
  }
}

function _msmcGetChunkRange() {
  const cx1 = parseInt(document.getElementById('msmceditor-chunk-x1').value);
  const cz1 = parseInt(document.getElementById('msmceditor-chunk-z1').value);
  const cx2 = parseInt(document.getElementById('msmceditor-chunk-x2').value);
  const cz2 = parseInt(document.getElementById('msmceditor-chunk-z2').value);

  if ([cx1, cz1, cx2, cz2].some(isNaN)) {
    showNotification('Enter chunk coordinates', 'warning');
    return null;
  }

  const coords = [];
  for (let cx = Math.min(cx1, cx2); cx <= Math.max(cx1, cx2); cx++) {
    for (let cz = Math.min(cz1, cz2); cz <= Math.max(cz1, cz2); cz++) {
      coords.push([cx, cz]);
    }
  }
  return coords;
}

// ==================== Save ====================

async function msmcSave() {
  if (!_msmcSession || _msmcSession.readOnly) {
    showNotification('Read-only mode', 'warning');
    return;
  }

  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/msmceditor/save`, { method: 'POST' });
    if (data.success) {
      showNotification(data.message || 'World saved', 'success');
    } else {
      showNotification(data.error || 'Save failed', 'error');
    }
  } catch (err) {
    showNotification('Save failed: ' + (err.message || err), 'error');
  }
}

// ==================== Tasks ====================

function _msmcRenderTasks() {
  const container = document.getElementById('msmceditor-tasks-list');
  const activeTasks = Object.values(_msmcTasks).filter(t => t.done < t.total);

  if (activeTasks.length === 0) {
    container.innerHTML = '<p class="msmceditor-hint">No active tasks</p>';
    return;
  }

  let html = '';
  activeTasks.forEach(t => {
    const pct = t.total > 0 ? Math.round((t.done / t.total) * 100) : 0;
    html += `<div class="msmceditor-task">
      <div class="msmceditor-task-label">${escapeHtml(t.label || 'Working...')}</div>
      <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
      <button class="btn btn-small btn-danger" onclick="msmcCancelTask('${t.taskId}')">Cancel</button>
    </div>`;
  });
  container.innerHTML = html;
}

async function msmcCancelTask(taskId) {
  try {
    await apiRequest(`/api/servers/${currentServerId}/msmceditor/cancel/${taskId}`, { method: 'POST' });
    showNotification('Task cancelled', 'success');
  } catch (err) {
    showNotification('Failed to cancel', 'error');
  }
}
