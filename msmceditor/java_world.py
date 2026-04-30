"""
JavaWorld — pure-Python Minecraft Java Edition world API.

Handles dimensions, chunk loading, block get/set, level.dat, players.
Internally caches open AnvilRegion handles and dirty chunks for batched save.

Modern chunk format (DataVersion >= 2844, MC 1.18+):
    sections[].block_states.palette  — ListTag<Compound{Name, Properties}>
    sections[].block_states.data     — LongArrayTag (packed indices)
    sections[].Y                     — section Y index (signed byte/int)

Index order in the packed array: y*256 + z*16 + x   (range 0..4095)
bits_per_entry = max(4, ceil(log2(len(palette))))
Non-dense packing (1.16+): values do not span across long boundaries.
"""

import logging
import math
import os
import threading
from pathlib import Path

from . import nbt as nbt_mod
from . import region as region_mod

log = logging.getLogger(__name__)

REGION_CACHE_LIMIT = 64
CHUNK_CACHE_LIMIT = 256


# ==================== Long-array packing helpers ====================

def decode_long_array(longs, num_entries, bits_per_entry):
    """
    Decode a packed long array into `num_entries` integer values.
    Uses the modern (MC 1.16+) non-dense packing where values don't span longs.
    Returns a list of ints.
    """
    if bits_per_entry == 0 or num_entries == 0:
        return [0] * num_entries

    # Number of values that fit in one 64-bit long
    values_per_long = 64 // bits_per_entry
    mask = (1 << bits_per_entry) - 1

    out = [0] * num_entries
    idx = 0
    for raw in longs:
        # Treat as unsigned 64-bit
        u = raw & 0xFFFFFFFFFFFFFFFF
        for k in range(values_per_long):
            if idx >= num_entries:
                break
            out[idx] = (u >> (k * bits_per_entry)) & mask
            idx += 1
        if idx >= num_entries:
            break
    return out


def encode_long_array(values, bits_per_entry):
    """
    Encode integer values into a packed long array (modern non-dense format).
    Returns a list of signed 64-bit ints suitable for LongArrayTag.
    """
    if not values:
        return []
    if bits_per_entry == 0:
        bits_per_entry = 1

    values_per_long = 64 // bits_per_entry
    num_longs = (len(values) + values_per_long - 1) // values_per_long
    longs = [0] * num_longs

    for i, v in enumerate(values):
        long_idx = i // values_per_long
        bit_pos = (i % values_per_long) * bits_per_entry
        longs[long_idx] |= (int(v) & ((1 << bits_per_entry) - 1)) << bit_pos

    # Convert to signed 64-bit
    out = []
    for u in longs:
        u &= 0xFFFFFFFFFFFFFFFF
        if u >= (1 << 63):
            u -= (1 << 64)
        out.append(u)
    return out


def bits_for_palette(palette_len):
    """bits_per_entry = max(4, ceil(log2(palette_len)))."""
    if palette_len <= 1:
        return 4
    n = max(4, math.ceil(math.log2(palette_len)))
    return n


# ==================== Block-state helpers ====================

def block_state_to_str(name, properties):
    """'minecraft:oak_stairs[facing=east,half=top]' canonical form."""
    if not properties:
        return name
    parts = ','.join(f"{k}={v}" for k, v in sorted(properties.items()))
    return f"{name}[{parts}]"


def parse_block_str(s):
    """
    Parse 'minecraft:oak_stairs[facing=east,half=top]' or just 'minecraft:stone'.
    Returns (name, properties_dict).
    """
    s = s.strip()
    if '[' in s:
        name, rest = s.split('[', 1)
        rest = rest.rstrip(']')
        props = {}
        if rest:
            for pair in rest.split(','):
                if '=' in pair:
                    k, v = pair.split('=', 1)
                    props[k.strip()] = v.strip()
        return (name.strip(), props)
    return (s, {})


def palette_entry_to_dict(entry):
    """Convert a palette CompoundTag into {name, properties}."""
    name = entry['Name'].value if 'Name' in entry else 'minecraft:air'
    props = {}
    if 'Properties' in entry:
        for k, v in entry['Properties'].items():
            props[k] = v.value
    return {'name': name, 'properties': props}


