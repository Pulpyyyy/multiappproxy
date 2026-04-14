#!/usr/bin/env python3

import yaml
import json
import os
import sys
import bcrypt
from urllib.parse import quote
try:
    import urllib.request
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
        print(f"[DEBUG] Debug mode: {debug_mode}")

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
            app_path = app.get('path', f"/{app['name'].lower().replace(' ', '-')}")
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
        print(f"[DEBUG] secrets.json written ({len(secrets_map)} secret(s))")

        print("[DEBUG] Generating Nginx config template...")

        # Log level based on debug mode
        error_log_level = "debug" if debug_mode else "warn"

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

    # Logging
    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log {error_log_level};

    # Performance
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;

    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml;

    # Rate limiting — secret verification (5 tentatives/min par IP)
    limit_req_zone $binary_remote_addr zone=verify_secret:10m rate=5r/m;

    # Protocole réel pour la réécriture des redirects upstream.
    # HA ingress pose X-Forwarded-Proto: https ; en accès direct on utilise $scheme.
    # Permet de retourner des Location absolus en HTTPS plutôt que relatifs (que HA
    # reconvertirait en http://host:8099/... illisibles par le service worker).
    map $http_x_forwarded_proto $proxy_redirect_proto {{
        ""      $scheme;
        default $http_x_forwarded_proto;
    }}

    # Map to handle the Ingress path prefix
    map $http_x_ingress_path $ingress_path {{
        default "{ingress_entry}";
    }}

    server {{
        listen 8099;
        server_name _;

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
            path = app.get('path', f"/{name.lower().replace(' ', '-')}")

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

            print(f"[DEBUG] Proxy {name}: {path} -> {url} (rewrite: {needs_rewrite}, preserve_path: {preserve_path})")

            # In ingress mode, absolute paths in HTML must include the full ingress prefix
            # so the browser resolves them correctly on the HA domain.
            # e.g. href="/nspm/settings" → href="/api/hassio_ingress/TOKEN/nspm/settings"
            if is_ingress:
                effective_path = f"{ingress_entry.rstrip('/')}{path}"
            else:
                effective_path = path
            print(f"[DEBUG] Effective path for sub_filter: {effective_path}")

            if preserve_path:
                # Preserve path mode — no prefix stripping, no sub_filter.
                # proxy_pass without trailing URI preserves the original request path.
                # Required for HA addon ingress where all URLs already contain the full path.
                nginx_config += f"""
        # Proxy for {name} (preserve path)
        location {path}/ {{
            proxy_pass {url};
            proxy_http_version 1.1;

            # Disable SSL verification (allows self-signed certificates)
            proxy_ssl_verify off;
            proxy_ssl_server_name on;

            # WebSocket support
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Sec-WebSocket-Protocol $http_sec_websocket_protocol;

            # Standard forwarding headers
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-Host $http_host;

            # Disable response buffering (required for WebSocket)
            proxy_buffering off;

            # Extended timeouts for long-lived WebSocket connections
            proxy_read_timeout 86400;
            proxy_send_timeout 86400;
        }}
"""
            elif needs_rewrite:
                # Full URL rewrite mode — used for apps like Z-Wave JS UI or Zigbee2MQTT
                # that embed absolute paths in their HTML/JS/CSS responses.
                token = app.get('token', '')

                # URL-encode the token to safely handle special characters
                if token:
                    token_encoded = quote(token, safe='')
                    print(f"[DEBUG] Token encoded: {token[:5]}... → {token_encoded[:5]}...")
                    token_config = f"""set $token "{token_encoded}";
            set $args $args&token=$token;
            """
                else:
                    token_encoded = ''
                    token_config = ''

                nginx_config += f"""
        # Proxy for {name} (full URL rewrite)
        location {path}/ {{

            # Authentication token
            {token_config}
            # Strip the path prefix before forwarding to the upstream
            rewrite ^{path}/(.*) /$1 break;

            proxy_pass {url};
            proxy_http_version 1.1;

            # Disable SSL verification (allows self-signed certificates)
            proxy_ssl_verify off;
            proxy_ssl_server_name on;

            # WebSocket support
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Sec-WebSocket-Protocol $http_sec_websocket_protocol;

            # Standard forwarding headers
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-Host $http_host;

            # Let the upstream know its external path
            proxy_set_header X-External-Path {path};

            # Rewrite upstream redirects so they go through the proxy
            proxy_redirect ~^/(.*) $proxy_redirect_proto://$host{effective_path}/$1;

            # Disable response buffering (required for WebSocket)
            proxy_buffering off;

            # Prevent caching of proxied responses
            add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0";
            add_header Pragma "no-cache";
            add_header Expires 0;

            # Extended timeouts for long-lived WebSocket connections
            proxy_read_timeout 86400;
            proxy_send_timeout 86400;
            proxy_connect_timeout 240;

            # Rewrite absolute paths in HTML/JS/CSS responses to add the proxy prefix
            sub_filter_types text/html text/css text/javascript application/javascript application/json;
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
            proxy_ssl_verify off;
            proxy_ssl_server_name on;
            proxy_set_header Host $host;
            proxy_cache_valid 200 1h;
            expires 1h;
        }}
"""
            else:
                # Standard reverse proxy — proxy_pass trailing slash strips the prefix
                token = app.get('token', '')

                # URL-encode the token to safely handle special characters
                if token:
                    token_encoded = quote(token, safe='')
                    print(f"[DEBUG] Token encoded: {token[:5]}... → {token_encoded[:5]}...")
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
                    from urllib.parse import urlparse as _urlparse
                    _parsed = _urlparse(url)
                    upstream_origin = f"{_parsed.scheme}://{_parsed.netloc}"
                    upstream_host = _parsed.netloc
                    # Override both Origin and Host with the upstream address.
                    # Django CSRF compares Origin against Host; making them equal lets the
                    # check pass without requiring CSRF_TRUSTED_ORIGINS on the upstream.
                    host_header = f'proxy_set_header Host "{upstream_host}";'
                    csrf_origin_header = f'proxy_set_header Origin "{upstream_origin}";'
                    print(f"[DEBUG] csrf_fix enabled for {name}: Origin → {upstream_origin}")
                else:
                    host_header = "proxy_set_header Host $host;"
                    csrf_origin_header = ""

                token_config = ''
                if token_encoded:
                    # Append the token to the query string, preserving existing args
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
            sub_filter_types text/html;
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

                    sub_filter_block = f"""
            # Rewrite absolute paths in HTML responses so they go through the proxy.
            # Covers static assets (src/href), forms (action), and HTMX attributes.
            sub_filter_types text/html;
            sub_filter_once off;
            sub_filter 'src="/'    'src="{effective_path}/';
            sub_filter 'href="/'   'href="{effective_path}/';
            sub_filter 'action="/' 'action="{effective_path}/';
            sub_filter 'hx-get="/'    'hx-get="{effective_path}/';
            sub_filter 'hx-post="/'   'hx-post="{effective_path}/';
            sub_filter 'hx-put="/'    'hx-put="{effective_path}/';
            sub_filter 'hx-delete="/' 'hx-delete="{effective_path}/';
            sub_filter 'hx-patch="/'  'hx-patch="{effective_path}/';{ws_inject}"""

                nginx_config += f"""
        # Proxy for {name}
        location {path}/ {{
            {token_config}
            proxy_pass {proxy_url};
            proxy_http_version 1.1;

            # Disable SSL verification (allows self-signed certificates)
            proxy_ssl_verify off;
            proxy_ssl_server_name on;

            # WebSocket support
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Sec-WebSocket-Protocol $http_sec_websocket_protocol;

            # Standard forwarding headers
            {host_header}
            {csrf_origin_header}
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-Host $http_host;

            # Do NOT forward X-Ingress-Path to the backend.
            # Some apps (e.g. Django) use this header to prefix their static URLs,
            # which causes a double-prefix when sub_filter also rewrites paths.
            proxy_set_header X-Ingress-Path "";

            # Disable compression so sub_filter can rewrite HTML responses
            proxy_set_header Accept-Encoding "";

            # Rewrite upstream redirects so they go through the proxy
            proxy_redirect ~^/(.*) $proxy_redirect_proto://$host{effective_path}/$1;

            # Prevent caching of proxied responses
            add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0";
            add_header Pragma "no-cache";
            add_header Expires 0;

            # Extended timeouts for long-lived WebSocket connections
            proxy_read_timeout 86400;
            proxy_send_timeout 86400;

            # Disable response buffering (required for progressive PHP output and WebSocket)
            proxy_buffering off;
{sub_filter_block}
        }}
"""


        nginx_config += """
    }
}
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
