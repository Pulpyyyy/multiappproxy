#!/usr/bin/env python3
"""Work out how an app has to be proxied, from nothing but its URL.

Startup autodetection answers a narrow question: given an app the user has
already configured, which options can be filled in for them. This module answers
the question that comes before it, and that the option list cannot answer at all
— what does this app need, and is there anything the proxy simply cannot do for
it.

The decisive output is not the list of options. It is the shape of the URLs the
app publishes, because that is what decides whether proxying can work:

  relative        the app is portable, nothing to do
  root-absolute   what sub_filter rewrites, the common case
  fully absolute  the app writes its own host into every link — no option fixes
                  this, the app itself has to be told its public address

That last case is invisible from the option list, and is what leaves users
staring at a half-rendered login page wondering which boolean they got wrong.
"""

import re
import unicodedata
from urllib.parse import urljoin, urlparse

from generate_config import _PROBE_HOST, _probe_get, detect_app_options

# Attributes whose value is fetched by the browser as part of rendering the page.
# href is deliberately absent: a canonical link or an outbound <a> is absolute on
# purpose, and counting those would report every site on the internet as broken.
_SRC_RE = re.compile(r'\b(?:src|action)\s*=\s*["\']([^"\']+)["\']', re.I)
# Stylesheets are the exception worth reading href for — they are assets, and they
# are what breaks first and most visibly when the prefix is missing.
_LINK_RE = re.compile(r'<link\b([^>]*)>', re.I)
_HREF_RE = re.compile(r'\bhref\s*=\s*["\']([^"\']+)["\']', re.I)
_BASE_RE = re.compile(r'<base\b[^>]*\bhref\s*=\s*["\']([^"\']+)["\']', re.I)
_TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.I | re.S)
_WS_RE = re.compile(r'\bwss?://[^\s"\'<>]+', re.I)
_NONCE_RE = re.compile(r"'nonce-([^']+)'", re.I)

_SENTINEL = '/__multiappproxy_probe__'
# Enough to judge the shape of a page without reporting a lone stray link.
_ABSOLUTE_THRESHOLD = 1


def _collect_refs(html: str) -> list:
    """Every asset reference in the markup, as written by the app."""
    refs = list(_SRC_RE.findall(html))
    for attrs in _LINK_RE.findall(html):
        href = _HREF_RE.search(attrs)
        if not href:
            continue
        value = href.group(1)
        if 'stylesheet' in attrs.lower() or '.css' in value.lower():
            refs.append(value)
    return refs


def _classify_refs(refs: list, upstream_netloc: str) -> dict:
    """Sort references into the three shapes that decide whether proxying works."""
    out = {'absolute_own': [], 'absolute_third_party': [], 'root': [], 'relative': []}
    for ref in refs:
        low = ref.strip()
        if not low or low.startswith(('data:', 'javascript:', '#', 'mailto:')):
            continue
        if low.startswith('//'):
            netloc = low[2:].split('/', 1)[0]
            key = 'absolute_own' if netloc == upstream_netloc else 'absolute_third_party'
            out[key].append(low)
        elif low.startswith(('http://', 'https://')):
            netloc = urlparse(low).netloc
            key = 'absolute_own' if netloc == upstream_netloc else 'absolute_third_party'
            out[key].append(low)
        elif low.startswith('/'):
            out['root'].append(low)
        else:
            out['relative'].append(low)
    return out


# ── Reading the scripts ───────────────────────────────────────────────────────
# Markup is only half the story. sub_filter cannot reach a URL that the app builds
# in JavaScript, which is the whole reason the runtime patch exists — so what the
# bundles contain decides whether that patch is enough, or whether something falls
# outside what it covers.
_SW_RE = re.compile(r'serviceWorker\s*\.\s*register\s*\(\s*["\']([^"\']+)["\']', re.I)
_WS_LITERAL_RE = re.compile(r'["\'](wss?://[^"\'\s]+)["\']', re.I)
_PUBLIC_PATH_RE = re.compile(r'__webpack_public_path__\s*=\s*["\']([^"\']*)["\']')
# Scripts are capped hard: this is a diagnostic, not a crawler.
_MAX_SCRIPTS = 3


def _script_urls(refs: list, base: str, netloc: str) -> list:
    """Same-origin script URLs from the markup, absolute and de-duplicated."""
    out = []
    for ref in refs:
        low = ref.strip()
        if '.js' not in low.lower():
            continue
        if low.startswith(('http://', 'https://')) and urlparse(low).netloc != netloc:
            continue
        if low.startswith('//'):
            continue
        absolute = urljoin(base, low)
        if absolute not in out:
            out.append(absolute)
    return out[:_MAX_SCRIPTS]


