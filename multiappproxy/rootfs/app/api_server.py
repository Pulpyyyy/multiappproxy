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
import socket
import struct
import base64

SECRETS_FILE = '/app/secrets.json'
SUPERVISOR_TOKEN = os.environ.get('SUPERVISOR_TOKEN', '')
print(f'[API DEBUG] SUPERVISOR_TOKEN set: {bool(SUPERVISOR_TOKEN)} len={len(SUPERVISOR_TOKEN)}')

import urllib.request
import urllib.error

def _get_ha_ws_address():
    """Return (host, port) for HA WebSocket, resolved via Supervisor API."""
    try:
        req = urllib.request.Request(
            'http://supervisor/core/info',
            headers={'Authorization': f'Bearer {SUPERVISOR_TOKEN}'},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            info = json.loads(resp.read())
        port = info.get('data', {}).get('port', 8123)
        print(f'[WS DEBUG] HA port from Supervisor: {port}')
        return 'homeassistant', port
    except Exception as e:
        print(f'[WS DEBUG] Could not resolve HA address via Supervisor: {e}, falling back to homeassistant:8123')
        return 'homeassistant', 8123

# Per-user admin status cache: {user_id: (is_admin, timestamp)}
_user_cache = {}
CACHE_TTL = 300  # 5 minutes


def _ws_get_users():
    """Fetch user list from HA WebSocket API using SUPERVISOR_TOKEN."""
    token = SUPERVISOR_TOKEN

    def recv_exactly(sock, n):
        data = b''
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError('Connection closed')
            data += chunk
        return data

    def recv_frame(sock):
        b0, b1 = recv_exactly(sock, 2)
        length = b1 & 0x7f
        if length == 126:
            length = struct.unpack('>H', recv_exactly(sock, 2))[0]
        elif length == 127:
            length = struct.unpack('>Q', recv_exactly(sock, 8))[0]
        return json.loads(recv_exactly(sock, length).decode())

    def send_frame(sock, data):
        payload = json.dumps(data).encode()
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        n = len(masked)
        if n < 126:
            header = bytes([0x81, 0x80 | n]) + mask
        elif n < 65536:
            header = bytes([0x81, 0xfe]) + struct.pack('>H', n) + mask
        else:
            header = bytes([0x81, 0xff]) + struct.pack('>Q', n) + mask
        sock.sendall(header + masked)

    sock = socket.create_connection(('supervisor', 80), timeout=5)
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((
            'GET /core/websocket HTTP/1.1\r\n'
            'Host: supervisor\r\n'
            f'Authorization: Bearer {token}\r\n'
            'Upgrade: websocket\r\n'
            'Connection: Upgrade\r\n'
            f'Sec-WebSocket-Key: {key}\r\n'
            'Sec-WebSocket-Version: 13\r\n'
            '\r\n'
        ).encode())
        buf = b''
        while b'\r\n\r\n' not in buf:
            buf += sock.recv(4096)
        http_status = buf.split(b'\r\n')[0].decode()
        print(f'[WS DEBUG] HTTP response: {http_status}')
        msg = recv_frame(sock)
        print(f'[WS DEBUG] Frame 1: {msg}')
        if msg.get('type') == 'auth_required':
            send_frame(sock, {'type': 'auth', 'access_token': token})
            msg = recv_frame(sock)
            print(f'[WS DEBUG] Frame 2 (auth result): {msg}')
        if msg.get('type') != 'auth_ok':
            return None
        send_frame(sock, {'id': 1, 'type': 'config/auth/list'})
        result = recv_frame(sock)
        print(f'[WS DEBUG] Frame 3 (result?): type={result.get("type")} success={result.get("success")}')
        if result.get('type') == 'result' and result.get('success'):
            return result.get('result', [])
        return None
    finally:
        sock.close()


def get_admin_status(user_id, user_name=''):
    """Return True if the given user has admin rights in Home Assistant.

    Uses HA WebSocket API (config/auth/list) with SUPERVISOR_TOKEN.
    A user is considered admin if they are the owner (is_owner=True) or
    belong to the 'system-admin' group. Results are cached for CACHE_TTL
    seconds to avoid repeated calls.
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
        users = _ws_get_users()
        if users is not None:
            print(f'[API DEBUG] {len(users)} user(s) via WebSocket')
            user = next((u for u in users if u.get('id') == user_id), None)
            print(f'[API DEBUG] Match user_id={user_id!r}: {user is not None}')
            if user:
                is_admin = (
                    'system-admin' in user.get('group_ids', [])
                    or user.get('is_owner', False)
                )
                print(f'[API DEBUG] is_owner={user.get("is_owner")} group_ids={user.get("group_ids")} → is_admin={is_admin}')
        else:
            print('[API DEBUG] WebSocket returned no data')
    except Exception as e:
        import traceback
        print(f'[API DEBUG] WebSocket error: {e!r}\n{traceback.format_exc()}')
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
