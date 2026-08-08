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
    rewrite: false
    category: Protocols
    
  - name: Zigbee2MQTT
    url: https://zigbee2mqtt.example.com:8080
    description: Zigbee to MQTT gateway
    icon: 🐝
    token: SuperSecretToken?
    rewrite: false
    category: Protocols
    
  - name: Matter Bridge
    url: http://matter-bridge.local:8283
    description: Matter gateway
    icon: 🌉
    logo: https://raw.githubusercontent.com/t0bst4r/matterbridge/main/frontend/public/matterbridge%2064x64.png
    category: Protocols

  - name: Portainer
    url: http://portainer:9000
    description: Docker management (admin only)
    icon: 🐳
    category: Tools
    admin: true        # Hidden from non-admin users

  - name: Private App
    url: http://192.168.1.200:5000
    description: Password-protected application
    icon: 🔒
    secret: MySecretPassword  # bcrypt-hashed at startup, never sent to the client
```

---

## 📋 Detailed Parameters

### Global Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `debug` | boolean | `false` | Enable real-time logs on interface and `error_log debug` in Nginx |
| `autodetect` | boolean | `true` | Probe every upstream at startup to infer the options that can be read off the wire. Overridable per app |

### Per-Application Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | ✅ Yes | - | Display name on card |
| `url` | string | ✅ Yes | - | Backend application URL (http/https) |
| `path` | string | — | derived from `name` | **Deprecated and ignored.** The proxy path is slugified from the app name (`BirdNET-Go` → `/birdnet-go`) and made unique automatically. Still accepted by the schema so older configurations start, but the configured value is not used |
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
| `csrf_fix` | boolean | No | autodetected | Override `Origin`, `Referer` and `Host` headers with the upstream URL. Required for apps that validate the request origin: Django apps (e.g. NSPanel Manager) or embedded firmwares (e.g. ESPSomfy-RTS) |
| `ws_rewrite` | boolean | No | `false` | Inject a JavaScript patch at runtime that rewrites WebSocket URLs so they go through the proxy. Use when the upstream constructs WebSocket URLs server-side with an absolute host/path |
| `ssl_verify` | boolean | No | `false` | Verify the upstream SSL certificate against the system CA bundle (https upstreams only) |
| `ws_target` | string | No | - | Dedicated WebSocket upstream (e.g. `http://192.168.1.223:8080`). Exposes it at `{path}/ws` through the proxy — for devices serving HTTP and WebSocket on different ports (ESPSomfy-RTS) |
| `hide_csp` | boolean | No | autodetected | Strip upstream `Content-Security-Policy` / `X-Frame-Options` headers. Required when the app forbids iframes (`frame-ancestors 'none'`) and must render inside HA ingress |
| `entry_path` | string | No | autodetected | Internal path the browser is sent to when the app is opened (e.g. `/ui/dashboard`). For apps that answer their root with a redirect |
| `native_base_path` | boolean | No | autodetected | Forward the proxy prefix as `X-Ingress-Path` / `X-Forwarded-Prefix` and stop rewriting anything — the app prefixes its own HTML, redirects and JavaScript. More reliable than rewriting, and compression is preserved |
| `autodetect` | boolean | No | `true` | Probe this upstream at startup. Set `false` to pin the configuration exactly as written |
| `fast_upstream` | boolean | No | `false` | Enable response buffering and stop forcing `no-store` on the app's own responses. Use when the app is much slower through the proxy than in direct access (embedded devices). Do **not** enable for apps that stream responses (SSE, live logs) unless they send `X-Accel-Buffering: no`. Static assets are always served compressed and cacheable, with or without this option |

### Autodetection

Most apps need nothing but a `name` and a `url`. At startup, before nginx is
launched, the proxy sends a couple of harmless `GET` requests to each upstream
and reads the answer:

| Inferred | Signal |
|----------|--------|
| `path` | slugified from `name`, made unique — no probe involved, and no longer configurable |
| `entry_path` | the app answers its root with a redirect to another path |
| `hide_csp` | the app returns `frame-ancestors 'none'` or `X-Frame-Options: DENY` |
| `csrf_fix` | the app returns 403 only once `Host` / `Origin` / `Referer` are foreign |
| `native_base_path` | a sentinel sent as `X-Ingress-Path` comes back inside the app's own response |

Anything written in the configuration always wins — autodetection only fills the
gaps, so a decision you disagree with can be pinned by hand. Every decision is
printed in the addon log (`[AUTO] …`).

The remaining options cannot be read off an HTTP response and stay manual:
`ws_target` (a different port), `preserve_path`, `rewrite`, `ssl_verify`,
`hassio_ingress_slug` and `fast_upstream`. Guessing them would be unreliable, and
a wrong guess costs more than an option set once.

If an upstream is powered off at startup, its probe times out after 3 s, a
warning is logged and its configured options are used unchanged — detection
never blocks the addon from starting. Restarting the addon re-runs it.

### Analyzing an app before you configure it

Autodetection fills in the options of an app you have already added. The analyzer
answers the question that comes first: given a URL, what does this app need, and
is there anything the proxy cannot do for it?

Open the portal and follow **🔎 Analyze an app** at the top of the page. The link
only appears for administrators, and the analysis itself refuses anyone else,
because it makes the addon send a request to any address you name.

