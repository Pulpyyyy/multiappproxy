#!/usr/bin/env python3
"""
Backend micro-service for Multi-App Proxy.

Endpoints:
  GET  /api/user          — current HA user info + admin status
  GET  /api/auth          — auth_request gate (type=admin | type=secret&path=…)
  POST /api/verify-secret — password verification (bcrypt) + session cookie

Listens on 127.0.0.1:8088 (internal only, proxied by Nginx at /api/).
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import bcrypt
import os
import time
import secrets
import threading
import traceback

SECRETS_FILE = '/app/secrets.json'
HA_AUTH_FILE = '/config/.storage/auth'
DEBUG_FLAG   = '/app/debug.flag'

DEBUG_MODE = os.path.exists(DEBUG_FLAG)

def _debug(*args):
    if DEBUG_MODE:
        print(*args)

# ── Rate limiting ─────────────────────────────────────────────────────────────
_verify_attempts: dict[str, list[float]] = {}
_VERIFY_MAX    = 5
_VERIFY_WINDOW = 60

def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    attempts = [t for t in _verify_attempts.get(ip, []) if now - t < _VERIFY_WINDOW]
    if len(attempts) >= _VERIFY_MAX:
        _verify_attempts[ip] = attempts
        return True
    attempts.append(now)
    _verify_attempts[ip] = attempts
    return False

# ── Admin status ──────────────────────────────────────────────────────────────
_user_cache: dict[str, tuple[bool, float]] = {}
CACHE_TTL = 300

def get_admin_status(user_id: str, user_name: str = '') -> bool:
    cache_key = user_id or user_name
    if not cache_key:
        return False
    if cache_key in _user_cache:
        is_admin, ts = _user_cache[cache_key]
        if time.time() - ts < CACHE_TTL:
            return is_admin
    is_admin = False
    _debug(f'[API] get_admin_status user_id={user_id!r}')
    try:
        with open(HA_AUTH_FILE) as f:
            auth_data = json.load(f)
        users = auth_data.get('data', {}).get('users', [])
        user = next((u for u in users if u.get('id') == user_id), None)
        if user:
            is_admin = (
                user.get('is_owner', False)
                or 'system-admin' in user.get('group_ids', [])
            )
    except Exception as e:
        _debug(f'[API] Auth file error: {e!r}\n{traceback.format_exc()}')
    _user_cache[cache_key] = (is_admin, time.time())
    return is_admin

# ── Secrets ───────────────────────────────────────────────────────────────────
def load_secrets() -> dict:
    try:
        with open(SECRETS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

# ── Session management ────────────────────────────────────────────────────────
# path → {token: expiry_timestamp}
_sessions: dict[str, dict[str, float]] = {}
_sessions_lock = threading.Lock()
SESSIONS_FILE  = '/app/sessions.json'
SESSION_TTL    = 8 * 3600  # 8 heures

def _load_sessions() -> None:
    global _sessions
    try:
        with open(SESSIONS_FILE) as f:
            raw = json.load(f)
        now = time.time()
        _sessions = {
            path: {t: exp for t, exp in tokens.items() if exp > now}
            for path, tokens in raw.items()
        }
        print(f'[API] Sessions chargées depuis {SESSIONS_FILE}')
    except FileNotFoundError:
        _sessions = {}
    except Exception as e:
        print(f'[API] Impossible de charger les sessions: {e!r}')
        _sessions = {}

def _save_sessions() -> None:
    try:
        with _sessions_lock:
            with open(SESSIONS_FILE, 'w') as f:
                json.dump(_sessions, f)
            os.chmod(SESSIONS_FILE, 0o600)
    except Exception as e:
        print(f'[API] Impossible de sauvegarder les sessions: {e!r}')

def _cookie_name(path: str) -> str:
    slug = path.strip('/').replace('/', '_') or 'root'
    return f'map_session_{slug}'

def create_session(path: str) -> str:
    token = secrets.token_urlsafe(32)
    now   = time.time()
    with _sessions_lock:
        # Purge expired tokens pour ce path
        _sessions[path] = {t: exp for t, exp in _sessions.get(path, {}).items() if exp > now}
        _sessions[path][token] = now + SESSION_TTL
    _save_sessions()
    return token

def has_valid_session(path: str, cookie_header: str) -> bool:
    name = _cookie_name(path)
    now  = time.time()
    for part in cookie_header.split(';'):
        part = part.strip()
        if '=' in part:
            k, v = part.split('=', 1)
            if k.strip() == name:
                return _sessions.get(path, {}).get(v.strip(), 0) > now
    return False


# ── Request handler ───────────────────────────────────────────────────────────
class APIHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        raw_path, _, qs = self.path.partition('?')

        if raw_path == '/api/user':
            _debug(f'[API] GET /api/user')
            user_id  = self.headers.get('X-Remote-User-Id', '')
            user_name = self.headers.get('X-Remote-User-Name', '')
            name     = self.headers.get('X-Remote-User-Display-Name', '') or user_name
            is_admin = get_admin_status(user_id, user_name)
            self._send_json(200, {'user_id': user_id, 'name': name, 'is_admin': is_admin})

        elif raw_path == '/api/auth/admin':
            user_id   = self.headers.get('X-Remote-User-Id', '')
            user_name = self.headers.get('X-Remote-User-Name', '')
            is_admin  = get_admin_status(user_id, user_name)
            _debug(f'[API] auth/admin user={user_id!r} → {is_admin}')
            self._send_json(200 if is_admin else 403, {})

        elif raw_path.startswith('/api/auth/secret'):
            # /api/auth/secret/myapp  →  app_path = /myapp
            app_path = raw_path[len('/api/auth/secret'):]
            if not app_path:
                app_path = '/'
            cookie = self.headers.get('Cookie', '')
            valid  = has_valid_session(app_path, cookie)
            _debug(f'[API] auth/secret path={app_path!r} → {valid}')
            self._send_json(200 if valid else 401, {})

        else:
            self._send_json(404, {'error': 'Not found'})

    def do_POST(self):
        if self.path == '/api/verify-secret':
            client_ip = self.headers.get('X-Real-IP', self.client_address[0])
            if _is_rate_limited(client_ip):
                self._send_json(429, {'error': 'Too many attempts'})
                return

            length = int(self.headers.get('Content-Length', 0))
            if length > 4096:
                self._send_json(413, {'error': 'Payload too large'})
                return
            try:
                body = json.loads(self.rfile.read(length).decode())
            except Exception:
                self._send_json(400, {'error': 'Invalid JSON'})
                return

            app_path = body.get('path', '')
            password = body.get('password', '')

            secrets_map = load_secrets()
            _debug(f'[API] verify-secret path={app_path!r}')
            stored_hash = secrets_map.get(app_path)

            if stored_hash and bcrypt.checkpw(password.encode(), stored_hash.encode()):
                token = create_session(app_path)
                self._send_json(200, {'valid': True}, cookies=[
                    f'{_cookie_name(app_path)}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}'
                ])
            else:
                self._send_json(200, {'valid': False})

        else:
            self._send_json(404, {'error': 'Not found'})

    def _send_json(self, code: int, data: dict, cookies: list[str] | None = None):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        for cookie in (cookies or []):
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        if args and str(args[1]) not in ('200', '204'):
            print(f'[API] {self.address_string()} - ' + fmt % args)


if __name__ == '__main__':
    _load_sessions()
    server = ThreadingHTTPServer(('127.0.0.1', 8088), APIHandler)
    print('[API] Server started on 127.0.0.1:8088')
    server.serve_forever()
