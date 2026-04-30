/**
 * MSMCeditor — Three.js 3D world viewer.
 *
 * Exposes a singleton `window.MSMC3D` controller with:
 *   init(canvas)               — set up scene, camera, renderer, controls
 *   loadChunks(chunks, palette) — replace currently-loaded chunks
 *   updateChunks(chunks, palette) — patch a subset of chunks (after edits)
 *   setRenderDistance(n)        — change radius (4..16)
 *   setFov(deg)                 — change camera FOV
 *   setShowGrid(bool)
 *   setShowHelpers(bool)
 *   onPick(handler)             — handler(blockInfo) when user clicks
 *   getCameraChunk()            — {cx, cz} of camera position
 *   dispose()
 *
 * Chunk data format (from server):
 *   {cx, cz, sections: [{y, palette: [{name, properties}], indices: [4096 ints]}]}
 *
 * Greedy meshing is used per chunk-section to keep triangle count low.
 * Each mesh uses vertex colors derived from the block palette JSON.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const SECTION_SIZE = 16;
const FACE_DIRS = [
  // [dx, dy, dz, nx, ny, nz, face-id]
  [ 1,  0,  0,  1,  0,  0, 'east'],
  [-1,  0,  0, -1,  0,  0, 'west'],
  [ 0,  1,  0,  0,  1,  0, 'top'],
  [ 0, -1,  0,  0, -1,  0, 'bottom'],
  [ 0,  0,  1,  0,  0,  1, 'south'],
  [ 0,  0, -1,  0,  0, -1, 'north'],
];

const AIR_NAMES = new Set([
  'minecraft:air',
  'minecraft:cave_air',
  'minecraft:void_air',
]);

function isAir(name) { return AIR_NAMES.has(name); }

function colorForBlock(name, palette) {
  const c = palette[name];
  if (c) {
    return [c[0] / 255, c[1] / 255, c[2] / 255, (c[3] !== undefined ? c[3] : 255) / 255];
  }
  // Hash name to a stable pastel colour so unknown blocks are still distinguishable
  let h = 0;
  for (let i = 0; i < name.length; i++) h = ((h << 5) - h + name.charCodeAt(i)) | 0;
  const hue = Math.abs(h) % 360;
  const c2 = new THREE.Color().setHSL(hue / 360, 0.45, 0.55);
  return [c2.r, c2.g, c2.b, 1];
}

class MSMC3DController {
  constructor() {
    this.canvas = null;
    this.renderer = null;
    this.scene = null;
    this.camera = null;
    this.controls = null;
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this._pickHandler = null;
    this._chunkMeshes = new Map(); // key 'cx,cz' -> THREE.Group
    this._gridHelper = null;
    this._axesHelper = null;
    this._showGrid = true;
    this._showHelpers = true;
    this._renderDistance = 8;
    this._animating = false;
    this._lastPalette = {};
    this._lastChunks = new Map();
    this._coordsEl = null;
    this._keyState = {};
  }

  init(canvas) {
    if (this.renderer) return;
    this.canvas = canvas;
    this._coordsEl = document.getElementById('msmceditor-coords');

    const w = canvas.clientWidth || 800;
    const h = canvas.clientHeight || 600;

    this.renderer = new THREE.WebGLRenderer({
      canvas, antialias: true, alpha: false,
    });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.setSize(w, h, false);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x1a2540);
    this.scene.fog = new THREE.Fog(0x1a2540, 80, 280);

    this.camera = new THREE.PerspectiveCamera(75, w / h, 0.1, 2000);
    this.camera.position.set(40, 100, 40);
    this.camera.lookAt(0, 64, 0);

    // Lights
    const ambient = new THREE.AmbientLight(0xffffff, 0.55);
    this.scene.add(ambient);
    const sun = new THREE.DirectionalLight(0xfff4e8, 0.85);
    sun.position.set(60, 120, 40);
    this.scene.add(sun);

    // Helpers
    this._gridHelper = new THREE.GridHelper(256, 16, 0x444466, 0x222244);
    this._gridHelper.position.y = 64;
    this.scene.add(this._gridHelper);
    this._axesHelper = new THREE.AxesHelper(20);
    this._axesHelper.position.set(0, 64, 0);
    this.scene.add(this._axesHelper);

    // Controls
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.target.set(0, 64, 0);
    this.controls.update();

    // Resize observer
    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(() => this._handleResize());
      ro.observe(canvas);
    }
    window.addEventListener('resize', () => this._handleResize());

    // Pointer + keyboard
    canvas.addEventListener('click', (e) => this._handleClick(e));
    canvas.tabIndex = 0;
    canvas.addEventListener('keydown', (e) => { this._keyState[e.code] = true; });
    canvas.addEventListener('keyup', (e) => { this._keyState[e.code] = false; });
    canvas.addEventListener('mousemove', (e) => this._handleMouseMove(e));

    this._animating = true;
    this._animate();
  }

  _handleResize() {
    if (!this.renderer || !this.canvas) return;
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    if (w === 0 || h === 0) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  _animate() {
    if (!this._animating) return;
    requestAnimationFrame(() => this._animate());

    // WASD movement on camera target
    const move = new THREE.Vector3();
    const speed = 0.8;
    if (this._keyState['KeyW'] || this._keyState['ArrowUp'])    move.z -= speed;
    if (this._keyState['KeyS'] || this._keyState['ArrowDown'])  move.z += speed;
    if (this._keyState['KeyA'] || this._keyState['ArrowLeft'])  move.x -= speed;
    if (this._keyState['KeyD'] || this._keyState['ArrowRight']) move.x += speed;
    if (this._keyState['Space'])      move.y += speed;
    if (this._keyState['ShiftLeft'])  move.y -= speed;

    if (move.lengthSq() > 0) {
      // Move along camera forward direction (XZ only for forward/back)
      const fwd = new THREE.Vector3();
      this.camera.getWorldDirection(fwd);
      fwd.y = 0; fwd.normalize();
      const right = new THREE.Vector3().crossVectors(fwd, this.camera.up).normalize();
      const delta = new THREE.Vector3();
      delta.addScaledVector(fwd, -move.z);
      delta.addScaledVector(right, move.x);
      delta.y += move.y;
      this.camera.position.add(delta);
      this.controls.target.add(delta);
    }

    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  _handleMouseMove(event) {
    if (!this._coordsEl) return;
    const rect = this.canvas.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    const hit = this._raycastBlock();
    if (hit) {
      const { x, y, z } = hit.block;
      this._coordsEl.textContent = `X:${x} Y:${y} Z:${z}  ${hit.block.name || ''}`;
    }
  }

  _handleClick(event) {
    if (!this._pickHandler) return;
    const rect = this.canvas.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    const hit = this._raycastBlock();
    if (hit) this._pickHandler(hit.block);
  }

  _raycastBlock() {
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const meshes = [];
    this._chunkMeshes.forEach(g => {
      g.traverse(o => { if (o.isMesh) meshes.push(o); });
    });
    const hits = this.raycaster.intersectObjects(meshes, false);
    if (hits.length === 0) return null;
    const h = hits[0];
    // Step inward along the normal to find the block coords
    const p = h.point.clone().addScaledVector(h.face.normal, -0.5);
    return {
      block: {
        x: Math.floor(p.x),
        y: Math.floor(p.y),
        z: Math.floor(p.z),
        name: h.object.userData.blockNames
          ? h.object.userData.blockNames[Math.floor(p.x)+','+Math.floor(p.y)+','+Math.floor(p.z)]
          : null,
      },
      object: h.object,
    };
  }

  setRenderDistance(n) { this._renderDistance = Math.max(4, Math.min(16, n|0)); }
  setFov(deg) { if (this.camera) { this.camera.fov = deg; this.camera.updateProjectionMatrix(); } }
  setShowGrid(b) { this._showGrid = !!b; if (this._gridHelper) this._gridHelper.visible = !!b; }
  setShowHelpers(b) { this._showHelpers = !!b; if (this._axesHelper) this._axesHelper.visible = !!b; }
  onPick(fn) { this._pickHandler = fn; }

  getCameraChunk() {
    if (!this.camera) return { cx: 0, cz: 0 };
    return {
      cx: Math.floor(this.camera.position.x / 16),
      cz: Math.floor(this.camera.position.z / 16),
    };
  }

  loadChunks(chunks, palette) {
    this._lastPalette = palette || {};
    // Clear all existing
    this._chunkMeshes.forEach(g => this._disposeGroup(g));
    this._chunkMeshes.clear();
    this._lastChunks.clear();

    chunks.forEach(c => this._addOrReplaceChunk(c));
    this._fitToData(chunks);
  }

  updateChunks(chunks, palette) {
    if (palette) this._lastPalette = palette;
    chunks.forEach(c => this._addOrReplaceChunk(c));
  }

  _addOrReplaceChunk(chunkData) {
    const key = `${chunkData.cx},${chunkData.cz}`;
    const old = this._chunkMeshes.get(key);
    if (old) {
      this.scene.remove(old);
      this._disposeGroup(old);
    }
    const group = this._buildChunkGroup(chunkData, this._lastPalette);
    this.scene.add(group);
    this._chunkMeshes.set(key, group);
    this._lastChunks.set(key, chunkData);
  }

  removeChunk(cx, cz) {
    const key = `${cx},${cz}`;
    const g = this._chunkMeshes.get(key);
    if (g) {
      this.scene.remove(g);
      this._disposeGroup(g);
      this._chunkMeshes.delete(key);
      this._lastChunks.delete(key);
    }
  }

  _disposeGroup(g) {
    g.traverse(o => {
      if (o.isMesh) {
        if (o.geometry) o.geometry.dispose();
        if (o.material) o.material.dispose();
      }
    });
  }

  _fitToData(chunks) {
    if (chunks.length === 0) return;
    let cx = 0, cz = 0;
    for (const c of chunks) { cx += c.cx; cz += c.cz; }
    cx = (cx / chunks.length) * 16 + 8;
    cz = (cz / chunks.length) * 16 + 8;
    const r = Math.sqrt(chunks.length) * 16;
    this.camera.position.set(cx + r, 90 + r * 0.3, cz + r);
    this.controls.target.set(cx, 64, cz);
    this.controls.update();
  }

  /**
   * Build a THREE.Group containing one merged BufferGeometry per chunk.
   * Uses simple culled-face meshing: only faces between solid<->non-solid are emitted.
   * Vertex colors from palette.json (or hashed fallback).
   */
  _buildChunkGroup(chunkData, palette) {
    const group = new THREE.Group();
    group.name = `chunk_${chunkData.cx}_${chunkData.cz}`;
    const baseX = chunkData.cx * 16;
    const baseZ = chunkData.cz * 16;

    const positions = [];
    const normals = [];
    const colors = [];
    const indices = [];

    // Build a map from (x,y,z) within chunk -> {name, color} for the whole chunk
    // Sections are 16-tall, indexed by y in absolute world coords
    const blockMap = new Map();
    for (const sec of chunkData.sections) {
      const sy = sec.y;
      const pal = sec.palette;
      const idx = sec.indices;
      // Skip sections that are 100% air
      let allAir = true;
      for (let p = 0; p < pal.length; p++) {
        if (!isAir(pal[p].name)) { allAir = false; break; }
      }
      if (allAir) continue;

      for (let ly = 0; ly < 16; ly++) {
        for (let lz = 0; lz < 16; lz++) {
          for (let lx = 0; lx < 16; lx++) {
            const i = ly * 256 + lz * 16 + lx;
            const block = pal[idx[i]];
            if (!block || isAir(block.name)) continue;
            const wy = sy * 16 + ly;
            const key = lx + ',' + wy + ',' + lz;
            blockMap.set(key, block);
          }
        }
      }
    }

    const isSolid = (lx, wy, lz) => blockMap.has(lx + ',' + wy + ',' + lz);

    // Emit faces for visible block sides
    let vertCount = 0;
    const blockNamesForPick = {};
    blockMap.forEach((block, key) => {
      const [lxs, wys, lzs] = key.split(',');
      const lx = +lxs, wy = +wys, lz = +lzs;
      const wx = baseX + lx;
      const wz = baseZ + lz;

      blockNamesForPick[wx + ',' + wy + ',' + wz] = block.name;

      const [r, g, b] = colorForBlock(block.name, palette);

      for (const [dx, dy, dz, nx, ny, nz] of FACE_DIRS) {
        if (isSolid(lx + dx, wy + dy, lz + dz)) continue;
        // Build a unit-square face on the cube
        const fx = wx, fy = wy, fz = wz;
        // Compute 4 corner positions for this face
        const verts = faceVerts(fx, fy, fz, dx, dy, dz);
        for (const v of verts) {
          positions.push(v[0], v[1], v[2]);
          normals.push(nx, ny, nz);
          colors.push(r, g, b);
        }
        indices.push(vertCount, vertCount + 1, vertCount + 2,
                     vertCount, vertCount + 2, vertCount + 3);
        vertCount += 4;
      }
    });

    if (positions.length === 0) return group;

    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geom.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
    geom.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    geom.setIndex(indices);
    geom.computeBoundingSphere();

    const mat = new THREE.MeshLambertMaterial({
      vertexColors: true,
      side: THREE.FrontSide,
    });
    const mesh = new THREE.Mesh(geom, mat);
    mesh.userData.blockNames = blockNamesForPick;
    mesh.userData.cx = chunkData.cx;
    mesh.userData.cz = chunkData.cz;
    group.add(mesh);
    return group;
  }

  dispose() {
    this._animating = false;
    this._chunkMeshes.forEach(g => this._disposeGroup(g));
    this._chunkMeshes.clear();
    if (this.renderer) {
      this.renderer.dispose();
      this.renderer = null;
    }
    this.scene = null;
    this.camera = null;
    this.controls = null;
  }
}

/** Return the 4 vertices for a unit cube face at (x,y,z) facing (dx,dy,dz). */
function faceVerts(x, y, z, dx, dy, dz) {
  // Block occupies [x..x+1] x [y..y+1] x [z..z+1]
  if (dx === 1)  return [[x+1, y,   z], [x+1, y+1, z], [x+1, y+1, z+1], [x+1, y,   z+1]];
  if (dx === -1) return [[x,   y,   z+1], [x,   y+1, z+1], [x,   y+1, z], [x,   y,   z]];
  if (dy === 1)  return [[x,   y+1, z+1], [x+1, y+1, z+1], [x+1, y+1, z], [x,   y+1, z]];
  if (dy === -1) return [[x,   y,   z], [x+1, y,   z], [x+1, y,   z+1], [x,   y,   z+1]];
  if (dz === 1)  return [[x+1, y,   z+1], [x+1, y+1, z+1], [x,   y+1, z+1], [x,   y,   z+1]];
  if (dz === -1) return [[x,   y,   z], [x,   y+1, z], [x+1, y+1, z], [x+1, y,   z]];
  return [];
}

window.MSMC3D = new MSMC3DController();
