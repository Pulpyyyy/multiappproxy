# 🚀 Multi-App Proxy
![GitHub release (with filter)](https://img.shields.io/github/v/release/Pulpyyyy/multiappproxy) ![GitHub](https://img.shields.io/github/license/Pulpyyyy/multiappproxy)

Simple and elegant reverse proxy for managing multiple web applications from Home Assistant.

![sample](img/multiproxy.png)

### Features

- 🔀 Multi-application reverse proxy with categories
- 🔐 Token authentication (zigbee2mqtt-proxy compatible)
- 🔑 Password-protected apps (bcrypt, server-side verification)
- 🛡️ Admin-only apps (hidden from non-admin HA users)
- 🎨 Modern interface with Home Assistant theme
- 📡 Native Home Assistant Ingress support
- 🌐 Full WebSocket support (Z-Wave JS UI, Zigbee2MQTT, Matter Bridge, etc.)
- 🔒 Self-signed SSL support
- 🐛 Debug mode with real-time logs
- 🖼️ Custom logos (emoji or image URL)

## Add repository

[![`Addon Home Assistant`](https://raw.githubusercontent.com/Pulpyyyy/multiappproxy/refs/heads/main/.github/img/addon-ha.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FPulpyyyy%2Fmultiappproxy)

---

## 🎯 Overview

Multi-App Proxy is a Home Assistant add-on that allows accessing multiple web applications through a unified interface with native Ingress support.

### Features

- ✅ **Multi-application proxy** with elegant web interface
- ✅ **Custom categories** with automatic icons
- ✅ **Debug mode** with real-time logs
- ✅ **Token authentication** (zigbee2mqtt-proxy style)
- ✅ **Password-protected apps** (bcrypt, server-side only)
- ✅ **Admin-only apps** (hidden from non-admin HA users)
- ✅ **Auto-signed SSL support**
- ✅ **Full WebSocket support** (Z-Wave, Zigbee, Matter)
- ✅ **Custom logos** (emoji or image URL)
- ✅ **Native Ingress** Home Assistant
- ✅ **Home Assistant internal DNS**
- ✅ **YAML order preserved**

---

## 📦 Installation

### Method 1: Via GitHub Repository

1. In Home Assistant, go to **Settings** → **Add-ons** → **Add-on Store**

2. Click **⋮** (menu) at the top right → **Repositories**

3. Add the URL:
   ```
   https://github.com/Pulpyyyy/multiappproxy
   ```

4. Click **Add**

5. Refresh the page and install **Multi-App Proxy**

### Method 2: Manual Installation

1. Copy the `ha-addon` folder to `/addons/multiappproxy/`

2. Reload add-ons

3. Install **Multi-App Proxy**

---

## ⚙️ Configuration

### Minimal Configuration

```yaml
apps:
  - name: My Application
    url: http://192.168.1.100:8080
```

### Complete Configuration

```yaml
debug: true  # Enable real-time logs

apps:
  - name: Z-Wave JS UI
    url: http://192.168.1.123:8091
    description: Z-Wave management interface
    icon: ⚡
    logo: https://example.com/zwave-logo.png
    path: /zwavejsui
    rewrite: false
    category: Protocols
    
  - name: Zigbee2MQTT
    url: https://zigbee2mqtt.example.com:8080
    description: Zigbee to MQTT gateway
    icon: 🐝
    path: /z2m
    token: SuperSecretToken?
    rewrite: false
    category: Protocols
    
  - name: Matter Bridge
    url: http://matter-bridge.local:8283
    description: Matter gateway
    icon: 🌉
    logo: https://raw.githubusercontent.com/t0bst4r/matterbridge/main/frontend/public/matterbridge%2064x64.png
    path: /matter
    category: Protocols

  - name: Portainer
    url: http://portainer:9000
    description: Docker management (admin only)
    icon: 🐳
    path: /portainer
    category: Tools
    admin: true        # Hidden from non-admin users

  - name: Private App
    url: http://192.168.1.200:5000
    description: Password-protected application
    icon: 🔒
    path: /private
    secret: MySecretPassword  # bcrypt-hashed at startup, never sent to the client
```

---

## 📋 Detailed Parameters

### Global Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `debug` | boolean | `false` | Enable real-time logs on interface and `error_log debug` in Nginx |

### Per-Application Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | ✅ Yes | - | Display name on card |
| `url` | string | ✅ Yes | - | Backend application URL (http/https) |
| `path` | string | No | `/app-name` | Access path in proxy |
| `description` | string | No | `""` | Description shown under name |
| `icon` | string | No | 📱 | Emoji to display (UTF-8) |
| `logo` | string | No | - | Image URL (takes priority over icon) |
| `category` | string | No | `Others` | Grouping category |
| `token` | string | No | - | Authentication token (added as query string) |
| `rewrite` | boolean | No | auto | Force URL rewriting on/off. Auto-detected by name if omitted (see below) |
| `preserve_path` | boolean | No | `false` | Forward requests as-is without stripping the path prefix (for apps already aware of their full path, e.g. HA-ingress-native addons) |
| `hassio_ingress_slug` | string | No | - | Slug of another HA addon; the proxy resolves its ingress URL via the Supervisor API and rewrites matching paths in HTML responses so they flow back through multiappproxy |
| `secret` | string | No | - | Password required to open the app (bcrypt-hashed at startup, never sent to the client) |
| `admin` | boolean | No | `false` | Hide this app from non-admin users (owner or system-admin group) |
| `csrf_fix` | boolean | No | `false` | Override `Origin` and `Host` headers with the upstream URL. Required for Django apps that enforce CSRF checks on the `Origin` header (e.g. NSPanel Manager accessed through ingress) |
| `ws_rewrite` | boolean | No | `false` | Inject a JavaScript patch at runtime that rewrites WebSocket URLs so they go through the proxy. Use when the upstream constructs WebSocket URLs server-side with an absolute host/path |

### Categories and Icons

The following categories have automatic icons:

| Category | Icon | Usage |
|----------|------|-------|
| `Automation` | 🏠 | Home automation applications |
| `Protocol` or `Protocols` | 📡 | Z-Wave, Zigbee, Matter |
| `Media` | 🎥 | Plex, Jellyfin, etc. |
| `Tools` | 🔧 | Utilities |
| `Network` | 🌐 | Network tools |
| `Security` | 🔒 | Cameras, alarms |
| `Others` | 📱 | Default |

### URL Format

- ✅ `http://192.168.1.100:8080`
- ✅ `https://app.domain.com:8443`
- ✅ `http://hostname.local:3000`
- ❌ No trailing slash
- ❌ No path in URL

### Path Format

- ✅ `/myapp` (no trailing slash)
- ❌ `/myapp/` (with trailing slash)
- ❌ `/my/long/path` (no sub-paths)

### Password Protection

Protect any app with a password using the `secret` field:

```yaml
- name: Private App
  url: http://192.168.1.200:5000
  path: /private
  secret: MyPassword123
```

**How it works:**
1. The user clicks the card — a password modal is shown
2. The frontend POSTs the plain password to `/api/verify-secret` over the HA Ingress connection (HTTPS)
3. The backend verifies it with `bcrypt.checkpw` against the stored hash; on success the browser navigates to the app
4. The plain-text password is never stored — only the bcrypt hash (with random salt) is kept in `/app/secrets.json`, server-side only

**Rate limiting:** `/api/verify-secret` is limited to **5 attempts per minute per IP** at the Nginx level (burst of 3). A secondary in-process counter in the API server provides defense-in-depth.

### Admin-Only Apps

Restrict an app's visibility to Home Assistant admin users:

```yaml
- name: Admin Tool
  url: http://192.168.1.50:8080
  path: /admin-tool
  admin: true
```

**How it works:**
- On page load, the frontend calls `/api/user` to get the current user's admin status
- Apps with `admin: true` are silently omitted from the rendered grid for non-admin users
- A user is considered admin if `is_owner: true` or `group_ids` contains `system-admin`, read from `/config/.storage/auth` (requires `config:ro` mapping)

### URL Rewriting Auto-Detection

When `rewrite` is not set, the proxy auto-detects whether full URL rewriting is needed based on the app name. Rewriting is automatically enabled if the name contains `zwave`, `zwavejs`, `zigbee2mqtt`, or `z2m` (case-insensitive).

Set `rewrite: false` explicitly to disable this behaviour for a matched name, or `rewrite: true` to force it for any other app.

### Token Authentication

The token is automatically added as a query string:

```yaml
token: MySecretToken123
```

Generates: `http://backend/?token=MySecretToken123`

**Special characters**: Automatically URL-encoded
- `?` → `%3F`
- `&` → `%26`
- `=` → `%3D`

---

## 🔧 Supported Applications

### ✅ Tested and Validated

#### Z-Wave JS UI
```yaml
- name: Z-Wave JS UI
  url: https://zwavejs.yourdomain.com:8091
  icon: ⚡
  path: /zwavejsui
  category: Protocols
```

**Notes:**
- Full WebSocket support
- Self-signed SSL supported
- No special configuration required

#### Zigbee2MQTT
```yaml
- name: Zigbee2MQTT
  url: http://zigbee2mqtt.local:8080
  icon: 🐝
  path: /z2m
  token: YourToken
  category: Protocols
```

**Zigbee2MQTT configuration required:**
```yaml
# In Zigbee2MQTT configuration.yaml
frontend:
  url: /z2m
```

**Notes:**
- Token automatically managed
- `frontend.url` configuration mandatory
- Compatible with official zigbee2mqtt-proxy logic

#### Matter Bridge
```yaml
- name: Matter Bridge
  url: http://matter-bridge.local:8283
  icon: 🌉
  path: /matter
  category: Protocols
```

### ⚙️ Other Applications

Any standard web application will work. Examples:

- **Portainer**: `http://portainer:9000`
- **Grafana**: `http://grafana:3000`
- **Node-RED**: `http://nodered:1880`
- **ESPHome**: `http://esphome:6052`

---

## 🛠 Troubleshooting

### Logs not displaying

**Solution:** Enable debug mode
```yaml
debug: true
```

### Application unreachable (404)

**Possible causes:**
1. Incorrect backend URL
2. Application not started
3. DNS issue

**Verification:**
```bash
# From the add-on terminal
curl -I http://your-app:8080
```

### Error 301 in loop

**Cause:** Application not configured for sub-path

**Solution for Zigbee2MQTT:**
```yaml
# In Zigbee2MQTT configuration.yaml
frontend:
  url: /z2m
```

### Token not transmitted

**Verification:**
```yaml
debug: true  # Enable logs
```

Look in logs for: `Token encoded: XXX... → YYY...`

**Nginx logs:** Enable debug to see full requests

### Self-signed SSL refused

**Solution:** Already handled automatically by add-on
```nginx
proxy_ssl_verify off;
proxy_ssl_server_name on;
```

### WebSocket not working

**Verification:** WebSocket headers are automatic
```nginx
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```

If issue persists, check backend URL.

---

## 🗂 Technical Architecture

### Stack

- **Nginx 1.28.2**: Reverse proxy
- **Python 3**: Configuration scripts
- **S6-overlay**: Service supervision

### Request Flow

```
Home Assistant Ingress
         ↓
/api/hassio_ingress/XXX/
         ↓
    Nginx (port 8099)
         ↓
    Backend Applications
```

### Configuration Generation

1. **Home Assistant** → `/data/options.json`
2. **sync_config.py** → YAML ↔ JSON sync
3. **json_to_yaml.py** → `/app/config.yml`
4. **generate_config.py** → `/etc/nginx/nginx.conf` + `/app/apps.json` + `/app/secrets.json`
5. **api_server.py** (port 8088) → `/api/user` (admin check) + `/api/verify-secret` (password check)
6. **index.html** → Loads `apps.json`, calls `/api/user`, renders interface

### Internal DNS

Automatic resolver on Home Assistant Supervisor DNS:
```nginx
resolver 172.30.32.3 valid=10s;
```

Allows using:
- `http://addon-name.local`
- `http://hostname.local`
- `http://192.168.1.X`

### Ingress Mode

Automatic detection via `$INGRESS_ENTRY`:
- Interface detects the basePath
- Nginx configures locations correctly
- No manual configuration needed

---

## 📝 Configuration Files

### Structure

```
/addon_configs/
└── xxxxx_multiappproxy/
    └── multi-app-proxy.yaml  # Config saved automatically
```

### Manual Editing

You can edit `multi-app-proxy.yaml` directly:

1. Edit the file
2. Restart the add-on
3. Config will sync automatically

---

## 🔐 Security

### Password Protection (`secret`)

- Password is **bcrypt-hashed** (with random salt) at startup; the plain value is immediately discarded
- Only the bcrypt hash is stored in `/app/secrets.json` (server-side only, never served to the browser)
- Verification happens via `POST /api/verify-secret` — the frontend sends the plain password over HTTPS and the backend calls `bcrypt.checkpw`
- A correct password grants navigation to the app URL for that browser session
- `/api/verify-secret` is rate-limited to **5 requests/min per IP** at the Nginx layer (burst 3), with a secondary in-process counter as defense-in-depth

### Admin Visibility (`admin`)

- Admin status is determined by reading `/config/.storage/auth` directly (requires `config:ro` mapping)
- A user is admin if `is_owner: true` or `'system-admin' in group_ids`
- Result is cached per user for 5 minutes to avoid repeated file reads
- Non-admin users never receive a filtered-out app in `apps.json` — filtering happens client-side after the `/api/user` call

### Token Authentication

- Automatically URL-encoded
- Added as query string (`?token=XXX` or `&token=XXX`)
- Never exposed in logs (truncated)

### Security Headers

```nginx
add_header Cache-Control "no-store, no-cache, must-revalidate";
add_header Pragma "no-cache";
add_header Expires 0;
```

### SSL/TLS

- HTTPS backends support
- Self-signed certificates accepted
- No strict validation

---

## 🎨 Customization

### Custom Logos

**Via emoji:**
```yaml
icon: 🐝
```

**Via image URL:**
```yaml
logo: https://example.com/logo.png
```

**Priority:** `logo` > `icon` > default (📱)

**Automatic fallback:** If logo fails to load, icon displays

### Display Order

Applications display **in YAML declaration order**.

Categories appear in order of the **first app** in each category.

---

## 📊 Logs and Debug

### Debug Mode

```yaml
debug: true
```

**Effects:**
- Shows logs on web interface
- Enables `error_log debug` in Nginx
- Detailed configuration generation logs

### Viewing Logs

**Web interface:**
- Visible at top of page if `debug: true`
- Real-time logs during loading

**Add-on logs:**
- Home Assistant → Add-ons → Multi-App Proxy → Logs

**Nginx logs:**
```bash
# From add-on terminal
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log
```

---

## 🆘 Support

### Known Issues

1. **Double slash in URL**: Fixed in v1.0.4
2. **App order**: Preserved since v1.0.4
3. **Token with special characters**: Automatically URL-encoded

### Report a Bug

GitHub Issues: https://github.com/Pulpyyyy/multiappproxy/issues

**Information to provide:**
- Add-on version
- Logs with `debug: true`
- Anonymized configuration
- Application concerned

---

## 📜 Changelog

### v1.0.8
- ✅ Password hashing upgraded from SHA256 to **bcrypt** (salted, resistant to rainbow tables)
- ✅ Rate limiting on `/api/verify-secret`: 5 req/min per IP at Nginx level + secondary in-process counter
- ✅ XSS fix in frontend: all user-supplied values now inserted via `textContent` / DOM API instead of `innerHTML`
- ✅ New parameters documented: `csrf_fix`, `ws_rewrite`

### v1.0.7
- ✅ New `preserve_path` parameter (forward requests without stripping the path prefix)
- ✅ New `hassio_ingress_slug` parameter (resolve another addon's ingress URL via Supervisor API)
- ✅ Reworked admin detection and config storage path
- ✅ Config mapped via `addon_config:rw` (replaces `config:rw`)
- ✅ Various path and proxy fixes

### v1.0.6
- ✅ Base image updated to addon-base 20.0.4

### v1.0.5
- ✅ Password-protected apps (`secret` field, server-side verification)
- ✅ Admin-only apps (`admin` field, HA WebSocket API)
- ✅ Bug fix: navigation after password validation now goes to the app
- ✅ All code comments translated to English
- ✅ Translations updated for all 6 languages

### v1.0.4 (2026-02-08)
- ✅ YAML order preserved
- ✅ Debug mode with UI logs
- ✅ Custom logo support
- ✅ Material Design icon
- ✅ Complete documentation

### v1.0.3
- ✅ Trailing slash fix
- ✅ Token URL-encoding
- ✅ Collapsible categories

### v1.0.2
- ✅ Native Ingress support
- ✅ Auto-signed SSL
- ✅ Full WebSocket support

### v1.0.1
- ✅ Initial version

---

## 📄 License

MIT License

---

## 🙏 Credits

- Inspired by [zigbee2mqtt-proxy](https://github.com/zigbee2mqtt/hassio-zigbee2mqtt/tree/master/zigbee2mqtt-proxy)
- Material Design icons: https://materialdesignicons.com
- Home Assistant community

---

**Maintained by:** [@Pulpyyyy](https://github.com/Pulpyyyy)
