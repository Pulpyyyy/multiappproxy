## 1.3.4

### Fixed
- **The addon could not start with 1.3.3.** The injected runtime patch carried a `$` — the end anchor of its WebSocket regex — and nginx reads `$` inside a `sub_filter` argument as the start of a variable name, not as a literal. The whole configuration was rejected (`invalid variable name`) and the container stopped. The anchor is unnecessary to capture the path and is gone; a check now refuses any `$` in the injected script and any `sub_filter` argument carrying one

---

## 1.3.3

### Added
- **Runtime URL patch**, injected right after `<head>` so it is in place before any of the app's own scripts run. `sub_filter` only reaches markup: URLs an app builds in JavaScript are invisible to it, and compressed JS bundles cannot be filtered at all. The patch closes that gap where the URL is actually used, prefixing root-absolute ones on `fetch`, `XMLHttpRequest.open`, `EventSource` and `WebSocket`. It is idempotent — a URL already under the proxy path is returned untouched — so an app that resolves its own base path correctly is unaffected, which is why it needs no option
- **`history.pushState` / `replaceState` are patched too**, and that is the one that mattered: a router rewriting the address bar without the prefix makes every app that derives its base path from the URL compute an empty one, after which every call, asset and stream targets the domain root with no way back
- **Stylesheets are rewritten**: `url(...)` references are absolute in most bundlers' output and no amount of markup rewriting reaches them. `text/css` joins `sub_filter_types`, and CSS now goes through the main location rather than the compressed asset one — small next to a JS bundle, so serving it uncompressed costs little

---

## 1.3.2

### Fixed
- **The portal links straight to an app's entry point** instead of linking to `{path}/` and letting the app redirect there. A redirect is the one step not controlled end to end — HA ingress rewrites `Location` headers, browsers cache them — and for an app that derives its base path from the URL, being rendered at `{path}/` even once is enough to compute an empty prefix and never recover: its router normalises the URL to the default route at the domain root, and every API call, asset and SSE stream then goes to the wrong origin. `apps.json` now carries an `entry` field for this; the nginx redirects remain for anyone typing the URL directly
- Autodetection now runs before anything is generated, so `apps.json` and the nginx config see the same options (the entry point was detected after `apps.json` had already been written)

---

## 1.3.1

### Fixed
- **Redirects are scheme-absolute again.** HA ingress prefixes any `Location` that does not start with `http(s)://` with `http://$host:8099` — it treats a bare path and a protocol-relative `//host/path` alike, producing `http://host:8099//host/path`, which an HTTPS dashboard blocks as mixed content. Only a fully absolute URL is passed through untouched
- When `X-Forwarded-Proto` is absent, the scheme now falls back to `https` for requests carrying `X-Ingress-Path` (always set by HA ingress) instead of to `$scheme`, which is plain http on the addon's listener

---

## 1.3.0

Fewer options to find: an app usually needs nothing but a `name` and a `url`.

### Breaking
- **`path` is no longer configurable** — the proxy path is derived from the app name (`BirdNET-Go` → `/birdnet-go`), accents folded, collisions and portal routes (`/api`, `/static`) resolved with a numeric suffix. It is deterministic, so URLs stay stable across restarts, **but apps whose configured path did not match their name change URL**: existing bookmarks and dashboard links must be updated. A leftover `path` is still accepted by the schema so older configurations start, and is reported as ignored in the log

### Added
- **Autodetection** (on by default, `autodetect: false` to disable globally or per app): each upstream is probed at startup and the options that can be read off an HTTP response are inferred — `entry_path` (the app redirects its root elsewhere), `hide_csp` (`frame-ancestors 'none'` / `X-Frame-Options: DENY`), `csrf_fix` (a `403` appearing only once `Origin`/`Referer` are foreign, including a `401` baseline turning into `403`). Configured values always win, every decision is logged as `[AUTO] …`, and an unreachable upstream degrades to the configured options instead of blocking startup.
  `csrf_fix` detection is best-effort by construction: an app whose check is confined to the endpoints its UI calls cannot be seen from the pages we know about — ESPSomfy-RTS answers 200 on `/` whatever the Origin and only rejects on `/bootstrap` — and still needs the option set by hand
- **`entry_path`** (per-app, usually autodetected): internal path the browser is sent to when the app is opened. Apps that answer their root with a redirect never reach it through HA ingress — the ingress follows the redirect itself, leaving the browser on `{path}/`, where apps deriving their base path from the URL compute the wrong prefix and send every call to the domain root (BirdNET-Go)

### Changed
- Static assets are now always served from their dedicated location, with no option to enable: it only matches requests with a file extension, so it cannot affect HTML, API calls, SSE or WebSockets. `fast_upstream` is back to what genuinely needs a decision — response buffering and cache headers on the app's own responses

