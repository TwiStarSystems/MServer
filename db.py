"""
db.py — SQLite connection management and schema for MServer.

Usage:
    from db import get_db, init_db

    # Read
    conn = get_db()
    row = conn.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()

    # Write
    conn = get_db()
    conn.execute('INSERT INTO users (...) VALUES (...)', (...))
    conn.commit()

    # Startup
    init_db()   # safe to call every boot — uses CREATE TABLE IF NOT EXISTS
"""

import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

# DB location is operator-overridable via the DB_PATH env var (e.g. to put the
# SQLite file on a separate volume). server.py calls load_dotenv() before
# importing this module, so a value set in .env is visible here. Relative values
# resolve against this file's directory; `~` is expanded.
_db_default = Path(__file__).parent.absolute() / 'msc.db'
_db_env = os.environ.get('DB_PATH', '').strip()
if _db_env:
    _db_path = Path(_db_env).expanduser()
    if not _db_path.is_absolute():
        _db_path = Path(__file__).parent.absolute() / _db_path
    DB_PATH = _db_path.resolve()
else:
    DB_PATH = _db_default.resolve()

# ── Thread-local storage for per-thread connections ──────────────────────────
_local = threading.local()


def get_db() -> sqlite3.Connection:
    """
    Return the SQLite connection for the current thread.
    Creates a new connection on first call per thread.
    WAL mode and foreign-key enforcement are set on every new connection.
    row_factory is sqlite3.Row so columns are accessible by name.
    """
    if not getattr(_local, 'conn', None):
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA foreign_keys=ON')
        # Reasonable busy timeout so concurrent writers retry instead of erroring
        conn.execute('PRAGMA busy_timeout=5000')
        _local.conn = conn
    return _local.conn


