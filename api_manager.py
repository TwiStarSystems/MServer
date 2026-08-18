#!/usr/bin/env python3
"""
MServer - Public API Manager
Handles API key management, authentication, rate limiting, and public API endpoints.
"""

import json
import time
import secrets
import hashlib
import threading
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps
from flask import Blueprint, request, jsonify, g, after_this_request

# Create Blueprint for API v1 (public, API-key authenticated)
api_v1 = Blueprint('api_v1', __name__, url_prefix='/api/v1')

# Separate blueprint for the session-authenticated admin/management routes.
# These live under /api/v1 too but must NOT be CSRF-exempt (unlike api_v1),
# since they are driven by the operator's browser session, not an API key.
api_v1_admin = Blueprint('api_v1_admin', __name__, url_prefix='/api/v1')

# Configuration
BASE_DIR = Path(__file__).parent.absolute()

from db import get_db

# ==================== server.py dependencies (injected, not imported) ====================
# api_manager.py is only ever imported FROM server.py (never the reverse), so by
# the time init_api_manager() runs, everything below already exists as globals
# in the already-executing server.py module. Routes must NOT do
# `from server import X` to reach them: the app is launched as `python
# server.py`, so Python registers it under sys.modules['__main__'], not
# sys.modules['server'] — a `from server import` doesn't find 'server' already
# loaded and re-executes the whole file as a second, independent module
# (re-running its module-level signal.signal() call off the main thread, which
# raises ValueError on every single call). Passing references in at
# registration time avoids the re-import entirely.
_server_manager = None
_get_current_user = None
_group_manager = None
_read_version_file = None


# API Key permissions
class APIPermission:
    READ = 'read'           # Read server info, status
    WRITE = 'write'         # Send commands, modify settings
    ADMIN = 'admin'         # Full access including user management
    CONSOLE = 'console'     # Console access (send commands)


# ==================== JSON response envelope ====================
# Local equivalent of server.py's api_success()/api_error() (issue #28) — this
# module can't import server.py's copy (see the module-docstring note on why
# api_manager.py never imports from server.py). Same shape/behavior: every
# response gets a top-level `success` boolean, and `data`/`extra` merge flat.

def api_success(data=None, status=200, **extra):
    body = {'success': True}
    if data:
        body.update(data)
    body.update(extra)
    return jsonify(body), status


def api_error(message, status=400, **extra):
    body = {'success': False, 'error': message}
    body.update(extra)
    return jsonify(body), status


# ==================== Data Storage ====================

def load_api_stats():
    """Load API statistics from SQLite."""
    conn = get_db()
    row = conn.execute('SELECT * FROM api_stats WHERE id=1').fetchone()
    stats = {
        'total_requests':       row['total_requests']      if row else 0,
        'successful_requests':  row['successful_requests'] if row else 0,
        'failed_requests':      row['failed_requests']     if row else 0,
        'last_reset':           row['last_reset']          if row else datetime.now().isoformat(),
        'requests_by_key':      {},
        'requests_by_endpoint': {},
    }
    for r in conn.execute('SELECT * FROM api_requests_by_key').fetchall():
        stats['requests_by_key'][r['key_id']] = r['count']
    for r in conn.execute('SELECT * FROM api_requests_by_endpoint').fetchall():
        stats['requests_by_endpoint'][r['endpoint']] = r['count']
    return stats


def increment_api_stats(key_id=None, endpoint=None, success=True):
    """Atomically increment API usage statistics in SQLite."""
    conn = get_db()
    if success:
        conn.execute(
            'UPDATE api_stats SET total_requests=total_requests+1, '
            'successful_requests=successful_requests+1 WHERE id=1'
        )
    else:
        conn.execute(
            'UPDATE api_stats SET total_requests=total_requests+1, '
            'failed_requests=failed_requests+1 WHERE id=1'
        )
    if key_id:
        conn.execute(
            'INSERT INTO api_requests_by_key (key_id, count) VALUES (?,1) '
            'ON CONFLICT(key_id) DO UPDATE SET count=count+1',
            (key_id,)
        )
    if endpoint:
        conn.execute(
            'INSERT INTO api_requests_by_endpoint (endpoint, count) VALUES (?,1) '
            'ON CONFLICT(endpoint) DO UPDATE SET count=count+1',
            (endpoint,)
        )
    conn.commit()


# ==================== API Key Management ====================

def generate_api_key():
    """Generate a secure API key."""
    return f"msc_{secrets.token_urlsafe(32)}"


