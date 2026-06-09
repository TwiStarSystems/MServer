# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

MServerController is a web-based panel for creating, running, and managing multiple Minecraft servers (Java + Bedrock) from one dashboard. Python/Flask + Flask-SocketIO backend, vanilla-JS frontend, SQLite for state. It spawns and supervises Minecraft server subprocesses and streams their console over WebSocket.

## Running & Development

The `install.sh` script is the single entry point for all environments (it shows an interactive menu, or takes a subcommand):

```bash
./install.sh dev            # Local dev: creates venv, installs deps, writes a dev .env (FLASK_ENV=development), runs on :3000. No sudo.
sudo ./install.sh install   # Fresh production install to /opt/mservercontroller + nginx + systemd
sudo ./install.sh update    # Update install, preserving data (servers/backups/settings/db)
sudo ./install.sh quick-update  # Copy app files only, no dep reinstall — fast iteration on an existing install
sudo ./install.sh status
sudo ./install.sh uninstall
```

Run directly during development (after `source venv/bin/activate`):

```bash
python server.py            # Serves on http://localhost:3000
python server.py --host 0.0.0.0 --port 8080
```

- **No test suite, linter, or build step exists.** Verify changes by running the app.
- Default login is `admin` / `admin` (created on first boot) — change immediately.
- Production runs behind nginx (`nginx.conf`) as the `mservercontroller` systemd service. Logs: `journalctl -u mservercontroller -f`.
- Releases: `./git-release.sh` bumps the `version` file (format `version=X.Y.Z`), commits, tags, and pushes; `.github/workflows/release.yml` builds the GitHub release.

## Architecture

This is a **monolith**: nearly all backend logic lives in `server.py` (~10k lines). Treat the file as a collection of subsystems rather than a small module.

**Core files:**
- `server.py` — Flask app, all manager classes, all HTTP routes, all Socket.IO handlers, and the entry point. Constants near the top (`BASE_DIR`, `SERVERS_DIR`, `BACKUPS_DIR`, etc.) define the on-disk layout.
- `db.py` — SQLite (`msc.db`). `get_db()` returns a **thread-local** connection (WAL mode, foreign keys on, `sqlite3.Row`). `init_db()` runs at import time and is idempotent (`CREATE TABLE IF NOT EXISTS`). Tables: `users`, `servers`, `backup_schedules`, `tasks`, `backup_events`, `stats_history`, `api_keys`, `api_stats`, `api_requests_by_*`.
- `api_manager.py` — Public REST API v1 (`/api/v1/...`) as a Flask Blueprint with its own API-key auth, permissions (`APIPermission`), and rate limiting. Registered onto the app in `server.py`.

**Where state lives — this matters:**
- Server definitions, users, tasks, schedules, API keys, stats, and backup-event history → **SQLite** (`msc.db`, project root). This was migrated from per-feature JSON files (`users.json`, `config.json`, `schedules.json`, `tasks.json`, `stats.json`, `api_keys.json`, `api_stats.json`, `_backup_log.json`) — **do not reintroduce JSON config for these.** Use `ServerManager`/`UserManager`/etc. methods, which query SQLite directly. WAL mode + a thread-local connection per request handle Flask's threaded model; there is no app-level write lock. `db_meta.schema_version` exists for future `ALTER TABLE` migrations. The old standalone `migrate_to_sqlite.py` has been removed.
- **App settings** (branding, SMTP creds, MFA policy, webhook secrets, email templates, app toggles) → `settings.json`, managed by `SettingsManager`. Kept as a file deliberately: nested, low-write, no relational benefit. NOT in the database.
- **Per-server flat files** live inside each server's own directory and are read/written on disk (not DB), because they're coupled to the server's filesystem:
  - `servers/<id>/managed.conf` — managed-server marker + metadata (engine, owner, version, port, AutoStart). Read/written via `_read_managed_conf` / `_write_managed_conf`.
  - `servers/<id>/canned_commands.conf` — saved per-server console commands (`_ensure_canned_commands_conf` creates it lazily for older servers).
  - plus the server's actual Minecraft files (`server.properties`, world, jar, mods/plugins).
- Backups are ZIPs under `backups/<id>/` (with `.sha256` sidecars); the SQLite `backup_events` table holds the history/log.

**Key classes in `server.py`** (each section is delimited by a `# ====` banner comment): `SettingsManager`, `EmailService`, `WebhookService`, `StatsManager`, `BackupScheduler`, `TaskScheduler` (both APScheduler-based), `UserManager`, `JarVersionManager`, `NBTEditor`, `JarBucketManager`, and the central pair `ServerManager` (owns all servers, talks to SQLite) + `ServerInstance` (one running Minecraft subprocess — holds the `process`, output buffer, status, online players, and a status-monitor thread).