### Fixed
- **Redirects carry a host and are no longer permanent.** They were emitted as a bare path, which HA ingress turns into `http://$host:8099/...` — blocked as mixed content on an HTTPS dashboard — and as a `301`, which browsers cache indefinitely and replay without ever contacting the server again, so updating the addon could not reach a client that had already cached a wrong one. They are now `302` and protocol-relative (`//$host/...`), letting the browser reuse the scheme of the page it is on: https behind the ingress, http on direct access. A browser still holding a cached `301` from an earlier version must be cleared once (private window, or clear cached files)
- `sub_filter_types` no longer lists `text/html`, which nginx always filters — it warned `duplicate MIME type "text/html"` on every start

---

## 1.2.3

### Changed
- **`fast_upstream`** now also gives static assets (`js`, `css`, fonts, images, audio, source maps) their own nginx location. The main location has to blank `Accept-Encoding` so `sub_filter` can rewrite HTML, but `sub_filter_types` is `text/html` only — assets were being decompressed for nothing and stripped of their `Cache-Control`. Measured on a BirdNET-Go SPA: main bundle **975 KB instead of 291 KB**, refetched on every load because the upstream `max-age=31536000, immutable` was overwritten with `no-store`
- `fast_upstream` is no longer limited to embedded devices: it applies to any backend slower through the proxy than in direct access, including SPA backends serving a large asset bundle. Apps streaming responses (SSE) are safe as long as they send `X-Accel-Buffering: no`, which nginx honours even with buffering on

### Documentation
- BirdNET-Go section added: it detects its own base path from the segment before `/ui/`, so it needs no rewriting beyond the default `sub_filter`

---

## 1.2.2

### Added
- **`fast_upstream`** (per-app): tunes the proxy for lightweight/embedded upstreams (ESP32 firmwares, MCU web servers). Re-enables `proxy_buffering` so the device's very few sockets are released as soon as nginx has drained the response, and stops forcing `Cache-Control: no-store` so the app's own cache headers reach the browser and its service worker. Fixes apps that are fast in direct access but sluggish or stuck re-bootstrapping through the proxy (e.g. **ESPSomfy-RTS**). Not for apps that stream responses progressively (SSE, live logs)

---

## 1.2.1


### 🛠️ Fixes & Updates