def hash_api_key(key):
    """Hash an API key for storage."""
    return hashlib.sha256(key.encode()).hexdigest()


def _row_to_key_dict(row):
    """Convert an api_keys DB row to the dict shape the app expects."""
    if row is None:
        return None
    return {
        'id':            row['id'],
        'name':          row['name'],
        'key_hash':      row['key_hash'],
        'key_prefix':    row['key_prefix'],
        'permissions':   json.loads(row['permissions']),
        'rate_limit':    row['rate_limit'],
        'created_at':    row['created'],
        'expires_at':    row['expires'],
        'last_used':     row['last_used'],
        'request_count': row['use_count'],
        'active':        bool(row['enabled']),
    }


def create_api_key(name, permissions=None, rate_limit=60, expires_days=None):
    """
    Create a new API key.

    Args:
        name: Display name for the key
        permissions: List of permissions (default: ['read'])
        rate_limit: Requests per minute (default: 60)
        expires_days: Days until expiration (None = never expires)

    Returns:
        Tuple of (key_id, full_key, key_data)
    """
    key_id     = secrets.token_hex(8)
    full_key   = generate_api_key()
    key_hash   = hash_api_key(full_key)
    key_prefix = full_key[:12]
    expires_at = (
        (datetime.now() + timedelta(days=expires_days)).isoformat()
        if expires_days else None
    )
    perms = json.dumps(permissions or [APIPermission.READ])
    now   = datetime.now().isoformat()

    conn = get_db()
    conn.execute(
        '''INSERT INTO api_keys
           (id, name, key_hash, key_prefix, permissions, rate_limit, created, expires, use_count, enabled)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 1)''',
        (key_id, name, key_hash, key_prefix, perms, rate_limit, now, expires_at)
    )
    conn.commit()

    row = conn.execute('SELECT * FROM api_keys WHERE id=?', (key_id,)).fetchone()
    return key_id, full_key, _row_to_key_dict(row)


def validate_api_key(provided_key):
    """
    Validate an API key.

    Args:
        provided_key: The full API key to validate

    Returns:
        key_data dict if valid, None otherwise
    """
    if not provided_key:
        return None

    key_hash = hash_api_key(provided_key)
    conn = get_db()
    row = conn.execute('SELECT * FROM api_keys WHERE key_hash=?', (key_hash,)).fetchone()
    if row is None:
        return None
    if not row['enabled']:
        return None
    if row['expires']:
        try:
            if datetime.now() > datetime.fromisoformat(row['expires']):
                return None
        except Exception:
            pass

    conn.execute(
        'UPDATE api_keys SET last_used=?, use_count=use_count+1 WHERE id=?',
        (datetime.now().isoformat(), row['id'])
    )
    conn.commit()
    row = conn.execute('SELECT * FROM api_keys WHERE id=?', (row['id'],)).fetchone()
    return _row_to_key_dict(row)


def update_api_key(key_id, updates):
    """Update an API key."""
    conn = get_db()
    row = conn.execute('SELECT * FROM api_keys WHERE id=?', (key_id,)).fetchone()
    if row is None:
        return None

    current    = _row_to_key_dict(row)
    name       = updates.get('name',        current['name'])
    perms      = json.dumps(updates.get('permissions', current['permissions']))
    rate_limit = updates.get('rate_limit',  current['rate_limit'])
    enabled    = 1 if updates.get('active', current['active']) else 0

    conn.execute(
        'UPDATE api_keys SET name=?, permissions=?, rate_limit=?, enabled=? WHERE id=?',
        (name, perms, rate_limit, enabled, key_id)
    )
    conn.commit()
    return _row_to_key_dict(conn.execute('SELECT * FROM api_keys WHERE id=?', (key_id,)).fetchone())


def delete_api_key(key_id):
    """Delete an API key."""
    conn = get_db()
    result = conn.execute('DELETE FROM api_keys WHERE id=?', (key_id,))
    conn.commit()
    return result.rowcount > 0


def list_api_keys():
    """List all API keys (without sensitive data)."""
    rows = get_db().execute('SELECT * FROM api_keys ORDER BY created').fetchall()
    result = []
    for row in rows:
        k = _row_to_key_dict(row)
        result.append({
            'id':            k['id'],
            'name':          k['name'],
            'key':           k['key_prefix'] + '...', 
            'permissions':   k['permissions'],
            'rate_limit':    k['rate_limit'],
            'created_at':    k['created_at'],
            'expires_at':    k['expires_at'],
            'last_used':     k['last_used'],
            'request_count': k['request_count'],
            'active':        k['active'],
        })
    return result


