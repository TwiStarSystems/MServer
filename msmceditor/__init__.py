"""
MSMCeditor — Pure-Python Minecraft world editor backend.

Replaces the amulet-* dependency stack with a self-contained NBT parser,
Anvil region reader/writer, and JavaWorld API. Bedrock support optional
(gated on plyvel).
"""

import logging

log = logging.getLogger(__name__)

# Always available — no compiled deps required for Java worlds.
AVAILABLE = True
AMULET_AVAILABLE = True  # legacy compat: server.py checks this name

try:
    import plyvel  # noqa: F401
    BEDROCK_AVAILABLE = True
except ImportError:
    BEDROCK_AVAILABLE = False


def __getattr__(name):
    """Lazy-import public API to avoid loading every submodule on package import."""
    if name in ('session_manager', 'WorldSession', 'SessionManager'):
        from . import session
        return getattr(session, name)
    if name in ('EditorTask', 'get_active_tasks', 'get_task',
                'register_task', 'finish_task'):
        from . import tasks
        return getattr(tasks, name)
    if name == 'JavaWorld':
        from .java_world import JavaWorld
        return JavaWorld
    if name in ('get_palette', 'invalidate_palette_cache', 'build_palette_from_jar'):
        from . import palette
        return getattr(palette, name)
    if name == 'get_chunk_mesh_data':
        from .renderer import get_chunk_mesh_data
        return get_chunk_mesh_data
    if name == 'discover_worlds':
        from .discovery import discover_worlds
        return discover_worlds
    if name in ('read_level_info', 'write_level_info', 'list_players',
                'read_player', 'write_player'):
        from . import level_info
        return getattr(level_info, name)
    if name in ('get_block_info', 'set_block', 'run_replace', 'run_fill',
                'delete_chunks', 'prune_chunks', 'save_world'):
        from . import ops
        return getattr(ops, name)
    raise AttributeError(f"module 'msmceditor' has no attribute {name!r}")
