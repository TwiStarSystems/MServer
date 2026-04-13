# SQLite Migration Plan

**Status:** Complete (all 7 phases done)  
**Scope:** Migrate all JSON-based persistence to a single SQLite database (`msc.db`)  
**No new dependencies** — Python's built-in `sqlite3` module is used throughout.  
**What stays as files:** `settings.json` (complex nested config, low-write, no relational benefit), `managed.conf` / `canned_commands.conf` per server (filesystem-coupled).

---

## Current JSON Data Stores

| File | Owner Class | Contents |
|------|-------------|----------|
| `users.json` | `UserManager` | User accounts, roles, MFA, lockout state, notification prefs |
| `config.json` | `ServerManager` | Server registrations (name, path, type, version, owner…) |
| `schedules.json` | `BackupScheduler` | Per-server backup schedules |
| `tasks.json` | `TaskScheduler` | Scheduled tasks (start/stop/reboot/command) per server |
| `stats.json` | `StatsManager` | System stats history (CPU, RAM, disk; 7-day rolling) |
| `api_keys.json` | `api_manager.py` | API keys (hashed), permissions, expiry |
| `api_stats.json` | `api_manager.py` | Global API request counters |
| `backups/<id>/_backup_log.json` | `BackupScheduler` | Per-server backup event history |

---

## Target Schema

All tables live in `msc.db` at the project root. WAL journal mode is enabled for safe concurrent access from Flask's threaded server.

