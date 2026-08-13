#!/usr/bin/env python3

import yaml
import gzip
import json
import os
import re
import socket
import ssl
import sys
import zlib
import unicodedata
import bcrypt
from urllib.parse import quote, urlparse
try:
    import urllib.request
    import urllib.error
except ImportError:
    pass


def get_ha_ingress_url(addon_slug):
    """Query HA Supervisor API to get the current ingress URL for a given addon slug.

    Returns the ingress_url string (e.g. '/api/hassio_ingress/TOKEN/') or None on failure.
    """
    supervisor_token = os.environ.get('SUPERVISOR_TOKEN', '')
    if not supervisor_token:
        print(f"[WARN] SUPERVISOR_TOKEN not set, cannot resolve ingress URL for {addon_slug}")
        return None
    try:
        req = urllib.request.Request(
            f'http://supervisor/addons/{addon_slug}/info',
            headers={
                'Authorization': f'Bearer {supervisor_token}',
                'Content-Type': 'application/json',
            }
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        ingress_url = data.get('data', {}).get('ingress_url', '')
        if ingress_url:
            print(f"[DEBUG] Resolved ingress URL for {addon_slug}: {ingress_url}")
            return ingress_url.rstrip('/')
        print(f"[WARN] No ingress_url found for addon {addon_slug}")
        return None
    except Exception as e:
        print(f"[WARN] Failed to resolve ingress URL for {addon_slug}: {e}")
        return None

_PATH_RE = re.compile(r'^/[a-zA-Z0-9_-]+$')
# entry_path may span several segments and carry a query (e.g. /ui/dashboard?tab=1).
# It is interpolated into an nginx `return 301`, so ';', quotes and whitespace —
# anything that could terminate the directive or inject another one — are excluded.
_ENTRY_RE = re.compile(r'^(?:/[a-zA-Z0-9._~%-]+)+/?(?:\?[a-zA-Z0-9._~%&=+-]*)?$')

# Proxy paths that would shadow the portal's own locations
_RESERVED_PATHS = {'/api', '/static', '/apps.json'}


def slugify(name: str) -> str:
    """Turn an app name into a path slug accepted by _PATH_RE.

    Accents are folded rather than dropped so 'Caméra Jardin' gives 'camera-jardin'
    instead of 'cam-ra-jardin'.
    """
    folded = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-zA-Z0-9]+', '-', folded).strip('-').lower() or 'app'


def assign_paths(apps: list) -> None:
    """Derive every app's proxy path from its name. Not configurable.

    The slug is deterministic — the same name always yields the same path, so URLs
    are stable across restarts. Collisions (two apps named alike, or a slug matching
    a portal route) get a numeric suffix, assigned by declaration order.

    A `path` left over from an older configuration is accepted by the schema so the
    addon still starts, but it is ignored and reported.
    """
    used = set(_RESERVED_PATHS)

    for app in apps:
        name = app.get('name', '?')
        configured = app.get('path')
        base = f"/{slugify(name)}"
        path, suffix = base, 2
        while path in used:
            path = f"{base}-{suffix}"
            suffix += 1
        used.add(path)
        app['path'] = path
        if configured and configured != path:
            print(f"[AUTO] {name}: path is derived from the name now — "
                  f"configured '{configured}' ignored, using {path}")
        else:
            print(f"[AUTO] {name}: path = {path}")


# LAN devices answer in milliseconds; this only has to bound the wait for one that
# is powered off, since every app is probed before nginx starts.
_PROBE_TIMEOUT = 3
# Deliberately not a real host: the csrf probe needs a Host/Origin the upstream
# cannot recognise, exactly like the one a browser sends through HA ingress.
_PROBE_HOST = 'multiappproxy-probe.invalid'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface 3xx responses instead of following them — the Location header is
    what tells us where the app really wants the browser to land."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_PROBE_BODY_MAX = 256 * 1024


def _decode_body(headers, raw: bytes) -> str:
    """Text of a probe response, whatever the upstream chose to encode it with.

    Asking for `identity` is not enough: an embedded firmware often serves one
    pre-compressed file and answers gzip regardless of what was requested. Reading
    those bytes as text yields noise in which no markup can be found, and a caller
    that concludes anything from that emptiness concludes wrongly.
    """
    encoding = (headers.get('Content-Encoding', '') or '').strip().lower()
    if encoding in ('gzip', 'x-gzip'):
        try:
            raw = gzip.decompress(raw)
        except Exception:
            # A truncated body is expected — the read is capped — so decompress
            # what can be decompressed and keep it.
            try:
                raw = zlib.decompressobj(zlib.MAX_WBITS | 16).decompress(raw)
            except Exception:
                return ''
    elif encoding == 'deflate':
        try:
            raw = zlib.decompressobj().decompress(raw)
        except Exception:
            return ''
    elif encoding:
        # br and anything else: no decoder here, and noise would be worse than
        # nothing since it reads as a body with no markup in it.
        return ''
    return raw[:_PROBE_BODY_MAX].decode('utf-8', 'replace')


def _probe_get(url, extra_headers=None):
    """GET url without following redirects.

    Returns (status, headers, body), or None if the upstream could not be reached.
    The body is capped: it is only read to look for a sentinel, never kept.
    Never raises: detection is best-effort and must never block startup.
    """
    headers = {'User-Agent': 'multiappproxy/probe', 'Accept': '*/*',
               'Accept-Encoding': 'identity'}
    if extra_headers:
        headers.update(extra_headers)

    handlers = [_NoRedirect]
    if url.startswith('https'):
        # Same posture as the generated config: ssl_verify defaults to off so a
        # self-signed LAN certificate does not defeat detection.
        handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))

    try:
        opener = urllib.request.build_opener(*handlers)
        with opener.open(urllib.request.Request(url, headers=headers), timeout=_PROBE_TIMEOUT) as resp:
            return resp.status, resp.headers, _decode_body(resp.headers, resp.read(_PROBE_BODY_MAX))
    except urllib.error.HTTPError as exc:
        # 3xx (redirect not followed) and 4xx both carry the headers we want
        try:
            body = _decode_body(exc.headers, exc.read(_PROBE_BODY_MAX))
        except Exception:
            body = ''
        return exc.code, exc.headers, body
    except Exception as exc:
        print(f"[AUTO] probe failed for {url}: {exc}")
        return None


