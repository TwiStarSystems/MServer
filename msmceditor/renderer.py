"""
Renderer — produce JSON-serializable chunk block data for the Three.js client.

The frontend uses this to build greedy-meshed BufferGeometry per chunk.
The renderer also exposes top-down preview rendering (PNG) for thumbnails
and the optional 2D fallback.
"""

import io
import logging

log = logging.getLogger(__name__)


def get_chunk_mesh_data(world, cx, cz, dimension):
    """
    Return JSON-serializable block data for one chunk:
        {
          'cx', 'cz',
          'sections': [
              {'y', 'palette': [{'name','properties'}], 'indices': [4096 ints]},
              ...
          ]
        }
    Returns None if chunk doesn't exist.
    """
    return world.get_chunk_block_data(cx, cz, dimension)


def get_chunks_in_range(world, center_cx, center_cz, radius, dimension):
    """List of chunk mesh dicts within square radius. Caps at 32x32 chunks."""
    radius = max(1, min(int(radius), 16))
    out = []
    for cz in range(center_cz - radius, center_cz + radius + 1):
        for cx in range(center_cx - radius, center_cx + radius + 1):
            d = world.get_chunk_block_data(cx, cz, dimension)
            if d is not None:
                out.append(d)
    return out


def render_chunk_thumbnail(world, cx, cz, dimension, palette):
    """
    Render a 16x16 top-down PNG thumbnail of a chunk for preview UIs.
    Returns PNG bytes or None.
    """
    try:
        from PIL import Image
    except ImportError:
        return None

    data = world.get_chunk_block_data(cx, cz, dimension)
    if data is None:
        return None

    img = Image.new('RGBA', (16, 16), (0, 0, 0, 0))
    pixels = img.load()
    sections = sorted(data['sections'], key=lambda s: s['y'], reverse=True)

    for lx in range(16):
        for lz in range(16):
            color = (0, 0, 0, 0)
            for sec in sections:
                pal = sec['palette']
                idx = sec['indices']
                for ly in range(15, -1, -1):
                    packed = ly * 256 + lz * 16 + lx
                    if packed >= len(idx):
                        continue
                    block = pal[idx[packed]]
                    name = block['name']
                    if name == 'minecraft:air' or name == 'minecraft:cave_air':
                        continue
                    color = tuple(palette.get(name, [180, 180, 180, 255]))
                    break
                if color[3] > 0:
                    break
            pixels[lx, lz] = color

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()
