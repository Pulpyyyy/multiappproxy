#!/usr/bin/env python3

import yaml
import json
import os
import sys
import hashlib
from urllib.parse import quote

def generate_nginx_config(config_file='/app/config.yml'):
    """Generate Nginx configuration from YAML config file.

    Reads /app/config.yml (converted from HA options.json by json_to_yaml.py),
    writes /app/apps.json (served to the frontend), /app/secrets.json (SHA256
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
                # Store SHA256 hash only — the plain secret never leaves the server
                secrets_map[app_path] = hashlib.sha256(secret_value.encode()).hexdigest()
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

        apps_json_str = json.dumps(apps_json).replace("'", "\\'").replace('"', '\\"')
        print(f"[DEBUG] JSON generated: {len(apps_json_str)} characters")

        # Write apps.json (served to the frontend, no secrets)
        with open('/app/apps.json', 'w') as f:
            json.dump({'apps': apps_json, 'debug': debug_mode}, f, indent=2)
        print(f"[DEBUG] apps.json written")

        # Write secrets.json (SHA256 hashes, server-side only — never served to the client)
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

        # Generate one proxy location block per configured app
        print("[DEBUG] Generating proxy configurations...")
        for app in apps:
            name = app['name']
            url = app['url']
            path = app.get('path', f"/{name.lower().replace(' ', '-')}")

            print(f"[DEBUG] App raw config: {app}")

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

            print(f"[DEBUG] Proxy {name}: {path} -> {url} (rewrite: {needs_rewrite})")

            if needs_rewrite:
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

            # Standard forwarding headers
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Let the upstream know its external path
            proxy_set_header X-External-Path {path};

            # Do not follow upstream redirects
            proxy_redirect off;

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
            sub_filter 'src="/' 'src="{path}/';
            sub_filter 'href="/' 'href="{path}/';
            sub_filter "src='/" "src='{path}/";
            sub_filter "href='/" "href='{path}/";
            sub_filter 'url(/' 'url({path}/';
            sub_filter '/api/' '{path}/api/';
            sub_filter '/socket.io/' '{path}/socket.io/';
            sub_filter '\\"/' '\\"{path}/';
            sub_filter "\\'/" "\\'{path}/";
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

            # Standard forwarding headers
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Ingress-Path $http_x_ingress_path;

            # Rewrite upstream redirects so they go through the proxy
            proxy_redirect / {path}/;
            proxy_redirect http://$host/ {path}/;
            proxy_redirect https://$host/ {path}/;

            # Prevent caching of proxied responses
            add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0";
            add_header Pragma "no-cache";
            add_header Expires 0;

            # Extended timeouts for long-lived WebSocket connections
            proxy_read_timeout 86400;
            proxy_send_timeout 86400;
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
