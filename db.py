"""
db.py — SQLite connection management and schema for MServerController.

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

import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(__file__).parent.absolute() / 'msc.db'

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

-- ── Users ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id                    TEXT PRIMARY KEY,
    username              TEXT UNIQUE NOT NULL COLLATE NOCASE,
    password              TEXT NOT NULL,
    role                  TEXT NOT NULL DEFAULT 'user',
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
    notification_prefs    TEXT NOT NULL DEFAULT '{}'
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
"""


def init_db():
    """
    Create all tables and indexes if they do not already exist.
    Safe to call on every application startup — all statements use
    CREATE TABLE IF NOT EXISTS / INSERT OR IGNORE.
    """
    conn = get_db()
    conn.executescript(_SCHEMA)
    conn.commit()
