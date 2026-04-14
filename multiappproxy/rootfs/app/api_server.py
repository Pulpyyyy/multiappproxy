#!/usr/bin/env python3
"""
Backend micro-service for Multi-App Proxy.

Endpoints:
  GET  /api/user          — current HA user info + admin status
  POST /api/verify-secret — password verification (bcrypt)

Listens on 127.0.0.1:8088 (internal only, proxied by Nginx at /api/).
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import bcrypt
import os
import time
import traceback

SECRETS_FILE = '/app/secrets.json'

# Rate limiting défense-en-profondeur pour /api/verify-secret
# Nginx est la première barrière ; ce compteur protège si nginx est contourné.
_verify_attempts: dict[str, list[float]] = {}
_VERIFY_MAX = 5      # tentatives max
_VERIFY_WINDOW = 60  # fenêtre en secondes

def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    attempts = [t for t in _verify_attempts.get(ip, []) if now - t < _VERIFY_WINDOW]
    if len(attempts) >= _VERIFY_MAX:
        _verify_attempts[ip] = attempts
        return True
    attempts.append(now)
    _verify_attempts[ip] = attempts
    return False

HA_AUTH_FILE = '/config/.storage/auth'

# Per-user admin status cache: {user_id: (is_admin, timestamp)}
_user_cache = {}
CACHE_TTL = 300  # 5 minutes


def get_admin_status(user_id, user_name=''):
    """Return True if the given user has admin rights in Home Assistant.

    Reads /config/.storage/auth (mapped via config:ro).
    A user is considered admin if they are the owner (is_owner=True) or
    belong to the 'system-admin' group. Results are cached for CACHE_TTL
    seconds to avoid repeated file reads.
    """
    cache_key = user_id or user_name
    if not cache_key:
        return False

    if cache_key in _user_cache:
        is_admin, ts = _user_cache[cache_key]
        if time.time() - ts < CACHE_TTL:
            return is_admin

    is_admin = False
    print(f'[API DEBUG] === get_admin_status START user_id={user_id!r} ===')
    try:
        with open(HA_AUTH_FILE) as f:
            auth_data = json.load(f)
        users = auth_data.get('data', {}).get('users', [])
        print(f'[API DEBUG] {len(users)} user(s) in auth file')
        user = next((u for u in users if u.get('id') == user_id), None)
        print(f'[API DEBUG] Match user_id={user_id!r}: {user is not None}')
        if user:
            is_admin = (
                user.get('is_owner', False)
                or 'system-admin' in user.get('group_ids', [])
            )
            print(f'[API DEBUG] is_owner={user.get("is_owner")} group_ids={user.get("group_ids")} → is_admin={is_admin}')
    except Exception as e:
        print(f'[API DEBUG] Auth file error: {e!r}\n{traceback.format_exc()}')
    print(f'[API DEBUG] === END is_admin={is_admin} ===')

    _user_cache[cache_key] = (is_admin, time.time())
    return is_admin


def load_secrets():
    """Load secrets.json — maps app path → bcrypt hash of its password."""
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
            client_ip = self.headers.get('X-Real-IP', self.client_address[0])
            if _is_rate_limited(client_ip):
                self._send_json(429, {'error': 'Too many attempts'})
                return

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
                # Vérification bcrypt — résistant aux rainbow tables
                valid = bcrypt.checkpw(password.encode(), stored_hash.encode())
                print(f'[SECRET DEBUG] bcrypt match={valid}')
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