def detect_app_options(name: str, url: str) -> dict:
    """Infer the proxy options that are directly observable from the upstream.

    Only three of them can be read off the wire with certainty, so only those are
    detected — guessing the rest (ws_target, preserve_path, rewrite) from an HTTP
    response would be unreliable, and a wrong guess is worse than an option the
    user has to set once:

      entry_path  the Location of the redirect the app answers its root with
      hide_csp    a CSP/X-Frame-Options that forbids embedding outright
      csrf_fix    a 403 that appears only once Host/Origin/Referer are foreign

    Returns a dict of inferred options, possibly empty.
    """
    base = url.rstrip('/') + '/'
    detected = {}

    first = _probe_get(base)
    if first is None:
        print(f"[AUTO] {name}: upstream unreachable, keeping configured options as-is")
        return detected
    status, headers, _body = first

    # native_base_path — the app builds its own URLs from a prefix header, so nothing
    # needs rewriting: BirdNET-Go returns a fully prefixed document and a prefixed
    # Location once X-Ingress-Path is set. Detected by replaying the request with a
    # sentinel prefix and looking for it in what comes back.
    sentinel = '/__multiappproxy_probe__'
    aware = _probe_get(base, {'X-Ingress-Path': sentinel, 'X-Forwarded-Prefix': sentinel})
    if aware and (sentinel in (aware[1].get('Location') or '') or sentinel in aware[2]):
        detected['native_base_path'] = True

    # entry_path — the app redirects its root somewhere else (BirdNET-Go: /ui/dashboard).
    # HA ingress can follow that redirect itself, leaving the browser on {path}/ where
    # apps that derive their base path from the URL compute the wrong prefix.
    if 300 <= status < 400:
        location = headers.get('Location', '') or ''
        parsed_loc = urlparse(location)
        upstream_host = urlparse(base).netloc
        same_host = not parsed_loc.netloc or parsed_loc.netloc == upstream_host
        # Keep the query: it is part of where the app wants the browser to land
        target = parsed_loc.path + (f"?{parsed_loc.query}" if parsed_loc.query else '')
        if same_host and target and target != '/' and _ENTRY_RE.match(target):
            detected['entry_path'] = target

    # hide_csp — only when the app forbids embedding outright. 'self' and SAMEORIGIN
    # are satisfied inside the HA ingress iframe (the proxied document is served from
    # the HA origin), so stripping them would weaken the app for nothing.
    csp = headers.get('Content-Security-Policy', '') or ''
    xfo = (headers.get('X-Frame-Options', '') or '').strip().upper()
    frame_ancestors = re.search(r'frame-ancestors([^;]*)', csp, re.IGNORECASE)
    if (frame_ancestors and "'none'" in frame_ancestors.group(1).lower()) or xfo == 'DENY':
        detected['hide_csp'] = True

    # csrf_fix — replay a request with the foreign Origin/Referer a browser sends
    # through the ingress, and look for a rejection that appears only then.
    #
    # The Host header is deliberately left correct: upstreams reached through a
    # host-routing reverse proxy answer 403/404 to an unknown Host, which would look
    # like an origin check that isn't there.
    #
    # Both the root and the entry point are tried, and a 401 baseline is not
    # disqualifying: what matters is that the status turns into a 403 once the Origin
    # is foreign.
    #
    # This stays best-effort by construction. An app whose check is confined to the
    # endpoints its UI calls cannot be caught from the pages we know about:
    # ESPSomfy-RTS answers 200 on / whatever the Origin and only turns 401 into 403 on
    # /bootstrap, an endpoint nothing in the response reveals. Such apps still need
    # csrf_fix set by hand — hence never *clearing* a configured value from a probe.
    foreign = {
        'Origin': f'https://{_PROBE_HOST}',
        'Referer': f'https://{_PROBE_HOST}/',
    }
    targets = [base]
    if detected.get('entry_path'):
        targets.append(base.rstrip('/') + detected['entry_path'])

    for target in targets:
        baseline = first if target == base else _probe_get(target)
        if baseline is None:
            continue
        probed = _probe_get(target, foreign)
        if probed is None:
            continue
        if probed[0] == 403 and baseline[0] != 403:
            detected['csrf_fix'] = True
            break

    return detected


def validate_apps(apps: list) -> None:
    """Fail fast with a clear message if any app has an invalid url or path."""
    for app in apps:
        name = app.get('name', '?')
        url  = app.get('url', '')
        path = app.get('path', '')

        try:
            parsed = urlparse(url)
        except Exception as exc:
            raise ValueError(f"App '{name}': url invalide — {exc}") from exc

        if parsed.scheme not in ('http', 'https'):
            raise ValueError(
                f"App '{name}': url doit commencer par http:// ou https:// (reçu: {url!r})"
            )
        if not parsed.netloc:
            raise ValueError(f"App '{name}': url invalide — hôte manquant ({url!r})")

        if path and not _PATH_RE.match(path):
            raise ValueError(
                f"App '{name}': path '{path}' invalide — "
                f"format attendu: /slug (lettres, chiffres, - et _ uniquement)"
            )

        entry_path = app.get('entry_path', '')
        if entry_path and not _ENTRY_RE.match(entry_path):
            raise ValueError(
                f"App '{name}': entry_path '{entry_path}' invalide — "
                f"format attendu: /chemin/dans/l-app (ex: /ui/dashboard), "
                f"sans query string"
            )

        ws_target = app.get('ws_target', '')
        if ws_target:
            try:
                ws_parsed = urlparse(ws_target)
            except Exception as exc:
                raise ValueError(f"App '{name}': ws_target invalide — {exc}") from exc
            if ws_parsed.scheme not in ('http', 'https') or not ws_parsed.netloc:
                raise ValueError(
                    f"App '{name}': ws_target doit être une URL http(s) "
                    f"(ex: http://192.168.1.223:8080, reçu: {ws_target!r})"
                )


