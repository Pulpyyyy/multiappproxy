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
