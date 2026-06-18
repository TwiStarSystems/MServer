# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

MServerController (v3.3.1) is a self-hosted web control panel for managing **Minecraft servers** (Java + Bedrock). It is a Python/Flask backend with a real-time websocket layer and a vanilla-JS multi-page frontend. A single operator host runs the panel; the panel launches, monitors, and manages multiple Minecraft server processes as subprocesses on the same machine.

## Commands

There is **no automated test suite, linter, or build step** — it is a plain Python app with static frontend assets. "Building" means restarting the service so the new files are loaded.

```bash
# --- Local development ---
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python server.py                 # serves on http://localhost:3000
python server.py --port 8080     # custom port (also --host)
# Dev mode (debug, looser cookies) is triggered by FLASK_ENV=development in .env

# --- Syntax check after editing (the only "lint" available) ---
python3 -m py_compile server.py db.py api_manager.py
node --check public/app.js       # if node is present; for JS files

# --- Installer / lifecycle (Debian/Ubuntu, run as root) ---
sudo ./install.sh install        # full install to /opt/mservercontroller + systemd (HTTP only; put your own reverse proxy in front)
sudo ./install.sh update         # pull/update an existing install
sudo ./install.sh status         # health/status report
sudo ./install.sh uninstall

# --- Production service (systemd unit name: mservercontroller) ---
sudo systemctl {start,stop,restart,status} mservercontroller
journalctl -u mservercontroller -f
```

## Architecture

### Backend is a monolith in `server.py` (~10k lines)
Almost all server logic lives in `server.py`. It is organized as a set of **manager classes**, each instantiated once as a module-level singleton near where it is defined. Knowing these singletons is the fastest way to navigate:

| Singleton | Class | Responsibility |
|-----------|-------|----------------|
| `settings_manager` | `SettingsManager` | App settings + branding, persisted to `configs/` |
| `user_manager` | `UserManager` | Users, roles, auth, MFA/TOTP. Defines the `ROLES` hierarchy |
| `server_manager` | `ServerManager` | CRUD for server configs; owns the live `ServerInstance` map |
| (per server) | `ServerInstance` | Wraps one running MC server: subprocess, stdin/stdout, status |
| `backup_scheduler` | `BackupScheduler` | APScheduler-driven automated backups + retention |
| `task_scheduler` | `TaskScheduler` | Scheduled per-server tasks/commands |
| `stats_manager` | `StatsManager` | CPU/RAM/disk sampling (psutil), history |
| `email_service` / `webhook_service` | `EmailService` / `WebhookService` | SMTP + webhook notifications |
| `jar_manager` / `jar_bucket` | `JarVersionManager` / `JarBucketManager` | Server JAR discovery/download. `JarBucketManager` is the current path; `JarVersionManager` is legacy (only `get_versions`/`copy_jar_to_server`/etc. are live) |
| `nbt_editor` | `NBTEditor` | Parse/edit Minecraft NBT (player/world data) |

The `__main__` block calls `parse_arguments()` → `run_server()` → `socketio.run(...)`. The DB and all singletons are initialized at import time (order matters: `settings_manager` before `UserManager`).

### HTTP + realtime layers
- **177 Flask routes** in `server.py`, grouped by prefix: `/api/servers/*` (~87, the bulk — lifecycle, files, mods, players, backups, properties, NBT), `/api/settings/*`, `/api/admin/*`, `/api/auth/*`, `/api/jar-bucket/*`, `/api/tools/*`, `/api/stats`, plus static page routes.
- **Flask-SocketIO** (`socketio`) provides live console/log streaming. Events: `connect`, `disconnect`, `command` (send to a server's stdin), `subscribe` (join a server's output room). Console output is pushed from `ServerInstance` to subscribed clients.
- **`api_manager.py`** defines a separate `api_v1` Blueprint (`/api/v1/*`) — the **public, API-key-authenticated** API (key CRUD, server status/start/stop/restart/command). Registered in `server.py` via `init_api_manager(app)`. This is distinct from the session-authenticated `/api/*` routes the web UI uses.

### Auth & authorization model (security-critical)
Session-cookie auth for the web UI; **role hierarchy** `ROLES = {public:0, user:1, admin:2}`. Decorators in `server.py` enforce access — always use these on new routes:
- `@login_required` — any approved logged-in user.
- `@role_required(min_role)` / `@admin_required` — role-gated.
- `@server_access_required` — **the correct guard for any `/api/servers/<server_id>/...` route**; calls `can_access_server()` = admin OR `server_config.owner == current user`. Using `@login_required` instead on a per-server route is an IDOR.
- `get_current_user()` → `(user_id, user_dict)`.