- **hassio-addons/addon-base** → [21.0.1](https://github.com/hassio-addons/addon-base/releases/tag/v21.0.1)

 --- 

## 1.2.0

### Added
- **`ws_target`** (per-app): dedicated WebSocket upstream on a separate port. Generates a `location = {path}/ws` that tunnels the WebSocket through the proxy — required for firmwares like **ESPSomfy-RTS** that serve HTTP on `:80` but WebSocket on `:8080` (also avoids mixed-content blocking on HTTPS pages)
- **`hide_csp`** (per-app): strips upstream `Content-Security-Policy` / `X-Frame-Options` headers that would prevent the app from loading inside the HA ingress iframe (e.g. ESPSomfy-RTS sends `frame-ancestors 'none'`)
- Trailing-slash redirect `location = {path} → {path}/` generated for every app: apps using relative assets no longer break when the URL lacks the final slash
- `client_max_body_size 64m`: large uploads through the proxy (e.g. ESP firmware OTA) no longer fail with HTTP 413

### Changed
- `csrf_fix` now also rewrites the `Referer` header to the upstream origin: embedded firmwares (ESPSomfy-RTS) validate Referer against Host on every GET when Origin is absent
- `Connection` header is now conditional (`map $http_upgrade`): `upgrade` only for real WebSocket handshakes instead of being forced on every proxied request, which confused some embedded HTTP servers

---

## 1.1.2


### 🛠️ Fixes & Updates

- **hassio-addons/addon-base** → [21.0.0](https://github.com/hassio-addons/addon-base/releases/tag/v21.0.0)

 --- 

## 1.1.1


### 🛠️ Fixes & Updates

- **hassio-addons/addon-base** → [20.2.0](https://github.com/hassio-addons/addon-base/releases/tag/v20.2.0)

 --- 

## 1.1.0

### Security
- **Server-side access control**: admin-only and secret-protected apps are now enforced by nginx `auth_request` — a direct URL access by a non-authorized HA user is redirected to the portal instead of reaching the upstream
- **Session cookies**: successful secret verification now issues an `HttpOnly; SameSite=Strict` session cookie (8h TTL), eliminating the need to re-enter the password on each page reload; sessions survive addon restarts
- **`secrets.json` hardened**: file permissions set to `600` at generation time
- **Security headers added**: `X-Frame-Options: SAMEORIGIN`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin` on all portal responses
- **CORS removed**: `Access-Control-Allow-Origin: *` removed from `/api/user` and `/api/verify-secret` (unnecessary in ingress context)
- **POST body size capped**: `/api/verify-secret` now rejects payloads larger than 4 KB

### Added
- New `ssl_verify` parameter (per-app, default `false`): when `true`, enables upstream SSL certificate verification against system CA bundle — opt-in for apps with valid certificates
- Config validation at startup: clear error messages for invalid `url` (must be `http://` or `https://`) and `path` (must be a simple `/slug`) before any nginx config is generated

### Changed
- API server switched to `ThreadingHTTPServer` — concurrent requests (e.g. simultaneous bcrypt checks) no longer block each other
- Debug logs (`[API DEBUG]`, `[SECRET DEBUG]`) are now conditional on `debug: true` — nothing sensitive leaks to system logs in production
- `nginx -t` exit code check corrected: the pipe through `grep` was masking the real nginx exit code

### Fixed
- `replaceAll()` instead of `replace()` in the secret verification path computation (JS)

---

## 1.0.10


### 🛠️ Fixes & Updates

- **hassio-addons/addon-base** → [20.1.1](https://github.com/hassio-addons/addon-base/releases/tag/v20.1.1)

 --- 

## 1.0.9


### 🛠️ Fixes & Updates

- **hassio-addons/addon-base** → [20.1.0](https://github.com/hassio-addons/addon-base/releases/tag/v20.1.0)

 --- 

# Changelog

All notable changes to this project will be documented in this file.

## 1.0.8

### Security
- Password hashing upgraded from SHA256 to **bcrypt** (salted, resistant to rainbow tables)
- Rate limiting on `/api/verify-secret`: 5 req/min per IP at Nginx level (burst 3) + secondary in-process counter
- XSS fix in frontend: all user-supplied values now inserted via `textContent` / DOM API instead of `innerHTML`

### Fixed
- Ingress mode: `sub_filter` rewrites now use the full ingress prefix (`effective_path`) instead of bare `path`, fixing 404 on static assets at absolute paths (e.g. BirdPi `/By_Date/…`)
- Ingress mode: upstream `Location` headers are now rewritten to absolute HTTPS URLs, preventing HA ingress from converting them to `http://host:8099/…` which the service worker could not follow
- Fixed f-string `SyntaxError` in `generate_config.py` caused by unescaped `map` block braces

### Documentation
- `csrf_fix` and `ws_rewrite` parameters added to the parameter table
- Password flow description corrected (frontend sends plain password over HTTPS, backend does bcrypt comparison)
- Admin detection description corrected (reads `/config/.storage/auth`, requires `config:ro` mapping)

---

## 1.0.7

### Added
- New `preserve_path` parameter (forward requests without stripping the path prefix)
- New `hassio_ingress_slug` parameter (resolve another addon's ingress URL via Supervisor API)
- New `csrf_fix` parameter (override Origin/Host headers for Django CSRF compatibility)
- New `ws_rewrite` parameter (inject JavaScript WebSocket URL patch at runtime)

### Changed
- Admin detection reworked: now uses HA WebSocket API (`config/auth/list`) instead of reading `/config/.storage/auth`
- Config storage mapped via `addon_config:rw` (replaces `config:rw`)

### Fixed
- Various path and proxy fixes

---

## 1.0.6

### Updates
- **hassio-addons/addon-base** → [20.0.4](https://github.com/hassio-addons/addon-base/releases/tag/v20.0.4)

---

## 1.0.5

### Updates
- **hassio-addons/addon-base** → [20.0.3](https://github.com/hassio-addons/addon-base/releases/tag/v20.0.3)

---

## 1.0.4

### Added
- YAML order preserved
- Debug mode with real-time UI logs
- Custom logo support (emoji or image URL)
- Material Design panel icon
- Complete documentation

### Updates
- **hassio-addons/addon-base** → [20.0.2](https://github.com/hassio-addons/addon-base/releases/tag/v20.0.2)

---

## 1.0.3

### Fixed
- Trailing slash fix
- Token URL-encoding (special characters)
- Collapsible categories

---

## 1.0.2

### Added
- Native Home Assistant Ingress support
- Self-signed SSL support
- Full WebSocket support (Z-Wave JS UI, Zigbee2MQTT, Matter Bridge)

---

## 1.0.1

### Added
- Password-protected apps (`secret` field, server-side verification)
- Admin-only apps (`admin` field)

### Fixed
- Navigation after password validation now goes to the app

### Updates
- **home-assistant/docker-base** → [2026.02.0](https://github.com/home-assistant/docker-base/releases/tag/2026.02.0)

---

## 1.0.0 - 2026-02-08

### Added
- Initial release
- Multi-application reverse proxy
- Home Assistant Ingress support
- Token authentication
- SSL/TLS support with self-signed certificates
- WebSocket support
- Category-based organization with automatic icons
- Custom logos and icons
- Debug mode with real-time logs
- YAML order preservation
