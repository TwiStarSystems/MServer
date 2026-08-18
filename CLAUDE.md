# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

MServer (v4.0.0) is a self-hosted web control panel for managing **Minecraft servers** (Java + Bedrock). It is a Python/Flask backend with a real-time websocket layer and a vanilla-JS multi-page frontend. A single operator host runs the panel; the panel launches, monitors, and manages multiple Minecraft server processes as subprocesses on the same machine.

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
sudo ./install.sh install        # full install to /opt/mserver + systemd (HTTP only; put your own reverse proxy in front)
sudo ./install.sh update         # pull/update an existing install
sudo ./install.sh status         # health/status report
sudo ./install.sh uninstall

# --- Production service (systemd unit name: mserver) ---
sudo systemctl {start,stop,restart,status} mserver
journalctl -u mserver -f
```

## Architecture

### Backend is a monolith in `server.py` (~14.5k lines)
Almost all server logic lives in `server.py`. It is organized as a set of **manager classes**, each instantiated once as a module-level singleton near where it is defined. Knowing these singletons is the fastest way to navigate:

| Singleton | Class | Responsibility |
|-----------|-------|----------------|
| `settings_manager` | `SettingsManager` | App settings + branding, persisted to `settings.json` |
| `user_manager` | `UserManager` | Users, auth, MFA/TOTP |
| `group_manager` | `GroupManager` | RBAC groups + their permission lists (`'*'` wildcard = admin group) |
| `server_manager` | `ServerManager` | CRUD for server configs; owns the live `ServerInstance` map |
| (per server) | `ServerInstance` | Wraps one running MC server: subprocess, stdin/stdout, status |
| `backup_scheduler` | `BackupScheduler` | APScheduler-driven automated backups + retention |
| `task_scheduler` | `TaskScheduler` | Scheduled per-server tasks/commands |
| `message_scheduler` | `MessageScheduler` | Cron- and event-triggered in-game announcement messages |
| `stats_manager` | `StatsManager` | CPU/RAM/disk sampling (psutil), history |
| `email_service` / `webhook_service` | `EmailService` / `WebhookService` | SMTP + webhook notifications |
| `notification_manager` | `NotificationManager` | In-app notification bell/dropdown (admin alerts + user feedback) |
| `pending_action_manager` | `PendingActionManager` | Actions queued for admin approval — see policy note below |
| `job_manager` | `JobManager` | Async job queue for long-running ops — see note below |
| `jar_manager` / `jar_bucket` | `JarVersionManager` / `JarBucketManager` | Server JAR discovery/download. `JarBucketManager` is the current path; `JarVersionManager` is legacy (only `get_versions`/`copy_jar_to_server`/etc. are live) |
| `nbt_editor` | `NBTEditor` | Parse/edit Minecraft NBT (player/world data) |

The `__main__` block calls `parse_arguments()` → `run_server()` → `socketio.run(...)`. The DB and all singletons are initialized at import time (order matters: `settings_manager` before `UserManager`).

**Action approval policy.** Many mutating per-server routes (mod install/enable/disable/delete, file upload, backup create/restore, ops/whitelist/ban add-remove) don't execute directly — they call `check_action_policy(action_type, user, payload, execute_fn=...)`, which looks up the admin-configured policy for that action type (`allow` / `notify` / `require_approval`, via `settings_manager.get_policy()`). Admins and `allow`-policy actions run `execute_fn()` immediately; `notify` runs it and pings admins; `require_approval` queues it in `pending_action_manager` (`pending_actions` table) instead of executing, returning the exempt `{'pending': True, 'pendingId': ..., 'message': ...}` shape at 202. An admin approving it via `/api/admin/pending-actions/<id>/approve` then runs the deferred action.

**Background job queue.** Long-running per-server operations (backup create/restore, server delete, JAR swap, zip download prep) submit to `job_manager` instead of blocking the request thread — a bounded `ThreadPoolExecutor` with a per-server lock (jobs on different servers run concurrently; jobs on the same server serialize), persisted in the `jobs` table so history and in-flight jobs survive a restart, with live progress pushed over Socket.IO and pollable via `GET /api/jobs/<id>`. Submitting one returns the exempt `{'started': True, 'jobId': ...}` shape at 202.

### HTTP + realtime layers
- **221 Flask routes** in `server.py`, grouped by prefix: `/api/servers/*` (~99, the bulk — lifecycle, files, mods, players, backups, properties, NBT, tasks, messages), `/api/admin/*` (25), `/api/jar-bucket/*` (18), `/api/settings/*` (22), `/api/auth/*` (16), `/api/tools/*` (6), `/api/notifications/*` (6), `/api/jobs/*` (5), `/api/system/*` (4), `/api/setup/*` (2), `/api/stats`, plus static page routes.
- **Flask-SocketIO** (`socketio`) provides live console/log streaming. Events: `connect`, `disconnect`, `command` (send to a server's stdin), `subscribe` (join a server's output room). Console output is pushed from `ServerInstance` to subscribed clients.
- **`api_manager.py`** defines a separate `api_v1` Blueprint (`/api/v1/*`) — the **public, API-key-authenticated** API (key CRUD, server status/start/stop/restart/command). Registered in `server.py` via `init_api_manager(app)`. This is distinct from the session-authenticated `/api/*` routes the web UI uses.
- **JSON response convention** (issue #28): every JSON response should include a top-level `success` boolean. Use `api_success(data=None, status=200, **extra)` / `api_error(message, status=400, **extra)` (defined near the other route-level helpers, just above the CSRF token endpoint) for new or touched routes — both merge fields flat at the top level, matching the `{'success': True, ...}` shape most routes already use. This is being migrated incrementally as routes are touched, not all at once — don't assume an untouched route already returns `success` on its GET/list responses.

### Auth & authorization model (security-critical)
Session-cookie auth for the web UI; authorization is **group/permission-based** (no role hierarchy): each user belongs to a group (`group_manager`), each group holds a list of permission strings (e.g. `panel.jars.manage`), and the `'*'` wildcard marks an admin group. Decorators in `server.py` enforce access — always use these on new routes:
- `@login_required` — any logged-in user.
- `@permission_required(*perms)` — requires ALL listed permissions (via `user_manager.user_has_permission`); the standard guard for admin/settings routes.
- `@admin_required` — user's group must have the `'*'` wildcard (`group_manager.is_admin_group`).
- `@server_access_required` — **the correct guard for any `/api/servers/<server_id>/...` route**; calls `can_access_server()` = `servers.access.all` permission OR `server_config.owner == current user` OR the user's group is in the server's shared-group list. Using `@login_required` instead on a per-server route is an IDOR.
- `get_current_user()` → `(user_id, user_dict)`.

**Path containment:** per-server file routes use `is_safe_path(base, requested)` to prevent traversal, where `base` is the server's stored `serverPath`. Because that base is trusted, `serverPath` itself must stay inside `SERVERS_DIR` — enforced by `is_server_path_allowed()` at create time and by stripping `serverPath` from `update_server`. Don't reintroduce a user-controlled base directory. Zip extraction of user uploads goes through `safe_extractall()` (rejects `..`, absolute paths, and symlink members) — use it, not `zipfile.extractall`, for any user-supplied archive.

The public REST API (`api_manager.py`) authenticates with SHA-256-hashed API keys generated via `secrets.token_urlsafe`; key permissions are modeled in `APIPermission`.

### Data layer — `db.py`
SQLite at `msc.db` (`DB_PATH`), WAL mode, 5s busy timeout. `get_db()` returns a **thread-local** connection (one per thread, cached for the thread's lifetime); `init_db()` runs the `_SCHEMA` DDL on every boot (all `CREATE TABLE IF NOT EXISTS`, so it is idempotent and additive). Tables: `db_meta`, `groups`, `users`, `servers`, `server_group_access`, `backup_schedules`, `tasks`, `scheduled_messages`, `backup_events`, `stats_history`, `jobs`, `pending_actions`, `notifications`, `api_keys`, `api_stats`, `api_requests_by_key`, `api_requests_by_endpoint`. **All queries are parameterized** — keep them that way. There are no migrations beyond the additive DDL; a column add means editing `_SCHEMA` and handling old rows in code.

**Every write still needs an explicit `conn.commit()`** at its call site — nothing does that for you. What *is* automatic: `server.py` calls `db.rollback_stray_transaction()` in an `@app.teardown_request` hook after every request. A write statement implicitly opens a transaction before it runs, so if it raises (e.g. a caught `UNIQUE` constraint violation) and the handler returns an error response without calling `commit()`/`rollback()`, that transaction — and the WAL write lock it holds — would otherwise stay open on the thread's connection indefinitely, silently blocking every future write app-wide until the process restarts. The teardown hook is a safety net for exactly that case; it does not replace calling `commit()` on the success path.

### Per-server on-disk layout
Each server lives in its own directory under `SERVERS_DIR` (`servers/<id>/`). A **`managed.conf`** file in that directory is the authoritative record of `Engine`/`Version`/etc. for a panel-managed server (read via `_read_managed_conf`, written via `_write_managed_conf`/`_create_managed_conf`). Server categories: `unmodded`, `modded`, `bedrock` (Bedrock uses a `server.sh` launcher instead of `server.jar`).

**Player management is edition-specific.** Java uses `ops.json`/`whitelist.json`/`banned-players.json`/`banned-ips.json`, driven through console commands while the server runs (the server owns those files and would overwrite a direct edit). Bedrock uses `permissions.json` (keyed by **XUID**, not UUID) and `allowlist.json`, and is driven the opposite way: write the file, then send `permission reload` / `allowlist reload` — that is what BDS's own `bedrock_server_how_to.html` prescribes, and unlike Bedrock's `op` it works for offline players. Bedrock has no ban list and no per-player data files at all, so the panel adds two dot-files of its own in the server directory, both on the Bedrock-update preserve list: `BEDROCK_XUID_CACHE` (`.mserver_xuids.json`, gamertag→XUID learned from `Player connected:` console lines — the only XUID source, since Bedrock has no gamertag lookup) and `BEDROCK_BANS_FILE` (`.mserver_bans.json`, the panel's own ban list, enforced by `ServerInstance._enforce_bedrock_ban` kicking on connect). Bedrock helpers live together under the `Bedrock player management` header in `server.py`.

### Key path constants (top of `server.py`)
`BASE_DIR`, `SERVERS_DIR` (`servers/`), `BACKUPS_DIR` (`backups/`), `UPLOADS_DIR` (`uploads/`), `JOBS_TMP_DIR` (`uploads/jobs/` — prepared zip-download artifacts from `JobManager`), `RESOURCEPACKS_DIR` (`public/resourcepacks/`), `TOOLS_DIR` (`tools/`), `DB_PATH` (`msc.db`), `SETTINGS_PATH` (`settings.json`), `JAR_URLS_PATH` (`configs/jarurls.conf`), `VERSION_FILE` (`version`). `SERVER_EXECUTABLES_DIR` (`serverexecutables/`) is defined separately, near `JarBucketManager`.

### Frontend (`public/`, vanilla JS, no framework/bundler)
Multi-page, classic (non-module) scripts — top-level `function` declarations are global and are wired to HTML via inline `onclick=`/`onsubmit=` or `addEventListener`/event delegation. Pages: `index.html` + `app.js` (main dashboard), `settings.html` + `settings.js` (admin/settings), `login.html` + `login.js` (auth incl. MFA), `public.html` + `public.js` (public read-only status), `setup.html` + `setup.js` (first-run admin-creation wizard, gated server-side by `needs_setup()`). `utils.js` holds shared helpers including `escapeHtml()` — use it before injecting any user content via `innerHTML`. `notifications.js` is the shared notification bell/dropdown, included on `index.html` and `settings.html`. CSRF tokens (`X-CSRF-Token`) are required on state-changing requests (Flask-WTF).

## Deployment

- **Connection details for the prod hosts are in `servers.md`** (App Server + nginx reverse proxy). The nginx panel config on the proxy lives at `/etc/nginx/live/twistar.org/panel.mc.conf`.
- Production install dir: `/opt/mserver`, owned by `www-data`, run by the `mserver` systemd service using its own `venv`. The live DB (`msc.db`) sits in that directory — **never overwrite it during a deploy**.
- **Prod is NOT a git checkout** — it is plain files. Deploying = copy changed files into `/opt/mserver`, `chown www-data:www-data`, `py_compile` to sanity-check, then `systemctl restart mserver`. Back up the files you replace first (e.g. to `/root/msc_deploy_backup_<ts>`). Verify with `systemctl is-active`, `journalctl`, and `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/` (expect `302` → login).
- Deploying the working tree can ship more than your latest change if prod is behind — diff the remote file against `git show HEAD:<file>` before overwriting.

## Bug-fix workflow

Issues are tracked on GitHub (`TwiStarSystems/MServer`). For each bug, work the full cycle before moving to the next issue:

1. **Find** — `gh issue view <n>` to read the report (root cause/fix are often already diagnosed in the issue body).
2. **Fix** — make the minimal code change that addresses the root cause.
3. **Verify** — `python3 -m py_compile server.py db.py api_manager.py` (and `node --check` for JS touched); exercise the affected flow when practical.
4. **Commit** — one commit per fix, referencing the issue.
5. **Deploy** — ship to prod per the Deployment section below.
6. **Close** — `gh issue close <n>` with a comment referencing the commit.

## Conventions / gotchas

- `server.py` is large; jump via the manager-class list above rather than reading top-to-bottom. Edits should match the surrounding style.
- Adding a per-server endpoint: route it under `/api/servers/<server_id>/...` and guard it with `@server_access_required`.
- Subprocess calls use list-form argv with fixed binaries (no `shell=True`); keep it that way to avoid command injection.
- `version` file holds the app version (`version=4.0.0`); referenced by the UI/update flow.