**Path containment:** per-server file routes use `is_safe_path(base, requested)` to prevent traversal, where `base` is the server's stored `serverPath`. Because that base is trusted, `serverPath` itself must stay inside `SERVERS_DIR` — enforced by `is_server_path_allowed()` at create time and by stripping `serverPath` from `update_server`. Don't reintroduce a user-controlled base directory. Zip extraction of user uploads goes through `safe_extractall()` (rejects `..`, absolute paths, and symlink members) — use it, not `zipfile.extractall`, for any user-supplied archive.

The public REST API (`api_manager.py`) authenticates with SHA-256-hashed API keys generated via `secrets.token_urlsafe`; key permissions are modeled in `APIPermission`.

### Data layer — `db.py`
SQLite at `msc.db` (`DB_PATH`). `get_db()` returns a **thread-local** connection; `init_db()` runs the `_SCHEMA` DDL on every boot (all `CREATE TABLE IF NOT EXISTS`, so it is idempotent and additive). Tables: `users`, `servers`, `backup_schedules`, `tasks`, `backup_events`, `stats_history`, `api_keys`, `api_stats`, `api_requests_by_key`, `api_requests_by_endpoint`, `db_meta`. **All queries are parameterized** — keep them that way. There are no migrations beyond the additive DDL; a column add means editing `_SCHEMA` and handling old rows in code.

### Per-server on-disk layout
Each server lives in its own directory under `SERVERS_DIR` (`servers/<id>/`). A **`managed.conf`** file in that directory is the authoritative record of `Engine`/`Version`/etc. for a panel-managed server (read via `_read_managed_conf`, written via `_write_managed_conf`/`_create_managed_conf`). Server categories: `unmodded`, `modded`, `bedrock` (Bedrock uses a `server.sh` launcher instead of `server.jar`).

### Key path constants (top of `server.py`)
`BASE_DIR`, `SERVERS_DIR` (`servers/`), `BACKUPS_DIR` (`backups/`), `UPLOADS_DIR` (`uploads/`), `RESOURCEPACKS_DIR` (`public/resourcepacks/`), `TOOLS_DIR` (`tools/`), `SERVER_EXECUTABLES_DIR` (`serverexecutables/`), `DB_PATH` (`msc.db`).

### Frontend (`public/`, vanilla JS, no framework/bundler)
Multi-page, classic (non-module) scripts — top-level `function` declarations are global and are wired to HTML via inline `onclick=`/`onsubmit=` or `addEventListener`/event delegation. Pages: `index.html` + `app.js` (main dashboard), `settings.html` + `settings.js` (admin/settings), `login.html` + `login.js` (auth incl. MFA), `public.html` + `public.js` (public read-only status). `utils.js` holds shared helpers including `escapeHtml()` — use it before injecting any user content via `innerHTML`. CSRF tokens (`X-CSRF-Token`) are required on state-changing requests (Flask-WTF).

## Deployment

- **Connection details for the prod hosts are in `docs/servers.md`** (App Server + nginx reverse proxy). The nginx panel config on the proxy lives at `/etc/nginx/live/twistar.org/panel.mc.conf`.
- Production install dir: `/opt/mservercontroller`, owned by `www-data`, run by the `mservercontroller` systemd service using its own `venv`. The live DB (`msc.db`) sits in that directory — **never overwrite it during a deploy**.
- **Prod is NOT a git checkout** — it is plain files. Deploying = copy changed files into `/opt/mservercontroller`, `chown www-data:www-data`, `py_compile` to sanity-check, then `systemctl restart mservercontroller`. Back up the files you replace first (e.g. to `/root/msc_deploy_backup_<ts>`). Verify with `systemctl is-active`, `journalctl`, and `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/` (expect `302` → login).
- Deploying the working tree can ship more than your latest change if prod is behind — diff the remote file against `git show HEAD:<file>` before overwriting.

## Conventions / gotchas

- `server.py` is large; jump via the manager-class list above rather than reading top-to-bottom. Edits should match the surrounding style.
- Adding a per-server endpoint: route it under `/api/servers/<server_id>/...` and guard it with `@server_access_required`.
- Subprocess calls use list-form argv with fixed binaries (no `shell=True`); keep it that way to avoid command injection.
- `version` file holds the app version (`version=3.3.1`); referenced by the UI/update flow.
