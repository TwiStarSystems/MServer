/**
 * MSMCeditor — World Editor Frontend Controller (Three.js 3D viewer).
 *
 * Wires the MSMCeditor tab UI to:
 *   - the backend /api/servers/<id>/msmceditor/* endpoints
 *   - window.MSMC3D (msmceditor-3d.js) for the 3D viewer
 *
 * Globals consumed: currentServerId, socket, apiRequest(), showNotification()
 */

// ==================== State ====================
let _msmcSession = null;          // {platform, version, dimensions, readOnly}
let _msmcDimension = 'minecraft:overworld';
let _msmcInitialized = false;
let _msmcTasks = {};              // taskId -> {done, total, label}
let _msmcLastInspect = null;      // {x, y, z, name, properties}
let _msmcPalette = {};            // block name -> [r,g,b,a]
let _msmcLoadedChunkKeys = new Set();
let _msmcSettings = _msmcLoadSettings();

// ==================== Settings ====================

function _msmcDefaultSettings() {
  return { renderDistance: 8, fov: 75, showGrid: true, showHelpers: true };
}

function _msmcLoadSettings() {
  try {
    const raw = localStorage.getItem('msmceditor.settings');
    if (raw) return Object.assign(_msmcDefaultSettings(), JSON.parse(raw));
  } catch (e) { /* ignore */ }
  return _msmcDefaultSettings();
}

function _msmcSaveSettings() {
  try { localStorage.setItem('msmceditor.settings', JSON.stringify(_msmcSettings)); }
  catch (e) { /* ignore */ }
}

function msmcResetSettings() {
  _msmcSettings = _msmcDefaultSettings();
  _msmcSaveSettings();
  _msmcApplySettingsToUI();
  _msmcApplySettingsToViewer();
}

function _msmcApplySettingsToUI() {
  const rd = document.getElementById('msmceditor-setting-render-distance');
  const rdv = document.getElementById('msmceditor-setting-render-distance-val');
  const fv = document.getElementById('msmceditor-setting-fov');
  const fvv = document.getElementById('msmceditor-setting-fov-val');
  const sg = document.getElementById('msmceditor-setting-show-grid');
  const sh = document.getElementById('msmceditor-setting-show-helpers');
  if (rd)  { rd.value = _msmcSettings.renderDistance; }
  if (rdv) { rdv.textContent = _msmcSettings.renderDistance; }
  if (fv)  { fv.value = _msmcSettings.fov; }
  if (fvv) { fvv.textContent = _msmcSettings.fov; }
  if (sg)  { sg.checked = !!_msmcSettings.showGrid; }
  if (sh)  { sh.checked = !!_msmcSettings.showHelpers; }
}

function _msmcApplySettingsToViewer() {
  if (!window.MSMC3D) return;
  MSMC3D.setRenderDistance(_msmcSettings.renderDistance);
  MSMC3D.setFov(_msmcSettings.fov);
  MSMC3D.setShowGrid(_msmcSettings.showGrid);
  MSMC3D.setShowHelpers(_msmcSettings.showHelpers);
}

// ==================== Initialization ====================

function initMSMCEditor() {
  if (!currentServerId) return;
  msmcLoadWorlds();

  document.querySelectorAll('.msmceditor-dim-btn').forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll('.msmceditor-dim-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _msmcDimension = btn.dataset.dim;
      msmcRefreshViewer();
    };
  });

  document.querySelectorAll('.msmceditor-panel-tab').forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll('.msmceditor-panel-tab').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.msmceditor-panel-content').forEach(c => c.classList.remove('active'));
      btn.classList.add('active');
      const target = document.getElementById('msmceditor-panel-' + btn.dataset.panel);
      if (target) target.classList.add('active');
      if (btn.dataset.panel === 'leveldat') msmcLoadLevelDat();
      if (btn.dataset.panel === 'players')  msmcLoadPlayers();
    };
  });

  // Init 3D viewer once
  const canvas = document.getElementById('msmceditor-canvas');
  if (canvas && window.MSMC3D && !_msmcInitialized) {
    MSMC3D.init(canvas);
    MSMC3D.onPick(_msmcOnBlockPicked);
    _msmcInitialized = true;
  }
  _msmcApplySettingsToUI();
  _msmcApplySettingsToViewer();
  _msmcWireSettingInputs();
  _msmcWireKeyboard();
  _msmcInitSocketListeners();
}