# ==================== Admin session gate ====================

def _require_admin_session():
    """Session-auth admin gate for the management routes.

    RBAC is group-based (there is no 'role' field on the user dict), so admin
    status is determined by group_manager.is_admin_group(). Returns (user, None)
    on success, or (None, (response, status)) to short-circuit the caller."""
    user_id, user = _get_current_user()
    if not user:
        return None, api_error('Authentication required', 401)
    if not _group_manager.is_admin_group(user.get('groupId')):
        return None, api_error('Admin access required', 403)
    return user, None


# ==================== Per-key rate limiting ====================

_RATE_LOCK = threading.Lock()
_RATE_HITS = {}          # key_id -> list[float] request timestamps within the window
_RATE_WINDOW = 60.0      # seconds


def _check_rate_limit(key_id, limit):
    """Sliding-window rate check. Returns (allowed, remaining, reset_epoch)."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 60
    if limit <= 0:
        limit = 60
    now = time.time()
    with _RATE_LOCK:
        hits = [t for t in _RATE_HITS.get(key_id, []) if now - t < _RATE_WINDOW]
        reset = int((hits[0] if hits else now) + _RATE_WINDOW)
        if len(hits) >= limit:
            _RATE_HITS[key_id] = hits
            return False, 0, reset
        hits.append(now)
        _RATE_HITS[key_id] = hits
        return True, limit - len(hits), reset


# ==================== Authentication Decorator ====================

def require_api_key(permissions=None):
    """
    Decorator to require API key authentication.
    
    Args:
        permissions: List of required permissions (any one of them)
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get API key from header or query param
            api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
            
            # These 4 error bodies carry both 'error' (short label) and 'message'
            # (longer description) — distinct pre-existing fields, not a case
            # api_error() can express, since its own first parameter is also
            # named 'message' (passing message=... as an extra kwarg collides
            # with it). Built by hand instead; still gets 'success': False.

            if not api_key:
                increment_api_stats(endpoint=request.path, success=False)
                return jsonify({
                    'success': False,
                    'error': 'API key required',
                    'message': 'Provide API key via X-API-Key header or api_key query parameter'
                }), 401

            # Validate key
            key_data = validate_api_key(api_key)
            if not key_data:
                increment_api_stats(endpoint=request.path, success=False)
                return jsonify({
                    'success': False,
                    'error': 'Invalid API key',
                    'message': 'The provided API key is invalid, expired, or disabled'
                }), 401

            # Check permissions
            if permissions:
                key_permissions = key_data.get('permissions', [])
                if APIPermission.ADMIN not in key_permissions:
                    if not any(p in key_permissions for p in permissions):
                        increment_api_stats(key_id=key_data['id'], endpoint=request.path, success=False)
                        return jsonify({
                            'success': False,
                            'error': 'Insufficient permissions',
                            'message': f'This endpoint requires one of: {permissions}'
                        }), 403

            # Enforce the per-key rate limit and advertise the documented headers.
            limit = key_data.get('rate_limit') or 60
            allowed, remaining, reset_ts = _check_rate_limit(key_data['id'], limit)

            @after_this_request
            def _add_rate_headers(resp):
                resp.headers['X-RateLimit-Limit'] = str(limit)
                resp.headers['X-RateLimit-Remaining'] = str(max(0, remaining))
                resp.headers['X-RateLimit-Reset'] = str(reset_ts)
                return resp

            if not allowed:
                increment_api_stats(key_id=key_data['id'], endpoint=request.path, success=False)
                return jsonify({
                    'success': False,
                    'error': 'Rate limit exceeded',
                    'message': f'API key is limited to {limit} requests per minute'
                }), 429

            # Store key data in request context
            g.api_key = key_data

            # Track stats
            increment_api_stats(key_id=key_data['id'], endpoint=request.path, success=True)

            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ==================== API Key Management Routes (Admin) ====================

@api_v1_admin.route('/keys', methods=['GET'])
def api_list_keys():
    """List all API keys (requires admin session)."""
    user, err = _require_admin_session()
    if err:
        return err

    keys = list_api_keys()
    return api_success(keys=keys)


@api_v1_admin.route('/keys', methods=['POST'])
def api_create_key():
    """Create a new API key (requires admin session)."""
    user, err = _require_admin_session()
    if err:
        return err

    data = request.get_json() or {}
    name = data.get('name', 'Unnamed Key')
    permissions = data.get('permissions', [APIPermission.READ])
    rate_limit = data.get('rate_limit', 60)
    expires_days = data.get('expires_days')
    
    key_id, full_key, key_data = create_api_key(
        name=name,
        permissions=permissions,
        rate_limit=rate_limit,
        expires_days=expires_days
    )
    
    # Return the full key only on creation
    return api_success({
        'message': 'API key created successfully',
        'id': key_id,
        'key': full_key,  # Only shown once!
        'name': name,
        'permissions': permissions
    }, status=201)


