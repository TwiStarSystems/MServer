"""
level.dat reader/writer + player data reader/writer.

Uses our own NBT module — no amulet_nbt.
"""

import logging
from pathlib import Path

from . import nbt as nbt_mod

log = logging.getLogger(__name__)


# ==================== level.dat ====================

def _data_compound(root):
    """Java level.dat root has a top-level 'Data' compound."""
    if 'Data' in root:
        return root['Data']
    return root


def read_level_info(session):
    """Read level.dat into a JSON-friendly dict."""
    level_dat_path = session.world_path / 'level.dat'
    if not level_dat_path.exists():
        return None

    try:
        _, root = nbt_mod.load(level_dat_path, gzipped=True)
        data = _data_compound(root)

        info = {}
        _extract(data, info, 'LevelName', 'levelName', str)
        _extract(data, info, 'RandomSeed', 'seed', int)
        _extract(data, info, 'SpawnX', 'spawnX', int)
        _extract(data, info, 'SpawnY', 'spawnY', int)
        _extract(data, info, 'SpawnZ', 'spawnZ', int)
        _extract(data, info, 'DayTime', 'dayTime', int)
        _extract(data, info, 'Time', 'time', int)
        _extract(data, info, 'Difficulty', 'difficulty', int)
        _extract(data, info, 'hardcore', 'hardcore', _to_bool)
        _extract(data, info, 'raining', 'raining', _to_bool)
        _extract(data, info, 'thundering', 'thundering', _to_bool)
        _extract(data, info, 'rainTime', 'rainTime', int)
        _extract(data, info, 'thunderTime', 'thunderTime', int)

        if 'GameRules' in data:
            rules = data['GameRules']
            info['gameRules'] = {}
            for key in rules.keys():
                try:
                    v = rules[key]
                    info['gameRules'][str(key)] = str(v.value) if hasattr(v, 'value') else str(v)
                except Exception:
                    pass

        # Version info
        if 'Version' in data:
            ver = data['Version']
            try:
                info['version'] = ver['Name'].value if 'Name' in ver else None
                info['dataVersion'] = ver['Id'].value if 'Id' in ver else None
            except Exception:
                pass
        elif 'DataVersion' in data:
            try:
                info['dataVersion'] = data['DataVersion'].value
            except Exception:
                pass

        return info
    except Exception as e:
        log.error(f"Failed to read level.dat: {e}")
        return None


# Field name -> (NBT key, NBT tag class, coerce fn)
_LEVEL_FIELD_MAP = {
    'levelName':  ('LevelName',  nbt_mod.StringTag, str),
    'seed':       ('RandomSeed', nbt_mod.LongTag,   int),
    'spawnX':     ('SpawnX',     nbt_mod.IntTag,    int),
    'spawnY':     ('SpawnY',     nbt_mod.IntTag,    int),
    'spawnZ':     ('SpawnZ',     nbt_mod.IntTag,    int),
    'dayTime':    ('DayTime',    nbt_mod.LongTag,   int),
    'time':       ('Time',       nbt_mod.LongTag,   int),
    'difficulty': ('Difficulty', nbt_mod.ByteTag,   int),
    'hardcore':   ('hardcore',   nbt_mod.ByteTag,   lambda v: 1 if v else 0),
    'raining':    ('raining',    nbt_mod.ByteTag,   lambda v: 1 if v else 0),
    'thundering': ('thundering', nbt_mod.ByteTag,   lambda v: 1 if v else 0),
    'rainTime':   ('rainTime',   nbt_mod.IntTag,    int),
    'thunderTime':('thunderTime',nbt_mod.IntTag,    int),
}


