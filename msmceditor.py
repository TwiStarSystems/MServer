"""
MSMCeditor - Web-native Minecraft World Editor backend
Provides world editing capabilities for Java (Anvil) and Bedrock (LevelDB) worlds.
"""

import io
import json
import logging
import threading
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from functools import wraps

from PIL import Image
import numpy

log = logging.getLogger(__name__)

# Try importing amulet-core; graceful fallback if not installed
try:
    import amulet
    from amulet.api.level import BaseLevel
    from amulet.api.block import Block
    from amulet.api.errors import ChunkDoesNotExist, ChunkLoadError
    from amulet.api.selection import SelectionBox, SelectionGroup
    import amulet_nbt
    AMULET_AVAILABLE = True
except ImportError:
    AMULET_AVAILABLE = False
    log.warning("amulet-core not installed — MSMCeditor will be unavailable")


# ==================== Configuration ====================

MAX_SESSIONS = 3
SESSION_IDLE_TIMEOUT = 600  # 10 minutes
MAX_TASKS_PER_SERVER = 1

# Default palette (common blocks) - loaded from file or fallback
_palette_cache = None


# ==================== World Session ====================

class WorldSession:
    """Wraps an open amulet level with locking and metadata."""

    def __init__(self, server_id, world_path, level):
        self.server_id = server_id
        self.world_path = Path(world_path)
        self.level = level
        self.opened_at = time.time()
        self.last_used = time.time()
        self.dirty = False
        self.lock = threading.Lock()
        self.platform = level.level_wrapper.platform
        try:
            self.version = level.level_wrapper.version
        except Exception:
            self.version = None
        self.dimensions = list(level.dimensions)

    def touch(self):
        self.last_used = time.time()

    def close(self):
        try:
            self.level.close()
        except Exception as e:
            log.error(f"Error closing level for {self.server_id}: {e}")


class SessionManager:
    """Process-wide registry of open world sessions."""

    def __init__(self):
        self._sessions = {}  # server_id -> WorldSession
        self._lock = threading.Lock()

    def open(self, server_id, world_path):
        """Open a world session. Returns WorldSession or raises."""
        if not AMULET_AVAILABLE:
            raise RuntimeError("MSMCeditor dependencies not installed (amulet-core)")

        with self._lock:
            if server_id in self._sessions:
                session = self._sessions[server_id]
                session.touch()
                return session

            if len(self._sessions) >= MAX_SESSIONS:
                # Evict oldest idle session
                oldest_id = min(self._sessions, key=lambda k: self._sessions[k].last_used)
                self._sessions[oldest_id].close()
                del self._sessions[oldest_id]

            level = amulet.load_level(str(world_path))
            session = WorldSession(server_id, world_path, level)
            self._sessions[server_id] = session
            return session

    def get(self, server_id):
        """Get existing session or None."""
        session = self._sessions.get(server_id)
        if session:
            session.touch()
        return session

    def close(self, server_id):
        """Close and remove a session."""
        with self._lock:
            session = self._sessions.pop(server_id, None)
            if session:
                session.close()
                # Clean tile cache
                cache_dir = session.world_path.parent / '.msmceditor-cache'
                if cache_dir.exists():
                    import shutil
                    shutil.rmtree(cache_dir, ignore_errors=True)

    def close_all(self):
        """Close all sessions (for shutdown)."""
        with self._lock:
            for session in self._sessions.values():
                session.close()
            self._sessions.clear()

    def evict_idle(self):
        """Close sessions that have been idle too long."""
        now = time.time()
        with self._lock:
            to_close = [
                sid for sid, s in self._sessions.items()
                if now - s.last_used > SESSION_IDLE_TIMEOUT
            ]
            for sid in to_close:
                self._sessions[sid].close()
                del self._sessions[sid]
                log.info(f"MSMCeditor: evicted idle session for server {sid}")


# Global session manager
session_manager = SessionManager()


# ==================== Background Tasks ====================

class EditorTask:
    """Represents a background editing task (replace, chunk ops, etc.)."""

    def __init__(self, task_id, server_id, label):
        self.task_id = task_id
        self.server_id = server_id
        self.label = label
        self.done = 0
        self.total = 0
        self.cancelled = False
        self.finished = False
        self.error = None
        self.result = None

    def cancel(self):
        self.cancelled = True


# Active tasks registry
_active_tasks = {}  # task_id -> EditorTask
_tasks_lock = threading.Lock()


def get_active_tasks(server_id):
    """Get active tasks for a server."""
    with _tasks_lock:
        return [t for t in _active_tasks.values() if t.server_id == server_id and not t.finished]


def get_task(task_id):
    with _tasks_lock:
        return _active_tasks.get(task_id)


