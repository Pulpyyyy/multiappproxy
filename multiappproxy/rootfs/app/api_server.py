#!/usr/bin/env python3
"""
Backend micro-service for Multi-App Proxy.

Endpoints:
  GET  /api/user          — current HA user info + admin status
  POST /api/verify-secret — password verification (SHA256 comparison)

Listens on 127.0.0.1:8088 (internal only, proxied by Nginx at /api/).
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import hashlib
import os
import time
import urllib.request
import urllib.error

SECRETS_FILE = '/app/secrets.json'
SUPERVISOR_TOKEN = os.environ.get('SUPERVISOR_TOKEN', '')
print(f'[API DEBUG] SUPERVISOR_TOKEN set: {bool(SUPERVISOR_TOKEN)} len={len(SUPERVISOR_TOKEN)}')

# Per-user admin status cache: {user_id: (is_admin, timestamp)}
_user_cache = {}
CACHE_TTL = 300  # 5 minutes


def get_admin_status(user_id, user_name=''):
    """Return True if the given user has admin rights in Home Assistant.

    Reads /homeassistant/.storage/auth (requires map: config:ro).
    With addon_config:rw + config:ro, the HA config root is mounted at
    /homeassistant/ and the addon's dedicated config dir at /config/.
    A user is considered admin if they are the owner (is_owner=True) or
    belong to the 'system-admin' group. Results are cached for CACHE_TTL
    seconds to avoid repeated file reads.
    """
    cache_key = user_id or user_name
    if not cache_key:
        return False

    # Return cached result if still fresh
    if cache_key in _user_cache:
        is_admin, ts = _user_cache[cache_key]
        if time.time() - ts < CACHE_TTL:
            return is_admin

    is_admin = False
    auth_file = '/homeassistant/.storage/auth'
    print(f'[API DEBUG] === get_admin_status START user_id={user_id!r} ===')
    try:
        with open(auth_file) as f:
            data = json.load(f)
        users = data.get('data', {}).get('users', [])
        print(f'[API DEBUG] {len(users)} user(s) in auth storage')
        user = next((u for u in users if u.get('id') == user_id), None)
        print(f'[API DEBUG] Match user_id={user_id!r}: {user is not None}')
        if user:
            is_admin = (
                'system-admin' in user.get('group_ids', [])
                or user.get('is_owner', False)
            )
            print(f'[API DEBUG] is_owner={user.get("is_owner")} group_ids={user.get("group_ids")} → is_admin={is_admin}')
    except FileNotFoundError:
        print(f'[API DEBUG] File {auth_file} not found')
    except Exception as e:
        import traceback
        print(f'[API DEBUG] Exception: {e!r}\n{traceback.format_exc()}')
    print(f'[API DEBUG] === END is_admin={is_admin} ===')

    _user_cache[cache_key] = (is_admin, time.time())
    return is_admin


def load_secrets():
    """Load secrets.json — maps app path → SHA256 hash of its password."""
    try:
        with open(SECRETS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


class APIHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == '/api/user':
            # HA Ingress injects user identity via these headers
            print(f'[API DEBUG] ALL headers: { {k: v for k, v in self.headers.items()} }')
            user_id = self.headers.get('X-Remote-User-Id', '')
            user_name = self.headers.get('X-Remote-User-Name', '')
            name = self.headers.get('X-Remote-User-Display-Name', '') or user_name
            print(f'[API DEBUG] user_id={user_id!r} user_name={user_name!r} name={name!r}')
            is_admin = get_admin_status(user_id, user_name)
            self._send_json(200, {
                'user_id': user_id,
                'name': name,
                'is_admin': is_admin,
            })
        else:
            self._send_json(404, {'error': 'Not found'})

    def do_POST(self):
        if self.path == '/api/verify-secret':
            length = int(self.headers.get('Content-Length', 0))
            try:
                body = json.loads(self.rfile.read(length).decode())
            except Exception:
                self._send_json(400, {'error': 'Invalid JSON'})
                return

            app_path = body.get('path', '')
            password = body.get('password', '')

            secrets = load_secrets()
            print(f'[SECRET DEBUG] path received={app_path!r}')
            print(f'[SECRET DEBUG] keys in secrets.json: {list(secrets.keys())}')
            stored_hash = secrets.get(app_path)
            print(f'[SECRET DEBUG] stored_hash found: {bool(stored_hash)}')
            if stored_hash:
                # Compare SHA256 of the submitted password against the stored hash
                input_hash = hashlib.sha256(password.encode()).hexdigest()
                valid = (input_hash == stored_hash)
                print(f'[SECRET DEBUG] input_hash={input_hash[:8]}... stored={stored_hash[:8]}... match={valid}')
            else:
                valid = False

            self._send_json(200, {'valid': valid})
        else:
            self._send_json(404, {'error': 'Not found'})

    def _send_json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Only log non-2xx responses to reduce noise
        if args and str(args[1]) not in ('200', '204'):
            print(f'[API] {self.address_string()} - ' + fmt % args)


if __name__ == '__main__':
    server = HTTPServer(('127.0.0.1', 8088), APIHandler)
    print('[API] Server started on 127.0.0.1:8088')
    server.serve_forever()