function _msmcWireSettingInputs() {
  const rd = document.getElementById('msmceditor-setting-render-distance');
  const fv = document.getElementById('msmceditor-setting-fov');
  const sg = document.getElementById('msmceditor-setting-show-grid');
  const sh = document.getElementById('msmceditor-setting-show-helpers');
  if (rd && !rd.dataset.wired) {
    rd.addEventListener('input', () => {
      _msmcSettings.renderDistance = +rd.value;
      document.getElementById('msmceditor-setting-render-distance-val').textContent = rd.value;
    });
    rd.addEventListener('change', () => {
      _msmcSaveSettings();
      _msmcApplySettingsToViewer();
      msmcRefreshViewer();
    });
    rd.dataset.wired = '1';
  }
  if (fv && !fv.dataset.wired) {
    fv.addEventListener('input', () => {
      _msmcSettings.fov = +fv.value;
      document.getElementById('msmceditor-setting-fov-val').textContent = fv.value;
      _msmcApplySettingsToViewer();
    });
    fv.addEventListener('change', _msmcSaveSettings);
    fv.dataset.wired = '1';
  }
  if (sg && !sg.dataset.wired) {
    sg.addEventListener('change', () => {
      _msmcSettings.showGrid = sg.checked;
      _msmcSaveSettings();
      _msmcApplySettingsToViewer();
    });
    sg.dataset.wired = '1';
  }
  if (sh && !sh.dataset.wired) {
    sh.addEventListener('change', () => {
      _msmcSettings.showHelpers = sh.checked;
      _msmcSaveSettings();
      _msmcApplySettingsToViewer();
    });
    sh.dataset.wired = '1';
  }
}

function _msmcWireKeyboard() {
  if (window._msmcKeysWired) return;
  window._msmcKeysWired = true;
  document.addEventListener('keydown', (e) => {
    // Only act when MSMCeditor tab is visible
    const tab = document.getElementById('msmceditor-tab');
    if (!tab || !tab.classList.contains('active')) return;
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) {
      e.preventDefault(); msmcUndo();
    } else if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) {
      e.preventDefault(); msmcRedo();
    }
  });
}

function _msmcInitSocketListeners() {
  if (typeof socket === 'undefined' || !socket) return;
  if (socket._msmcWired) return;
  socket._msmcWired = true;
  socket.on('msmceditor:progress', (data) => {
    _msmcTasks[data.taskId] = data;
    _msmcRenderTasks();
  });
  socket.on('msmceditor:chunks-changed', (data) => {
    if (!_msmcSession || data.dim !== _msmcDimension) return;
    msmcReloadChunks(data.chunks || []);
  });
  socket.on('msmceditor:error', (data) => {
    showNotification(data.message || 'Editor error', 'error');
  });
}

// ==================== World / session ====================

async function msmcLoadWorlds() {
  if (!currentServerId) return;
  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/msmceditor/worlds`);
    const select = document.getElementById('msmceditor-world-select');
    select.innerHTML = '<option value="">— Select World —</option>';
    (data.worlds || []).forEach(w => {
      const opt = document.createElement('option');
      opt.value = w.path;
      opt.textContent = `${w.name} (${w.platform})`;
      select.appendChild(opt);
    });
    if (data.session) {
      _msmcSession = data.session;
      _msmcShowSessionUI(true);
      await _msmcLoadPalette();
      msmcRefreshViewer();
    }
  } catch (err) {
    if (err && err.message && err.message.includes('not installed')) {
      showNotification('World Editor dependencies not installed', 'error');
    }
  }
}

async function msmcOpenSession() {
  const select = document.getElementById('msmceditor-world-select');
  const worldPath = select.value;
  if (!worldPath) { showNotification('Select a world first', 'warning'); return; }
  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/msmceditor/open`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ worldPath })
    });
    if (data.error) { showNotification(data.error, 'error'); return; }
    _msmcSession = data;
    _msmcShowSessionUI(true);
    await _msmcLoadPalette();
    msmcRefreshViewer();
    showNotification('World opened', 'success');
  } catch (err) { showNotification('Open failed: ' + (err.message||err), 'error'); }
}