@api_v1_admin.route('/keys/<key_id>', methods=['PATCH'])
def api_update_key(key_id):
    """Update an API key (requires admin session)."""
    user, err = _require_admin_session()
    if err:
        return err

    data = request.get_json() or {}
    updated = update_api_key(key_id, data)

    if not updated:
        return api_error('API key not found', 404)

    return api_success(message='API key updated', key=updated)


@api_v1_admin.route('/keys/<key_id>', methods=['DELETE'])
def api_delete_key(key_id):
    """Delete an API key (requires admin session)."""
    user, err = _require_admin_session()
    if err:
        return err

    if delete_api_key(key_id):
        return api_success(message='API key deleted')

    return api_error('API key not found', 404)


@api_v1_admin.route('/stats', methods=['GET'])
def api_get_stats():
    """Get API usage statistics (requires admin session)."""
    user, err = _require_admin_session()
    if err:
        return err

    stats = load_api_stats()
    return api_success(stats)


# ==================== Public API Endpoints ====================

@api_v1.route('/docs', methods=['GET'])
def api_docs():
    """Return API documentation."""
    docs = {
        'name': 'MServer API',
        'version': 'v1',
        'description': 'Public API for MServer',
        'authentication': {
            'method': 'API Key',
            'header': 'X-API-Key',
            'query_param': 'api_key'
        },
        'permissions': {
            'read': 'Read server information and status',
            'write': 'Modify server settings',
            'console': 'Send console commands',
            'admin': 'Full administrative access'
        },
        'endpoints': {
            'GET /api/v1/status': {
                'description': 'Get MServer status',
                'permissions': ['read'],
                'response': {'success': 'boolean', 'status': 'string', 'version': 'string', 'timestamp': 'string'}
            },
            'GET /api/v1/servers': {
                'description': 'List all servers',
                'permissions': ['read'],
                'response': {'success': 'boolean', 'servers': 'array', 'count': 'number'}
            },
            'GET /api/v1/servers/{id}': {
                'description': 'Get server details',
                'permissions': ['read'],
                'params': {'id': 'Server ID'},
                'response': {'success': 'boolean', 'server': 'object'}
            },
            'GET /api/v1/servers/{id}/status': {
                'description': 'Get server status',
                'permissions': ['read'],
                'params': {'id': 'Server ID'},
                'response': {'success': 'boolean', 'id': 'string', 'status': 'string',
                             'running': 'boolean', 'port': 'number', 'players': 'object'}
            },
            'POST /api/v1/servers/{id}/command': {
                'description': 'Send command to server',
                'permissions': ['console'],
                'params': {'id': 'Server ID'},
                'body': {'command': 'string'},
                'response': {'success': 'boolean', 'message': 'string', 'error': 'string (on failure)'}
            },
            'POST /api/v1/servers/{id}/start': {
                'description': 'Start a server',
                'permissions': ['write'],
                'params': {'id': 'Server ID'},
                'response': {'success': 'boolean', 'message': 'string', 'error': 'string (on failure)'}
            },
            'POST /api/v1/servers/{id}/stop': {
                'description': 'Stop a server',
                'permissions': ['write'],
                'params': {'id': 'Server ID'},
                'response': {'success': 'boolean', 'message': 'string', 'error': 'string (on failure)'}
            },
            'POST /api/v1/servers/{id}/restart': {
                'description': 'Restart a server',
                'permissions': ['write'],
                'params': {'id': 'Server ID'},
                'response': {'success': 'boolean', 'message': 'string', 'error': 'string (on failure)'}
            }
        },
        'rate_limiting': {
            'default': '60 requests/minute per API key',
            'headers': {
                'X-RateLimit-Limit': 'Request limit',
                'X-RateLimit-Remaining': 'Remaining requests',
                'X-RateLimit-Reset': 'Reset timestamp'
            }
        }
    }
    return api_success(docs)


@api_v1.route('/status', methods=['GET'])
@require_api_key(permissions=[APIPermission.READ])
def api_status():
    """Get MServer status."""
    version = _read_version_file() or 'unknown'

    return api_success({
        'status': 'online',
        'version': version,
        'timestamp': datetime.now().isoformat()
    })