**Realtime model:** Socket.IO runs in **threading async mode** (no gevent/eventlet monkey-patching) — it composes with the subprocess/thread-per-server design. Handlers: `connect`, `disconnect`, `command` (send to a server), `subscribe` (join a server's output room). Console output and 10s system stats are pushed to clients. For higher load, deploy under gunicorn with threads (`gunicorn -w 1 --threads 100 "server:app"`) — single worker only, since `ServerInstance` state is in-process.

**Frontend** (`public/`, plain JS, no framework/bundler): `index.html` + `app.js` (main panel), `settings.html` + `settings.js` (admin settings), `login.html`/`login.js`, `public.html`/`public.js` (public status page), `styles.css`. Edit these files directly; they are served statically by Flask.

## Conventions & Gotchas

- **Auth/RBAC:** decorators `@login_required`, `@admin_required`, `@role_required(...)`, `@server_access_required` gate routes. Three roles: admin / moderator / user; non-admins only see servers they're granted access to. Honor these when adding routes.
- **CSRF:** Flask-WTF protects all state-changing endpoints. Only pre-auth routes (login/register/MFA-verify/logout/csrf-token) are `@csrf.exempt`. New mutating UI endpoints need a CSRF token; the public `/api/v1` Blueprint uses API-key auth instead.
- **Path safety:** all file operations must go through `is_safe_path()` / `secure_filename` and verify the resolved path stays within the server's directory. Backup/file routes already do explicit `.startswith(BACKUPS_DIR.resolve())` checks — follow that pattern.
- **MC version eras:** use `mc_version_is_modern()` / `mc_version_is_legacy()` / `compare_mc_versions()` helpers when branching on Minecraft version; the modern world/NBT format differs from legacy.
- **Managed servers:** `ServerManager.MANAGED_CONF_REQUIRED_FIELDS` defines fields required for managed-mode servers — keep it in sync when changing the managed-conf shape.
- **Graceful shutdown:** `_graceful_shutdown` (registered on SIGTERM/SIGINT/atexit) sends `stop` to all running servers and waits up to 60s before exit; preserve this when touching process lifecycle.
- **CLI surface is tiny:** `parse_arguments()` only accepts `--host` and `--port`. There is **no** `--mode`/`--node-id`/`--ssl-cert` — see "Stale docs" below.

## Security model (as actually implemented)

- **Passwords:** min 12 chars, requiring upper + lower + digit — enforced server-side on register, password change, AND admin reset.
- **Sessions:** `HttpOnly`, `SameSite=Lax`; `SESSION_COOKIE_SECURE` is driven by env (`true` when behind HTTPS). Lifetime defaults to 7 days (`PERMANENT_SESSION_LIFETIME`).
- **Rate limits (Flask-Limiter, HTTP only — sockets are NOT limited):** login 10/min, register 5/hr, MFA 10/min, uploads 10–20/15min, backup create 5/15min, default 100/15min.
- **MFA:** TOTP (pyotp) + QR provisioning + hashed recovery codes; 5-minute window to complete login verification; policy enforceable for admins-only or all users.
- **API keys:** SHA-256 hashed at rest, shown once on creation; permissions = `read`/`write`/`servers`/`console`/`players`/`admin`; sent via `X-API-Key` header or `?api_key=`.
- **Anti-lockout:** if all admins get disabled (5 failed logins disables an account), an emergency `emergency_admin_*` account is auto-created and printed to console only (the old `anti_lockout_credentials.log` file write was removed).
- **Security headers** are added in `add_security_headers` (`@app.after_request`): X-Frame-Options, X-Content-Type-Options, CSP, HSTS, Referrer-Policy. (`Permissions-Policy` is currently missing — see open issues.)
- **TLS** is terminated at nginx, not the app — there are no in-process SSL CLI flags.

## Deployment topology

- Production install dir: `/opt/mservercontroller`, run as systemd unit `mservercontroller`, behind nginx.
- App host (twistar.org deployment): `172.16.5.2`; nginx reverse-proxy host: `172.16.6.50`. The live nginx site config is at `/etc/nginx/live/twistar.org/panel.mc.conf` (the repo `nginx.conf` is the template). Detailed connection notes are in `docs/servers.md`.
- Versioning: SemVer in the root `version` file (`version=X.Y.Z`, read by `read_version_file()`, exposed at `GET /api/system/version`). `./git-release.sh` automates bump/commit/tag/push; pushing a `v*` tag triggers `.github/workflows/release.yml` to publish a GitHub release with an auto-generated changelog. Note: there is **no** in-app auto-update/"check for updates" feature despite what some docs claim.

## Stale docs — DO NOT TRUST (verified against current `main`, 2026-06-08)

`docs/` contains older design notes describing features that were **removed or never built**. Ignore these for current behavior:
- **BlueMap / World Map** (`docs/update-maps.md`) — fully removed; zero references remain in `server.py` or `public/`.
- **Central/Client "distributed" mode, Master–Slave nodes, Fernet payload encryption, load balancing** (`docs/REFACTORING.md`, `docs/IMPLEMENTATION_STATUS.md`, `docs/COMPLETION_SUMMARY.md`, `docs/SECURITY.md`) — never implemented (or removed). `server_core.py`/`server_client.py` do not exist; `--mode`/`--node-id`/`--ssl-cert` are not real flags despite docs showing them.
- **In-app auto-update system** (`docs/VERSION_FILE_GUIDE.md`, `docs/RELEASE_VERSIONING_GUIDE.md`) — not implemented; the `get_remote_version_file()` it references is dead code.
- Any doc referencing JSON stores (`users.json`, `config.json`, `api_stats.json`, etc.) predates the SQLite migration — see "Where state lives" above for the current model.
- `docs/SQLITE_MIGRATION_PLAN.md` is accurate and matches the current schema. The `docs/SECURITY_QUICK_REFERENCE.md` security facts are accurate except its JSON-file and `--ssl-cert`/`anti_lockout_credentials.log` references.
