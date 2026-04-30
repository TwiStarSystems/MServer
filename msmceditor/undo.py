"""
UndoManager — per-session undo/redo stack for block operations.

Snapshots are stored as compressed serialized chunk NBT (zlib-compressed
encoded chunk bytes). When undoing, the snapshots are decoded and applied
back to the world.
"""

import threading
import zlib
import io

from . import nbt as nbt_mod


def _snapshot_chunk(world, dimension, cx, cz):
    """Capture the current chunk state as compressed bytes. Returns None if missing."""
    chunk = world.get_chunk(cx, cz, dimension)
    if chunk is None:
        return None
    name, tag = chunk
    raw = nbt_mod.encode_chunk(name, tag, compression_type=2)
    return raw


def _restore_chunk(world, dimension, cx, cz, snapshot):
    """Apply a snapshot back to the world. snapshot=None means delete chunk."""
    if snapshot is None:
        world.delete_chunk(cx, cz, dimension)
        # Also clear any cached/dirty version
        with world._lock:
            world._dirty.pop((dimension, cx, cz), None)
            world._chunk_cache.pop((dimension, cx, cz), None)
        return
    name, tag = nbt_mod.load_compressed_chunk(snapshot, 2)
    world.mark_chunk_dirty(cx, cz, dimension, name, tag)


class UndoOp:
    """One undoable operation containing snapshots of all affected chunks."""
    __slots__ = ('label', 'dimension', 'snapshots')

    def __init__(self, label, dimension, snapshots):
        # snapshots: dict {(cx, cz): bytes_or_None}
        self.label = label
        self.dimension = dimension
        self.snapshots = snapshots

    def chunk_count(self):
        return len(self.snapshots)

    def byte_size(self):
        return sum(len(v) for v in self.snapshots.values() if v is not None)


class UndoManager:
    """Per-session undo/redo stacks."""

    def __init__(self, max_history=50):
        self.max_history = max_history
        self._undo = []  # list[UndoOp]
        self._redo = []
        self._lock = threading.RLock()
        self._building = None  # currently-building UndoOp during an operation
        self._building_world = None
        self._building_dim = None

    # ---------- Recording ----------

    def begin(self, world, dimension, label):
        """Start a new recording context. Snapshots taken via record_chunk()."""
        with self._lock:
            self._building = UndoOp(label, dimension, {})
            self._building_world = world
            self._building_dim = dimension

    def record_chunk(self, cx, cz):
        """Capture the pre-edit state of a chunk if not already captured."""
        with self._lock:
            if self._building is None:
                return
            key = (cx, cz)
            if key in self._building.snapshots:
                return
            snap = _snapshot_chunk(self._building_world, self._building_dim, cx, cz)
            self._building.snapshots[key] = snap

    def commit(self):
        """Finalize the current recording and push to undo stack."""
        with self._lock:
            if self._building is None or not self._building.snapshots:
                self._building = None
                self._building_world = None
                self._building_dim = None
                return
            self._undo.append(self._building)
            self._redo.clear()
            while len(self._undo) > self.max_history:
                self._undo.pop(0)
            self._building = None
            self._building_world = None
            self._building_dim = None

    def cancel(self):
        with self._lock:
            self._building = None
            self._building_world = None
            self._building_dim = None

    # ---------- Undo / Redo ----------

    def undo(self, world):
        """Undo the most recent operation. Returns the UndoOp applied or None."""
        with self._lock:
            if not self._undo:
                return None
            op = self._undo.pop()
            # Capture current state for redo
            redo_snapshots = {}
            for (cx, cz) in op.snapshots:
                redo_snapshots[(cx, cz)] = _snapshot_chunk(world, op.dimension, cx, cz)
            self._redo.append(UndoOp(op.label, op.dimension, redo_snapshots))
            # Restore originals
            for (cx, cz), snap in op.snapshots.items():
                _restore_chunk(world, op.dimension, cx, cz, snap)
            return op

    def redo(self, world):
        """Redo the most recently undone operation."""
        with self._lock:
            if not self._redo:
                return None
            op = self._redo.pop()
            undo_snapshots = {}
            for (cx, cz) in op.snapshots:
                undo_snapshots[(cx, cz)] = _snapshot_chunk(world, op.dimension, cx, cz)
            self._undo.append(UndoOp(op.label, op.dimension, undo_snapshots))
            for (cx, cz), snap in op.snapshots.items():
                _restore_chunk(world, op.dimension, cx, cz, snap)
            return op

    # ---------- Status ----------

    def can_undo(self):
        with self._lock:
            return len(self._undo) > 0

    def can_redo(self):
        with self._lock:
            return len(self._redo) > 0

    def history(self):
        with self._lock:
            return {
                'undo': [{'label': op.label, 'chunks': op.chunk_count()} for op in self._undo],
                'redo': [{'label': op.label, 'chunks': op.chunk_count()} for op in self._redo],
            }

    def clear(self):
        with self._lock:
            self._undo.clear()
            self._redo.clear()
            self._building = None