def register_task(task):
    with _tasks_lock:
        _active_tasks[task.task_id] = task


def finish_task(task_id):
    with _tasks_lock:
        task = _active_tasks.get(task_id)
        if task:
            task.finished = True


# ==================== Tile Renderer ====================

def get_palette(base_dir):
    """Load the block color palette from configs/msmceditor/palette.json."""
    global _palette_cache
    if _palette_cache is not None:
        return _palette_cache

    palette_path = base_dir / 'configs' / 'msmceditor' / 'palette.json'
    if palette_path.exists():
        try:
            with open(palette_path, 'r') as f:
                _palette_cache = json.load(f)
            return _palette_cache
        except Exception as e:
            log.error(f"Failed to load palette: {e}")

    # Minimal fallback
    _palette_cache = _get_fallback_palette()
    return _palette_cache


def invalidate_palette_cache():
    """Force palette reload on next access."""
    global _palette_cache
    _palette_cache = None


def render_chunk_tile(level, cx, cz, dimension, palette):
    """
    Render a 16x16 top-down PNG tile for a single chunk.
    Returns PNG bytes or None if chunk doesn't exist.
    """
    try:
        chunk = level.get_chunk(cx, cz, dimension)
    except (ChunkDoesNotExist, ChunkLoadError):
        return None
    except Exception as e:
        log.debug(f"Chunk load error ({cx},{cz}): {e}")
        return None

    img = Image.new('RGBA', (16, 16), (0, 0, 0, 0))
    pixels = img.load()

    blocks = chunk.blocks
    # Get the block palette for this chunk
    block_palette = level.block_palette

    # Determine Y range
    try:
        bounds = level.bounds(dimension)
        min_y = bounds.min[1]
        max_y = bounds.max[1]
    except Exception:
        min_y = -64
        max_y = 320

    for local_x in range(16):
        for local_z in range(16):
            # Scan from top down to find first non-air block
            color = (0, 0, 0, 0)
            for y in range(max_y - 1, min_y - 1, -1):
                try:
                    # Get the block at this position
                    block_id = blocks[local_x, y, local_z]
                    block = block_palette[block_id]
                    block_name = f"{block.namespace}:{block.base_name}"

                    if block_name in ('minecraft:air', 'minecraft:cave_air', 'minecraft:void_air'):
                        continue

                    # Look up color from palette
                    if block_name in palette:
                        rgba = palette[block_name]
                        # Apply height shading
                        shade = max(0.6, min(1.2, 0.7 + (y - min_y) / (max_y - min_y) * 0.6))
                        r = min(255, int(rgba[0] * shade))
                        g = min(255, int(rgba[1] * shade))
                        b = min(255, int(rgba[2] * shade))
                        color = (r, g, b, rgba[3] if len(rgba) > 3 else 255)
                    else:
                        # Unknown block — grey with height shading
                        shade = max(0.6, min(1.2, 0.7 + (y - min_y) / (max_y - min_y) * 0.6))
                        v = min(255, int(128 * shade))
                        color = (v, v, v, 255)
                    break
                except (IndexError, KeyError):
                    continue

            pixels[local_x, local_z] = color

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def get_cached_tile(server_path, dimension, cx, cz):
    """Get a cached tile PNG or None."""
    cache_path = _tile_cache_path(server_path, dimension, cx, cz)
    if cache_path.exists():
        return cache_path.read_bytes()
    return None


def save_cached_tile(server_path, dimension, cx, cz, png_bytes):
    """Save a tile to cache."""
    cache_path = _tile_cache_path(server_path, dimension, cx, cz)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(png_bytes)


def invalidate_tile_cache(server_path, dimension=None, chunks=None):
    """Invalidate cached tiles. If dimension is None, invalidate all."""
    cache_dir = Path(server_path) / '.msmceditor-cache'
    if not cache_dir.exists():
        return

    if dimension is None:
        import shutil
        shutil.rmtree(cache_dir, ignore_errors=True)
        return

    dim_dir = cache_dir / _dim_folder(dimension)
    if chunks is None:
        import shutil
        shutil.rmtree(dim_dir, ignore_errors=True)
    else:
        for cx, cz in chunks:
            path = dim_dir / str(cz) / f"{cx}.png"
            if path.exists():
                path.unlink()


def _tile_cache_path(server_path, dimension, cx, cz):
    return Path(server_path) / '.msmceditor-cache' / _dim_folder(dimension) / str(cz) / f"{cx}.png"


def _dim_folder(dimension):
    """Convert dimension string to safe folder name."""
    return dimension.replace(':', '_').replace('/', '_')


# ==================== Palette Builder ====================

