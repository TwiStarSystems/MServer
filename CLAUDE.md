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
venv/bin/python -m pyflakes server.py db.py api_manager.py   # optional; pyflakes is in the dev venv, not requirements.txt

# --- Release ---
./git-release.sh                 # bumps the `version` file, commits, tags vX.Y.Z, pushes;
                                 # the tag triggers .github/workflows/release.yml (GitHub Release + changelog)

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

### Backend is a monolith in `server.py` (~17.9k lines)
Almost all server logic lives in `server.py`. It is organized as a set of **manager classes**, each instantiated once as a module-level singleton near where it is defined. Knowing these singletons is the fastest way to navigate:

| Singleton | Class | Responsibility |
|-----------|-------|----------------|
| `settings_manager` | `SettingsManager` | App settings + branding, persisted to `settings.json` |
| `user_manager` | `UserManager` | Users, auth, MFA/TOTP |
| `group_manager` | `GroupManager` | RBAC groups + their permission lists (`'*'` wildcard = admin group) |
| `server_manager` | `ServerManager` | CRUD for server configs; owns the live `ServerInstance` map |
| (per server) | `ServerInstance` | Wraps one running MC server: subprocess, stdin/stdout, status, resource sampling, crash/hang detection |
| `crash_supervisor` | `CrashSupervisor` | In-memory per-server auto-restart budget over a sliding window (keyed by server id because a new `ServerInstance` is built on every start) |
| `rollback_manager` | `RollbackManager` | Rollback points: the record of which backup was taken before a risky change (`rollback_points` table) |
| `template_manager` | `TemplateManager` | Reusable server recipes — config + `server.properties` snapshot, never world data (`server_templates` table) |
| `backup_scheduler` | `BackupScheduler` | APScheduler-driven automated backups + retention |
| `task_scheduler` | `TaskScheduler` | Scheduled per-server tasks/commands |
| `message_scheduler` | `MessageScheduler` | Cron- and event-triggered in-game announcement messages |
| `stats_manager` | `StatsManager` | CPU/RAM/disk sampling (psutil), history |
| `email_service` / `webhook_service` | `EmailService` / `WebhookService` | SMTP + webhook notifications |
| `notification_manager` | `NotificationManager` | In-app notification bell/dropdown (admin alerts + user feedback) |
| `pending_action_manager` | `PendingActionManager` | Actions queued for admin approval — see policy note below |
| `job_manager` | `JobManager` | Async job queue for long-running ops — see note below |
| `jar_manager` / `jar_bucket` | `JarVersionManager` / `JarBucketManager` | Server JAR discovery/download. `JarBucketManager` is the current path; `JarVersionManager` is legacy (only `get_local_jar_info`/`copy_jar_to_server` are still live) |
| `nbt_editor` | `NBTEditor` | Parse/edit Minecraft NBT (player/world data) |

The `__main__` block calls `parse_arguments()` → `run_server()` → `socketio.run(...)`. The DB and all singletons are initialized at import time (order matters: `settings_manager` before `UserManager`). Because every manager, the live `ServerInstance` map, the job pool and the rate-limit counters are in-process state, the app must run as **one process** (threads are fine; `gunicorn -w 1` only).

**Configuration comes from `.env`** via the typed helpers at the top of `server.py` (`_env_str` / `_env_int` / `_env_bool` / `_env_path`) — use them rather than raw `os.environ` reads. `.env.example` documents every key. `SERVERS_DIR`, `BACKUPS_DIR` and `DB_PATH` are operator-overridable; the crash/limit tunables (`CRASH_*`, `HANG_RESTART_SECONDS`, `ROLLBACK_HEALTH_WINDOW_SECONDS`, `RESOURCE_*`) sit beside the path constants.