async function msmcCloseSession() {
  if (!currentServerId) return;
  try {
    await apiRequest(`/api/servers/${currentServerId}/msmceditor/close`, { method: 'POST' });
    _msmcSession = null;
    _msmcLoadedChunkKeys.clear();
    if (window.MSMC3D) MSMC3D.loadChunks([], _msmcPalette);
    _msmcShowSessionUI(false);
  } catch (err) { showNotification('Close failed', 'error'); }
}

function _msmcShowSessionUI(open) {
  const closeBtn = document.getElementById('msmceditor-close-btn');
  const openBtn = document.getElementById('msmceditor-open-btn');
  const status = document.getElementById('msmceditor-session-status');
  const saveCtl = document.querySelector('.msmceditor-save-controls');
  const ro = document.getElementById('msmceditor-readonly-banner');
  if (open && _msmcSession) {
    if (openBtn)  openBtn.style.display = 'none';
    if (closeBtn) closeBtn.style.display = '';
    if (status)   { status.style.display = ''; status.textContent =
      `${_msmcSession.platform} • ${_msmcSession.version || '?'}`; }
    if (saveCtl)  saveCtl.style.display = '';
    if (ro)       ro.style.display = _msmcSession.readOnly ? '' : 'none';
    _msmcUpdateUndoButtons();
  } else {
    if (openBtn)  openBtn.style.display = '';
    if (closeBtn) closeBtn.style.display = 'none';
    if (status)   status.style.display = 'none';
    if (saveCtl)  saveCtl.style.display = 'none';
    if (ro)       ro.style.display = 'none';
  }
}

// ==================== Viewer ====================

async function _msmcLoadPalette() {
  try {
    const data = await apiRequest('/api/msmceditor/palette');
    if (data && typeof data === 'object') _msmcPalette = data;
  } catch (e) { _msmcPalette = {}; }
}

async function msmcRefreshViewer() {
  if (!_msmcSession || !currentServerId || !window.MSMC3D) return;
  const cam = MSMC3D.getCameraChunk();
  const r = _msmcSettings.renderDistance;
  try {
    const data = await apiRequest(
      `/api/servers/${currentServerId}/msmceditor/chunks?dim=${encodeURIComponent(_msmcDimension)}&cx=${cam.cx}&cz=${cam.cz}&radius=${r}`
    );
    MSMC3D.loadChunks(data.chunks || [], _msmcPalette);
    _msmcLoadedChunkKeys = new Set((data.chunks || []).map(c => `${c.cx},${c.cz}`));
  } catch (err) {
    showNotification('Failed to load chunks: ' + (err.message || err), 'error');
  }
}

async function msmcReloadChunks(chunkCoords) {
  if (!_msmcSession || !window.MSMC3D || chunkCoords.length === 0) return;
  const reloaded = [];
  for (const [cx, cz] of chunkCoords) {
    try {
      const d = await apiRequest(
        `/api/servers/${currentServerId}/msmceditor/chunk/${encodeURIComponent(_msmcDimension)}/${cx}/${cz}`
      );
      if (d && d.cx !== undefined) reloaded.push(d);
      else MSMC3D.removeChunk(cx, cz);
    } catch (e) { MSMC3D.removeChunk(cx, cz); }
  }
  if (reloaded.length) MSMC3D.updateChunks(reloaded, _msmcPalette);
}

function _msmcOnBlockPicked(block) {
  _msmcLastInspect = block;
  msmcInspectBlock(block.x, block.y, block.z);
}

// ==================== Block inspector ====================

