"""
Background editor task registry. Lightweight — actual work runs in a thread
spawned by server.py routes; this module just tracks task state for cancel/poll.
"""

import threading

MAX_TASKS_PER_SERVER = 1


class EditorTask:
    """Represents a background editing task (replace, fill, chunk ops, etc.)."""

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


_active_tasks = {}
_tasks_lock = threading.Lock()


def get_active_tasks(server_id):
    with _tasks_lock:
        return [t for t in _active_tasks.values()
                if t.server_id == server_id and not t.finished]


def get_task(task_id):
    with _tasks_lock:
        return _active_tasks.get(task_id)


def register_task(task):
    with _tasks_lock:
        _active_tasks[task.task_id] = task


def finish_task(task_id):
    with _tasks_lock:
        t = _active_tasks.get(task_id)
        if t:
            t.finished = True
        # Drop finished tasks older than current to avoid unbounded growth
        if len(_active_tasks) > 32:
            for tid in list(_active_tasks.keys()):
                if _active_tasks[tid].finished:
                    _active_tasks.pop(tid, None)


def server_has_active_task(server_id):
    with _tasks_lock:
        return any(
            t.server_id == server_id and not t.finished
            for t in _active_tasks.values()
        )