```sql
-- Schema version tracking
CREATE TABLE IF NOT EXISTS db_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO db_meta VALUES ('schema_version', '1');

-- ── Users ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id                      TEXT PRIMARY KEY,
    username                TEXT UNIQUE NOT NULL COLLATE NOCASE,
    password                TEXT NOT NULL,
    role                    TEXT NOT NULL DEFAULT 'user',
    name                    TEXT NOT NULL DEFAULT '',
    email                   TEXT NOT NULL DEFAULT '',
    mfa_enabled             INTEGER NOT NULL DEFAULT 0,
    mfa_secret              TEXT,
    mfa_recovery_code       TEXT,
    approved                INTEGER NOT NULL DEFAULT 0,
    created                 TEXT NOT NULL,
    last_login              TEXT,
    failed_login_attempts   INTEGER NOT NULL DEFAULT 0,
    account_disabled        INTEGER NOT NULL DEFAULT 0,
    disabled_at             TEXT,
    is_anti_lockout         INTEGER NOT NULL DEFAULT 0,
    notification_prefs      TEXT NOT NULL DEFAULT '{}'  -- JSON blob
);

-- ── Servers ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS servers (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    server_path TEXT NOT NULL,
    executable  TEXT NOT NULL DEFAULT 'server.jar',
    java_args   TEXT NOT NULL DEFAULT '-Xmx4G -Xms1G',
    server_type TEXT,
    version     TEXT,
    owner       TEXT,
    auto_start  INTEGER NOT NULL DEFAULT 0,
    approved    INTEGER NOT NULL DEFAULT 1,
    category    TEXT NOT NULL DEFAULT 'unmodded',
    created     TEXT NOT NULL
);

-- ── Backup Schedules ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS backup_schedules (
    server_id           TEXT PRIMARY KEY,
    enabled             INTEGER NOT NULL DEFAULT 0,
    schedule_type       TEXT NOT NULL DEFAULT 'daily',
    hour                INTEGER NOT NULL DEFAULT 3,
    minute              INTEGER NOT NULL DEFAULT 0,
    day_of_week         INTEGER NOT NULL DEFAULT 0,
    cron                TEXT NOT NULL DEFAULT '',
    compression_level   INTEGER NOT NULL DEFAULT 6,
    stop_server         INTEGER NOT NULL DEFAULT 1,
    restart_after       INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE
);

-- ── Scheduled Tasks ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id                      TEXT PRIMARY KEY,
    server_id               TEXT NOT NULL,
    name                    TEXT NOT NULL,
    action                  TEXT NOT NULL,       -- START | STOP | REBOOT | COMMAND
    interval                TEXT,               -- cron expression
    enabled                 INTEGER NOT NULL DEFAULT 1,
    command                 TEXT,               -- for COMMAND action
    runs                    INTEGER NOT NULL DEFAULT 0,
    run_count               INTEGER NOT NULL DEFAULT 0,
    last_run                TEXT,
    delete_after_execution  INTEGER NOT NULL DEFAULT 0,
    delete_after_runs_count INTEGER NOT NULL DEFAULT 0,
    created                 TEXT NOT NULL,
    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE
);

-- ── Backup Event Log ────────────────────────────────────────────────────────
-- Replaces per-server backups/<id>/_backup_log.json files
CREATE TABLE IF NOT EXISTS backup_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id   TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    type        TEXT NOT NULL,   -- 'manual' | 'scheduled'
    backup_name TEXT,
    size        INTEGER,
    success     INTEGER NOT NULL DEFAULT 1,
    error       TEXT,
    checksum    TEXT,
    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_backup_events_server ON backup_events(server_id, timestamp DESC);

-- ── System Stats History ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS stats_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    cpu             REAL NOT NULL DEFAULT 0,
    memory_used     INTEGER NOT NULL DEFAULT 0,
    memory_total    INTEGER NOT NULL DEFAULT 0,
    memory_percent  REAL NOT NULL DEFAULT 0,
    disk_used       INTEGER NOT NULL DEFAULT 0,
    disk_total      INTEGER NOT NULL DEFAULT 0,
    disk_percent    REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_stats_timestamp ON stats_history(timestamp);

-- ── API Keys ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_keys (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    key_hash    TEXT UNIQUE NOT NULL,
    permissions TEXT NOT NULL DEFAULT '[]',  -- JSON array
    rate_limit  INTEGER NOT NULL DEFAULT 60,
    created     TEXT NOT NULL,
    expires     TEXT,
    last_used   TEXT,
    use_count   INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 1
);

-- ── API Statistics ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_stats (
    id                   INTEGER PRIMARY KEY CHECK (id = 1),
    total_requests       INTEGER NOT NULL DEFAULT 0,
    successful_requests  INTEGER NOT NULL DEFAULT 0,
    failed_requests      INTEGER NOT NULL DEFAULT 0,
    last_reset           TEXT NOT NULL
);
INSERT OR IGNORE INTO api_stats VALUES (1, 0, 0, 0, datetime('now'));

CREATE TABLE IF NOT EXISTS api_requests_by_key (
    key_id  TEXT PRIMARY KEY,
    count   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS api_requests_by_endpoint (
    endpoint  TEXT PRIMARY KEY,
    count     INTEGER NOT NULL DEFAULT 0
);
```

---

## Database Connection Design

A `db.py` module is introduced at the project root. It owns:
- `DB_PATH` constant
- `get_db()` — returns a thread-local connection with WAL mode, foreign keys, and row_factory set to `sqlite3.Row`
- `init_db()` — runs the schema DDL on first startup
- Context manager `with get_db() as conn` for write transactions

```python
# db.py (outline)
import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(__file__).parent / 'msc.db'
_local = threading.local()

def get_db() -> sqlite3.Connection:
    if not hasattr(_local, 'conn') or _local.conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA foreign_keys=ON')
        _local.conn = conn
    return _local.conn

def init_db():
    """Create schema if not present."""
    conn = get_db()
    conn.executescript(SCHEMA)  # SCHEMA = the DDL string above
    conn.commit()
```

> **Thread safety note:** WAL mode allows concurrent reads and one writer. Each thread gets its own connection via `threading.local`. This matches Flask's threaded request model exactly.

---

## Migration Script

`migrate_to_sqlite.py` is a standalone script (not imported by the app). Run it once on an existing installation before switching to the new code.

```
python3 migrate_to_sqlite.py
```