async function msmcInspectBlock(x, y, z) {
  if (!_msmcSession) return;
  try {
    const info = await apiRequest(
      `/api/servers/${currentServerId}/msmceditor/block?x=${x}&y=${y}&z=${z}&dim=${encodeURIComponent(_msmcDimension)}`
    );
    if (info.error) { showNotification(info.error, 'error'); return; }
    document.getElementById('msmceditor-block-info').style.display = '';
    document.getElementById('msmceditor-block-coords').textContent = `X:${x} Y:${y} Z:${z}`;
    document.getElementById('msmceditor-block-id').textContent = info.block;
    document.getElementById('msmceditor-block-props').textContent =
      JSON.stringify(info.properties || {}, null, 2);
    document.getElementById('msmceditor-block-nbt').textContent = info.blockEntity || '(none)';
    if (!_msmcSession.readOnly) {
      document.getElementById('msmceditor-block-edit').style.display = '';
      document.getElementById('msmceditor-set-block-y').value = y;
    }
    _msmcLastInspect = { x, y, z, name: info.block };
  } catch (err) { showNotification('Inspect failed', 'error'); }
}

async function msmcSetBlock() {
  if (!_msmcSession || _msmcSession.readOnly) {
    showNotification('Read-only — stop the server first', 'warning'); return;
  }
  const blockId = document.getElementById('msmceditor-set-block-id').value.trim();
  if (!blockId) { showNotification('Enter a block ID', 'warning'); return; }
  if (!_msmcLastInspect) { showNotification('Click a block first', 'warning'); return; }
  const y = parseInt(document.getElementById('msmceditor-set-block-y').value, 10) || _msmcLastInspect.y;
  try {
    const r = await apiRequest(`/api/servers/${currentServerId}/msmceditor/block`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        x: _msmcLastInspect.x, y, z: _msmcLastInspect.z,
        dim: _msmcDimension, block: blockId,
      })
    });
    if (r.error) { showNotification(r.error, 'error'); return; }
    showNotification('Block set', 'success');
    _msmcUpdateUndoButtons();
    if (r.chunk) msmcReloadChunks([r.chunk]);
  } catch (err) { showNotification('Set block failed', 'error'); }
}

// ==================== Replace ====================

async function msmcReplace() {
  if (!_msmcSession || _msmcSession.readOnly) {
    showNotification('Read-only — stop the server first', 'warning'); return;
  }
  const from = document.getElementById('msmceditor-replace-from').value.trim();
  const to = document.getElementById('msmceditor-replace-to').value.trim();
  const box = _msmcReadBox('replace');
  if (!from || !to) { showNotification('Enter both block IDs', 'warning'); return; }
  if (!box) return;
  const dryRun = document.getElementById('msmceditor-replace-dryrun').checked;
  try {
    const r = await apiRequest(`/api/servers/${currentServerId}/msmceditor/replace`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dim: _msmcDimension, box, from, to, dryRun })
    });
    if (r.error) { showNotification(r.error, 'error'); return; }
    showNotification('Replace started (taskId: ' + r.taskId + ')', 'info');
  } catch (err) { showNotification('Replace failed', 'error'); }
}

// ==================== Fill ====================

async function msmcFill() {
  if (!_msmcSession || _msmcSession.readOnly) {
    showNotification('Read-only — stop the server first', 'warning'); return;
  }
  const block = document.getElementById('msmceditor-fill-block').value.trim();
  const box = _msmcReadBox('fill');
  if (!block) { showNotification('Enter a block ID', 'warning'); return; }
  if (!box) return;
  try {
    const r = await apiRequest(`/api/servers/${currentServerId}/msmceditor/fill`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dim: _msmcDimension, box, block })
    });
    if (r.error) { showNotification(r.error, 'error'); return; }
    showNotification('Fill started', 'info');
  } catch (err) { showNotification('Fill failed', 'error'); }
}