def dict_to_palette_entry(name, properties):
    """Build a palette CompoundTag for the given block."""
    d = {'Name': nbt_mod.StringTag(name)}
    if properties:
        d['Properties'] = nbt_mod.CompoundTag({
            k: nbt_mod.StringTag(str(v)) for k, v in properties.items()
        })
    return nbt_mod.CompoundTag(d)


# ==================== JavaWorld ====================

# Default dimension folder mapping
DIMENSION_FOLDERS = {
    'minecraft:overworld': '',          # world root
    'minecraft:the_nether': 'DIM-1',
    'minecraft:the_end': 'DIM1',
}


class JavaWorld:
    """
    Java Edition world. Provides chunk read/write, block get/set, level.dat IO.

    Open regions are cached. Dirty chunks are buffered until save() flushes them.
    """

    def __init__(self, world_path):
        self.world_path = Path(world_path)
        if not (self.world_path / 'level.dat').exists():
            raise ValueError(f"Not a Java world: {self.world_path}")

        self._lock = threading.RLock()
        # cache: {(dim, rx, rz): AnvilRegion}
        self._regions = {}
        # dirty chunks: {(dim, cx, cz): (root_name, CompoundTag)}
        self._dirty = {}
        # decoded chunk cache: {(dim, cx, cz): (root_name, CompoundTag)}
        self._chunk_cache = {}

        self._level_name, self._level_root = self._load_level_root()
        self._dimensions = self._discover_dimensions()

    # ---------- Discovery ----------

    def _load_level_root(self):
        return nbt_mod.load(self.world_path / 'level.dat', gzipped=True)

    def _discover_dimensions(self):
        """Return list of dimension IDs available in this world."""
        dims = []
        if (self.world_path / 'region').is_dir():
            dims.append('minecraft:overworld')
        if (self.world_path / 'DIM-1' / 'region').is_dir():
            dims.append('minecraft:the_nether')
        if (self.world_path / 'DIM1' / 'region').is_dir():
            dims.append('minecraft:the_end')

        # Custom dimensions: dimensions/<namespace>/<name>/region
        dim_root = self.world_path / 'dimensions'
        if dim_root.is_dir():
            for ns_dir in dim_root.iterdir():
                if not ns_dir.is_dir():
                    continue
                for name_dir in ns_dir.iterdir():
                    if (name_dir / 'region').is_dir():
                        dims.append(f"{ns_dir.name}:{name_dir.name}")

        if not dims:
            dims = ['minecraft:overworld']
        return dims

    @property
    def dimensions(self):
        return list(self._dimensions)

    @property
    def name(self):
        try:
            data = self._level_root['Data']
            if 'LevelName' in data:
                return data['LevelName'].value
        except Exception:
            pass
        return self.world_path.name

    # ---------- Region management ----------

    def _region_dir(self, dimension):
        if dimension == 'minecraft:overworld':
            return self.world_path / 'region'
        if dimension == 'minecraft:the_nether':
            return self.world_path / 'DIM-1' / 'region'
        if dimension == 'minecraft:the_end':
            return self.world_path / 'DIM1' / 'region'
        if ':' in dimension:
            ns, nm = dimension.split(':', 1)
            return self.world_path / 'dimensions' / ns / nm / 'region'
        return self.world_path / 'region'

    def _get_region(self, dimension, rx, rz, *, create=False):
        key = (dimension, rx, rz)
        with self._lock:
            r = self._regions.get(key)
            if r is not None:
                return r
            path = self._region_dir(dimension) / region_mod.region_filename(rx, rz)
            if not path.exists() and not create:
                return None
            r = region_mod.AnvilRegion(path, create_if_missing=create)
            self._regions[key] = r
            # Simple LRU eviction
            if len(self._regions) > REGION_CACHE_LIMIT:
                oldest_key = next(iter(self._regions))
                if oldest_key != key:
                    self._regions.pop(oldest_key).close()
            return r

    # ---------- Chunk access ----------

    def all_chunk_coords(self, dimension):
        """Return set of (cx, cz) for all chunks in the dimension."""
        out = set()
        rdir = self._region_dir(dimension)
        if not rdir.is_dir():
            return out
        for f in region_mod.iter_region_files(rdir):
            coords = region_mod.region_coords_from_filename(f.name)
            if coords is None:
                continue
            rx, rz = coords
            r = self._get_region(dimension, rx, rz)
            if r:
                out |= r.all_chunk_coords()
        return out

    def get_chunk(self, cx, cz, dimension):
        """Return (root_name, CompoundTag) or None."""
        with self._lock:
            key = (dimension, cx, cz)
            if key in self._dirty:
                return self._dirty[key]
            if key in self._chunk_cache:
                return self._chunk_cache[key]
            rx, rz = region_mod.chunk_to_region(cx, cz)
            r = self._get_region(dimension, rx, rz)
            if r is None:
                return None
            chunk = r.read_chunk(cx, cz)
            if chunk is None:
                return None
            # Simple cache eviction
            if len(self._chunk_cache) >= CHUNK_CACHE_LIMIT:
                self._chunk_cache.pop(next(iter(self._chunk_cache)))
            self._chunk_cache[key] = chunk
            return chunk

    def mark_chunk_dirty(self, cx, cz, dimension, name, tag):
        """Mark a chunk as dirty (will be written on save)."""
        with self._lock:
            key = (dimension, cx, cz)
            self._dirty[key] = (name, tag)
            self._chunk_cache.pop(key, None)

    # ---------- Block access ----------

    @staticmethod
    def _section_key(chunk):
        """Return the list of section CompoundTags. Modern format only."""
        if 'sections' in chunk:
            return chunk['sections'].value
        # Legacy fallback (1.17 and earlier): chunk['Level']['Sections']
        if 'Level' in chunk and 'Sections' in chunk['Level']:
            return chunk['Level']['Sections'].value
        return []

    @staticmethod
    def _section_y(section):
        if 'Y' in section:
            return section['Y'].value
        return 0

    @staticmethod
    def _decode_section_palette(section):
        """Return (palette_list_of_dicts, indices_4096_or_None)."""
        bs = section.get('block_states')
        if bs is None:
            # Pre-1.18 format
            if 'Palette' in section and 'BlockStates' in section:
                palette_tag = section['Palette']
                data_tag = section['BlockStates']
            else:
                return ([], None)
        else:
            palette_tag = bs.get('palette')
            data_tag = bs.get('data')

        if palette_tag is None:
            return ([], None)

        palette = [palette_entry_to_dict(e) for e in palette_tag]

        if data_tag is None or len(palette) == 1:
            # Single-block section
            indices = [0] * 4096
            return (palette, indices)

        bits = bits_for_palette(len(palette))
        indices = decode_long_array(data_tag.value, 4096, bits)
        return (palette, indices)

    @staticmethod
    def _encode_section_palette(section, palette_dicts, indices):
        """Write palette + indices back into section's block_states."""
        new_palette = nbt_mod.ListTag(
            [dict_to_palette_entry(p['name'], p.get('properties', {})) for p in palette_dicts],
            list_type=nbt_mod.TAG_COMPOUND,
        )

        if len(palette_dicts) <= 1:
            # No data array needed
            bs_data = nbt_mod.CompoundTag({'palette': new_palette})
        else:
            bits = bits_for_palette(len(palette_dicts))
            longs = encode_long_array(indices, bits)
            bs_data = nbt_mod.CompoundTag({
                'palette': new_palette,
                'data': nbt_mod.LongArrayTag(longs),
            })
        section['block_states'] = bs_data

    def _block_index(self, x, y, z):
        """Return (section_y, local_x, local_y, local_z, packed_index)."""
        section_y = y >> 4
        lx = x & 15
        ly = y & 15
        lz = z & 15
        return section_y, lx, ly, lz, ly * 256 + lz * 16 + lx

    def get_block(self, x, y, z, dimension):
        """Return {name, properties} for a block, or None if chunk missing."""
        cx, cz = x >> 4, z >> 4
        chunk = self.get_chunk(cx, cz, dimension)
        if chunk is None:
            return None
        _, root = chunk
        section_y, _, _, _, packed = self._block_index(x, y, z)
        for sec in self._section_key(root):
            if self._section_y(sec) != section_y:
                continue
            palette, indices = self._decode_section_palette(sec)
            if not palette:
                return {'name': 'minecraft:air', 'properties': {}}
            if indices is None:
                return palette[0]
            return palette[indices[packed]]
        return {'name': 'minecraft:air', 'properties': {}}

    def set_block(self, x, y, z, dimension, name, properties=None):
        """Set a single block. Marks chunk dirty (call save() to persist)."""
        cx, cz = x >> 4, z >> 4
        chunk = self.get_chunk(cx, cz, dimension)
        if chunk is None:
            raise KeyError(f"Chunk ({cx},{cz}) does not exist in {dimension}")
        root_name, root = chunk
        section_y, _, _, _, packed = self._block_index(x, y, z)
        properties = properties or {}

        sections_list = self._section_key(root)
        target = None
        for sec in sections_list:
            if self._section_y(sec) == section_y:
                target = sec
                break

        if target is None:
            target = nbt_mod.CompoundTag({
                'Y': nbt_mod.ByteTag(section_y),
                'block_states': nbt_mod.CompoundTag({
                    'palette': nbt_mod.ListTag(
                        [dict_to_palette_entry('minecraft:air', {})],
                        list_type=nbt_mod.TAG_COMPOUND,
                    ),
                }),
            })
            if 'sections' in root:
                root['sections'].append(target)
            else:
                root['sections'] = nbt_mod.ListTag([target], list_type=nbt_mod.TAG_COMPOUND)

        palette, indices = self._decode_section_palette(target)
        if not palette:
            palette = [{'name': 'minecraft:air', 'properties': {}}]
            indices = [0] * 4096

        # Find or add palette entry
        target_idx = None
        for i, p in enumerate(palette):
            if p['name'] == name and p.get('properties', {}) == properties:
                target_idx = i
                break
        if target_idx is None:
            palette.append({'name': name, 'properties': dict(properties)})
            target_idx = len(palette) - 1

        if indices is None:
            indices = [0] * 4096
        indices[packed] = target_idx

        self._encode_section_palette(target, palette, indices)
        self.mark_chunk_dirty(cx, cz, dimension, root_name, root)

    def get_chunk_block_data(self, cx, cz, dimension):
        """
        Return a JSON-serializable dict describing all blocks in a chunk:
        {
          'cx': cx, 'cz': cz,
          'sections': [
            {'y': sy, 'palette': [{'name','properties'},...], 'indices': [4096 ints]},
            ...
          ]
        }
        Returns None if chunk doesn't exist.
        """
        chunk = self.get_chunk(cx, cz, dimension)
        if chunk is None:
            return None
        _, root = chunk
        out_sections = []
        for sec in self._section_key(root):
            sy = self._section_y(sec)
            palette, indices = self._decode_section_palette(sec)
            if not palette:
                continue
            out_sections.append({
                'y': int(sy),
                'palette': palette,
                'indices': indices if indices is not None else [0] * 4096,
            })
        return {'cx': cx, 'cz': cz, 'sections': out_sections}

    def get_chunks_in_range(self, center_cx, center_cz, radius, dimension):
        """Yield chunk block data for chunks in a square radius around center."""
        for cz in range(center_cz - radius, center_cz + radius + 1):
            for cx in range(center_cx - radius, center_cx + radius + 1):
                data = self.get_chunk_block_data(cx, cz, dimension)
                if data is not None:
                    yield data

    # ---------- Chunk delete ----------

    def delete_chunk(self, cx, cz, dimension):
        rx, rz = region_mod.chunk_to_region(cx, cz)
        r = self._get_region(dimension, rx, rz)
        if r is None:
            return False
        with self._lock:
            self._dirty.pop((dimension, cx, cz), None)
            self._chunk_cache.pop((dimension, cx, cz), None)
        return r.delete_chunk(cx, cz)

    # ---------- Save / close ----------

    def save(self):
        """Flush all dirty chunks to their region files."""
        with self._lock:
            for (dim, cx, cz), (name, tag) in list(self._dirty.items()):
                rx, rz = region_mod.chunk_to_region(cx, cz)
                r = self._get_region(dim, rx, rz, create=True)
                r.write_chunk(cx, cz, name, tag)
            self._dirty.clear()

    def close(self):
        with self._lock:
            self._dirty.clear()
            self._chunk_cache.clear()
            for r in self._regions.values():
                r.close()
            self._regions.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