**Server lifecycle, crashes and limits (issue #40).** `ServerInstance._intentional_stop` is the whole basis of crash detection: `stop()`, `kill()`, a console `stop`, and the limit/hang handlers set it, and `_monitor_process` treats any exit with it still `False` as a crash (so an in-game `/stop` counts as one). Any new code path that ends a server process must go through `ServerManager.stop_server`/`kill_server` or set the flag itself, or auto-restart will undo it. A crash fails the server's open rollback point (`rollback_manager.mark_crashed`); surviving `ROLLBACK_HEALTH_WINDOW_SECONDS` verifies it and resets the crash budget. Per-server limits live on the `servers` row (`memory_limit_mb`, `cpu_limit_percent`, `limit_action`, `auto_restart`, `restart_attempts`), are clamped in `ServerManager.update_server`, and are read fresh at each start: memory becomes the JVM `-Xmx` plus an RSS sampler, CPU becomes an affinity mask. The rollback/template/resources/limits work is **backend-only so far** — nothing in `public/` calls `/api/templates*`, `/rollback-points*` or `/resources` yet.

**Action approval policy.** Many mutating per-server routes (mod install/enable/disable/delete, file upload, backup create/restore, ops/whitelist/ban add-remove) don't execute directly — they call `check_action_policy(action_type, user, payload, execute_fn=...)`, which looks up the admin-configured policy for that action type (`allow` / `notify` / `require_approval`, via `settings_manager.get_policy()`). Admins and `allow`-policy actions run `execute_fn()` immediately; `notify` runs it and pings admins; `require_approval` queues it in `pending_action_manager` (`pending_actions` table) instead of executing, returning the exempt `{'pending': True, 'pendingId': ..., 'message': ...}` shape at 202. An admin approving it via `/api/admin/pending-actions/<id>/approve` then runs the deferred action.

**Background job queue.** Long-running per-server operations (backup create/restore, server delete, zip download prep) submit to `job_manager` instead of blocking the request thread — a bounded `ThreadPoolExecutor` with a per-server lock (jobs on different servers run concurrently; jobs on the same server serialize), persisted in the `jobs` table so history and in-flight jobs survive a restart, with live progress pushed over Socket.IO and pollable via `GET /api/jobs/<id>`. Submitting one returns the exempt `{'started': True, 'jobId': ...}` shape at 202. Registered job types: `backup`, `restore`, `rollback`, `delete_server`, `zip_download`, `jar_download`. Handlers assume their params were validated by the submitting route, and a job can run long after it was queued — so the server may be gone by then: `ServerManager.get_server_path()` raises `LookupError` for an unknown id (it must never fall back to a shared parent directory), which fails the job cleanly. Validate an archive before deleting what it is meant to replace.

### HTTP + realtime layers
- **229 Flask routes** in `server.py`, grouped by prefix: `/api/servers/*` (104, the bulk — lifecycle, files, mods, players, backups, rollback points, resources, properties, NBT, tasks, messages), `/api/admin/*` (25), `/api/settings/*` (22), `/api/jar-bucket/*` (18), `/api/auth/*` (16), `/api/templates/*` (8), `/api/tools/*` (6), `/api/notifications/*` (6), `/api/jobs/*` (5), `/api/system/*` (4), `/api/setup/*` (2), `/api/stats/*` (2), plus static page routes.
- **Flask-SocketIO** (`socketio`) provides live console/log streaming. Events: `connect`, `disconnect`, `command` (send to a server's stdin), `subscribe` (join a server's output room). Access is enforced by **room membership**, not client-side filtering: `server_<id>` (console/status, joined only after the same check as `can_access_server`), `user_<id>` (notifications, job events), `admins` (all job events), `stats_viewers` (host stats). Rooms are assigned at connect, so anything that can shrink a user's access must call `_resync_user_rooms(user_id)` / `_resync_all_connected_rooms()`.
- **`api_manager.py`** registers two Blueprints under `/api/v1/*`: `api_v1` — the **public, API-key-authenticated**, CSRF-exempt API (server list/status/start/stop/restart/command, `/docs`) — and `api_v1_admin` — the session-authenticated, admin-only, CSRF-protected key management (`/keys`, `/stats`). It never imports from `server.py`; its dependencies are injected by `init_api_manager(app, server_manager, get_current_user, group_manager, read_version_file)`, because the app runs as `__main__` and a `from server import` would re-execute the whole module. New `api_v1` routes need `@require_api_key(permissions=[...])`.
- **Rate limiting**: Flask-Limiter's `default_limits` (`RATE_LIMIT_DEFAULT`, default `100 per 15 minutes`) applies to **every route, counted per endpoint per client IP** — including `/api/v1/*`. A route the UI polls, or re-reads on socket events, must carry `@limiter.limit(POLLED_READ_LIMIT)` instead (the dashboard polls `/api/servers` every 10s — 90 per default window from one tab). `/api/v1` has its own per-IP ceiling (`RATE_LIMIT_API_V1`) on top of each key's limit. 429s are returned as JSON. Socket events are throttled separately by `_socket_rate_limited`, and the socket only accepts the panel's own origin unless `CORS_ORIGINS` lists others (`*` is treated as unset).
- **JSON response convention** (issue #28): every JSON response should include a top-level `success` boolean. Use `api_success(data=None, status=200, **extra)` / `api_error(message, status=400, **extra)` (defined near the other route-level helpers, just above the CSRF token endpoint) for new or touched routes — both merge fields flat at the top level, matching the `{'success': True, ...}` shape most routes already use. This is being migrated incrementally as routes are touched, not all at once — don't assume an untouched route already returns `success` on its GET/list responses.

### Auth & authorization model (security-critical)
Session-cookie auth for the web UI; authorization is **group/permission-based** (no role hierarchy): each user belongs to a group (`group_manager`), each group holds a list of permission strings (e.g. `panel.jars.manage`), and the `'*'` wildcard marks an admin group. Decorators in `server.py` enforce access — always use these on new routes:
- `@login_required` — any logged-in user.
- `@permission_required(*perms)` — requires ALL listed permissions (via `user_manager.user_has_permission`); the standard guard for admin/settings routes.
- `@admin_required` — user's group must have the `'*'` wildcard (`group_manager.is_admin_group`).
- `@server_access_required` — **the correct guard for any `/api/servers/<server_id>/...` route**; calls `can_access_server()` = `servers.access.all` permission OR `server_config.owner == current user` OR the user's group is in the server's shared-group list. Using `@login_required` instead on a per-server route is an IDOR.
- `get_current_user()` → `(user_id, user_dict)`. Sessions are signed client-side cookies with no server-side record, so revocation works by comparison: the session carries `_session_stamp(user)` (a digest of the password hash + MFA secret) and `get_current_user()` rejects a mismatch. Always open a full session with `_begin_session(user_id)`, and call `_restamp_session()` after a route changes the *current* user's own password or MFA — otherwise that user is logged out by their own request. Logout itself still cannot revoke a copied cookie (#104).

**Permissions that are admin-equivalent in practice.** `GroupManager.ALL_PERMISSIONS` is the catalog (keep `db._DEFAULT_USER_PERMISSIONS` in sync), and `.*` prefix wildcards are honoured. Two non-`'*'` permissions still reach full control and should be granted as if they were admin: `panel.tools.manage` (runs uploaded Python as the panel user) and `panel.settings.manage` (`footerAddition` is injected as raw HTML for every user; email templates are operator-editable and must stay in the Jinja2 sandbox). `panel.users.manage` and `panel.groups.manage` are safe to delegate only because their routes refuse to act on admins: `_admin_target_denied()` (admin accounts), `_admin_group_denied()` (groups holding `'*'`) and `_group_grant_error()` (no wildcards, nothing the caller lacks) — use them on any new user/group route. Likewise anyone who can run a server (`servers.create`, or access to one) executes arbitrary JARs/`server.sh` as the same OS user as the panel — there is no sandbox between a Minecraft server process and `msc.db`/`.env`. When adding a route under one of these permissions, decide explicitly whether it also needs `_actor_is_admin()` (the pattern used for assigning the admin group).

**Path containment:** per-server file routes use `is_safe_path(base, requested)` to prevent traversal, where `base` is the server's stored `serverPath`. Because that base is trusted, `serverPath` itself must stay inside `SERVERS_DIR` — enforced at create time by `is_server_path_allowed()` (strictly inside `SERVERS_DIR`) plus `server_path_conflict()` (no overlap with another server's directory; a custom path also needs `servers.access.all`), and by stripping `serverPath` from `update_server`. `@server_access_required` also 404s a server id that has no row. Don't reintroduce a user-controlled base directory. Use `is_safe_path()` for any new containment check; the older `str(path).startswith(str(base))` idiom still present in the backup/tools routes is a prefix match (`/x/servers` also matches `/x/servers-old`) and only holds there because the name went through `secure_filename()` first. Zip extraction of user uploads goes through `safe_extractall()` (rejects `..`, absolute paths, and symlink members) — use it, not `zipfile.extractall`, for any user-supplied archive.

The public REST API (`api_manager.py`) authenticates with SHA-256-hashed API keys generated via `secrets.token_urlsafe`; key permissions are modeled in `APIPermission`.

### Data layer — `db.py`
SQLite at `msc.db` (`DB_PATH`), WAL mode, 5s busy timeout. `get_db()` returns a **thread-local** connection (one per thread, cached for the thread's lifetime); `init_db()` runs the `_SCHEMA` DDL on every boot (all `CREATE TABLE IF NOT EXISTS`, so it is idempotent and additive). Tables: `db_meta`, `groups`, `users`, `servers`, `server_group_access`, `backup_schedules`, `tasks`, `scheduled_messages`, `backup_events`, `stats_history`, `jobs`, `pending_actions`, `notifications`, `rollback_points`, `server_templates`, `api_keys`, `api_stats`, `api_requests_by_key`, `api_requests_by_endpoint`. **All queries are parameterized** — keep them that way. Migrations are additive only: a new table goes in `_SCHEMA`; a new column on an existing table goes in `_SCHEMA` **and** in `_COLUMN_MIGRATIONS` (applied by `_apply_column_migrations()` on boot via `ALTER TABLE ADD COLUMN`, so a `NOT NULL` column needs a default). Read such columns with `_row_get(row, key, default)` in `server.py`. Background threads (monitors, schedulers, job workers) each get their own connection and have no teardown hook — commit or roll back explicitly there.

**Every write still needs an explicit `conn.commit()`** at its call site — nothing does that for you. What *is* automatic: `server.py` calls `db.rollback_stray_transaction()` in an `@app.teardown_request` hook after every request. A write statement implicitly opens a transaction before it runs, so if it raises (e.g. a caught `UNIQUE` constraint violation) and the handler returns an error response without calling `commit()`/`rollback()`, that transaction — and the WAL write lock it holds — would otherwise stay open on the thread's connection indefinitely, silently blocking every future write app-wide until the process restarts. The teardown hook is a safety net for exactly that case; it does not replace calling `commit()` on the success path.

### Per-server on-disk layout
Each server lives in its own directory under `SERVERS_DIR` (`servers/<id>/`). A **`managed.conf`** file in that directory is the authoritative record of `Engine`/`Version`/etc. for a panel-managed server (read via `_read_managed_conf`, written via `_write_managed_conf`/`_create_managed_conf`). Server categories: `unmodded`, `modded`, `bedrock` (Bedrock uses a `server.sh` launcher instead of `server.jar`).

**Player management is edition-specific.** Java uses `ops.json`/`whitelist.json`/`banned-players.json`/`banned-ips.json`, driven through console commands while the server runs (the server owns those files and would overwrite a direct edit). Bedrock uses `permissions.json` (keyed by **XUID**, not UUID) and `allowlist.json`, and is driven the opposite way: write the file, then send `permission reload` / `allowlist reload` — that is what BDS's own `bedrock_server_how_to.html` prescribes, and unlike Bedrock's `op` it works for offline players. Bedrock has no ban list and no per-player data files at all, so the panel adds two dot-files of its own in the server directory, both on the Bedrock-update preserve list: `BEDROCK_XUID_CACHE` (`.mserver_xuids.json`, gamertag→XUID learned from `Player connected:` console lines — the only XUID source, since Bedrock has no gamertag lookup) and `BEDROCK_BANS_FILE` (`.mserver_bans.json`, the panel's own ban list, enforced by `ServerInstance._enforce_bedrock_ban` kicking on connect). Bedrock helpers live together under the `Bedrock player management` header in `server.py`.

### Key path constants (top of `server.py`)
`BASE_DIR`, `SERVERS_DIR` (`servers/`), `BACKUPS_DIR` (`backups/`), `UPLOADS_DIR` (`uploads/`), `JOBS_TMP_DIR` (`uploads/jobs/` — prepared zip-download artifacts from `JobManager`), `RESOURCEPACKS_DIR` (`public/resourcepacks/`), `TOOLS_DIR` (`tools/`), `DB_PATH` (`msc.db`), `SETTINGS_PATH` (`settings.json`), `JAR_URLS_PATH` (`configs/jarurls.conf`), `VERSION_FILE` (`version`). `SERVER_EXECUTABLES_DIR` (`serverexecutables/`) is defined separately, near `JarBucketManager`.

### Frontend (`public/`, vanilla JS, no framework/bundler)
Multi-page, classic (non-module) scripts — top-level `function` declarations are global and are wired to HTML via inline `onclick=`/`onsubmit=` or `addEventListener`/event delegation. Inline handlers are why the CSP in `add_security_headers` allows `'unsafe-inline'`, so the CSP does **not** stop XSS — escaping is the only defence. `utils.js` has three escapers for three contexts: `escapeHtml()` for element content, `escapeAttrValue()` for a quoted HTML attribute, and `escapeAttr()` for a value placed inside a JS string in an inline handler (`onclick="fn('${escapeAttr(x)}')"`). Values read from files a server owner controls (`ops.json`, `managed.conf`, playerdata filenames) are untrusted too. All API calls go through `apiRequest()` in `utils.js`, which attaches the CSRF token. Socket.IO (4.7.2) and Chart.js load from CDNs allowed by the CSP. Pages: `index.html` + `app.js` (main dashboard), `settings.html` + `settings.js` (admin/settings), `login.html` + `login.js` (auth incl. MFA), `public.html` + `public.js` (public read-only status), `setup.html` + `setup.js` (first-run admin-creation wizard, gated server-side by `needs_setup()`). `utils.js` holds shared helpers including `escapeHtml()` — use it before injecting any user content via `innerHTML`. `notifications.js` is the shared notification bell/dropdown, included on `index.html` and `settings.html`. CSRF tokens (`X-CSRF-Token`) are required on state-changing requests (Flask-WTF).

**Boolean inputs are toggle switches.** Every checkbox in the panel renders as the same square switch, defined once at the bottom of `styles.css` ("Toggle switch — the app-wide standard"). It is drawn entirely on the `<input>` itself (track = its border/background, knob = a sliding `background-image`), so no wrapper spans are needed — a checkbox becomes a switch just by sitting inside one of the listed wrappers (`.switch-row`, `.checkbox-label`, `.notif-pref-row`, `.perm-checkbox`, `.toggle-switch`) or by carrying the `switch` class itself. Add new checkboxes one of those ways rather than writing another toggle. The one deliberate exception is `.msg-format-toggles` (the B/I/U/S formatting toggles), which read as formatting buttons, not settings.

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
- Anything written to a server's stdin must be a single line: validate with `_safe_player_token` / `_safe_bedrock_name` / `_safe_message_target` / `_safe_console_text` so a value can't smuggle a second console command. All console input funnels through `ServerManager.send_command`, which is where `BLOCKED_CONSOLE_COMMANDS` (op/deop) is applied.
- Bedrock launchers must `exec` the server (`BEDROCK_LAUNCHER`); the process the panel holds has to be the server itself, or Kill only ends a wrapper shell.
- A server's unapproved state is enforced in `ServerManager.start_server()`; `approved` is changed only by the admin approve route.
- `ServerManager.update_server()` always resets `executable` to `server.jar`/`server.sh` from the category, whatever the caller passes — a server's launch file name is fixed, so code that installs a JAR must write it as `server.jar`.
- Committing a fix while unrelated uncommitted work sits in the same file: don't stage with `git apply --cached` and reduced context — `server.py` has many near-identical blocks (`if not success: return api_error(...)`) and a low-context hunk can land in the wrong function without any error. Build the committed version with `git merge-file` (HEAD's file, the pre-fix working file as base, the post-fix working file as theirs) and stage that blob.
- The action-approval policy only covers the routes that call `check_action_policy()`. A new mutating per-server route (or a second way to do an already-gated thing, e.g. installing a mod by a different path) has to call it too, or it bypasses the policy.
- Host-level actions (OS update, service restart) go through the root-owned helper `mserver-hostctl` (installed to `/usr/local/sbin`, the only command the `www-data` sudoers rule allows, authenticated with the root password per request). Add new privileged operations there as a subcommand, never as a broader sudo rule.
- Static files under `public/` are served by the catch-all `static_files` route, which requires a session for everything except its short `public_files` allowlist — an asset needed on `login.html`/`public.html`/`setup.html` must be added to that list. `/resourcepacks/` is expected to be served by the reverse proxy (see `nginx.conf`), since Minecraft clients fetch packs without a session.
- `version` file holds the app version (`version=4.0.0`); referenced by the UI/update flow.