def build_palette_from_jar(jar_path, output_path):
    """
    Parse a Minecraft client JAR to extract block texture colors.
    Returns the palette dict and saves to output_path.
    """
    palette = {}

    try:
        with zipfile.ZipFile(jar_path, 'r') as jar:
            # Find all block textures
            texture_prefix = 'assets/minecraft/textures/block/'
            texture_files = [
                name for name in jar.namelist()
                if name.startswith(texture_prefix) and name.endswith('.png')
            ]

            for tex_path in texture_files:
                try:
                    tex_name = tex_path[len(texture_prefix):-4]  # Strip prefix and .png
                    with jar.open(tex_path) as f:
                        img = Image.open(io.BytesIO(f.read())).convert('RGBA')
                        # Compute average color
                        arr = numpy.array(img)
                        # Only consider non-transparent pixels
                        mask = arr[:, :, 3] > 0
                        if mask.any():
                            r = int(arr[:, :, 0][mask].mean())
                            g = int(arr[:, :, 1][mask].mean())
                            b = int(arr[:, :, 2][mask].mean())
                            a = int(arr[:, :, 3][mask].mean())
                            palette[f"minecraft:{tex_name}"] = [r, g, b, a]
                except Exception:
                    continue

            # Handle _top variants: prefer _top for block entries
            top_overrides = {}
            for key in list(palette.keys()):
                if key.endswith('_top'):
                    base_key = key[:-4]
                    if base_key in palette:
                        top_overrides[base_key] = palette[key]

            palette.update(top_overrides)

    except Exception as e:
        log.error(f"Failed to build palette from JAR: {e}")
        raise

    # Save
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(palette, f, indent=2)

    # Invalidate cache
    invalidate_palette_cache()

    return palette


# ==================== World Discovery ====================

def discover_worlds(server_path):
    """
    Find editable worlds in a server directory.
    Returns list of {name, path, platform, hasDimensions}.
    """
    worlds = []
    server_path = Path(server_path)

    # Java: look for directories with level.dat
    for item in server_path.iterdir():
        if not item.is_dir():
            continue
        level_dat = item / 'level.dat'
        if level_dat.exists():
            # Determine platform
            is_bedrock = (item / 'db').is_dir()
            platform = 'bedrock' if is_bedrock else 'java'
            worlds.append({
                'name': item.name,
                'path': str(item),
                'platform': platform,
            })

    return worlds


# ==================== Level.dat Operations ====================

def read_level_info(session):
    """Read level.dat info using amulet_nbt for richer parsing."""
    level_dat_path = session.world_path / 'level.dat'
    if not level_dat_path.exists():
        return None

    try:
        nbt = amulet_nbt.load(str(level_dat_path))
        # Navigate to the Data compound (Java) or root (Bedrock)
        if session.platform == 'java':
            data = nbt.compound.get('Data', nbt.compound)
        else:
            data = nbt.compound

        info = {}
        # Extract common fields
        _extract_field(data, info, 'LevelName', 'levelName', str)
        _extract_field(data, info, 'RandomSeed', 'seed', int)
        _extract_field(data, info, 'SpawnX', 'spawnX', int)
        _extract_field(data, info, 'SpawnY', 'spawnY', int)
        _extract_field(data, info, 'SpawnZ', 'spawnZ', int)
        _extract_field(data, info, 'DayTime', 'dayTime', int)
        _extract_field(data, info, 'Time', 'time', int)
        _extract_field(data, info, 'Difficulty', 'difficulty', int)
        _extract_field(data, info, 'hardcore', 'hardcore', bool)

        # Weather
        _extract_field(data, info, 'raining', 'raining', bool)
        _extract_field(data, info, 'thundering', 'thundering', bool)
        _extract_field(data, info, 'rainTime', 'rainTime', int)
        _extract_field(data, info, 'thunderTime', 'thunderTime', int)

        # Game rules (Java)
        if 'GameRules' in data:
            rules = data['GameRules']
            info['gameRules'] = {}
            for key in rules:
                try:
                    info['gameRules'][str(key)] = str(rules[key])
                except Exception:
                    pass

        return info
    except Exception as e:
        log.error(f"Failed to read level.dat: {e}")
        return None