def _scan_scripts(urls: list, netloc: str) -> tuple:
    """Read the app's own bundles and report only what is actually found there.

    Absence is never claimed: _probe_get stops at 256 KB, so a pattern that is not
    seen may simply be further down a bundle. Saying "no service worker" from a
    truncated read would be a guess dressed as a fact.
    """
    findings, read = [], 0
    baked, sw, ws_literals, public_path = [], None, [], None

    for url in urls:
        got = _probe_get(url)
        if not got or got[0] >= 400:
            continue
        js = got[2]
        read += 1
        if not sw:
            match = _SW_RE.search(js)
            if match:
                sw = (match.group(1), url)
        for literal in _WS_LITERAL_RE.findall(js):
            host = urlparse(literal).netloc
            # A URL built from location.host comes out as a fragment, not a literal;
            # what lands here is hardcoded, which is the case worth reporting.
            if host and host not in ws_literals:
                ws_literals.append(literal)
        if not public_path:
            match = _PUBLIC_PATH_RE.search(js)
            if match:
                public_path = (match.group(1), url)
        for hit in re.findall(r'["\'](https?://' + re.escape(netloc) + r'[^"\'\s]*)["\']', js):
            if hit not in baked:
                baked.append(hit)

    if sw:
        findings.append({
            'tag': 'service worker', 'value': None,
            'claim': 'It registers a service worker, and the proxy does not rewrite that '
                     'registration — the worker may end up outside the app\'s prefix.',
            'evidence': f'{sw[1]}\nserviceWorker.register("{sw[0]}")',
        })
    if baked:
        findings.append({
            'tag': 'urls in script', 'value': None,
            'claim': 'A bundle carries its own address in full. The runtime patch rewrites '
                     'those as they are used, so this is covered.',
            'evidence': "\n".join(baked[:3]),
        })
    if public_path:
        findings.append({
            'tag': 'asset base', 'value': None,
            'claim': 'The bundler baked an asset base into the chunk loader, which the '
                     'runtime patch corrects when a chunk is requested.',
            'evidence': f'{public_path[1]}\n__webpack_public_path__ = "{public_path[0]}"',
        })
    if ws_literals:
        findings.append({
            'tag': 'ws_target', 'value': None,
            'claim': 'A WebSocket address is hardcoded rather than built from the page, so '
                     'it will not follow the proxy.',
            'evidence': "\n".join(ws_literals[:3]),
        })
    return findings, read, ws_literals


_NAME_SAFE_RE = re.compile(r'[^A-Za-z0-9]+')


def _name_from_host(hostname: str) -> str:
    """Fallback name: the host with no scheme and no port, dots turned into
    underscores. Always available and obviously a placeholder, which is the point
    — for an IP it reads as 192_168_1_50, which nobody will mistake for a name
    they chose.
    """
    return _NAME_SAFE_RE.sub('_', hostname or '').strip('_') or 'app'


def _title(html: str, fallback: str) -> str:
    """The app's own name when its page states one, the host otherwise."""
    match = _TITLE_RE.search(html)
    if not match:
        return fallback
    # Titles are usually "Login | BookStack" — the app name is the distinctive half.
    parts = [p.strip() for p in re.split(r'[|·–—]', match.group(1)) if p.strip()]
    if not parts:
        return fallback
    name = max(parts, key=len) if len(parts) > 1 else parts[0]
    name = re.sub(r'\s+', ' ', name)[:40].strip()
    return name or fallback


def _display_width(text: str) -> int:
    """Column width of text, counting wide glyphs (emoji) as the two they occupy."""
    return sum(2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1 for ch in text)


def _yaml(header: list, entries: list) -> str:
    """Render the snippet with every comment aligned in one column.

    entries are (key, value, comment). Placeholder lines say so in their comment,
    so a line the user is expected to change never looks like a line that was
    worked out from the app.
    """
    body = [(f"- {key}: {value}" if i == 0 else f"  {key}: {value}", comment)
            for i, (key, value, comment) in enumerate(entries)]
    width = max(_display_width(code) for code, _ in body)
    lines = list(header)
    for code, comment in body:
        pad = ' ' * (width - _display_width(code) + 2)
        lines.append(f"{code}{pad}# {comment}" if comment else code)
    return "\n".join(lines)