function _msmcReadBox(prefix) {
  const ids = ['x1','y1','z1','x2','y2','z2'];
  const out = {};
  for (const k of ids) {
    const el = document.getElementById(`msmceditor-${prefix}-${k}`);
    const v = parseInt(el && el.value, 10);
    if (Number.isNaN(v)) { showNotification('Fill in all coords', 'warning'); return null; }
    out[k] = v;
  }
  return out;
}

// ==================== Undo / Redo ====================

async function msmcUndo() {
  if (!_msmcSession || _msmcSession.readOnly) return;
  try {
    const r = await apiRequest(`/api/servers/${currentServerId}/msmceditor/undo`, { method: 'POST' });
    if (r.error) { showNotification(r.error, 'warning'); return; }
    showNotification('Undid: ' + r.label, 'info');
    _msmcUpdateUndoButtons(r);
    if (r.chunks && r.chunks.length) msmcReloadChunks(r.chunks);
  } catch (err) { /* ignore */ }
}

async function msmcRedo() {
  if (!_msmcSession || _msmcSession.readOnly) return;
  try {
    const r = await apiRequest(`/api/servers/${currentServerId}/msmceditor/redo`, { method: 'POST' });
    if (r.error) { showNotification(r.error, 'warning'); return; }
    showNotification('Redid: ' + r.label, 'info');
    _msmcUpdateUndoButtons(r);
    if (r.chunks && r.chunks.length) msmcReloadChunks(r.chunks);
  } catch (err) { /* ignore */ }
}

async function _msmcUpdateUndoButtons(hint) {
  const u = document.getElementById('msmceditor-undo-btn');
  const r = document.getElementById('msmceditor-redo-btn');
  if (!u || !r) return;
  let canU = hint && hint.canUndo !== undefined ? hint.canUndo : null;
  let canR = hint && hint.canRedo !== undefined ? hint.canRedo : null;
  if (canU === null && _msmcSession) {
    try {
      const h = await apiRequest(`/api/servers/${currentServerId}/msmceditor/history`);
      canU = (h.undo && h.undo.length > 0);
      canR = (h.redo && h.redo.length > 0);
    } catch (e) { canU = false; canR = false; }
  }
  u.disabled = !canU;
  r.disabled = !canR;
}

// ==================== Level.dat ====================

async function msmcLoadLevelDat() {
  if (!_msmcSession) return;
  try {
    const info = await apiRequest(`/api/servers/${currentServerId}/msmceditor/levelinfo`);
    if (info.error) { showNotification(info.error, 'error'); return; }
    const form = document.getElementById('msmceditor-leveldat-form');
    form.innerHTML = '';
    const fields = [
      ['levelName', 'World Name', 'text'],
      ['seed', 'Seed', 'number'],
      ['spawnX', 'Spawn X', 'number'],
      ['spawnY', 'Spawn Y', 'number'],
      ['spawnZ', 'Spawn Z', 'number'],
      ['dayTime', 'Day Time', 'number'],
      ['difficulty', 'Difficulty (0-3)', 'number'],
      ['hardcore', 'Hardcore', 'checkbox'],
      ['raining', 'Raining', 'checkbox'],
      ['thundering', 'Thundering', 'checkbox'],
    ];
    for (const [k, label, type] of fields) {
      const v = info[k];
      const id = `msmceditor-ld-${k}`;
      const wrap = document.createElement('div');
      wrap.className = 'form-group';
      if (type === 'checkbox') {
        wrap.innerHTML = `<label class="msmceditor-checkbox"><input type="checkbox" id="${id}" ${v?'checked':''}> ${label}</label>`;
      } else {
        wrap.innerHTML = `<label>${label}</label><input type="${type}" id="${id}" class="form-control" value="${v ?? ''}">`;
      }
      form.appendChild(wrap);
    }
    if (info.gameRules) {
      const grWrap = document.createElement('div');
      grWrap.className = 'form-group';
      grWrap.innerHTML = '<label>Game Rules</label>';
      for (const [k, v] of Object.entries(info.gameRules)) {
        const r = document.createElement('div');
        r.className = 'msmceditor-gr-row';
        r.innerHTML = `<label>${k}</label><input type="text" id="msmceditor-gr-${k}" class="form-control" value="${v}">`;
        grWrap.appendChild(r);
      }
      form.appendChild(grWrap);
    }
  } catch (err) { showNotification('Load level.dat failed', 'error'); }
}

