"""
Block palette loader + JAR texture extractor.

Palette is {block_name: [r, g, b, a]} loaded from configs/msmceditor/palette.json
with a small built-in fallback for the most common blocks.
"""

import json
import logging
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)

_palette_cache = None


def get_palette(base_dir):
    """Load the block color palette from configs/msmceditor/palette.json."""
    global _palette_cache
    if _palette_cache is not None:
        return _palette_cache

    palette_path = Path(base_dir) / 'configs' / 'msmceditor' / 'palette.json'
    if palette_path.exists():
        try:
            with open(palette_path) as f:
                _palette_cache = json.load(f)
                return _palette_cache
        except Exception as e:
            log.error(f"Failed to load palette: {e}")

    _palette_cache = _fallback_palette()
    return _palette_cache


def invalidate_palette_cache():
    global _palette_cache
    _palette_cache = None


def build_palette_from_jar(jar_path, output_path):
    """
    Parse a Minecraft client JAR to extract average colors for block textures.
    Saves a JSON dict {block_name: [r,g,b,a]} to output_path. Requires Pillow.
    """
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("Pillow is required for build_palette_from_jar (pip install Pillow)")

    palette = {}
    jar_path = Path(jar_path)
    output_path = Path(output_path)

    try:
        with zipfile.ZipFile(jar_path) as zf:
            for name in zf.namelist():
                if not name.startswith('assets/minecraft/textures/block/'):
                    continue
                if not name.endswith('.png'):
                    continue
                base = Path(name).stem
                # Skip animated/extra textures
                if '_' in base and base.split('_')[-1].isdigit():
                    continue
                try:
                    with zf.open(name) as f:
                        img = Image.open(f).convert('RGBA')
                        # Average non-transparent pixels
                        pixels = img.load()
                        r_sum = g_sum = b_sum = a_sum = 0
                        count = 0
                        for y in range(img.height):
                            for x in range(img.width):
                                px = pixels[x, y]
                                if px[3] < 16:
                                    continue
                                r_sum += px[0]
                                g_sum += px[1]
                                b_sum += px[2]
                                a_sum += px[3]
                                count += 1
                        if count == 0:
                            continue
                        palette[f"minecraft:{base}"] = [
                            r_sum // count,
                            g_sum // count,
                            b_sum // count,
                            a_sum // count,
                        ]
                except Exception:
                    continue
    except Exception as e:
        raise RuntimeError(f"Failed to parse JAR: {e}") from e

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(palette, f, indent=2, sort_keys=True)

    invalidate_palette_cache()
    return palette


def _fallback_palette():
    return {
        'minecraft:stone':       [125, 125, 125, 255],
        'minecraft:dirt':        [134,  96,  67, 255],
        'minecraft:grass_block': [ 91, 169,  59, 255],
        'minecraft:water':       [ 47,  67, 244, 180],
        'minecraft:lava':        [207,  92,  15, 255],
        'minecraft:sand':        [219, 207, 163, 255],
        'minecraft:cobblestone': [127, 127, 127, 255],
        'minecraft:oak_log':     [109,  85,  50, 255],
        'minecraft:oak_planks':  [162, 131,  78, 255],
        'minecraft:oak_leaves':  [ 59, 122,  25, 200],
        'minecraft:bedrock':     [ 85,  85,  85, 255],
        'minecraft:air':         [  0,   0,   0,   0],
    }