def generate_nginx_config(config_file='/app/config.yml'):
    """Generate Nginx configuration from YAML config file.

    Reads /app/config.yml (converted from HA options.json by json_to_yaml.py),
    writes /app/apps.json (served to the frontend), /app/secrets.json (bcrypt
    hashes for password-protected apps, server-side only), and
    /etc/nginx/nginx.conf.
    """

    print("[DEBUG] generate_config.py - Starting")

    try:
        print(f"[DEBUG] Reading {config_file}...")
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)

        apps = config.get('apps', [])
        debug_mode = config.get('debug', False)
        print(f"[DEBUG] {len(apps)} application(s) found")
        assign_paths(apps)
        validate_apps(apps)
        print(f"[DEBUG] Debug mode: {debug_mode}")

        # Probe the upstreams before anything is generated, so both apps.json and the
        # nginx config see the same, complete set of options.
        # Autodetection fills the gaps only: anything written in the config wins, so a
        # detection the user disagrees with can always be pinned by hand.
        autodetect_default = config.get('autodetect', True)
        for app in apps:
            if not app.get('autodetect', autodetect_default):
                print(f"[AUTO] {app['name']}: autodetect disabled")
                continue
            for key, value in detect_app_options(app['name'], app['url']).items():
                if key in app:
                    print(f"[AUTO] {app['name']}: {key} detected as {value}, "
                          f"keeping configured value {app[key]!r}")
                else:
                    app[key] = value
                    print(f"[AUTO] {app['name']}: {key} = {value}")

        # Detect Ingress mode via the HA environment variable
        ingress_entry = os.environ.get('INGRESS_ENTRY', '/')
        is_ingress = ingress_entry != '/'

        print(f"[DEBUG] Ingress mode: {is_ingress}")
        print(f"[DEBUG] Ingress entry: {ingress_entry}")

        # Build the JSON payload for the frontend home page
        apps_json = []
        secrets_map = {}
        for i, app in enumerate(apps):
            print(f"[DEBUG] App {i+1}: {app.get('name', 'N/A')}")
            app_path = app['path']  # always set by assign_paths()
            secret_value = app.get('secret', '')
            has_secret = bool(secret_value)
            if has_secret:
                # Store bcrypt hash only — the plain secret never leaves the server
                secrets_map[app_path] = bcrypt.hashpw(secret_value.encode(), bcrypt.gensalt()).decode()
            apps_json.append({
                'name': app['name'],
                'url': app['url'],
                'description': app.get('description', ''),
                'icon': app.get('icon', ''),
                'logo': app.get('logo', ''),
                'category': app.get('category', 'default'),
                'path': app_path,
                # Where the portal must send the browser. Linking straight to the app's
                # entry point instead of letting it redirect there matters for apps that
                # derive their base path from the URL: a redirect is the one step we do
                # not control end to end (HA ingress rewrites Location headers, browsers
                # cache them), and landing on {path}/ is enough for such an app to
                # compute an empty prefix and never recover.
                'entry': app.get('entry_path', ''),
                'admin': app.get('admin', False),
                'has_secret': has_secret,
                'debug': debug_mode
            })

        # Write apps.json (served to the frontend, no secrets)
        with open('/app/apps.json', 'w') as f:
            json.dump({'apps': apps_json, 'debug': debug_mode}, f, indent=2)
        print(f"[DEBUG] apps.json written")

        # Write secrets.json (bcrypt hashes, server-side only — never served to the client)
        with open('/app/secrets.json', 'w') as f:
            json.dump(secrets_map, f, indent=2)
        os.chmod('/app/secrets.json', 0o600)
        print(f"[DEBUG] secrets.json written ({len(secrets_map)} secret(s))")

        # Write debug flag for api_server.py (reads it at startup)
        flag_path = '/app/debug.flag'
        if debug_mode:
            open(flag_path, 'w').close()
        elif os.path.exists(flag_path):
            os.remove(flag_path)

        print("[DEBUG] Generating Nginx config template...")

        # Log level based on debug mode
        # nginx at debug level writes kilobytes per request, and the [DEBUG] lines
        # this addon's own logs carry come from Python, not from nginx. info gives
        # the connection-level detail worth having without turning the log into the
        # slowest part of a page load.
        error_log_level = "info" if debug_mode else "warn"

        nginx_config = f"""
events {{
    worker_connections 1024;
}}

http {{
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # DNS resolver (uses Home Assistant Supervisor DNS)
    resolver 172.30.32.3 valid=10s;
    resolver_timeout 5s;

    # Logging. The access log is buffered: one write per request is a poor deal on
    # the SD card most Home Assistant boxes run from.
    access_log /var/log/nginx/access.log combined buffer=32k flush=5s;
    error_log /var/log/nginx/error.log {error_log_level};

    # Performance
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;

    # Allow large uploads to upstreams (e.g. ESP firmware OTA through the
    # proxy). The nginx default (1m) makes them fail with HTTP 413.
    client_max_body_size 64m;

    # Proper Connection header: "upgrade" only when the client actually asks
    # for a WebSocket, "close" otherwise. Forcing "upgrade" on every request
    # confuses some embedded HTTP servers (ESP32, etc.).
    map $http_upgrade $connection_upgrade {{
        default upgrade;
        ''      close;
    }}

    # Compression is deliberately left off for proxied responses (gzip_proxied
    # defaults to off). Home Assistant's ingress decompresses whatever it receives
    # and re-encodes it for the browser on its own, so compressing here would only
    # cover the local hop to the ingress and would cost the box a compress and a
    # decompress for nothing. Measured through the ingress on an unmodified 1.4.1:
    # Zigbee2MQTT 2789 -> 1992, Z-Wave JS UI 3521 -> 2496, ESPSomfy 114516 -> 27360,
    # all delivered as deflate without this addon compressing anything.
    gzip on;
    gzip_vary on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml;

    # Rate limiting — secret verification (5 tentatives/min par IP)
    limit_req_zone $binary_remote_addr zone=verify_secret:10m rate=5r/m;

    # The scheme the browser actually used. HA ingress sets X-Forwarded-Proto: https;
    # on direct access $scheme is the truth. It serves two purposes: the Location
    # headers we rewrite come back absolute in HTTPS rather than relative (HA would
    # turn a relative one into http://host:8099/..., unreadable by the service
    # worker), and it is what we forward upstream. $scheme must never be forwarded:
    # on the ingress hop it is plain http, so an app deriving its own absolute URLs
    # from it — as any Laravel app does — builds them on http and an HTTPS dashboard
    # blocks every one of them as mixed content.
    # A chain of proxies appends to the header, so keep only the first hop; the whole
    # list would be neither a valid scheme nor a usable one.
    map $http_x_forwarded_proto $public_proto {{
        ""                    $fallback_proto;
        "~^(?<xfp>[^,\\s]+)"  $xfp;
        default               $fallback_proto;
    }}

    # Fallback when X-Forwarded-Proto is missing. HA ingress always sets
    # X-Ingress-Path, so its presence means the browser is on the HA page, which is
    # https whenever HA is reachable over TLS — and an https page could not follow an
    # http redirect anyway. On direct access, $scheme is the truth.
    map $http_x_ingress_path $fallback_proto {{
        ""      $scheme;
        default https;
    }}

    # The host the browser actually typed. Behind HA ingress $host is whatever the
    # addon's listener was reached as, which can be an internal name the browser
    # cannot resolve — an app that builds its own absolute URLs from Host then sends
    # the browser somewhere that does not exist. X-Forwarded-Host carries the real
    # one; when it is absent (direct access) $host already is the real one.
    # A chain of proxies appends to X-Forwarded-Host, so it can arrive as
    # "public.example, inner.example". Only the first hop is the browser's, and
    # sending the whole list as a Host header would be malformed — take the first
    # value, fall back to $host on anything unexpected.
    map $http_x_forwarded_host $public_host {{
        ""                    $host;
        "~^(?<xfh>[^,\\s]+)"  $xfh;
        default               $host;
    }}

    # An app with a strict CSP (script-src 'nonce-...' 'strict-dynamic') blocks the
    # runtime URL patch injected below, and does it silently: the page renders, the
    # console shows one violation, and only the URLs the app builds in JavaScript
    # stay wrong. The nonce is minted per response, so it is read off the upstream
    # header and carried onto our own script tag — the policy then accepts it, and
    # nothing has to be disabled. hide_csp remains for the apps whose policy breaks
    # the ingress iframe itself, which is a different problem.
    # script-src is tried first: default-src only applies where script-src is absent.
    map $upstream_http_content_security_policy $csp_nonce_attr {{
        ""                                            "";
        "~*script-src[^;]*'nonce-(?<cspn>[^']+)'"     ' nonce="$cspn"';
        "~*default-src[^;]*'nonce-(?<cspd>[^']+)'"    ' nonce="$cspd"';
        default                                       "";
    }}

    # Map to handle the Ingress path prefix
    map $http_x_ingress_path $ingress_path {{
        default "{ingress_entry}";
    }}

    server {{
        listen 8099;
        server_name _;

        # Security headers (portal pages only — not forwarded to upstreams)
        add_header X-Frame-Options SAMEORIGIN always;
        add_header X-Content-Type-Options nosniff always;
        add_header Referrer-Policy strict-origin-when-cross-origin always;

        # Redirect auth failures (admin/secret) to the portal home page
        error_page 401 403 = @auth_error;

        # Base path for Ingress
        set $base_path "";
"""

        if is_ingress:
            nginx_config += f"""
        # Ingress mode — HA strips the token prefix before forwarding, so we use /
        set $base_path "";
"""

        nginx_config += """

        # Home page
        location = / {
            alias /app/;
            try_files /index.html =404;
        }

        # App list (no secrets, cache disabled)
        location = /apps.json {
            alias /app/apps.json;
            default_type application/json;
            add_header Access-Control-Allow-Origin *;
            add_header Cache-Control "no-cache, no-store, must-revalidate";
        }

        location /static/ {
            alias /app/static/;
        }

        # Secret verification — rate limité à 5 req/min par IP (burst=3)
        location = /api/verify-secret {
            limit_req zone=verify_secret burst=3 nodelay;
            limit_req_status 429;
            proxy_pass http://127.0.0.1:8088;
            proxy_http_version 1.1;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header Host $host;
            proxy_connect_timeout 5s;
            proxy_read_timeout 10s;
        }

        # String catalogue, shared by both portal pages so there is one list of
        # supported languages rather than a copy per page.
        location = /i18n.js {
            alias /app/i18n.js;
            default_type application/javascript;
            add_header Cache-Control "no-cache";
        }

        # Analyzer page. Static, and left ungated on purpose: it shows nothing on
        # its own, and the API it calls refuses anyone who is not an administrator.
        location = /analyze {
            alias /app/;
            try_files /analyze.html =404;
        }

        # The analyzer issues several probes to the upstream, each with its own
        # timeout, so it needs far more room than the portal's own API calls.
        location = /api/analyze {
            proxy_pass http://127.0.0.1:8088;
            proxy_http_version 1.1;
            proxy_set_header X-Remote-User-Id $http_x_remote_user_id;
            proxy_set_header X-Remote-User-Name $http_x_remote_user_name;
            proxy_set_header X-Remote-User-Display-Name $http_x_remote_user_display_name;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header Host $host;
            proxy_connect_timeout 5s;
            proxy_read_timeout 60s;
        }

        # Internal API: user info and secret verification
        # Proxied to the Python api_server running on 127.0.0.1:8088
        location /api/ {
            proxy_pass http://127.0.0.1:8088;
            proxy_http_version 1.1;
            proxy_set_header X-Remote-User-Id $http_x_remote_user_id;
            proxy_set_header X-Remote-User-Name $http_x_remote_user_name;
            proxy_set_header X-Remote-User-Display-Name $http_x_remote_user_display_name;
            proxy_set_header Host $host;
            proxy_connect_timeout 5s;
            proxy_read_timeout 10s;
        }
"""

        # En mode ingress, HA peut reconstruire des redirects en URL absolue avec le
        # port backend (8099). Le navigateur tape alors directement sur nginx avec le
        # préfixe /api/hassio_ingress/TOKEN intact. Ce bloc le strip et réinjecte
        # le chemin dans la chaîne de location normale.
        if is_ingress:
            nginx_config += f"""
        location ^~ /api/hassio_ingress/ {{
            rewrite ^{ingress_entry}(/.*)$ $1 last;
            return 404;
        }}
"""

        # Generate one proxy location block per configured app
        print("[DEBUG] Generating proxy configurations...")
        for app in apps:
            name = app['name']
            url = app['url']
            path = app['path']  # always set by assign_paths()

            print(f"[DEBUG] App raw config: {app}")

            # hassio_ingress_slug — resolve the HA ingress path dynamically from Supervisor API.
            # Generates a secondary nginx location that strips the ingress prefix before
            # forwarding to Django, so static files and API calls embedded in HA-ingress-aware
            # HTML are served correctly without touching the main proxy path.
            hassio_ingress_slug = app.get('hassio_ingress_slug', '')
            resolved_ingress_path = None
            if hassio_ingress_slug:
                resolved_ingress_path = get_ha_ingress_url(hassio_ingress_slug)
                if resolved_ingress_path:
                    print(f"[DEBUG] Resolved ingress path for {name}: {resolved_ingress_path}")
                else:
                    print(f"[WARN] Could not resolve ingress URL for {name}, secondary location skipped")

            # preserve_path mode — forwards requests as-is without stripping the prefix.
            # Used for apps that already embed their full path in URLs.
            preserve_path = app.get('preserve_path', False)

            # Determine whether the app needs full URL rewriting.
            # If 'rewrite' is explicitly set (True or False) in the config, honour it.
            # Otherwise fall back to name-based auto-detection.
            if 'rewrite' in app:
                needs_rewrite = app['rewrite']
                print(f"[DEBUG] Explicit rewrite for {name}: {needs_rewrite}")
            else:
                name_lower = name.lower()
                needs_rewrite = (
                    'zwave' in name_lower or
                    'zwavejs' in name_lower or
                    'zigbee2mqtt' in name_lower or
                    'z2m' in name_lower
                )
                print(f"[DEBUG] Auto-detected rewrite for {name}: {needs_rewrite}")

            # native_base_path — the app is told its prefix and builds every URL from it,
            # so the proxy must stop rewriting entirely: the document, the redirects and
            # the URLs built at runtime already carry the prefix, and rewriting them
            # again would double it. This is the clean way to proxy such an app, and it
            # also lets compression through — nothing has to be filtered any more.
            native_base_path = app.get('native_base_path', False)
            if native_base_path and needs_rewrite:
                needs_rewrite = False
                print(f"[DEBUG] native_base_path for {name}: rewrite forced off")

            print(f"[DEBUG] Proxy {name}: {path} -> {url} (rewrite: {needs_rewrite}, preserve_path: {preserve_path}, native_base_path: {native_base_path})")

            # hide_csp — drop upstream security headers that break embedding.
            # e.g. ESPSomfy-RTS sends "frame-ancestors 'none'" + a connect-src limited
            # to ws://*:8080, both incompatible with the HA ingress iframe.
            if app.get('hide_csp', False):
                hide_csp_block = """
            # Drop upstream security headers incompatible with HA ingress (iframe)
            proxy_hide_header Content-Security-Policy;
            proxy_hide_header X-Frame-Options;"""
                print(f"[DEBUG] hide_csp enabled for {name}")
            else:
                hide_csp_block = ""

            # fast_upstream — stops the proxy from pessimizing backends that are
            # noticeably slower through it than in direct access (ESP32 firmwares,
            # MCU web servers, but also SPA backends serving a large asset bundle).
            # Three defaults that suit a generic app but hurt here are lifted:
            #  - proxy_buffering is re-enabled, so nginx drains the upstream at LAN
            #    speed and releases its socket immediately instead of holding it open
            #    for the whole (possibly remote) client transfer;
            #  - the forced no-store headers are dropped, so the app's own cache
            #    headers reach the browser and its service worker can actually cache
            #    assets instead of refetching the whole UI on every load;
            #  - static assets get their own location (see asset_location below) that
            #    keeps upstream compression, which the main location has to disable
            #    for sub_filter.
            # Do not enable for apps that stream responses progressively (SSE, live
            # logs) unless they send X-Accel-Buffering: no, which nginx honours even
            # with buffering on. WebSocket locations are unaffected — nginx always
            # tunnels 101 responses unbuffered.
            fast_upstream = app.get('fast_upstream', False)
            if fast_upstream:
                buffering_directive = "proxy_buffering on;"
                cache_headers_block = ""
                print(f"[DEBUG] fast_upstream enabled for {name}: buffering on, upstream cache headers preserved")
            else:
                buffering_directive = "proxy_buffering off;"
                cache_headers_block = """
            # Prevent caching of proxied responses
            add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0";
            add_header Pragma "no-cache";
            add_header Expires 0;
"""

            # SSL verification (only relevant for https upstreams)
            ssl_verify = app.get('ssl_verify', False)
            if url.startswith('https'):
                if ssl_verify:
                    ssl_block = """proxy_ssl_verify on;
            proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;
            proxy_ssl_server_name on;"""
                else:
                    ssl_block = """proxy_ssl_verify off;
            proxy_ssl_server_name on;"""
            else:
                ssl_block = ""

            # Server-side access control via nginx auth_request
            is_admin_app  = app.get('admin', False)
            has_secret    = bool(app.get('secret', ''))
            if is_admin_app:
                # Admin apps: verify HA admin status on every request
                auth_request_block = """
            auth_request /api/auth/admin;"""
            elif has_secret:
                # Secret apps: verify session cookie set by /api/verify-secret
                # Path is encoded in the URI itself — no query string (auth_request encodes '?')
                auth_request_block = f"""
            auth_request /api/auth/secret{path};"""
            else:
                auth_request_block = ""

            # In ingress mode, absolute paths in HTML must include the full ingress prefix
            # so the browser resolves them correctly on the HA domain.
            # e.g. href="/nspm/settings" → href="/api/hassio_ingress/TOKEN/nspm/settings"
            if is_ingress:
                effective_path = f"{ingress_entry.rstrip('/')}{path}"
            else:
                effective_path = path
            print(f"[DEBUG] Effective path for sub_filter: {effective_path}")

            if native_base_path:
                # The nginx variable is used rather than effective_path on purpose: HA
                # regenerates its ingress token, so a prefix frozen at generation time
                # would go stale. $http_x_ingress_path follows the live request, and is
                # empty on direct access, which leaves just {path} — also correct.
                prefix_header_block = f"""
            # This app prefixes its own URLs from the header below, so it is forwarded
            # instead of blanked. X-Forwarded-Prefix carries the same contract under
            # another name (Grafana, Django, ...).
            proxy_set_header X-Ingress-Path "$http_x_ingress_path{path}";
            proxy_set_header X-Forwarded-Prefix "$http_x_ingress_path{path}";

            # Still blanked: the runtime patch and the stylesheet rewrite below have to
            # see uncompressed responses. Only HTML and CSS come through here — the JS
            # bundles are served by the asset location, compression intact.
            proxy_set_header Accept-Encoding "";
"""
                # Its Location headers already carry the prefix — only the scheme and
                # host are missing, without which HA ingress rewrites the bare path into
                # http://$host:8099/... and the browser blocks it as mixed content.
                # Its Location headers already carry the prefix, so only the scheme and
                # host are added — inserting the prefix again would double it.
                redirect_block = (
                    "            proxy_redirect ~^/(.*) "
                    "$public_proto://$public_host/$1;"
                )
                asset_prefix_header = (
                    f'proxy_set_header X-Ingress-Path "$http_x_ingress_path{path}";'
                )
                print(f"[DEBUG] native_base_path for {name}: forwarding prefix, no rewriting")
            else:
                prefix_header_block = """
            # Do NOT forward X-Ingress-Path to the backend.
            # Some apps (e.g. Django) use this header to prefix their static URLs,
            # which causes a double-prefix when sub_filter also rewrites paths.
            proxy_set_header X-Ingress-Path "";

            # Disable compression so sub_filter can rewrite HTML responses
            proxy_set_header Accept-Encoding "";
"""
                # Two shapes have to be caught. A path-only Location is missing the
                # prefix and the scheme both. An absolute one — built by an app that
                # derives its URLs from the Host header, as Laravel does — names the
                # right host but knows nothing of the prefix. Matching on our own host
                # keeps third-party redirects (OAuth providers) strictly untouched.
                # nginx tries these in order and stops at the first match, so the
                # already-prefixed shapes come first. Without them, an app configured
                # by hand with the full public URL — the workaround people reach for
                # when an app cannot find its own prefix — would get it added twice.
                redirect_block = "\n".join([
                    f"            proxy_redirect http://$public_host{effective_path}/"
                    f" $public_proto://$public_host{effective_path}/;",
                    f"            proxy_redirect https://$public_host{effective_path}/"
                    f" $public_proto://$public_host{effective_path}/;",
                    f"            proxy_redirect {effective_path}/"
                    f" $public_proto://$public_host{effective_path}/;",
                    f"            proxy_redirect http://$public_host/"
                    f" $public_proto://$public_host{effective_path}/;",
                    f"            proxy_redirect https://$public_host/"
                    f" $public_proto://$public_host{effective_path}/;",
                    f"            proxy_redirect ~^/(.*)"
                    f" $public_proto://$public_host{effective_path}/$1;",
                ])
                asset_prefix_header = 'proxy_set_header X-Ingress-Path "";'

            if preserve_path:
                # Preserve path mode — no prefix stripping, no sub_filter.
                # proxy_pass without trailing URI preserves the original request path.
                # Required for HA addon ingress where all URLs already contain the full path.
                nginx_config += f"""
        # Proxy for {name} (preserve path)
        location {path}/ {{{auth_request_block}
            proxy_pass {url};
            proxy_http_version 1.1;

            {ssl_block}{hide_csp_block}

            # WebSocket support
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_set_header Sec-WebSocket-Protocol $http_sec_websocket_protocol;

            # Standard forwarding headers
            proxy_set_header Host $public_host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $public_proto;
            proxy_set_header X-Forwarded-Host $public_host;

            # Response buffering (nginx always tunnels WebSocket upgrades unbuffered)
            {buffering_directive}

            proxy_read_timeout 86400;
            proxy_send_timeout 86400;
        }}
"""
            elif needs_rewrite:
                # Full URL rewrite mode — used for apps like Z-Wave JS UI or Zigbee2MQTT
                # that embed absolute paths in their HTML/JS/CSS responses.
                token = app.get('token', '')

                if token:
                    token_encoded = quote(token, safe='')
                    print(f"[DEBUG] Token configured for {name}")
                    token_config = f"""set $token "{token_encoded}";
            set $args $args&token=$token;
            """
                else:
                    token_encoded = ''
                    token_config = ''

                nginx_config += f"""
        # Proxy for {name} (full URL rewrite)
        location {path}/ {{{auth_request_block}

            # Authentication token
            {token_config}
            # Strip the path prefix before forwarding to the upstream
            rewrite ^{path}/(.*) /$1 break;

            proxy_pass {url};
            proxy_http_version 1.1;

            {ssl_block}{hide_csp_block}

            # WebSocket support
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_set_header Sec-WebSocket-Protocol $http_sec_websocket_protocol;

            # Standard forwarding headers
            proxy_set_header Host $public_host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $public_proto;
            proxy_set_header X-Forwarded-Host $public_host;

            # Let the upstream know its external path
            proxy_set_header X-External-Path {path};

            # Rewrite upstream redirects so they go through the proxy
            proxy_redirect ~^/(.*) $public_proto://$public_host{effective_path}/$1;

            # Response buffering (nginx always tunnels WebSocket upgrades unbuffered)
            {buffering_directive}
{cache_headers_block}
            proxy_read_timeout 86400;
            proxy_send_timeout 86400;
            proxy_connect_timeout 30;

            # Rewrite absolute paths in HTML/JS/CSS responses to add the proxy prefix
            # text/html is always filtered, listing it would warn about a duplicate
            sub_filter_types text/css text/javascript application/javascript application/json;
            sub_filter_once off;
            sub_filter 'src="/' 'src="{effective_path}/';
            sub_filter 'href="/' 'href="{effective_path}/';
            sub_filter "src='/" "src='{effective_path}/";
            sub_filter "href='/" "href='{effective_path}/";
            sub_filter 'url(/' 'url({effective_path}/';
            sub_filter '/api/' '{effective_path}/api/';
            sub_filter '/socket.io/' '{effective_path}/socket.io/';
            sub_filter '\\"/' '\\"{effective_path}/';
            sub_filter "\\'/" "\\'{effective_path}/";
        }}

        # Static assets (css, js, fonts, images) — served without rewriting
        location ~ ^{path}/(static|css|js|fonts|img|images)/ {{
            rewrite ^{path}/(.*) /$1 break;
            proxy_pass {url};
            {ssl_block}
            proxy_set_header Host $public_host;
            proxy_cache_valid 200 1h;
            expires 1h;
        }}
"""
            else:
                # Standard reverse proxy — proxy_pass trailing slash strips the prefix
                token = app.get('token', '')
                if token:
                    token_encoded = quote(token, safe='')
                else:
                    token_encoded = ''

                proxy_url = f"{url}/"

                # csrf_fix — overrides the Origin header with the upstream URL so Django's
                # CSRF middleware sees a matching Origin and Host (both set to the upstream
                # address). Required when the upstream is a Django app without HA ingress
                # (e.g. NSPanel Manager), accessed through the multiappproxy ingress, because
                # the browser sends Origin: https://homeassistant.example.com but Django
                # receives an internal Host that does not match.
                csrf_fix = app.get('csrf_fix', False)
                if csrf_fix:
                    _parsed = urlparse(url)
                    upstream_origin = f"{_parsed.scheme}://{_parsed.netloc}"
                    upstream_host = _parsed.netloc
                    # Override Origin, Referer and Host with the upstream address.
                    # Django CSRF compares Origin against Host; making them equal lets the
                    # check pass without requiring CSRF_TRUSTED_ORIGINS on the upstream.
                    # Referer is rewritten too: some embedded firmwares (e.g. ESPSomfy-RTS)
                    # fall back to Referer when Origin is absent (all GET requests) and
                    # reject the request if its host differs from the Host header.
                    host_header = f'proxy_set_header Host "{upstream_host}";'
                    csrf_origin_header = (
                        f'proxy_set_header Origin "{upstream_origin}";\n'
                        f'            proxy_set_header Referer "{upstream_origin}/";'
                    )
                    print(f"[DEBUG] csrf_fix enabled for {name}: Origin/Referer → {upstream_origin}")
                else:
                    host_header = "proxy_set_header Host $public_host;"
                    csrf_origin_header = ""

                token_config = ''
                if token_encoded:
                    token_config = f"""# Authentication token
            set $suffix '';
            if ($args != '') {{
                set $suffix '&';
            }}
            set $token "{token_encoded}";
            set $args $args${{suffix}}token=$token;
            """

                # Build the sub_filter directives.
                # For HA-ingress-aware apps (hassio_ingress_slug set), Django already generates
                # absolute paths with its own ingress token (e.g. /api/hassio_ingress/TOKEN/static/).
                # We replace that token prefix with multiappproxy's effective_path so the browser
                # requests flow back through multiappproxy → Django correctly.
                # For regular apps, we prepend effective_path to all root-relative paths.
                if resolved_ingress_path:
                    sub_filter_block = f"""
            # App is HA-ingress-aware: replace its own ingress token with our proxy path.
            # This turns /api/hassio_ingress/APP_TOKEN/... → {effective_path}/...
            # so the browser re-routes those requests through multiappproxy.
            sub_filter_once off;
            sub_filter '{resolved_ingress_path}' '{effective_path}';"""
                    print(f"[DEBUG] Using ingress-token sub_filter for {name}: replace '{resolved_ingress_path}' → '{effective_path}'")
                else:
                    ws_rewrite = app.get('ws_rewrite', False)

                    # When ws_rewrite is enabled, inject a small script that patches
                    # window.WebSocket at runtime. The script rewrites any WebSocket URL
                    # containing /websocket/ (absolute or relative) so the path goes through
                    # this app's proxy location instead of hitting the domain root directly.
                    # This handles URLs constructed server-side (ws://ip:port/websocket/stomp)
                    # and client-side (wss://window.location.host + "/websocket/stomp").
                    if ws_rewrite:
                        ws_script = (
                            "(function(){"
                            "var W=window.WebSocket;"
                            "window.WebSocket=function(u,p){"
                            'if(typeof u==="string"&&/\\/(websocket|wss?)\\//.test(u)){'
                            "var m=u.match(/^wss?:\\/\\/[^\\/]+(\\/.*)/);var path=m?m[1]:u;"
                            'u=(location.protocol==="https:"?"wss":"ws")+"://"+location.host'
                            f'+"{ effective_path }"+path;'
                            "}return p?new W(u,p):new W(u);};"
                            "}());"
                        )
                        ws_inject = f"\n            sub_filter '</body>' '<script>{ws_script}</script></body>';"
                        print(f"[DEBUG] ws_rewrite enabled for {name}: injecting WebSocket patch via sub_filter")
                    else:
                        ws_inject = ""

                    # Runtime URL patch, injected right after <head> so it is in place
                    # before any of the app's own scripts run.
                    #
                    # sub_filter can only reach markup: URLs an app builds in JavaScript
                    # are invisible to it, and its compressed JS bundles cannot be
                    # filtered at all. This patch closes that gap at the moment a URL is
                    # used, by prefixing root-absolute ones with the proxy path.
                    #
                    # It is idempotent — a URL already under the prefix is returned
                    # untouched — so an app that resolves its own base path correctly is
                    # unaffected, which is why it needs no option.
                    #
                    # history.pushState/replaceState matter as much as the network calls:
                    # a router that rewrites the address bar without the prefix makes
                    # every app that derives its base path from the URL compute an empty
                    # one, and nothing recovers from that.
                    patch = (
                        "(function(){"
                        f'var P="{effective_path}";if(!P)return;'
                        "function f(u){"
                        'if(typeof u!=="string")return u;'
                        'if(u.charAt(0)==="/"&&u.charAt(1)!=="/")'
                        'return(u===P||u.indexOf(P+"/")===0)?u:P+u;'
                        # Bundlers resolve their baked asset base against the page origin
                        # before using it, so what reaches us is a fully absolute URL with
                        # the prefix missing from its path. Same origin only: anything
                        # third-party (telemetry, CDNs) must be left strictly alone.
                        "var o=location.origin;"
                        'if(u.indexOf(o+"/")===0){var r=u.slice(o.length);'
                        'if(r!==P&&r.indexOf(P+"/")!==0)return o+P+r;}'
                        "return u;}"
                        "var F=window.fetch;if(F)window.fetch=function(i,o){"
                        'if(typeof i==="string")i=f(i);'
                        "else if(i&&i.url)i=new Request(f(i.url),i);"
                        "return F.call(this,i,o);};"
                        "var X=XMLHttpRequest.prototype.open;"
                        "XMLHttpRequest.prototype.open=function(){"
                        "arguments[1]=f(arguments[1]);return X.apply(this,arguments);};"
                        # Wrapping a constructor must carry its interface constants over.
                        # A bare function loses EventSource.CONNECTING/OPEN and
                        # WebSocket.CLOSING/CLOSED, and reconnection state machines compare
                        # against exactly those: every comparison silently turns false and
                        # the client drops and reopens the stream in a loop.
                        "function K(N,C){C.prototype=N.prototype;"
                        '["CONNECTING","OPEN","CLOSING","CLOSED"].forEach(function(k){'
                        "if(k in N)try{C[k]=N[k];}catch(e){}});return C;}"
                        "var E=window.EventSource;"
                        "if(E)window.EventSource=K(E,function(u,c){return new E(f(u),c);});"
                        "var W=window.WebSocket;"
                        "if(W)window.WebSocket=K(W,function(u,p){"
                        # No '$' anywhere in this script: nginx reads it as the start of
                        # a variable inside a sub_filter argument and refuses the whole
                        # configuration ("invalid variable name"). The regex therefore
                        # carries no end anchor — it is not needed to capture the path.
                        'if(typeof u==="string"){var m=u.match(/^wss?:\\/\\/[^\\/]+(\\/.*)/);'
                        'if(m)u=(location.protocol==="https:"?"wss":"ws")+"://"+location.host+f(m[1]);'
                        "else u=f(u);}"
                        "return p?new W(u,p):new W(u);});"
                        '["pushState","replaceState"].forEach(function(n){'
                        "var o=history[n];history[n]=function(s,t,u){"
                        "return o.call(this,s,t,u==null?u:f(String(u)));};});"
                        # Media assigned from script never touches fetch or XHR: an app
                        # doing img.src="/api/..." (spectrograms, thumbnails, audio)
                        # would still reach the domain root. Patch the property setter
                        # and setAttribute, the only two ways to get there.
                        "function P2(C,k){if(!C)return;"
                        "var d=Object.getOwnPropertyDescriptor(C.prototype,k);"
                        "if(!d||!d.set)return;"
                        "Object.defineProperty(C.prototype,k,{configurable:true,"
                        "enumerable:d.enumerable,get:d.get,set:function(v){"
                        'd.set.call(this,typeof v==="string"?f(v):v);}});}'
                        "P2(window.HTMLImageElement,\"src\");"
                        "P2(window.HTMLMediaElement,\"src\");"
                        "P2(window.HTMLSourceElement,\"src\");"
                        "P2(window.HTMLScriptElement,\"src\");"
                        "P2(window.HTMLLinkElement,\"href\");"
                        "var SA=Element.prototype.setAttribute;"
                        "Element.prototype.setAttribute=function(n,v){"
                        'if((n==="src"||n==="href")&&typeof v==="string")v=f(v);'
                        "return SA.call(this,n,v);};"
                        "}());"
                    )
                    # $csp_nonce_attr carries the upstream nonce when the app sends a
                    # strict CSP, and expands to nothing otherwise — so the tag stays
                    # plain <script> for the apps that have no policy at all.
                    patch_inject = (
                        f"\n            sub_filter '<head>' "
                        f"'<head><script$csp_nonce_attr>{patch}</script>';"
                    )
                    print(f"[DEBUG] Runtime URL patch injected for {name} (prefix {effective_path})")

                    if native_base_path:
                        # The app prefixes its own markup, so rewriting it again would
                        # double the prefix — src="/api/hassio_ingress/..." starts with
                        # src="/ and would be prefixed a second time.
                        #
                        # Two things it cannot prefix are still rewritten. Its bundler
                        # bakes an absolute base into the chunk loader, so lazily loaded
                        # components are requested from the domain root whatever the
                        # server says — that is what broke BirdNET-Go's detection route.
                        # The runtime patch catches those where they are used, and being
                        # idempotent it leaves the URLs the app already prefixed alone.
                        # Stylesheets are static build artefacts the app never touches,
                        # so their url(...) references need the rewrite.
                        sub_filter_block = f"""
            # The app prefixes its own markup; only what it cannot reach is rewritten.
            sub_filter_types text/css;
            sub_filter_once off;
            sub_filter 'url(/'     'url({effective_path}/';
            sub_filter "url('/"    "url('{effective_path}/";
            sub_filter 'url("/'    'url("{effective_path}/';{patch_inject}{ws_inject}"""
                        print(f"[DEBUG] native_base_path for {name}: markup left alone, "
                              f"runtime patch kept for bundler-baked asset URLs")
                    else:
                        sub_filter_block = f"""
            # Rewrite absolute paths in responses so they go through the proxy.
            # Markup: static assets (src/href), forms (action), HTMX attributes.
            # Stylesheets: url(...) references, which no amount of markup rewriting
            # would reach — that is where BirdNET-Go's fonts were being lost.
            sub_filter_types text/css;
            sub_filter_once off;
            sub_filter 'src="/'    'src="{effective_path}/';
            sub_filter 'href="/'   'href="{effective_path}/';
            sub_filter 'action="/' 'action="{effective_path}/';
            sub_filter 'hx-get="/'    'hx-get="{effective_path}/';
            sub_filter 'hx-post="/'   'hx-post="{effective_path}/';
            sub_filter 'hx-put="/'    'hx-put="{effective_path}/';
            sub_filter 'hx-delete="/' 'hx-delete="{effective_path}/';
            sub_filter 'hx-patch="/'  'hx-patch="{effective_path}/';
            sub_filter 'url(/'     'url({effective_path}/';
            sub_filter "url('/"    "url('{effective_path}/";
            sub_filter 'url("/'    'url("{effective_path}/';{patch_inject}{ws_inject}"""

                nginx_config += f"""
        # Proxy for {name}
        location {path}/ {{{auth_request_block}
            {token_config}
            proxy_pass {proxy_url};
            proxy_http_version 1.1;

            {ssl_block}{hide_csp_block}

            # WebSocket support
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_set_header Sec-WebSocket-Protocol $http_sec_websocket_protocol;

            # Standard forwarding headers
            {host_header}
            {csrf_origin_header}
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $public_proto;
            proxy_set_header X-Forwarded-Host $public_host;

{prefix_header_block}
            # Rewrite upstream redirects so they go through the proxy
{redirect_block}

{cache_headers_block}
            proxy_read_timeout 86400;
            proxy_send_timeout 86400;

            # Response buffering — off by default for progressive PHP output and
            # streaming; on with fast_upstream to free the upstream socket fast.
            {buffering_directive}
{sub_filter_block}
        }}
"""

                # Static assets always get their own location.
                # The main location has to blank Accept-Encoding so sub_filter can
                # rewrite HTML, but sub_filter_types is text/html only — JS, CSS and
                # images were being decompressed for nothing (a modern SPA bundle
                # easily triples in size) and stripped of their Cache-Control, so the
                # browser refetched the whole bundle on every load. Here compression
                # and the upstream cache headers are left alone. A regex location wins
                # over the prefix location above regardless of declaration order.
                # No option gates this: it only ever matches requests with a file
                # extension, so it cannot affect HTML, API calls, SSE or WebSockets.
                # css is deliberately absent: stylesheets go through the main location
                # so sub_filter can rewrite their url(...) references. They are small
                # next to a JS bundle, so serving them uncompressed costs little.
                asset_exts = (
                    'js|mjs|map|woff2?|ttf|otf|eot|'
                    'png|jpe?g|gif|svg|webp|avif|ico|webmanifest|mp3|wav|ogg'
                )
                nginx_config += f"""
        # Static assets for {name} (compression and upstream caching preserved)
        location ~* ^{path}/.+\\.(?:{asset_exts})$ {{{auth_request_block}
            {token_config}
            # Strip the path prefix before forwarding to the upstream
            rewrite ^{path}/(.*) /$1 break;

            proxy_pass {url};
            proxy_http_version 1.1;

            {ssl_block}{hide_csp_block}

            # Standard forwarding headers
            {host_header}
            {csrf_origin_header}
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $public_proto;
            proxy_set_header X-Forwarded-Host $public_host;
            {asset_prefix_header}

            # Rewrite upstream redirects so they go through the proxy
            proxy_redirect ~^/(.*) $public_proto://$public_host{effective_path}/$1;

            proxy_buffering on;
        }}
"""

            # entry_path — force the browser onto the app's real entry URL.
            # Apps that answer their root with a redirect (BirdNET-Go: / → /ui/dashboard)
            # can end up rendered at {path}/ instead: HA ingress follows the upstream
            # redirect itself, so the browser address bar never leaves {path}/. Apps that
            # derive their own base path from the URL then compute the wrong prefix and
            # send every API call to the domain root. Redirecting the entry point
            # ourselves keeps the browser on a URL the app can parse.
            entry_path = app.get('entry_path', '')
            # Fully absolute, scheme included. HA ingress prefixes anything that does
            # not start with http(s):// with http://$host:8099 — it treats a bare path
            # and a protocol-relative //host/path alike, producing
            # http://host:8099//host/path, which an HTTPS dashboard blocks as mixed
            # content. Only an absolute URL is passed through untouched.
            landing = "$public_proto://$public_host" + (
                f"{effective_path}{entry_path}" if entry_path else f"{effective_path}/"
            )
            # 302, not 301: the entry point comes from a probe replayed at every start,
            # so it is not permanent. A 301 is cached by browsers indefinitely and
            # replayed without ever asking the server again — an addon update then has
            # no effect on the client, whatever the new configuration says.
            if entry_path:
                print(f"[DEBUG] entry_path for {name}: {path}/ → {landing}")
                nginx_config += f"""
        # Entry point for {name} (the app cannot be rendered at {path}/ itself)
        location = {path}/ {{
            return 302 {landing};
        }}
"""

            # Redirect /path → landing : apps with relative assets (embedded firmwares,
            # simple web UIs) resolve them against the wrong base without the slash.
            nginx_config += f"""
        # Trailing-slash redirect for {name}
        location = {path} {{
            return 302 {landing};
        }}
"""

            # ws_target — dedicated WebSocket upstream on a separate port.
            # e.g. ESPSomfy-RTS serves HTTP on :80 but its WebSocket on :8080.
            # The client connects to {path}/ws through the proxy (wss on HTTPS pages,
            # no mixed content) and nginx forwards to the ws_target in clear on the LAN.
            ws_target = app.get('ws_target', '')
            if ws_target:
                ws_parsed = urlparse(ws_target)
                ws_host = ws_parsed.netloc
                ws_url = ws_target.rstrip('/') + '/'
                if ws_target.startswith('https'):
                    ws_ssl_block = """proxy_ssl_verify off;
            proxy_ssl_server_name on;"""
                else:
                    ws_ssl_block = ""
                # An app that checks the request origin checks it on the socket too,
                # and it is one session across both. Leaving the browser's own Origin
                # here while csrf_fix rewrites it on every other location shows the
                # app two different origins for one session. Recomputed rather than
                # borrowed: csrf_origin_header exists only in the standard-proxy
                # branch, and an app can reach here from any of the three.
                if app.get('csrf_fix', False):
                    _csrf = urlparse(url)
                    _origin = f"{_csrf.scheme}://{_csrf.netloc}"
                    ws_origin_header = (
                        f'proxy_set_header Origin "{_origin}";\n'
                        f'            proxy_set_header Referer "{_origin}/";'
                    )
                else:
                    ws_origin_header = ""
                print(f"[DEBUG] ws_target for {name}: {path}/ws → {ws_url}"
                      + (" (csrf_fix origin applied)" if ws_origin_header else ""))
                nginx_config += f"""
        # Dedicated WebSocket upstream for {name}
        location = {path}/ws {{{auth_request_block}
            proxy_pass {ws_url};
            proxy_http_version 1.1;
            {ws_ssl_block}
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_set_header Sec-WebSocket-Protocol $http_sec_websocket_protocol;
            proxy_set_header Host {ws_host};
            {ws_origin_header}
            proxy_buffering off;
            proxy_read_timeout 86400;
            proxy_send_timeout 86400;
        }}
"""

        # Absolute for the same reason as the entry-point redirects: HA ingress
        # rewrites anything else into http://$host:8099/...
        home_redirect = "$public_proto://$public_host" + (
            ingress_entry.rstrip('/') + '/' if is_ingress else '/'
        )
        nginx_config += f"""
        # Auth failure handler: redirect to portal home page
        location @auth_error {{
            return 302 {home_redirect};
        }}
    }}
}}
"""

        # Write the final Nginx config
        print("[DEBUG] Writing /etc/nginx/nginx.conf...")
        with open('/etc/nginx/nginx.conf', 'w') as f:
            f.write(nginx_config)

        print(f"✓ Nginx configuration generated successfully")
        print(f"✓ Mode: {'Ingress' if is_ingress else 'Standalone'}")
        print(f"✓ Base path: {ingress_entry}")
        print(f"✓ {len(apps)} application(s) configured")

    except FileNotFoundError as e:
        print(f"[ERROR] File not found: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyError as e:
        print(f"[ERROR] Missing key in configuration: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    generate_nginx_config()