def write_level_info(session, updates):
    """Write updated fields back to level.dat."""
    level_dat_path = session.world_path / 'level.dat'
    if not level_dat_path.exists():
        return False

    try:
        name, root = nbt_mod.load(level_dat_path, gzipped=True)
        data = _data_compound(root)

        for key, value in updates.items():
            if key == 'gameRules' and isinstance(value, dict):
                if 'GameRules' not in data:
                    data['GameRules'] = nbt_mod.CompoundTag()
                rules = data['GameRules']
                for rk, rv in value.items():
                    rules[rk] = nbt_mod.StringTag(str(rv))
            elif key in _LEVEL_FIELD_MAP:
                nbt_key, tag_cls, coerce = _LEVEL_FIELD_MAP[key]
                data[nbt_key] = tag_cls(coerce(value))

        nbt_mod.save(name, root, level_dat_path, gzipped=True)
        session.dirty = True
        return True
    except Exception as e:
        log.error(f"Failed to write level.dat: {e}")
        return False


def _extract(data, info, nbt_key, json_key, type_fn):
    if nbt_key not in data:
        return
    try:
        v = data[nbt_key]
        info[json_key] = type_fn(v.value if hasattr(v, 'value') else v)
    except Exception:
        pass


def _to_bool(v):
    return bool(int(v))


# ==================== Players ====================

def _playerdata_dir(world_path):
    """Return the playerdata directory, supporting both legacy and modern layouts.

    Legacy (<=1.21.x): world/playerdata/
    Modern (26.x+):    world/players/data/
    """
    legacy = world_path / 'playerdata'
    if legacy.is_dir():
        return legacy
    return world_path / 'players' / 'data'


def list_players(session):
    """List player UUIDs available in the world."""
    players = []
    pdir = _playerdata_dir(session.world_path)
    if pdir.exists():
        for f in pdir.glob('*.dat'):
            players.append({'uuid': f.stem, 'platform': 'java', 'path': str(f)})
    return players


def read_player(session, player_uuid):
    """Read player data file and return structured info."""
    pf = _playerdata_dir(session.world_path) / f'{player_uuid}.dat'
    if not pf.exists():
        return None

    try:
        _, data = nbt_mod.load(pf, gzipped=True)
        info = {}

        if 'Pos' in data:
            pos = data['Pos']
            try:
                info['position'] = {
                    'x': float(pos[0].value),
                    'y': float(pos[1].value),
                    'z': float(pos[2].value),
                }
            except Exception:
                pass

        _extract(data, info, 'playerGameType', 'gamemode', int)
        _extract(data, info, 'Health',         'health',   float)
        _extract(data, info, 'foodLevel',      'food',     int)
        _extract(data, info, 'XpLevel',        'xpLevel',  int)

        if 'Dimension' in data:
            try:
                dv = data['Dimension']
                info['dimension'] = str(dv.value if hasattr(dv, 'value') else dv)
            except Exception:
                pass

        return info
    except Exception as e:
        log.error(f"Failed to read player data: {e}")
        return None


def write_player(session, player_uuid, updates):
    """Write updates to player data file."""
    pf = _playerdata_dir(session.world_path) / f'{player_uuid}.dat'
    if not pf.exists():
        return False

    try:
        name, data = nbt_mod.load(pf, gzipped=True)

        if 'position' in updates and 'Pos' in data:
            pos = updates['position']
            data['Pos'].value[0] = nbt_mod.DoubleTag(float(pos['x']))
            data['Pos'].value[1] = nbt_mod.DoubleTag(float(pos['y']))
            data['Pos'].value[2] = nbt_mod.DoubleTag(float(pos['z']))

        if 'gamemode' in updates:
            data['playerGameType'] = nbt_mod.IntTag(int(updates['gamemode']))
        if 'health' in updates:
            data['Health'] = nbt_mod.FloatTag(float(updates['health']))
        if 'food' in updates:
            data['foodLevel'] = nbt_mod.IntTag(int(updates['food']))

        nbt_mod.save(name, data, pf, gzipped=True)
        session.dirty = True
        return True
    except Exception as e:
        log.error(f"Failed to write player data: {e}")
        return False