def analyze(url: str) -> dict:
    """Probe url and return a verdict, the evidence behind it, and a YAML snippet.

    Never raises on a network problem: an unreachable upstream is a result, not an
    error, and the caller shows it as such.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return {'ok': False, 'error': 'The URL must start with http:// or https:// and name a host.'}

    base = url.rstrip('/') + '/'
    netloc = parsed.netloc
    probe = []
    findings = []

    first = _probe_get(base)
    if first is None:
        probe.append({'step': f'GET {base}', 'detail': 'no answer', 'ok': False})
        return {
            'ok': False,
            'error': 'No answer from that address. Check the app is running and reachable '
                     'from Home Assistant, then try again.',
            'probe': probe,
        }
    status, headers, body = first
    probe.append({'step': f'GET {base}', 'detail': f'{status}', 'ok': True})

    # The options that can be read off the wire are already known how to detect —
    # reuse that logic rather than growing a second, divergent copy of it.
    detected = detect_app_options('analyzer', url)
    probe.append({'step': 'GET / with a sentinel prefix header', 'detail':
                  'prefix echoed back' if detected.get('native_base_path') else 'prefix ignored',
                  'ok': True})
    probe.append({'step': 'GET with a foreign Origin', 'detail':
                  '403 — origin is checked' if detected.get('csrf_fix') else 'unchanged',
                  'ok': True})

    # The markup that matters is the first real page, which for many apps is not
    # the root but wherever the root redirects to.
    page_url, page_body = base, body
    entry = detected.get('entry_path')
    if entry:
        page_url = base.rstrip('/') + entry
        landed = _probe_get(page_url)
        if landed:
            page_body = landed[2]
    probe.append({'step': f'GET {page_url}', 'detail': f'{len(page_body)} bytes of markup', 'ok': True})

    refs = _collect_refs(page_body)
    shapes = _classify_refs(refs, netloc)
    probe.append({'step': 'scanning the markup for link shapes', 'detail':
                  f"{len(shapes['absolute_own'])} absolute, {len(shapes['root'])} root-relative, "
                  f"{len(shapes['relative'])} relative", 'ok': True})

    script_findings, scripts_read, ws_in_script = _scan_scripts(
        _script_urls(refs, page_url, netloc), netloc)
    if scripts_read:
        probe.append({'step': f'reading {scripts_read} script bundle(s)', 'detail':
                      f'{len(script_findings)} thing(s) worth reporting', 'ok': True})

    csp = headers.get('Content-Security-Policy', '') or ''
    nonce = _NONCE_RE.search(csp)
    base_tag = _BASE_RE.search(page_body)
    ws_urls = _WS_RE.findall(page_body)

    options = []
    header_lines = []
    # The host always yields a name; the page title yields a better one when it has
    # one, and costs nothing since the markup is already in hand.
    host_name = _name_from_host(parsed.hostname)
    name = _title(page_body, host_name)
    name_why = ('derived from the address, rename it' if name == host_name
                else 'read from the page title, rename it if you like')

    # ── The decisive call: how does this app publish its links ────────────────
    if detected.get('native_base_path'):
        tone, pill = 'ok', 'Ready to use'
        title = 'The app prefixes its own links'
        text = ('It picked up the prefix we sent and used it. That is the most reliable '
                'arrangement: the proxy stops rewriting entirely, and the app keeps its '
                'compression.')
        options.append(('native_base_path', 'true', 'sentinel prefix came back in the response'))
        header_lines = ['# Reads X-Ingress-Path and prefixes its own markup and redirects.',
                        '# Nothing is rewritten, compression is preserved.']
        findings.append({
            'tag': 'native_base_path', 'value': True,
            'claim': 'Echoed our sentinel prefix back in its own markup.',
            'evidence': f'GET {base} — X-Ingress-Path: {_SENTINEL}\n'
                        f'-> the sentinel came back in the response',
        })
    elif len(shapes['absolute_own']) >= _ABSOLUTE_THRESHOLD:
        tone, pill = 'stop', 'Needs a setting in the app'
        title = 'No proxy option can fix this one alone'
        text = (f'{name} writes its own hostname into its links. There is nothing left for '
                'the proxy to rewrite, and no way to tell those apart from links that point '
                'elsewhere on purpose. The app has to be told its public address once.')
        header_lines = [
            '# This app builds absolute URLs from its own configured base.',
            '# Set that base (APP_URL, BASE_URL, "external address"... the name',
            '# varies) to the address the portal shows for this app, then this',
            '# entry is all the proxy needs.',
        ]
        findings.append({
            'tag': 'url shape', 'value': None,
            'claim': 'Links carry a full scheme and host, not a path.',
            'evidence': "\n".join(shapes['absolute_own'][:3]),
        })
    elif shapes['root']:
        tone, pill = 'ok', 'Ready to use'
        title = 'Standard rewriting fits this app'
        text = ('It publishes its links as paths from the site root, which is exactly what '
                'the proxy rewrites. Anything else worth setting is already in the snippet.')
        header_lines = ['# Publishes root-absolute links and ignores prefix headers.',
                        '# Default rewriting applies, so nothing has to be chosen.']
        findings.append({
            'tag': 'url shape', 'value': None,
            'claim': 'Links are paths from the site root, which the proxy rewrites.',
            'evidence': "\n".join(shapes['root'][:3]),
        })
    else:
        tone, pill = 'ok', 'Ready to use'
        title = 'This app is already portable'
        text = ('Every link it publishes is relative, so it works under any prefix without '
                'the proxy touching a thing.')
        header_lines = ['# All links are relative — nothing needs rewriting.']
        findings.append({
            'tag': 'url shape', 'value': None,
            'claim': 'Every reference is relative, so the prefix takes care of itself.',
            'evidence': "\n".join(shapes['relative'][:3]) or 'no asset references found',
        })

    # ── Independent options ───────────────────────────────────────────────────
    if entry:
        options.append(('entry_path', entry, f'root answers {status} -> {entry}'))
        findings.append({
            'tag': 'entry_path', 'value': True,
            'claim': 'The root sends the browser elsewhere, so the portal links straight there.',
            'evidence': f'GET {base}\n<- {status} Location: {entry}',
        })
    if detected.get('csrf_fix'):
        options.append(('csrf_fix', 'true', '403 appears only with a foreign Origin'))
        findings.append({
            'tag': 'csrf_fix', 'value': True,
            'claim': 'Rejects requests whose Origin is foreign, which is what a browser '
                     'sends through the ingress.',
            'evidence': f'GET {page_url}  Origin: https://{_PROBE_HOST}\n<- 403',
        })
    if detected.get('hide_csp'):
        options.append(('hide_csp', 'true', 'policy forbids being embedded in a frame'))
        findings.append({
            'tag': 'hide_csp', 'value': True,
            'claim': 'Its policy forbids embedding, which the HA ingress frame needs lifted.',
            'evidence': (csp or headers.get('X-Frame-Options', ''))[:200],
        })
    elif csp:
        findings.append({
            'tag': 'CSP', 'value': None,
            'claim': ('Its policy accepts a nonced script, so the runtime URL patch will run.'
                      if nonce else
                      'Its policy allows embedding, so nothing is stripped.'),
            'evidence': f'Content-Security-Policy: {csp[:180]}',
        })
    if base_tag:
        findings.append({
            'tag': 'base href', 'value': None,
            'claim': 'The page declares its own base, which overrides how relative links resolve.',
            'evidence': f'<base href="{base_tag.group(1)}">',
        })

    findings.extend(script_findings)

    manual = ('<strong>Left for you:</strong> <code>fast_upstream</code> is a performance call '
              'rather than a property of the app, and <code>ws_target</code> only matters if the '
              'app serves WebSockets on a different port. Neither can be read off an HTTP response.')
    ws_seen = ws_urls + ws_in_script
    if ws_seen:
        manual = ('<strong>Worth a look:</strong> the page builds WebSocket URLs '
                  f'(<code>{ws_seen[0][:60]}</code>). If live updates stay silent through the '
                  'proxy, that is where to look, and <code>ws_target</code> is the option. '
                  ) + manual
    if parsed.scheme == 'https':
        manual += (' This upstream is https, so <code>ssl_verify</code> is yours to decide: it '
                   'defaults to off, which is what a self-signed LAN certificate needs.')

    return {
        'ok': True,
        'url': url,
        'verdict': {'tone': tone, 'pill': pill, 'title': title, 'text': text},
        'findings': findings,
        'yaml': _yaml(header_lines, [
            ('name', name, name_why),
            ('url', url, 'the address the proxy connects to'),
            ('description', '""', 'shown under the name on the card'),
            ('icon', '📱', 'any emoji, or use "logo:" with an image URL instead'),
            ('category', 'Others', 'cards are grouped by category'),
        ] + options),
        'manual': manual,
        'probe': probe,
    }