def write_level_info(session, updates):
    """Write updated fields back to level.dat."""
    level_dat_path = session.world_path / 'level.dat'
    if not level_dat_path.exists():
        return False

    try:
        nbt = amulet_nbt.load(str(level_dat_path))
        if session.platform == 'java':
            data = nbt.compound.get('Data', nbt.compound)
        else:
            data = nbt.compound

        # Apply updates
        field_map = {
            'levelName': ('LevelName', amulet_nbt.StringTag),
            'seed': ('RandomSeed', amulet_nbt.LongTag),
            'spawnX': ('SpawnX', amulet_nbt.IntTag),
            'spawnY': ('SpawnY', amulet_nbt.IntTag),
            'spawnZ': ('SpawnZ', amulet_nbt.IntTag),
            'dayTime': ('DayTime', amulet_nbt.LongTag),
            'time': ('Time', amulet_nbt.LongTag),
            'difficulty': ('Difficulty', amulet_nbt.ByteTag),
            'hardcore': ('hardcore', amulet_nbt.ByteTag),
            'raining': ('raining', amulet_nbt.ByteTag),
            'thundering': ('thundering', amulet_nbt.ByteTag),
            'rainTime': ('rainTime', amulet_nbt.IntTag),
            'thunderTime': ('thunderTime', amulet_nbt.IntTag),
        }

        for key, value in updates.items():
            if key == 'gameRules' and isinstance(value, dict):
                if 'GameRules' in data:
                    for rule_key, rule_val in value.items():
                        data['GameRules'][rule_key] = amulet_nbt.StringTag(str(rule_val))
            elif key in field_map:
                nbt_key, tag_type = field_map[key]
                if tag_type == amulet_nbt.ByteTag:
                    data[nbt_key] = tag_type(int(bool(value)))
                else:
                    data[nbt_key] = tag_type(value)

        nbt.save_to(str(level_dat_path))
        session.dirty = True
        return True
    except Exception as e:
        log.error(f"Failed to write level.dat: {e}")
        return False


def _extract_field(data, info, nbt_key, json_key, type_fn):
    """Extract a field from NBT data into the info dict."""
    if nbt_key in data:
        try:
            val = data[nbt_key]
            if hasattr(val, 'py_data'):
                info[json_key] = type_fn(val.py_data)
            elif hasattr(val, 'value'):
                info[json_key] = type_fn(val.value)
            else:
                info[json_key] = type_fn(val)
        except Exception:
            pass


# ==================== Player Data ====================

def list_players(session):
    """List player UUIDs available in the world."""
    players = []
    world_path = session.world_path

    # Java: playerdata/ directory
    playerdata_dir = world_path / 'playerdata'
    if playerdata_dir.exists():
        for f in playerdata_dir.glob('*.dat'):
            players.append({
                'uuid': f.stem,
                'platform': 'java',
                'path': str(f),
            })

    # Bedrock: db-based, list via level
    # (Bedrock player data is stored in LevelDB — would need amulet API)

    return players


def read_player(session, player_uuid):
    """Read player data file and return structured info."""
    world_path = session.world_path
    player_file = world_path / 'playerdata' / f'{player_uuid}.dat'

    if not player_file.exists():
        return None

    try:
        nbt = amulet_nbt.load(str(player_file))
        data = nbt.compound
        info = {}

        # Position
        if 'Pos' in data:
            pos = data['Pos']
            info['position'] = {
                'x': float(pos[0].value if hasattr(pos[0], 'value') else pos[0]),
                'y': float(pos[1].value if hasattr(pos[1], 'value') else pos[1]),
                'z': float(pos[2].value if hasattr(pos[2], 'value') else pos[2]),
            }

        # Gamemode
        _extract_field(data, info, 'playerGameType', 'gamemode', int)

        # Health & Food
        _extract_field(data, info, 'Health', 'health', float)
        _extract_field(data, info, 'foodLevel', 'food', int)
        _extract_field(data, info, 'XpLevel', 'xpLevel', int)

        # Dimension
        if 'Dimension' in data:
            try:
                dim_val = data['Dimension']
                if hasattr(dim_val, 'py_str'):
                    info['dimension'] = dim_val.py_str
                elif hasattr(dim_val, 'value'):
                    info['dimension'] = str(dim_val.value)
                else:
                    info['dimension'] = str(dim_val)
            except Exception:
                pass

        return info
    except Exception as e:
        log.error(f"Failed to read player data: {e}")
        return None


def write_player(session, player_uuid, updates):
    """Write updates to player data file."""
    world_path = session.world_path
    player_file = world_path / 'playerdata' / f'{player_uuid}.dat'

    if not player_file.exists():
        return False

    try:
        nbt = amulet_nbt.load(str(player_file))
        data = nbt.compound

        if 'position' in updates:
            pos = updates['position']
            if 'Pos' in data:
                data['Pos'][0] = amulet_nbt.DoubleTag(float(pos['x']))
                data['Pos'][1] = amulet_nbt.DoubleTag(float(pos['y']))
                data['Pos'][2] = amulet_nbt.DoubleTag(float(pos['z']))

        if 'gamemode' in updates:
            data['playerGameType'] = amulet_nbt.IntTag(int(updates['gamemode']))

        if 'health' in updates:
            data['Health'] = amulet_nbt.FloatTag(float(updates['health']))

        if 'food' in updates:
            data['foodLevel'] = amulet_nbt.IntTag(int(updates['food']))

        nbt.save_to(str(player_file))
        session.dirty = True
        return True
    except Exception as e:
        log.error(f"Failed to write player data: {e}")
        return False