def _api_server_view(server_id):
    """Return the runtime-status dict for one server (or None), as exposed by
    ServerManager.get_servers_list()."""
    for s in _server_manager.get_servers_list():
        if s.get('id') == server_id:
            return s
    return None


@api_v1.route('/servers', methods=['GET'])
@require_api_key(permissions=[APIPermission.READ])
def api_list_servers():
    """List all servers."""
    result = []
    for server in _server_manager.get_servers_list():
        result.append({
            'id': server.get('id'),
            'name': server.get('name'),
            'type': server.get('serverType'),
            'version': server.get('version'),
            'status': server.get('status', 'stopped'),
            'running': server.get('running', False),
            'port': server.get('port'),
            'category': server.get('category'),
        })

    return api_success(servers=result, count=len(result))


@api_v1.route('/servers/<server_id>', methods=['GET'])
@require_api_key(permissions=[APIPermission.READ])
def api_get_server(server_id):
    """Get server details."""
    server = _api_server_view(server_id)
    if not server:
        return api_error('Server not found', 404)

    return api_success(server=server)


@api_v1.route('/servers/<server_id>/status', methods=['GET'])
@require_api_key(permissions=[APIPermission.READ])
def api_server_status(server_id):
    """Get server status."""
    server = _api_server_view(server_id)
    if not server:
        return api_error('Server not found', 404)

    instance = _server_manager.servers.get(server_id)
    online = list(instance.online_players.keys()) if (instance and instance.is_running()) else []

    return api_success({
        'id': server_id,
        'status': server.get('status', 'stopped'),
        'running': server.get('running', False),
        'port': server.get('port'),
        'players': {'online': len(online), 'list': online},
    })


# send_command/start/stop/restart return (success, message) from server_manager.
# The 'message' key predates this envelope and real API-key consumers may
# already read it on failure, so it's kept as-is on both paths; 'error' is
# added alongside it on failure so new consumers can rely on the standard key.
# Built by hand rather than via api_error() — same 'message' collision as above.

@api_v1.route('/servers/<server_id>/command', methods=['POST'])
@require_api_key(permissions=[APIPermission.CONSOLE])
def api_send_command(server_id):
    """Send a command to the server console."""
    if _api_server_view(server_id) is None:
        return api_error('Server not found', 404)

    data = request.get_json() or {}
    command = data.get('command')

    if not command:
        return api_error('Command is required', 400)

    success, message = _server_manager.send_command(server_id, command)
    if success:
        return api_success(message=message)
    return jsonify({'success': False, 'error': message, 'message': message}), 400


@api_v1.route('/servers/<server_id>/start', methods=['POST'])
@require_api_key(permissions=[APIPermission.WRITE])
def api_start_server(server_id):
    """Start a server."""
    if _api_server_view(server_id) is None:
        return api_error('Server not found', 404)

    success, message = _server_manager.start_server(server_id)
    if success:
        return api_success(message=message)
    return jsonify({'success': False, 'error': message, 'message': message}), 400


@api_v1.route('/servers/<server_id>/stop', methods=['POST'])
@require_api_key(permissions=[APIPermission.WRITE])
def api_stop_server(server_id):
    """Stop a server."""
    if _api_server_view(server_id) is None:
        return api_error('Server not found', 404)

    success, message = _server_manager.stop_server(server_id)
    if success:
        return api_success(message=message)
    return jsonify({'success': False, 'error': message, 'message': message}), 400


@api_v1.route('/servers/<server_id>/restart', methods=['POST'])
@require_api_key(permissions=[APIPermission.WRITE])
def api_restart_server(server_id):
    """Restart a server."""
    if _api_server_view(server_id) is None:
        return api_error('Server not found', 404)

    success, message = _server_manager.restart_server(server_id)
    if success:
        return api_success(message=message)
    return jsonify({'success': False, 'error': message, 'message': message}), 400


# ==================== Utility Functions ====================

def init_api_manager(app, server_manager, get_current_user, group_manager, read_version_file):
    """Initialize the API manager with the Flask app and the server.py
    dependencies its routes need (see the comment near the top of this file
    for why these are passed in rather than imported by module name)."""
    global _server_manager, _get_current_user, _group_manager, _read_version_file
    _server_manager = server_manager
    _get_current_user = get_current_user
    _group_manager = group_manager
    _read_version_file = read_version_file

    app.register_blueprint(api_v1)
    app.register_blueprint(api_v1_admin)
    print(f"[API Manager] Public API v1 initialized at /api/v1/")