async function msmcSaveLevelDat() {
  if (!_msmcSession || _msmcSession.readOnly) {
    showNotification('Read-only', 'warning'); return;
  }
  const updates = {};
  const fields = ['levelName','seed','spawnX','spawnY','spawnZ','dayTime','difficulty','hardcore','raining','thundering'];
  for (const k of fields) {
    const el = document.getElementById('msmceditor-ld-' + k);
    if (!el) continue;
    if (el.type === 'checkbox') updates[k] = el.checked;
    else if (el.type === 'number') updates[k] = parseInt(el.value, 10);
    else updates[k] = el.value;
  }
  const grInputs = document.querySelectorAll('[id^="msmceditor-gr-"]');
  if (grInputs.length) {
    updates.gameRules = {};
    grInputs.forEach(el => {
      const k = el.id.replace('msmceditor-gr-', '');
      updates.gameRules[k] = el.value;
    });
  }
  try {
    const r = await apiRequest(`/api/servers/${currentServerId}/msmceditor/levelinfo`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    });
    if (r.success) showNotification('Level.dat saved', 'success');
    else showNotification(r.error || 'Save failed', 'error');
  } catch (err) { showNotification('Save failed', 'error'); }
}

// ==================== Players ====================

async function msmcLoadPlayers() {
  if (!_msmcSession) return;
  try {
    const data = await apiRequest(`/api/servers/${currentServerId}/msmceditor/players`);
    const list = document.getElementById('msmceditor-players-list');
    list.innerHTML = '';
    (data.players || []).forEach(p => {
      const div = document.createElement('div');
      div.className = 'msmceditor-player-row';
      div.innerHTML = `<button class="btn btn-small" onclick="msmcLoadPlayer('${p.uuid}')">${p.uuid}</button>`;
      list.appendChild(div);
    });
  } catch (err) { /* ignore */ }
}

async function msmcLoadPlayer(uuid) {
  try {
    const info = await apiRequest(`/api/servers/${currentServerId}/msmceditor/player/${uuid}`);
    if (info.error) { showNotification(info.error, 'error'); return; }
    const detail = document.getElementById('msmceditor-player-detail');
    detail.style.display = '';
    const pos = info.position || {x:0,y:0,z:0};
    detail.innerHTML = `
      <h5>${uuid}</h5>
      <div class="form-group"><label>Position</label>
        <div>X: ${pos.x.toFixed(1)} Y: ${pos.y.toFixed(1)} Z: ${pos.z.toFixed(1)}</div></div>
      <div class="form-group"><label>Gamemode</label>
        <input type="number" id="msmceditor-player-gm" class="form-control" value="${info.gamemode ?? 0}"></div>
      <div class="form-group"><label>Health</label>
        <input type="number" step="0.1" id="msmceditor-player-health" class="form-control" value="${info.health ?? 20}"></div>
      <div class="form-group"><label>Food</label>
        <input type="number" id="msmceditor-player-food" class="form-control" value="${info.food ?? 20}"></div>
      <button class="btn btn-primary" onclick="msmcSavePlayer('${uuid}')" style="width:100%">Save Player</button>`;
  } catch (err) { /* ignore */ }
}

