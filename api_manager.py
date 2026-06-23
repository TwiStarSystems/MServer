#!/usr/bin/env python3
"""
MServer - Public API Manager
Handles API key management, authentication, rate limiting, and public API endpoints.
"""

import json
import secrets
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps
from flask import Blueprint, request, jsonify, g

# Create Blueprint for API v1
api_v1 = Blueprint('api_v1', __name__, url_prefix='/api/v1')

# Configuration
BASE_DIR = Path(__file__).parent.absolute()

from db import get_db

# API Key permissions
class APIPermission:
    READ = 'read'           # Read server info, status
    WRITE = 'write'         # Send commands, modify settings
    ADMIN = 'admin'         # Full access including user management
    SERVERS = 'servers'     # Server management (create, delete)
    PLAYERS = 'players'     # Player-related queries
    CONSOLE = 'console'     # Console access (send commands)


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
            
            if not api_key:
                increment_api_stats(endpoint=request.path, success=False)
                return jsonify({
                    'error': 'API key required',
                    'message': 'Provide API key via X-API-Key header or api_key query parameter'
                }), 401
            
            # Validate key
            key_data = validate_api_key(api_key)
            if not key_data:
                increment_api_stats(endpoint=request.path, success=False)
                return jsonify({
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
                            'error': 'Insufficient permissions',
                            'message': f'This endpoint requires one of: {permissions}'
                        }), 403
            
            # Store key data in request context
            g.api_key = key_data
            
            # Track stats
            increment_api_stats(key_id=key_data['id'], endpoint=request.path, success=True)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ==================== API Key Management Routes (Admin) ====================

@api_v1.route('/keys', methods=['GET'])
def api_list_keys():
    """List all API keys (requires admin session)."""
    # This endpoint uses session auth, not API key auth
    # Import here to avoid circular imports
    from server import get_current_user
    
    user_id, user = get_current_user()
    if not user or user.get('role') != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    keys = list_api_keys()
    return jsonify({'keys': keys})


@api_v1.route('/keys', methods=['POST'])
def api_create_key():
    """Create a new API key (requires admin session)."""
    from server import get_current_user
    
    user_id, user = get_current_user()
    if not user or user.get('role') != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
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
    return jsonify({
        'message': 'API key created successfully',
        'id': key_id,
        'key': full_key,  # Only shown once!
        'name': name,
        'permissions': permissions
    }), 201


@api_v1.route('/keys/<key_id>', methods=['PATCH'])
def api_update_key(key_id):
    """Update an API key (requires admin session)."""
    from server import get_current_user
    
    user_id, user = get_current_user()
    if not user or user.get('role') != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    data = request.get_json() or {}
    updated = update_api_key(key_id, data)
    
    if not updated:
        return jsonify({'error': 'API key not found'}), 404
    
    return jsonify({'message': 'API key updated', 'key': updated})


@api_v1.route('/keys/<key_id>', methods=['DELETE'])
def api_delete_key(key_id):
    """Delete an API key (requires admin session)."""
    from server import get_current_user
    
    user_id, user = get_current_user()
    if not user or user.get('role') != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    if delete_api_key(key_id):
        return jsonify({'message': 'API key deleted'})
    
    return jsonify({'error': 'API key not found'}), 404