Paste the app's URL and you get three things: a verdict in one sentence, the
requests and responses that led to it, and a YAML entry to copy into the addon
configuration. Every line of that entry carries the reason it is there, so a
decision you disagree with can be spotted and removed rather than trusted blind.

The verdict comes down to how the app writes its links, which is what decides
whether proxying can work at all:

| The app publishes | What happens |
|-------------------|--------------|
| relative links | nothing to do, it works under any prefix |
| links starting with `/` | the common case, the proxy rewrites them |
| links carrying its own host | **no option fixes this** — the app has to be told its own public address, in its own configuration |

That last row is the one worth knowing about. Nothing in the option list expresses
it, and an app in that state renders a half-broken page that looks like a proxy
misconfiguration when it is not one. BookStack is the usual example: it needs
`APP_URL` set, and no combination of `rewrite`, `preserve_path` or
`native_base_path` will substitute for it.

The analyzer also reads the app's own scripts, up to three of them, because
`sub_filter` never sees a URL built in JavaScript. It reports what it finds there:
a service worker registration (which the proxy does **not** rewrite), a WebSocket
address hardcoded rather than derived from the page (which is what `ws_target` is
for), and asset bases baked in by a bundler (which the runtime patch corrects).
It never reports the absence of any of these: each script is read up to 256 KB, so
"not found" would mean "not found yet".

The portal, the analyzer and the generated YAML comments follow your browser's
language, in the same six languages the addon options are available in: English,
French, German, Spanish, Italian and Portuguese. The evidence is deliberately left
untranslated, since an HTTP header or a snippet of markup is protocol output
rather than prose.

`fast_upstream`, `ssl_verify` and `ws_target` stay yours to decide. The first is a
performance judgement rather than a property of the app, the second is a question
of trust, and the third needs a port number that no HTTP response reveals.

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
  category: Protocols
```

#### ESPSomfy-RTS (ESP32 Somfy blinds controller)

ESPSomfy-RTS serves its web UI over HTTP on port 80 and its real-time
WebSocket on a **separate port (8080)**. It also validates the `Host`/`Origin`/
`Referer` headers on every API call (403 otherwise) and sends a
`frame-ancestors 'none'` CSP that blocks the HA ingress iframe. The following
combination handles all of that:

```yaml
- name: ESPSomfy RTS
  url: http://192.168.1.223
  icon: 🪟
  description: "Contrôle des volets Somfy RTS via ESP32"
  category: Domotique
  ws_target: http://192.168.1.223:8080    # WebSocket tunnelled at /espsomfy-rts/ws
  fast_upstream: true                     # buffering on, for the ESP32's few sockets
```

`csrf_fix` and `hide_csp` are detected automatically: the firmware answers 403
once `Host`/`Origin`/`Referer` are foreign, and sends `frame-ancestors 'none'`.
`ws_target` has to be given — nothing in an HTTP response reveals that the
WebSocket lives on another port.

`fast_upstream` matters a lot here. Without it the proxy keeps response
buffering off and stamps `Cache-Control: no-store` on every response, which on
an ESP32 means: each of its handful of sockets stays busy for the whole client
transfer, and the browser plus the app's service worker refetch the entire UI
from the device on every load. The result is an app that feels fast on
`http://192.168.1.223/` and sluggish — or stuck in a reload loop — through the
proxy.

Requirements on the firmware side: the stock ESPSomfy-RTS web app builds its
API and WebSocket URLs without any base path, so it must include the
proxy-aware patch (base-path detection in `index.js`); see the
[ESPSomfy-RTS fork](https://github.com/Pulpyyyy/ESPSomfy-RTS). The browser
never talks to the ESP directly: HTTPS/WSS terminate at HA and nginx forwards
in clear HTTP/WS on the LAN — no mixed content.

#### BirdNET-Go (bird sound identification)

BirdNET-Go serves a Svelte SPA under `/ui/` and derives its own base path from
the URL segment that precedes `/ui/`. Behind the proxy at `/birdnet`, the
browser lands on `/birdnet/ui/dashboard` and the app resolves every API, SSE
and media URL under `/birdnet` on its own — no rewriting is needed beyond the
default `sub_filter`, which fixes the asset paths in the initial HTML.

```yaml
- name: BirdNET-Go
  url: http://192.168.1.119:8080
  icon: 🐦
  description: "Identification des oiseaux au son"
  category: Domotique
```

BirdNET-Go reads `X-Ingress-Path`, so `native_base_path` is detected and the
proxy simply tells it where it lives: the app then prefixes its own HTML,
redirects, API calls and lazily loaded components. Nothing is rewritten, which
also means its bundle keeps its compression — 291 KB instead of 975 KB.

`entry_path: /ui/dashboard` is detected too, from the redirect the app answers
its root with, and the portal links straight to it.

Its asset bundle needs no option either: static files always keep their
compression and cache headers (291 KB gzipped instead of 975 KB, cached rather
than refetched on every load). `hide_csp` is correctly *not* detected —
BirdNET-Go sends `frame-ancestors 'self'` and `X-Frame-Options: SAMEORIGIN`,
both satisfied inside the ingress iframe since the proxied document is served
from the Home Assistant origin.

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