# ── Schema DDL ────────────────────────────────────────────────────────────────
_SCHEMA = """
-- Schema version tracking
CREATE TABLE IF NOT EXISTS db_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO db_meta VALUES ('schema_version', '1');

-- ── Permission Groups ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS groups (
    id          TEXT PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL COLLATE NOCASE,
    permissions TEXT NOT NULL DEFAULT '[]',
    is_default  INTEGER NOT NULL DEFAULT 0,
    is_builtin  INTEGER NOT NULL DEFAULT 0,
    priority    INTEGER NOT NULL DEFAULT 0,
    created     TEXT NOT NULL
);

-- ── Users ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id                    TEXT PRIMARY KEY,
    username              TEXT UNIQUE NOT NULL COLLATE NOCASE,
    password              TEXT NOT NULL,
    group_id              TEXT,
    name                  TEXT NOT NULL DEFAULT '',
    email                 TEXT NOT NULL DEFAULT '',
    mfa_enabled           INTEGER NOT NULL DEFAULT 0,
    mfa_secret            TEXT,
    mfa_recovery_code     TEXT,
    approved              INTEGER NOT NULL DEFAULT 0,
    created               TEXT NOT NULL,
    last_login            TEXT,
    failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    account_disabled      INTEGER NOT NULL DEFAULT 0,
    disabled_at           TEXT,
    is_anti_lockout       INTEGER NOT NULL DEFAULT 0,
    notification_prefs    TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE SET NULL
);

-- ── Servers ───────────────────────────────────────────────────────────────────
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

-- ── Backup Schedules ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS backup_schedules (
    server_id         TEXT PRIMARY KEY,
    enabled           INTEGER NOT NULL DEFAULT 0,
    schedule_type     TEXT NOT NULL DEFAULT 'daily',
    hour              INTEGER NOT NULL DEFAULT 3,
    minute            INTEGER NOT NULL DEFAULT 0,
    day_of_week       INTEGER NOT NULL DEFAULT 0,
    cron              TEXT NOT NULL DEFAULT '',
    compression_level INTEGER NOT NULL DEFAULT 6,
    stop_server       INTEGER NOT NULL DEFAULT 1,
    restart_after     INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE
);

-- ── Scheduled Tasks ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id                      TEXT PRIMARY KEY,
    server_id               TEXT NOT NULL,
    name                    TEXT NOT NULL,
    action                  TEXT NOT NULL,
    interval                TEXT,
    enabled                 INTEGER NOT NULL DEFAULT 1,
    command                 TEXT,
    runs                    INTEGER NOT NULL DEFAULT 0,
    run_count               INTEGER NOT NULL DEFAULT 0,
    last_run                TEXT,
    delete_after_execution  INTEGER NOT NULL DEFAULT 0,
    delete_after_runs_count INTEGER NOT NULL DEFAULT 0,
    created                 TEXT NOT NULL,
    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE
);

-- ── Scheduled / Event-Triggered Messages ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS scheduled_messages (
    id          TEXT PRIMARY KEY,
    server_id   TEXT NOT NULL,
    name        TEXT NOT NULL,
    trigger     TEXT NOT NULL,          -- 'cron' or event name: 'backup_start', 'backup_complete', 'server_start', 'server_stop', 'server_crash'
    cron_expr   TEXT,                   -- only for trigger='cron'
    msg_type    TEXT NOT NULL DEFAULT 'say',  -- 'say', 'msg', 'chat' (tellraw), 'title', 'subtitle', 'actionbar'
    target      TEXT NOT NULL DEFAULT '@a',
    message     TEXT NOT NULL,
    color       TEXT NOT NULL DEFAULT 'white',
    bold        INTEGER NOT NULL DEFAULT 0,
    italic      INTEGER NOT NULL DEFAULT 0,
    underlined  INTEGER NOT NULL DEFAULT 0,
    strikethrough INTEGER NOT NULL DEFAULT 0,
    obfuscated  INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 1,
    run_count   INTEGER NOT NULL DEFAULT 0,
    last_run    TEXT,
    created     TEXT NOT NULL,
    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE
);

-- ── Backup Event Log ──────────────────────────────────────────────────────────
-- Replaces per-server backups/<id>/_backup_log.json files
CREATE TABLE IF NOT EXISTS backup_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id   TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    type        TEXT NOT NULL,
    backup_name TEXT,
    size        INTEGER,
    success     INTEGER NOT NULL DEFAULT 1,
    error       TEXT,
    checksum    TEXT,
    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_backup_events_server
    ON backup_events(server_id, timestamp DESC);

-- ── System Stats History ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS stats_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp      TEXT NOT NULL,
    cpu            REAL NOT NULL DEFAULT 0,
    memory_used    INTEGER NOT NULL DEFAULT 0,
    memory_total   INTEGER NOT NULL DEFAULT 0,
    memory_percent REAL NOT NULL DEFAULT 0,
    disk_used      INTEGER NOT NULL DEFAULT 0,
    disk_total     INTEGER NOT NULL DEFAULT 0,
    disk_percent   REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_stats_timestamp ON stats_history(timestamp);

-- ── API Keys ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_keys (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    key_hash    TEXT UNIQUE NOT NULL,
    key_prefix  TEXT NOT NULL DEFAULT '',
    permissions TEXT NOT NULL DEFAULT '[]',
    rate_limit  INTEGER NOT NULL DEFAULT 60,
    created     TEXT NOT NULL,
    expires     TEXT,
    last_used   TEXT,
    use_count   INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 1
);

-- ── API Statistics ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_stats (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    total_requests      INTEGER NOT NULL DEFAULT 0,
    successful_requests INTEGER NOT NULL DEFAULT 0,
    failed_requests     INTEGER NOT NULL DEFAULT 0,
    last_reset          TEXT NOT NULL
);
INSERT OR IGNORE INTO api_stats (id, total_requests, successful_requests, failed_requests, last_reset)
    VALUES (1, 0, 0, 0, datetime('now'));

CREATE TABLE IF NOT EXISTS api_requests_by_key (
    key_id TEXT PRIMARY KEY,
    count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS api_requests_by_endpoint (
    endpoint TEXT PRIMARY KEY,
    count    INTEGER NOT NULL DEFAULT 0
);

-- ── Background Job Queue ──────────────────────────────────────────────────────
-- Tracks long-running operations (backups, restores, deletes, JAR swaps, zips)
-- run by the JobManager. No FK on server_id: a delete_server job must outlive
-- the server row it removes.
CREATE TABLE IF NOT EXISTS jobs (
    id         TEXT PRIMARY KEY,
    type       TEXT NOT NULL,                  -- backup|restore|delete_server|swap_jar|zip_download
    server_id  TEXT,                           -- nullable, no FK (jobs outlive servers)
    title      TEXT NOT NULL,                  -- human label, e.g. "Backup: SurvivalSMP"
    status     TEXT NOT NULL DEFAULT 'queued', -- queued|running|completed|failed|cancelled
    progress   INTEGER NOT NULL DEFAULT 0,     -- 0-100
    message    TEXT,                           -- current step text
    params     TEXT,                           -- JSON input args
    result     TEXT,                           -- JSON output (e.g. {"download": true})
    error      TEXT,
    created_by TEXT,                           -- user_id
    created    TEXT NOT NULL,
    started    TEXT,
    finished   TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_server ON jobs(server_id, created DESC);

-- ── Pending Actions (approval-gated user requests) ───────────────────────────
CREATE TABLE IF NOT EXISTS pending_actions (
    id          TEXT PRIMARY KEY,
    action_type TEXT NOT NULL,              -- registration|serverCreate|serverDelete|serverEdit|serverLifecycle|backupCreate|backupDelete|fileUpload|modManagement|playerManagement
    target_id   TEXT,                       -- server_id or other resource id (null for creation)
    user_id     TEXT NOT NULL,              -- who requested the action
    payload     TEXT NOT NULL DEFAULT '{}', -- JSON: full action parameters
    status      TEXT NOT NULL DEFAULT 'pending', -- pending|approved|rejected
    reviewed_by TEXT,                       -- admin user_id who acted on it
    review_note TEXT,                       -- optional admin comment
    created     TEXT NOT NULL,
    reviewed    TEXT                        -- timestamp of approval/rejection
);
CREATE INDEX IF NOT EXISTS idx_pending_actions_status ON pending_actions(status, created DESC);
CREATE INDEX IF NOT EXISTS idx_pending_actions_user   ON pending_actions(user_id, created DESC);

-- ── Notifications ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notifications (
    id        TEXT PRIMARY KEY,
    user_id   TEXT NOT NULL,                -- recipient user_id
    type      TEXT NOT NULL,                -- approval_request|action_notify|action_approved|action_rejected|system
    title     TEXT NOT NULL,
    message   TEXT NOT NULL DEFAULT '',
    link      TEXT,                         -- optional route to navigate to (e.g. /settings#approvals)
    ref_type  TEXT,                         -- pending_action|server|user (nullable)
    ref_id    TEXT,                         -- id of referenced object (nullable)
    read      INTEGER NOT NULL DEFAULT 0,
    dismissed INTEGER NOT NULL DEFAULT 0,
    created   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, dismissed, created DESC);

-- ── Server Group Access (sharing) ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS server_group_access (
    server_id TEXT NOT NULL,
    group_id  TEXT NOT NULL,
    PRIMARY KEY (server_id, group_id),
    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE,
    FOREIGN KEY (group_id)  REFERENCES groups(id)  ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sga_group ON server_group_access(group_id);
"""