Steps it performs:
1. Calls `init_db()` to ensure schema exists
2. Reads each JSON file, inserts rows into the corresponding table
3. Handles missing/partial JSON gracefully (skips rows on error, logs them)
4. After success, renames each JSON file to `<name>.json.bak` — the originals are never deleted automatically
5. Prints a summary: `N rows migrated, M skipped`

The app itself also runs an **auto-migration on startup**: if `users.json` exists and the `users` table is empty, it calls the same migration logic automatically. This means existing deployments that simply `git pull` the new code will migrate transparently on next start.

---

## Service Class Changes (File-by-File)

### `db.py` — **NEW FILE**
Full connection management, schema DDL, `init_db()`.

### `server.py`

#### `UserManager`
| Was | Becomes |
|-----|---------|
| `self.users = json.load(USERS_PATH)` | `get_db()` query on startup |
| `_save_users()` writes entire dict back | Individual `UPDATE`/`INSERT` per operation |
| `self.lock` (threading.Lock) | Removed — SQLite WAL handles concurrent writers |
| `_migrate_users()` schema patch loop | Replaced by schema DDL (new columns have defaults) |

Key method changes:
- `authenticate()` → `SELECT WHERE username=? COLLATE NOCASE`, then `UPDATE failed_login_attempts/last_login`
- `register()` / `create_user()` → `INSERT INTO users`
- `get_user()` → `SELECT WHERE id=?`
- `update_user()` → `UPDATE users SET ... WHERE id=?`
- `get_all_users()` → `SELECT * FROM users`

#### `ServerManager`
| Was | Becomes |
|-----|---------|
| `self.config = json.load(CONFIG_PATH)` | Query `servers` table |
| `_save_config()` | `INSERT`/`UPDATE` individual rows |

Key method changes:
- `create_server()` → `INSERT INTO servers`
- `get_server_config()` → `SELECT WHERE id=?`
- `get_servers_list()` → `SELECT * FROM servers`
- `delete_server()` → `DELETE FROM servers WHERE id=?` (cascades to schedules/tasks/events)
- `approve_server()` → `UPDATE servers SET approved=1 WHERE id=?`

#### `BackupScheduler`
| Was | Becomes |
|-----|---------|
| `self.schedules = json.load(SCHEDULES_PATH)` | Query `backup_schedules` |
| `_backup_log.json` per server | `INSERT INTO backup_events` |
| `_load_backup_log()` / `_save_backup_log()` | Removed |

Key method changes:
- `set_schedule()` → `INSERT OR REPLACE INTO backup_schedules`
- `get_schedule()` → `SELECT WHERE server_id=?`
- `delete_schedule()` → `DELETE FROM backup_schedules WHERE server_id=?`
- `_log_backup_event()` → `INSERT INTO backup_events`
- `get_backup_history()` → `SELECT FROM backup_events WHERE server_id=? ORDER BY timestamp DESC LIMIT ?`

#### `TaskScheduler`
| Was | Becomes |
|-----|---------|
| `self.tasks = json.load(TASKS_PATH)` | Query `tasks` table |
| `_save_tasks()` | `UPDATE`/`DELETE` individual rows |

Key method changes:
- `create_task()` → `INSERT INTO tasks`
- `update_task()` → `UPDATE tasks SET ... WHERE id=?`
- `delete_task()` → `DELETE FROM tasks WHERE id=?`
- `get_tasks()` → `SELECT WHERE server_id=?`
- `_restore_tasks()` → `SELECT WHERE enabled=1` (called at startup)
- Run count tracking → `UPDATE tasks SET run_count=run_count+1, last_run=? WHERE id=?`

#### `StatsManager`
| Was | Becomes |
|-----|---------|
| `self.stats = json.load(STATS_PATH)` | No load on startup |
| `_save_stats()` writes whole list | `INSERT INTO stats_history` per tick |
| `_cleanup_old_stats()` list filter | `DELETE FROM stats_history WHERE timestamp < ?` |
| `get_stats_history()` → returns list | `SELECT * FROM stats_history WHERE timestamp > ? ORDER BY timestamp` |