# ==================== Block Operations ====================

def get_block_info(session, x, y, z, dimension):
    """Get block info at coordinates."""
    level = session.level
    try:
        block = level.get_block(x, y, z, dimension)
        block_name = f"{block.namespace}:{block.base_name}"
        properties = dict(block.properties) if block.properties else {}
        # Convert property values to strings
        props_str = {k: str(v) for k, v in properties.items()}

        # Get block entity
        cx, cz = x >> 4, z >> 4
        block_entity_data = None
        try:
            chunk = level.get_chunk(cx, cz, dimension)
            be = chunk.block_entities.get((x, y, z))
            if be:
                block_entity_data = str(be.nbt)
        except Exception:
            pass

        return {
            'block': block_name,
            'properties': props_str,
            'blockEntity': block_entity_data,
            'x': x, 'y': y, 'z': z,
            'dimension': dimension,
        }
    except (ChunkDoesNotExist, ChunkLoadError):
        return {'error': 'Chunk not loaded', 'x': x, 'y': y, 'z': z}
    except Exception as e:
        return {'error': str(e), 'x': x, 'y': y, 'z': z}


def set_block(session, x, y, z, dimension, block_str):
    """Set a block at coordinates. block_str is 'namespace:name[prop=val,...]'."""
    level = session.level
    try:
        # Parse block string
        namespace, rest = block_str.split(':', 1) if ':' in block_str else ('minecraft', block_str)
        props = {}
        if '[' in rest and rest.endswith(']'):
            name = rest[:rest.index('[')]
            props_str = rest[rest.index('[') + 1:-1]
            for pair in props_str.split(','):
                if '=' in pair:
                    k, v = pair.split('=', 1)
                    props[k.strip()] = amulet_nbt.StringTag(v.strip())
        else:
            name = rest

        block = Block(namespace, name, props)
        level.set_version_block(
            x, y, z, dimension,
            (session.platform, session.version),
            block
        )
        session.dirty = True

        # Invalidate tile cache for this chunk
        cx, cz = x >> 4, z >> 4
        invalidate_tile_cache(session.world_path, dimension, [(cx, cz)])

        return {'success': True, 'block': str(block)}
    except Exception as e:
        return {'error': str(e)}


# ==================== Region Replace ====================

def run_replace(session, dimension, box, from_block_str, to_block_str, dry_run, task, emit_fn):
    """
    Replace blocks in a region. Runs in background thread.
    emit_fn(event, data) is used to broadcast progress.
    """
    level = session.level
    try:
        from_ns, from_name = _parse_block_id(from_block_str)
        to_ns, to_name = _parse_block_id(to_block_str)

        x1, y1, z1, x2, y2, z2 = box['x1'], box['y1'], box['z1'], box['x2'], box['y2'], box['z2']
        selection = SelectionBox((min(x1, x2), min(y1, y2), min(z1, z2)),
                                 (max(x1, x2) + 1, max(y1, y2) + 1, max(z1, z2) + 1))

        total_blocks = selection.volume
        task.total = total_blocks
        count = 0
        replaced = 0
        affected_chunks = set()

        for x in range(selection.min[0], selection.max[0]):
            for z in range(selection.min[2], selection.max[2]):
                for y in range(selection.min[1], selection.max[1]):
                    if task.cancelled:
                        task.result = {'replaced': replaced, 'cancelled': True}
                        finish_task(task.task_id)
                        return

                    count += 1
                    try:
                        block = level.get_block(x, y, z, dimension)
                        if block.namespace == from_ns and block.base_name == from_name:
                            if not dry_run:
                                new_block = Block(to_ns, to_name)
                                level.set_version_block(
                                    x, y, z, dimension,
                                    (session.platform, session.version),
                                    new_block
                                )
                                affected_chunks.add((x >> 4, z >> 4))
                            replaced += 1
                    except (ChunkDoesNotExist, ChunkLoadError):
                        pass
                    except Exception:
                        pass

                    # Emit progress periodically
                    if count % 1000 == 0:
                        task.done = count
                        emit_fn('msmceditor:progress', {
                            'taskId': task.task_id,
                            'done': count,
                            'total': total_blocks,
                            'label': f'Replacing... {replaced} found'
                        })

        if not dry_run and affected_chunks:
            session.dirty = True
            invalidate_tile_cache(session.world_path, dimension, list(affected_chunks))
            emit_fn('msmceditor:tile-invalidate', {
                'dim': dimension,
                'chunks': list(affected_chunks)
            })

        task.done = total_blocks
        task.result = {'replaced': replaced, 'dryRun': dry_run, 'cancelled': False}
        emit_fn('msmceditor:progress', {
            'taskId': task.task_id,
            'done': total_blocks,
            'total': total_blocks,
            'label': f'Done — {replaced} blocks {"would be " if dry_run else ""}replaced'
        })

    except Exception as e:
        task.error = str(e)
        emit_fn('msmceditor:error', {'message': str(e)})
    finally:
        finish_task(task.task_id)