_DEFAULT_USER_PERMISSIONS = json.dumps([
    'servers.view', 'servers.create', 'servers.edit', 'servers.delete',
    'servers.start', 'servers.stop', 'servers.restart', 'servers.console',
    'servers.files.view', 'servers.files.edit',
    'servers.properties.view', 'servers.properties.edit',
    'servers.mods.view', 'servers.mods.manage',
    'servers.backups.view', 'servers.backups.create', 'servers.backups.delete',
    'servers.backups.restore', 'servers.backups.schedule',
    'servers.players.view', 'servers.players.manage',
    'servers.tasks.view', 'servers.tasks.manage',
    'servers.messages.view', 'servers.messages.manage',
    'servers.nbt.view', 'servers.nbt.edit',
])


def _seed_default_groups():
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute(
        '''INSERT OR IGNORE INTO groups (id, name, permissions, is_default, is_builtin, priority, created)
           VALUES (?, ?, ?, 0, 1, 100, ?)''',
        ('builtin-admin', 'Admin', '["*"]', now)
    )
    conn.execute(
        '''INSERT OR IGNORE INTO groups (id, name, permissions, is_default, is_builtin, priority, created)
           VALUES (?, ?, ?, 1, 1, 50, ?)''',
        ('builtin-user', 'User', _DEFAULT_USER_PERMISSIONS, now)
    )
    conn.execute(
        '''INSERT OR IGNORE INTO groups (id, name, permissions, is_default, is_builtin, priority, created)
           VALUES (?, ?, ?, 0, 1, 10, ?)''',
        ('builtin-public', 'Public', '["servers.view"]', now)
    )
    conn.commit()


def init_db():
    """
    Create all tables and indexes if they do not already exist.
    Safe to call on every application startup — all statements use
    CREATE TABLE IF NOT EXISTS / INSERT OR IGNORE.
    """
    conn = get_db()
    conn.executescript(_SCHEMA)
    conn.commit()
    _seed_default_groups()
    recover_interrupted_jobs()


def recover_interrupted_jobs():
    """
    Mark any jobs left in 'queued' or 'running' from a previous run as 'failed'.
    Background jobs do not survive a process restart, so a row still flagged as
    active on boot was interrupted. Safe to call once at startup after init_db().
    """
    conn = get_db()
    conn.execute(
        '''UPDATE jobs
           SET status='failed',
               error=COALESCE(error, 'Interrupted by panel restart'),
               finished=datetime('now')
           WHERE status IN ('queued', 'running')'''
    )
    conn.commit()
