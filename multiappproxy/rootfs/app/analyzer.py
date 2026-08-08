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

# Every piece of prose leaves this module as an identifier plus its parameters:
# the portal holds the catalogue, so one analysis reads in the language of
# whoever asked for it. Evidence is deliberately left alone — it is protocol
# output, and a translated HTTP header would be a lie.
def _m(key, **params):
    """A message the caller will render, never a finished sentence."""
    return {'id': key, 'params': params} if params else {'id': key}


# Stands in for evidence when a page carries no asset reference at all.
_NO_REFS = '(no asset references in the markup)'

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
            'tag': _m('tag.sw'), 'value': None, 'claim': _m('finding.sw'),
            'evidence': f'{sw[1]}\nserviceWorker.register("{sw[0]}")',
        })
    if baked:
        findings.append({
            'tag': _m('tag.baked'), 'value': None, 'claim': _m('finding.baked'),
            'evidence': "\n".join(baked[:3]),
        })
    if public_path:
        findings.append({
            'tag': _m('tag.assetbase'), 'value': None, 'claim': _m('finding.publicpath'),
            'evidence': f'{public_path[1]}\n__webpack_public_path__ = "{public_path[0]}"',
        })
    if ws_literals:
        findings.append({
            'tag': 'ws_target', 'value': None, 'claim': _m('finding.ws'),
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


def analyze(url: str) -> dict:
    """Probe url and return a verdict, the evidence behind it, and a YAML snippet.

    Never raises on a network problem: an unreachable upstream is a result, not an
    error, and the caller shows it as such.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return {'ok': False, 'error': _m('error.badurl')}

    base = url.rstrip('/') + '/'
    netloc = parsed.netloc
    probe = []
    findings = []

    first = _probe_get(base)
    if first is None:
        probe.append({'step': _m('probe.get', url=base), 'detail': _m('probe.noanswer'), 'ok': False})
        return {'ok': False, 'error': _m('error.noanswer'), 'probe': probe}
    status, headers, body = first
    probe.append({'step': _m('probe.get', url=base), 'detail': str(status), 'ok': True})

    # The options that can be read off the wire are already known how to detect —
    # reuse that logic rather than growing a second, divergent copy of it.
    detected = detect_app_options('analyzer', url)
    probe.append({'step': _m('probe.sentinel'), 'ok': True, 'detail': _m(
        'probe.sentinel.yes' if detected.get('native_base_path') else 'probe.sentinel.no')})
    probe.append({'step': _m('probe.origin'), 'ok': True, 'detail': _m(
        'probe.origin.yes' if detected.get('csrf_fix') else 'probe.origin.no')})

    # The markup that matters is the first real page, which for many apps is not
    # the root but wherever the root redirects to.
    page_url, page_body, page_headers = base, body, headers
    entry = detected.get('entry_path')
    if entry:
        page_url = base.rstrip('/') + entry
        landed = _probe_get(page_url)
        if landed:
            page_headers, page_body = landed[1], landed[2]
    probe.append({'step': _m('probe.page', url=page_url), 'ok': True,
                  'detail': _m('probe.page.detail', bytes=len(page_body))})

    refs = _collect_refs(page_body)
    shapes = _classify_refs(refs, netloc)
    probe.append({'step': _m('probe.shapes'), 'ok': True,
                  'detail': _m('probe.shapes.detail', absolute=len(shapes['absolute_own']),
                               root=len(shapes['root']), relative=len(shapes['relative']))})

    script_findings, scripts_read, ws_in_script = _scan_scripts(
        _script_urls(refs, page_url, netloc), netloc)
    if scripts_read:
        probe.append({'step': _m('probe.scripts', count=scripts_read), 'ok': True,
                      'detail': _m('probe.scripts.detail', count=len(script_findings))})

    # Read from the page actually served, not the root: an app whose root is a bare
    # redirect carries no policy there, and the login page is exactly where a strict
    # one shows up.
    csp = (page_headers.get('Content-Security-Policy', '')
           or headers.get('Content-Security-Policy', '') or '')
    nonce = _NONCE_RE.search(csp)
    base_tag = _BASE_RE.search(page_body)
    ws_urls = _WS_RE.findall(page_body)

    options = []
    # The host always yields a name; the page title yields a better one when it has
    # one, and costs nothing since the markup is already in hand.
    host_name = _name_from_host(parsed.hostname)
    name = _title(page_body, host_name)
    name_why = _m('yaml.name.host') if name == host_name else _m('yaml.name.title')

    # ── The decisive call: how does this app publish its links ────────────────
    if detected.get('native_base_path'):
        tone, kind = 'ok', 'native'
        options.append(('native_base_path', 'true', _m('yaml.native')))
        findings.append({
            'tag': 'native_base_path', 'value': True, 'claim': _m('finding.native'),
            'evidence': 'GET {0} — X-Ingress-Path: {1}'.format(base, _SENTINEL),
        })
    elif len(shapes['absolute_own']) >= _ABSOLUTE_THRESHOLD:
        tone, kind = 'stop', 'appside'
        findings.append({
            'tag': _m('tag.urlshape'), 'value': None, 'claim': _m('finding.absolute'),
            'evidence': "\n".join(shapes['absolute_own'][:3]),
        })
    elif shapes['root']:
        tone, kind = 'ok', 'root'
        findings.append({
            'tag': _m('tag.urlshape'), 'value': None, 'claim': _m('finding.root'),
            'evidence': "\n".join(shapes['root'][:3]),
        })
    else:
        tone, kind = 'ok', 'relative'
        findings.append({
            'tag': _m('tag.urlshape'), 'value': None, 'claim': _m('finding.relative'),
            'evidence': "\n".join(shapes['relative'][:3]) or _NO_REFS,
        })

    # ── Independent options ───────────────────────────────────────────────────
    if entry:
        options.append(('entry_path', entry, _m('yaml.entry', status=status, entry=entry)))
        findings.append({
            'tag': 'entry_path', 'value': True, 'claim': _m('finding.entry'),
            'evidence': 'GET {0}\n<- {1} Location: {2}'.format(base, status, entry),
        })
    if detected.get('csrf_fix'):
        options.append(('csrf_fix', 'true', _m('yaml.csrf')))
        findings.append({
            'tag': 'csrf_fix', 'value': True, 'claim': _m('finding.csrf'),
            'evidence': 'GET {0}  Origin: https://{1}\n<- 403'.format(page_url, _PROBE_HOST),
        })
    if detected.get('hide_csp'):
        options.append(('hide_csp', 'true', _m('yaml.hidecsp')))
        findings.append({
            'tag': 'hide_csp', 'value': True, 'claim': _m('finding.hidecsp'),
            'evidence': (csp or page_headers.get('X-Frame-Options', '')
                         or headers.get('X-Frame-Options', ''))[:200],
        })
    elif csp:
        findings.append({
            'tag': _m('tag.csp'), 'value': None,
            'claim': _m('finding.csp.nonce') if nonce else _m('finding.csp.embed'),
            'evidence': 'Content-Security-Policy: {0}'.format(csp[:180]),
        })
    if base_tag:
        findings.append({
            'tag': _m('tag.base'), 'value': None, 'claim': _m('finding.base'),
            'evidence': '<base href="{0}">'.format(base_tag.group(1)),
        })

    findings.extend(script_findings)

    manual = []
    ws_seen = ws_urls + ws_in_script
    if ws_seen:
        manual.append(_m('manual.ws', url=ws_seen[0][:60]))
    manual.append(_m('manual.left'))
    if parsed.scheme == 'https':
        manual.append(_m('manual.ssl'))

    return {
        'ok': True,
        'url': url,
        'verdict': {
            'tone': tone,
            'pill': _m('pill.appside' if kind == 'appside' else 'pill.ready'),
            'title': _m('verdict.' + kind + '.title'),
            'text': _m('verdict.' + kind + '.text', name=name),
        },
        'findings': findings,
        'header': _m('yaml.header.' + kind),
        'entries': [
            {'key': 'name', 'value': name, 'comment': name_why},
            {'key': 'url', 'value': url, 'comment': _m('yaml.url')},
            {'key': 'description', 'value': '""', 'comment': _m('yaml.description')},
            {'key': 'icon', 'value': '\U0001F4F1', 'comment': _m('yaml.icon')},
            {'key': 'category', 'value': 'Others', 'comment': _m('yaml.category')},
        ] + [{'key': k, 'value': v, 'comment': c} for k, v, c in options],
        'manual': manual,
        'probe': probe,
    }