> Stats are the highest-frequency writes (~every 30s). SQLite WAL mode handles this without issue. The `_cleanup_old_stats()` cleanup becomes a periodic `DELETE` instead of writing the entire JSON array.

### `api_manager.py`

| Was | Becomes |
|-----|---------|
| `load_api_keys()` / `save_api_keys()` | `SELECT`/`INSERT`/`UPDATE` on `api_keys` |
| `load_api_stats()` / `save_api_stats()` | `SELECT`/`UPDATE` on `api_stats` tables |
| `increment_api_stats()` reads+rewrites entire JSON | `UPDATE api_stats SET total_requests=total_requests+1` + upsert on per-key/endpoint tables |

`increment_api_stats()` goes from a read-modify-write JSON operation on every request to atomic `UPDATE ... SET count=count+1` — significantly better for concurrent API calls.

---

## What Does NOT Change

| File | Reason |
|------|--------|
| `settings.json` | Complex nested config with SMTP passwords, email templates, webhook secrets. Rarely written. Structure doesn't benefit from relational queries. Keep as-is. |
| `managed.conf` | Per-server flat file in the server directory. Tightly coupled to server file layout. Continue reading/writing on disk. |
| `canned_commands.conf` | Same as above. |
| Backup ZIP files | Binary files in `backups/<id>/`. Storage unchanged. |

---

## Migration Phases

### Phase 1 — `db.py` + Schema
- Create `db.py` with `get_db()`, `init_db()`, schema DDL
- Add `DB_PATH` constant to `server.py`
- Call `init_db()` in the app startup block
- No service class changes yet — app still runs on JSON

### Phase 2 — `migrate_to_sqlite.py`
- Standalone one-shot migration script
- Imports `db.py`, reads all JSON files, bulk-inserts into tables
- Auto-migration hook in `server.py` startup (checks for `users.json` + empty `users` table)

### Phase 3 — `UserManager` + `ServerManager`
- Highest impact, most endpoints touch these two
- Update all methods to SQL, remove JSON load/save
- Run full integration test before proceeding

### Phase 4 — `BackupScheduler` + `TaskScheduler`
- Update schedule/task CRUD and backup event log
- `_backup_log.json` files are superseded — existing log data migrated in Phase 2

### Phase 5 — `StatsManager`
- Switch stats history from JSON array to `stats_history` table
- Update stats API endpoints to query SQLite

### Phase 6 — `api_manager.py`
- Update `load_api_keys`, `save_api_keys`, `increment_api_stats`

### Phase 7 — Cleanup
- Delete `_load_*` / `_save_*` JSON methods from all classes
- Remove `USERS_PATH`, `CONFIG_PATH`, `SCHEDULES_PATH`, `TASKS_PATH`, `STATS_PATH` constants
- Keep `API_KEYS_PATH` / `API_STATS_PATH` references removed from `api_manager.py`
- Add SQLite backup to the existing backup system (copy `msc.db` into server ZIPs if desired)
- Update `TASK-LIST.md`

---

## Risk Notes

| Risk | Mitigation |
|------|-----------|
| Concurrent writes from multiple Flask threads | WAL journal mode; each thread uses its own connection via `threading.local` |
| Migration data loss | JSON files renamed to `.bak`, never deleted; can revert by renaming back |
| `stats.json` large file on old installs | Migration imports all rows; cleanup deletes >7-day-old rows immediately after |
| APScheduler jobs reference in-memory state | `_restore_tasks` and `_restore_schedules` re-read from DB at startup (same as today) |
| Schema changes in future | `db_meta.schema_version` allows future `ALTER TABLE` migrations |

---

## Requirements Changes

No new pip packages. `sqlite3` is part of the Python standard library (Python 3.x).

Optional: consider adding `apsw` (another SQLite wrapper) only if advanced WAL control is needed — not required.