async function msmcSavePlayer(uuid) {
  if (!_msmcSession || _msmcSession.readOnly) return;
  const updates = {
    gamemode: parseInt(document.getElementById('msmceditor-player-gm').value, 10),
    health: parseFloat(document.getElementById('msmceditor-player-health').value),
    food: parseInt(document.getElementById('msmceditor-player-food').value, 10),
  };
  try {
    const r = await apiRequest(`/api/servers/${currentServerId}/msmceditor/player/${uuid}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    });
    if (r.success) showNotification('Player saved', 'success');
    else showNotification(r.error || 'Save failed', 'error');
  } catch (err) { /* ignore */ }
}

// ==================== Chunks ====================

async function msmcDeleteChunks() {
  if (!_msmcSession || _msmcSession.readOnly) {
    showNotification('Read-only', 'warning'); return;
  }
  const range = _msmcReadChunkRange();
  if (!range) return;
  const coords = [];
  for (let cz = range.z1; cz <= range.z2; cz++)
    for (let cx = range.x1; cx <= range.x2; cx++) coords.push([cx, cz]);
  if (!confirm(`Delete ${coords.length} chunks? Backup is created on next Save.`)) return;
  try {
    const r = await apiRequest(`/api/servers/${currentServerId}/msmceditor/chunk/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dim: _msmcDimension, coords })
    });
    if (r.error) showNotification(r.error, 'error');
    else showNotification('Delete started', 'info');
  } catch (err) { showNotification('Delete failed', 'error'); }
}

async function msmcPruneChunks() {
  if (!_msmcSession || _msmcSession.readOnly) {
    showNotification('Read-only', 'warning'); return;
  }
  const range = _msmcReadChunkRange();
  if (!range) return;
  if (!confirm('Prune will DELETE all chunks OUTSIDE the selected range. Continue?')) return;
  try {
    const r = await apiRequest(`/api/servers/${currentServerId}/msmceditor/chunk/prune`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dim: _msmcDimension, keepBox: { x1: range.x1, z1: range.z1, x2: range.x2, z2: range.z2 } })
    });
    if (r.error) showNotification(r.error, 'error');
    else showNotification('Prune started', 'info');
  } catch (err) { showNotification('Prune failed', 'error'); }
}

function _msmcReadChunkRange() {
  const ids = ['x1','z1','x2','z2'];
  const v = {};
  for (const k of ids) {
    const el = document.getElementById('msmceditor-chunk-' + k);
    const n = parseInt(el && el.value, 10);
    if (Number.isNaN(n)) { showNotification('Fill in all chunk coords', 'warning'); return null; }
    v[k] = n;
  }
  return {
    x1: Math.min(v.x1, v.x2), x2: Math.max(v.x1, v.x2),
    z1: Math.min(v.z1, v.z2), z2: Math.max(v.z1, v.z2),
  };
}

// ==================== Save ====================

async function msmcSave() {
  if (!_msmcSession || _msmcSession.readOnly) {
    showNotification('Read-only', 'warning'); return;
  }
  if (!confirm('Save changes? An auto-backup will be created first.')) return;
  try {
    const r = await apiRequest(`/api/servers/${currentServerId}/msmceditor/save`, { method: 'POST' });
    if (r.success) showNotification(r.message || 'Saved', 'success');
    else showNotification(r.error || 'Save failed', 'error');
  } catch (err) { showNotification('Save failed', 'error'); }
}

// ==================== Tasks ====================

function _msmcRenderTasks() {
  const list = document.getElementById('msmceditor-tasks-list');
  if (!list) return;
  const ids = Object.keys(_msmcTasks);
  if (ids.length === 0) { list.innerHTML = '<p class="msmceditor-hint">No active tasks</p>'; return; }
  list.innerHTML = '';
  for (const id of ids) {
    const t = _msmcTasks[id];
    const pct = t.total ? Math.round((t.done / t.total) * 100) : 0;
    const div = document.createElement('div');
    div.className = 'msmceditor-task';
    div.innerHTML = `
      <div>${t.label || 'Task'}</div>
      <div class="msmceditor-progress"><div class="msmceditor-progress-bar" style="width:${pct}%"></div></div>
      <div>${t.done}/${t.total} (${pct}%)
        <button class="btn btn-small" onclick="msmcCancelTask('${id}')">Cancel</button></div>`;
    list.appendChild(div);
  }
}

async function msmcCancelTask(taskId) {
  try {
    await apiRequest(`/api/servers/${currentServerId}/msmceditor/cancel/${taskId}`, { method: 'POST' });
    delete _msmcTasks[taskId];
    _msmcRenderTasks();
  } catch (err) { /* ignore */ }
}