# ==================== Chunk Operations ====================

def delete_chunks(session, dimension, coords, task, emit_fn):
    """Delete specified chunks. coords is list of [cx, cz]."""
    level = session.level
    task.total = len(coords)

    try:
        for i, (cx, cz) in enumerate(coords):
            if task.cancelled:
                break
            try:
                level.delete_chunk(cx, cz, dimension)
            except Exception:
                pass
            task.done = i + 1
            if (i + 1) % 10 == 0:
                emit_fn('msmceditor:progress', {
                    'taskId': task.task_id,
                    'done': i + 1,
                    'total': len(coords),
                    'label': f'Deleting chunks... {i + 1}/{len(coords)}'
                })

        session.dirty = True
        invalidate_tile_cache(session.world_path, dimension, coords)
        emit_fn('msmceditor:tile-invalidate', {
            'dim': dimension,
            'chunks': coords
        })
        task.result = {'deleted': task.done, 'cancelled': task.cancelled}
        emit_fn('msmceditor:progress', {
            'taskId': task.task_id,
            'done': task.done,
            'total': len(coords),
            'label': f'Done — {task.done} chunks deleted'
        })
    except Exception as e:
        task.error = str(e)
        emit_fn('msmceditor:error', {'message': str(e)})
    finally:
        finish_task(task.task_id)


def prune_chunks(session, dimension, keep_box, task, emit_fn):
    """Delete all chunks OUTSIDE the keep_box. keep_box is {x1,z1,x2,z2} in chunk coords."""
    level = session.level
    all_chunks = level.all_chunk_coords(dimension)

    x1 = min(keep_box['x1'], keep_box['x2'])
    z1 = min(keep_box['z1'], keep_box['z2'])
    x2 = max(keep_box['x1'], keep_box['x2'])
    z2 = max(keep_box['z1'], keep_box['z2'])

    to_delete = [(cx, cz) for cx, cz in all_chunks if not (x1 <= cx <= x2 and z1 <= cz <= z2)]
    task.total = len(to_delete)

    try:
        for i, (cx, cz) in enumerate(to_delete):
            if task.cancelled:
                break
            try:
                level.delete_chunk(cx, cz, dimension)
            except Exception:
                pass
            task.done = i + 1
            if (i + 1) % 10 == 0:
                emit_fn('msmceditor:progress', {
                    'taskId': task.task_id,
                    'done': i + 1,
                    'total': len(to_delete),
                    'label': f'Pruning... {i + 1}/{len(to_delete)}'
                })

        session.dirty = True
        invalidate_tile_cache(session.world_path, dimension)
        emit_fn('msmceditor:tile-invalidate', {'dim': dimension, 'chunks': []})
        task.result = {'pruned': task.done, 'cancelled': task.cancelled}
        emit_fn('msmceditor:progress', {
            'taskId': task.task_id,
            'done': task.done,
            'total': len(to_delete),
            'label': f'Done — {task.done} chunks pruned'
        })
    except Exception as e:
        task.error = str(e)
        emit_fn('msmceditor:error', {'message': str(e)})
    finally:
        finish_task(task.task_id)


# ==================== Save / Backup ====================

def save_world(session, backup_dir):
    """
    Save the world. Creates an auto-backup first.
    Returns (success, message).
    """
    try:
        # Auto-backup before save
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"auto-pre-edit-{timestamp}.zip"
        backup_path = Path(backup_dir) / backup_name

        backup_path.parent.mkdir(parents=True, exist_ok=True)

        # Zip the world directory
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file in session.world_path.rglob('*'):
                if file.is_file():
                    # Skip cache directory
                    if '.msmceditor-cache' in str(file):
                        continue
                    arcname = file.relative_to(session.world_path.parent)
                    zf.write(file, arcname)

        # Now save via amulet
        session.level.save()
        session.dirty = False

        return True, f"Saved successfully (backup: {backup_name})"
    except Exception as e:
        log.error(f"Failed to save world: {e}")
        return False, str(e)


