"""
WorldSession + SessionManager — process-wide registry of open JavaWorld instances.

Replaces the amulet-based WorldSession; wraps a JavaWorld plus an UndoManager.
"""

import logging
import shutil
import threading
import time
from pathlib import Path

from .java_world import JavaWorld
from .undo import UndoManager

log = logging.getLogger(__name__)

MAX_SESSIONS = 3
SESSION_IDLE_TIMEOUT = 600  # 10 minutes


class WorldSession:
    """Wraps an open JavaWorld with locking, undo history, and metadata."""

    def __init__(self, server_id, world_path, world):
        self.server_id = server_id
        self.world_path = Path(world_path)
        self.world = world  # JavaWorld
        self.opened_at = time.time()
        self.last_used = time.time()
        self.dirty = False
        self.lock = threading.RLock()
        self.platform = 'java'
        self.version = self._extract_version(world)
        self.dimensions = list(world.dimensions)
        self.undo = UndoManager(max_history=50)

    @staticmethod
    def _extract_version(world):
        try:
            data = world._level_root['Data']
            if 'Version' in data and 'Name' in data['Version']:
                return data['Version']['Name'].value
            if 'Version' in data and 'Id' in data['Version']:
                return f"DataVersion {data['Version']['Id'].value}"
            if 'DataVersion' in data:
                return f"DataVersion {data['DataVersion'].value}"
        except Exception:
            pass
        return None

    def touch(self):
        self.last_used = time.time()

    def close(self):
        try:
            self.world.close()
        except Exception as e:
            log.error(f"Error closing world for {self.server_id}: {e}")


class SessionManager:
    """Process-wide registry of open world sessions."""

    def __init__(self):
        self._sessions = {}
        self._lock = threading.Lock()

    def open(self, server_id, world_path):
        with self._lock:
            existing = self._sessions.get(server_id)
            if existing:
                if str(existing.world_path) == str(world_path):
                    existing.touch()
                    return existing
                # Different world path — close the old session
                existing.close()
                del self._sessions[server_id]

            if len(self._sessions) >= MAX_SESSIONS:
                oldest_id = min(self._sessions, key=lambda k: self._sessions[k].last_used)
                self._sessions[oldest_id].close()
                del self._sessions[oldest_id]

            world = JavaWorld(world_path)
            session = WorldSession(server_id, world_path, world)
            self._sessions[server_id] = session
            return session

    def get(self, server_id):
        session = self._sessions.get(server_id)
        if session:
            session.touch()
        return session

    def close(self, server_id):
        with self._lock:
            session = self._sessions.pop(server_id, None)
            if session:
                session.close()

    def close_all(self):
        with self._lock:
            for s in self._sessions.values():
                s.close()
            self._sessions.clear()

    def evict_idle(self):
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


session_manager = SessionManager()