@api_v1.route('/stats', methods=['GET'])
def api_get_stats():
    """Get API usage statistics (requires admin session)."""
    from server import get_current_user
    
    user_id, user = get_current_user()
    if not user or user.get('role') != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    stats = load_api_stats()
    return jsonify(stats)


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
            'servers': 'Create and delete servers',
            'console': 'Send console commands',
            'players': 'Query player information',
            'admin': 'Full administrative access'
        },
        'endpoints': {
            'GET /api/v1/status': {
                'description': 'Get MServer status',
                'permissions': ['read'],
                'response': {'status': 'string', 'version': 'string', 'uptime': 'number'}
            },
            'GET /api/v1/servers': {
                'description': 'List all servers',
                'permissions': ['read'],
                'response': {'servers': 'array'}
            },
            'GET /api/v1/servers/{id}': {
                'description': 'Get server details',
                'permissions': ['read'],
                'params': {'id': 'Server ID'},
                'response': {'server': 'object'}
            },
            'GET /api/v1/servers/{id}/status': {
                'description': 'Get server status',
                'permissions': ['read'],
                'params': {'id': 'Server ID'},
                'response': {'status': 'string', 'players': 'object'}
            },
            'POST /api/v1/servers/{id}/command': {
                'description': 'Send command to server',
                'permissions': ['console'],
                'params': {'id': 'Server ID'},
                'body': {'command': 'string'},
                'response': {'success': 'boolean'}
            },
            'POST /api/v1/servers/{id}/start': {
                'description': 'Start a server',
                'permissions': ['write'],
                'params': {'id': 'Server ID'},
                'response': {'success': 'boolean'}
            },
            'POST /api/v1/servers/{id}/stop': {
                'description': 'Stop a server',
                'permissions': ['write'],
                'params': {'id': 'Server ID'},
                'response': {'success': 'boolean'}
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
    return jsonify(docs)


@api_v1.route('/status', methods=['GET'])
@require_api_key(permissions=[APIPermission.READ])
def api_status():
    """Get MServer status."""
    from server import read_version_file
    
    version = read_version_file() or 'unknown'
    
    return jsonify({
        'status': 'online',
        'version': version,
        'timestamp': datetime.now().isoformat()
    })


@api_v1.route('/servers', methods=['GET'])
@require_api_key(permissions=[APIPermission.READ])
def api_list_servers():
    """List all servers."""
    from server import server_manager
    
    servers = server_manager.list_servers()
    
    # Return basic info for each server
    result = []
    for server in servers:
        result.append({
            'id': server.get('id'),
            'name': server.get('name'),
            'type': server.get('type'),
            'version': server.get('version'),
            'status': server.get('status', 'stopped'),
            'port': server.get('port'),
            'players': server.get('players', {'online': 0, 'max': 0})
        })
    
    return jsonify({'servers': result, 'count': len(result)})


@api_v1.route('/servers/<server_id>', methods=['GET'])
@require_api_key(permissions=[APIPermission.READ])
def api_get_server(server_id):
    """Get server details."""
    from server import server_manager
    
    server = server_manager.get_server(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404
    
    return jsonify({'server': server})


@api_v1.route('/servers/<server_id>/status', methods=['GET'])
@require_api_key(permissions=[APIPermission.READ])
def api_server_status(server_id):
    """Get server status."""
    from server import server_manager
    
    server = server_manager.get_server(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404
    
    return jsonify({
        'id': server_id,
        'status': server.get('status', 'stopped'),
        'players': server.get('players', {'online': 0, 'max': 0}),
        'uptime': server.get('uptime'),
        'last_started': server.get('last_started')
    })


@api_v1.route('/servers/<server_id>/command', methods=['POST'])
@require_api_key(permissions=[APIPermission.CONSOLE])
def api_send_command(server_id):
    """Send a command to the server console."""
    from server import server_manager
    
    server = server_manager.get_server(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404
    
    if server.get('status') != 'running':
        return jsonify({'error': 'Server is not running'}), 400
    
    data = request.get_json() or {}
    command = data.get('command')
    
    if not command:
        return jsonify({'error': 'Command is required'}), 400
    
    success = server_manager.send_command(server_id, command)
    
    return jsonify({
        'success': success,
        'message': 'Command sent' if success else 'Failed to send command'
    })


@api_v1.route('/servers/<server_id>/start', methods=['POST'])
@require_api_key(permissions=[APIPermission.WRITE])
def api_start_server(server_id):
    """Start a server."""
    from server import server_manager
    
    server = server_manager.get_server(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404
    
    if server.get('status') == 'running':
        return jsonify({'error': 'Server is already running'}), 400
    
    success = server_manager.start_server(server_id)
    
    return jsonify({
        'success': success,
        'message': 'Server starting' if success else 'Failed to start server'
    })


@api_v1.route('/servers/<server_id>/stop', methods=['POST'])
@require_api_key(permissions=[APIPermission.WRITE])
def api_stop_server(server_id):
    """Stop a server."""
    from server import server_manager
    
    server = server_manager.get_server(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404
    
    if server.get('status') != 'running':
        return jsonify({'error': 'Server is not running'}), 400
    
    success = server_manager.stop_server(server_id)
    
    return jsonify({
        'success': success,
        'message': 'Server stopping' if success else 'Failed to stop server'
    })


@api_v1.route('/servers/<server_id>/restart', methods=['POST'])
@require_api_key(permissions=[APIPermission.WRITE])
def api_restart_server(server_id):
    """Restart a server."""
    from server import server_manager
    
    server = server_manager.get_server(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404
    
    success = server_manager.restart_server(server_id)
    
    return jsonify({
        'success': success,
        'message': 'Server restarting' if success else 'Failed to restart server'
    })


# ==================== Utility Functions ====================

def init_api_manager(app):
    """Initialize the API manager with the Flask app."""
    app.register_blueprint(api_v1)
    print(f"[API Manager] Public API v1 initialized at /api/v1/")