# ==================== Helpers ====================

def _parse_block_id(block_str):
    """Parse 'namespace:name' into (namespace, name)."""
    if ':' in block_str:
        ns, name = block_str.split(':', 1)
        # Strip properties if present
        if '[' in name:
            name = name[:name.index('[')]
        return ns, name
    return 'minecraft', block_str


def _get_fallback_palette():
    """Minimal built-in palette for common blocks."""
    return {
        "minecraft:stone": [125, 125, 125, 255],
        "minecraft:granite": [149, 103, 85, 255],
        "minecraft:diorite": [188, 188, 188, 255],
        "minecraft:andesite": [136, 136, 136, 255],
        "minecraft:grass_block": [91, 169, 59, 255],
        "minecraft:dirt": [134, 96, 67, 255],
        "minecraft:cobblestone": [127, 127, 127, 255],
        "minecraft:oak_planks": [162, 131, 78, 255],
        "minecraft:spruce_planks": [114, 84, 48, 255],
        "minecraft:birch_planks": [196, 179, 123, 255],
        "minecraft:water": [47, 67, 244, 180],
        "minecraft:lava": [207, 92, 15, 255],
        "minecraft:sand": [219, 207, 163, 255],
        "minecraft:gravel": [131, 127, 126, 255],
        "minecraft:gold_ore": [145, 133, 106, 255],
        "minecraft:iron_ore": [136, 129, 122, 255],
        "minecraft:coal_ore": [105, 105, 105, 255],
        "minecraft:oak_log": [109, 85, 50, 255],
        "minecraft:spruce_log": [58, 37, 16, 255],
        "minecraft:birch_log": [216, 215, 210, 255],
        "minecraft:oak_leaves": [59, 122, 25, 200],
        "minecraft:spruce_leaves": [61, 99, 61, 200],
        "minecraft:birch_leaves": [80, 132, 56, 200],
        "minecraft:glass": [175, 213, 219, 100],
        "minecraft:sandstone": [216, 203, 155, 255],
        "minecraft:snow_block": [249, 254, 254, 255],
        "minecraft:snow": [249, 254, 254, 255],
        "minecraft:ice": [145, 183, 253, 200],
        "minecraft:clay": [160, 166, 179, 255],
        "minecraft:obsidian": [15, 10, 24, 255],
        "minecraft:netherrack": [97, 38, 38, 255],
        "minecraft:soul_sand": [81, 62, 50, 255],
        "minecraft:glowstone": [171, 131, 73, 255],
        "minecraft:end_stone": [219, 222, 158, 255],
        "minecraft:bedrock": [85, 85, 85, 255],
        "minecraft:deepslate": [80, 80, 82, 255],
        "minecraft:copper_ore": [124, 125, 120, 255],
        "minecraft:diamond_ore": [121, 141, 140, 255],
        "minecraft:redstone_ore": [133, 107, 107, 255],
        "minecraft:emerald_ore": [109, 133, 109, 255],
        "minecraft:lapis_ore": [102, 112, 134, 255],
        "minecraft:mossy_cobblestone": [110, 127, 93, 255],
        "minecraft:bricks": [150, 97, 83, 255],
        "minecraft:tnt": [219, 68, 44, 255],
        "minecraft:bookshelf": [162, 131, 78, 255],
        "minecraft:torch": [255, 216, 0, 255],
        "minecraft:crafting_table": [132, 88, 49, 255],
        "minecraft:furnace": [127, 127, 127, 255],
        "minecraft:chest": [162, 130, 56, 255],
        "minecraft:diamond_block": [98, 237, 228, 255],
        "minecraft:gold_block": [246, 208, 61, 255],
        "minecraft:iron_block": [220, 220, 220, 255],
        "minecraft:emerald_block": [42, 176, 72, 255],
        "minecraft:redstone_block": [171, 26, 5, 255],
        "minecraft:lapis_block": [30, 67, 140, 255],
        "minecraft:coal_block": [16, 15, 15, 255],
        "minecraft:copper_block": [192, 107, 79, 255],
        "minecraft:terracotta": [152, 94, 67, 255],
        "minecraft:white_terracotta": [209, 178, 161, 255],
        "minecraft:orange_terracotta": [161, 83, 37, 255],
        "minecraft:magenta_terracotta": [149, 88, 108, 255],
        "minecraft:light_blue_terracotta": [113, 108, 137, 255],
        "minecraft:yellow_terracotta": [186, 133, 35, 255],
        "minecraft:lime_terracotta": [103, 117, 52, 255],
        "minecraft:pink_terracotta": [161, 78, 78, 255],
        "minecraft:gray_terracotta": [57, 42, 35, 255],
        "minecraft:light_gray_terracotta": [135, 106, 97, 255],
        "minecraft:cyan_terracotta": [86, 91, 91, 255],
        "minecraft:purple_terracotta": [118, 70, 86, 255],
        "minecraft:blue_terracotta": [74, 59, 91, 255],
        "minecraft:brown_terracotta": [77, 51, 35, 255],
        "minecraft:green_terracotta": [76, 83, 42, 255],
        "minecraft:red_terracotta": [143, 61, 46, 255],
        "minecraft:black_terracotta": [37, 22, 16, 255],
        "minecraft:white_concrete": [207, 213, 214, 255],
        "minecraft:orange_concrete": [224, 97, 0, 255],
        "minecraft:magenta_concrete": [169, 48, 159, 255],
        "minecraft:light_blue_concrete": [35, 137, 198, 255],
        "minecraft:yellow_concrete": [240, 175, 21, 255],
        "minecraft:lime_concrete": [94, 168, 24, 255],
        "minecraft:pink_concrete": [213, 101, 142, 255],
        "minecraft:gray_concrete": [54, 57, 61, 255],
        "minecraft:light_gray_concrete": [125, 125, 115, 255],
        "minecraft:cyan_concrete": [21, 119, 136, 255],
        "minecraft:purple_concrete": [100, 31, 156, 255],
        "minecraft:blue_concrete": [44, 46, 143, 255],
        "minecraft:brown_concrete": [96, 59, 31, 255],
        "minecraft:green_concrete": [73, 91, 36, 255],
        "minecraft:red_concrete": [142, 32, 32, 255],
        "minecraft:black_concrete": [8, 10, 15, 255],
        "minecraft:white_wool": [233, 236, 236, 255],
        "minecraft:orange_wool": [240, 118, 19, 255],
        "minecraft:magenta_wool": [189, 68, 179, 255],
        "minecraft:light_blue_wool": [58, 175, 217, 255],
        "minecraft:yellow_wool": [248, 197, 39, 255],
        "minecraft:lime_wool": [112, 185, 25, 255],
        "minecraft:pink_wool": [237, 141, 172, 255],
        "minecraft:gray_wool": [62, 68, 71, 255],
        "minecraft:light_gray_wool": [142, 142, 134, 255],
        "minecraft:cyan_wool": [21, 137, 145, 255],
        "minecraft:purple_wool": [121, 42, 172, 255],
        "minecraft:blue_wool": [53, 57, 157, 255],
        "minecraft:brown_wool": [114, 71, 40, 255],
        "minecraft:green_wool": [84, 109, 27, 255],
        "minecraft:red_wool": [160, 39, 34, 255],
        "minecraft:black_wool": [20, 21, 25, 255],
        "minecraft:mycelium": [111, 99, 107, 255],
        "minecraft:podzol": [91, 63, 24, 255],
        "minecraft:coarse_dirt": [119, 85, 59, 255],
        "minecraft:farmland": [109, 74, 45, 255],
        "minecraft:grass_path": [148, 121, 65, 255],
        "minecraft:dirt_path": [148, 121, 65, 255],
        "minecraft:prismarine": [99, 171, 158, 255],
        "minecraft:dark_prismarine": [51, 91, 75, 255],
        "minecraft:sea_lantern": [172, 199, 190, 255],
        "minecraft:nether_bricks": [44, 21, 26, 255],
        "minecraft:red_nether_bricks": [69, 7, 9, 255],
        "minecraft:basalt": [72, 72, 78, 255],
        "minecraft:blackstone": [42, 35, 40, 255],
        "minecraft:crying_obsidian": [32, 10, 60, 255],
        "minecraft:warped_nylium": [43, 114, 101, 255],
        "minecraft:crimson_nylium": [130, 31, 31, 255],
        "minecraft:moss_block": [89, 109, 45, 255],
        "minecraft:mud": [60, 57, 53, 255],
        "minecraft:packed_mud": [142, 106, 79, 255],
        "minecraft:mud_bricks": [137, 104, 75, 255],
        "minecraft:mangrove_roots": [75, 60, 39, 255],
        "minecraft:sculk": [12, 29, 36, 255],
        "minecraft:dripstone_block": [134, 107, 82, 255],
        "minecraft:amethyst_block": [133, 97, 191, 255],
        "minecraft:tuff": [108, 109, 102, 255],
        "minecraft:calcite": [223, 224, 220, 255],
        "minecraft:raw_iron_block": [166, 135, 107, 255],
        "minecraft:raw_copper_block": [154, 105, 73, 255],
        "minecraft:raw_gold_block": [221, 169, 46, 255],
    }
