## 1.4.4


### 🛠️ Fixes & Updates

- **hassio-addons/addon-base** → [21.0.2](https://github.com/hassio-addons/addon-base/releases/tag/v21.0.2)

 --- 

## 1.4.3

### Fixed
- **1.4.2 could not start.** The buffered access log was written as `access_log <path> buffer=32k flush=5s`, and nginx reads the token after the path as the name of a log format, so it refused the configuration with `unknown log format "buffer=32k"` and the addon stopped at boot. The format has to be named: `access_log <path> combined buffer=32k flush=5s`. The local harness that was supposed to catch this rewrote the whole `access_log` directive while adapting paths, so it validated a line that was never shipped; it now swaps the path only, and the buffered directive is verified as generated

---

## 1.4.2

### Changed
- **`debug: true` no longer puts nginx in `debug` log level**, which writes kilobytes per request onto the SD card most Home Assistant boxes run from. It logs at `info` now; the `[DEBUG]` and `[AUTO]` lines the option exists for come from the addon's own Python, not from nginx
- The access log is buffered (`buffer=32k flush=5s`) rather than written once per request

### Added
- **The analyzer reports a WebSocket an app builds at runtime**, not only one written as a literal. An app that assembles its address from `location.host` and a port leaves nothing to search for, which is exactly how ESPSomfy-RTS does it, and a socket that never connects through the proxy is one of the better disguises for slowness. The surrounding code is shown as the evidence, so the port it reaches for is visible and `ws_target` can be pointed at it

### Fixed
- **Probes could not read a compressed response.** An embedded firmware often serves one pre-compressed file and answers `gzip` whatever was asked, so the probe was reading compressed bytes as text. Everything downstream then looked at noise: autodetection found no sentinel, and the analyzer found no link at all in a page that has thirty-nine, concluding out loud that the app was "already portable". Probes now ask for `identity` and decompress anyway when the upstream ignores it. Measured on an ESPSomfy-RTS: 21 112 characters of noise before, 114 462 characters of markup after
- **The analyzer no longer draws a verdict from an empty page.** Finding no reference is not evidence of portability: it also happens when the body cannot be decoded, or when the interface is built entirely in JavaScript. That case now has its own verdict which says so, rather than borrowing the reassuring one
- **`csrf_fix` now covers the WebSocket too.** It rewrote `Origin` and `Referer` on every HTTP location and left the socket alone, so an app that checks the request origin — the only reason to turn the option on — was shown two different origins for one session. This one ships to be judged in place: the only client able to get a `join` frame accepted by ESPSomfy-RTS is a real browser session, so a test harness could not settle it

---

## 1.4.1

### Added
- **The portal speaks the same six languages as the options** (English, French, German, Spanish, Italian, Portuguese), picked from the browser. Both the analyzer and the app list were English-only, and `index.html` even declared `lang="fr"` over English text
- The analyzer sends message identifiers rather than sentences, so one analysis reads in the language of whoever asked for it. The YAML comments are translated too, since the person reading them is the user. Evidence is deliberately left alone: an HTTP header or a snippet of markup is protocol output, and translating it would turn a fact into a paraphrase

### Fixed
- **The analyzer read the Content-Security-Policy from the wrong response.** It looked at the root, which for many apps is a bare redirect carrying no policy at all, so a strict CSP on the login page went unreported. It now reads the page actually served

---

## 1.4.0

Configuring an app stops being a guess.

### Added
- **App analyzer** (`🔎 Analyze an app` in the portal, administrators only). Paste a URL and the addon probes it, then answers with a verdict in one sentence, the requests and responses behind that verdict, and a YAML entry to copy. Every generated line carries the reason it is there, so a decision can be argued with rather than trusted. The decisive output is the shape of the links the app publishes: relative (nothing to do), root-absolute (the proxy rewrites them), or carrying the app's own host — the last one **cannot be fixed by any option**, and until now nothing said so. BookStack is that case
- The analyzer also reads up to three of the app's own scripts, since `sub_filter` never sees a URL built in JavaScript. It reports a service worker registration (which the proxy does not rewrite), a hardcoded WebSocket address, and bundler-baked asset bases. It never reports their absence: each script is read up to 256 KB, so "not found" would only mean "not found yet"
- `POST /api/analyze`, gated on administrator status, rate limited to 10 per minute per client, and serialised to one probe run at a time

### Fixed
- **`X-Forwarded-Proto` no longer forwards the ingress hop's scheme.** It was sent as `$scheme`, which is plain `http` on the listener HA ingress talks to, so an app deriving its own absolute URLs from it — as any Laravel app does — built them on `http` and an HTTPS dashboard blocked every one as mixed content. The real browser scheme was already resolved for redirects; it is now used for both, under the clearer name `$public_proto`. A proxy chain that turns the header into `https, http` keeps only its first hop
- **The runtime URL patch is no longer blocked by a strict CSP.** An app sending `script-src 'nonce-…' 'strict-dynamic'` refused the injected script and said so only in the browser console, leaving the URLs built in JavaScript wrong while the page looked fine. The nonce is now read off the upstream response and carried onto the injected tag, so the app's own policy accepts it and nothing has to be disabled. `hide_csp` stays for policies that break the ingress iframe, which is a different problem. An app that delivers its policy in a `<meta>` tag rather than a header is still out of reach

---

## 1.3.1

### Fixed
- **Apps that build their own absolute URLs are now told the host the browser actually typed.** Behind HA ingress, `$host` is whatever the addon's listener was reached as, which can be an internal name: an app deriving its URLs from `Host`, as any Laravel app does, then redirects the browser to a name it cannot resolve (`homeassistant's server IP address could not be found`). `X-Forwarded-Host` carries the real one, and is used when present. On direct access nothing changes, since `$host` already is the real one. A multi-valued header keeps only its first hop, so a chain of proxies cannot produce a malformed `Host`
- **Absolute `Location` headers pointing at our own host are prefixed too.** Only path-only redirects were being rewritten; an app that names the host but knows nothing of the proxy prefix was passed through untouched. Redirects to a third party, an OAuth provider for instance, are strictly unaffected since the match is on our own host. Locations that already carry the prefix are matched first and left alone, so an app configured by hand with the full public URL does not get it added twice
- `csrf_fix` still overrides the `Host` header, and apps in `native_base_path` mode still get no prefixing at all: both were verified on the generated configuration

---

## 1.3.0

Fewer options to find, and apps that work behind the proxy without being told how.

### Breaking
- **`path` is no longer configurable** — the proxy path is derived from the app name (`BirdNET-Go` → `/birdnet-go`), accents folded, collisions and portal routes (`/api`, `/static`) resolved with a numeric suffix. It is deterministic, so URLs stay stable across restarts, **but apps whose configured path did not match their name change URL**: existing bookmarks and dashboard links must be updated. A leftover `path` is still accepted by the schema so older configurations start, and is reported as ignored in the log

### Added
- **Autodetection** (on by default, `autodetect: false` to disable globally or per app). Each upstream is probed at startup and the options that can be read off an HTTP response are inferred:

  | Inferred | Signal |
  |---|---|
  | `entry_path` | the app answers its root with a redirect elsewhere |
  | `hide_csp` | `frame-ancestors 'none'` or `X-Frame-Options: DENY` |
  | `csrf_fix` | a `403` appearing only once `Origin`/`Referer` are foreign |
  | `native_base_path` | a sentinel sent as `X-Ingress-Path` comes back in the response |

  Configured values always win, every decision is logged as `[AUTO] …`, and an unreachable upstream degrades to the configured options instead of blocking startup. `csrf_fix` stays best-effort: an app whose check is confined to the endpoints its UI calls cannot be seen from the pages we know about — ESPSomfy-RTS answers 200 on `/` whatever the Origin and only rejects on `/bootstrap` — and still needs the option set by hand
- **`native_base_path`**: when an app can build its own URLs from a prefix header, the proxy tells it where it lives (`X-Ingress-Path` and `X-Forwarded-Prefix`, set to `$http_x_ingress_path{path}` so the value follows the live request rather than an ingress token frozen at generation time) and stops rewriting its markup. The addon used to blank that header unconditionally — a rule that made sense only while rewriting, and that removed the very information such an app needed
- **`entry_path`**: internal path the browser is sent to when the app is opened. The portal links straight to it rather than letting the app redirect: HA ingress follows redirects itself, and an app that derives its base path from the URL only has to be rendered at `{path}/` once to compute an empty prefix and never recover
- **Runtime URL patch**, injected before the app's own scripts. `sub_filter` only reaches markup; URLs built in JavaScript are invisible to it and compressed bundles cannot be filtered at all. The patch prefixes root-relative *and* same-origin absolute URLs on `fetch`, `XMLHttpRequest`, `EventSource`, `WebSocket`, the `src`/`href` setters of image, media, source, script and link elements, `setAttribute`, and `history.pushState`/`replaceState`. It is idempotent, so an app that resolves its own base path correctly is unaffected — which is what lets it apply everywhere without an option. Third-party origins are left strictly alone

### Changed
- Static assets are always served from a dedicated location that keeps upstream compression and cache headers. It only matches requests with a file extension, so it cannot affect HTML, API calls, SSE or WebSockets. Measured on a SPA bundle: **291 KB instead of 975 KB**, cached instead of refetched on every load
- Stylesheets are rewritten (`url(...)` references are absolute in most bundler output and markup rewriting never reaches them)
- `fast_upstream` is back to what genuinely needs a decision: response buffering and cache headers on the app's own responses
- Redirects are `302` and scheme-absolute. HA ingress prefixes any `Location` that does not start with `http(s)://` with `http://$host:8099`, which an HTTPS dashboard blocks as mixed content; and a `301` is cached by browsers indefinitely, so a fixed configuration never reaches a client that already holds a wrong one. When `X-Forwarded-Proto` is absent the scheme falls back to `https` for requests carrying `X-Ingress-Path`
- `sub_filter_types` no longer lists `text/html`, which nginx always filters — it warned `duplicate MIME type` on every start

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
