"""Explicit security boundaries; install_api_security must be called by the app factory.

No import-time hooks, credentials in URLs, or trust in forwarded client headers.
"""
import hmac
import ipaddress
import math
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit


def safe_component(value):
    """Portable filename/job-id component, excluding Windows devices and ADS."""
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value)
            or value.endswith('.') or value.split('.')[0].upper() in
            {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))}):
        raise ValueError('Invalid path component')
    return value


def safe_path(root, *parts):
    """Resolve beneath a trusted, privately writable root, including symlinks."""
    base = Path(root).resolve()
    target = base.joinpath(*(safe_component(p) for p in parts)).resolve()
    if target == base or not target.is_relative_to(base):
        raise ValueError('Path escapes its root')
    return target


def https_url(url, hosts=None):
    """Strict HTTPS URL syntax. DNS/address checks belong at socket connection."""
    try:
        if not isinstance(url, str) or len(url) > 8192 or any(c.isspace() or ord(c) < 32 for c in url) or '\\' in url:
            raise ValueError()
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)
                or '%' in parsed.hostname or parsed.fragment
                or hosts is not None and parsed.hostname not in hosts):
            raise ValueError()
        return parsed
    except (ValueError, TypeError):
        raise ValueError('Only HTTPS URLs on allowed public hosts are supported') from None


def public_address(address):
    try:
        ip = ipaddress.ip_address(address)
        if '%' in address or not ip.is_global or ip.is_multicast or ip.is_unspecified:
            return False
        if isinstance(ip, ipaddress.IPv6Address):
            # Reject transition/tunnel addresses as well as mapped private IPv4.
            if ip.sixtofour or ip.teredo:
                return False
            if ip.ipv4_mapped:
                return public_address(str(ip.ipv4_mapped))
        return True
    except ValueError:
        return False


def api_headers(url, token=None):
    """Bearer credentials are env-only and require TLS except on literal loopback."""
    token = os.getenv('LIM_API_TOKEN', '') if token is None else token
    parsed = urlsplit(url)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment):
        raise ValueError('Invalid API URL')
    parsed.port  # Validate malformed ports before creating a client.
    if token:
        if not isinstance(token, str) or not re.fullmatch(r'[\x21-\x7e]{32,4096}', token):
            raise ValueError('LIM_API_TOKEN must contain 32-4096 visible ASCII characters')
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = parsed.hostname == 'localhost'
        if parsed.scheme != 'https' and not loopback:
            raise ValueError('API tokens require HTTPS for remote hosts')
    return {'Authorization': 'Bearer ' + token} if token else {}


def escape_drawtext(text):
    """Return an UNQUOTED drawtext text= value for a subprocess argv filtergraph.

    Use expansion=none. Escape the option parser, then the filtergraph parser;
    shell quoting is neither supplied nor supported here.
    """
    if not isinstance(text, str) or len(text) > 8000 or any(ord(c) < 32 for c in text):
        raise ValueError('Text must be a single line of at most 8000 characters')
    option = ''.join('\\' + c if c in "\\': " else c for c in text)
    return ''.join('\\' + c if c in "\\'[],; " else c for c in option)


def validate_media_metadata(info, *, max_duration=43200, max_pixels=3840 * 2160,
                            max_fps=240, max_pixel_rate=3840 * 2160 * 60):
    try:
        duration, fps = float(info['duration']), float(info['fps'])
        width, height = int(info['width']), int(info['height'])
        container = float(info.get('container_duration', duration))
        if (not all(math.isfinite(x) and x > 0 for x in (duration, container, fps))
                or max(duration, container) > max_duration or fps > max_fps
                or width <= 0 or height <= 0 or width * height > max_pixels
                or width * height * fps > max_pixel_rate):
            raise ValueError()
    except (KeyError, ValueError, TypeError, OverflowError):
        raise ValueError('Video exceeds duration, dimensions, or frame-rate limits') from None
    return info


class RateLimiter:
    """Thread-safe fixed windows with bounded identities; fail closed when full."""
    def __init__(self, limit=120, window=60, max_clients=4096, clock=time.monotonic):
        if type(limit) is not int or limit <= 0 or not math.isfinite(window) or window <= 0 or max_clients <= 0:
            raise ValueError('Invalid rate limits')
        self.limit, self.window, self.max_clients, self.clock = limit, window, max_clients, clock
        self.lock, self.clients = threading.Lock(), {}

    def allow(self, key):
        now = self.clock()
        with self.lock:
            self.clients = {k: v for k, v in self.clients.items() if now < v[0]}
            if key not in self.clients:
                if len(self.clients) >= self.max_clients:
                    return False
                self.clients[key] = [now + self.window, 0]
            record = self.clients[key]
            if record[1] >= self.limit:
                return False
            record[1] += 1
            return True


def install_api_security(app, *, token=None, limiter=None):
    """Opt-in auth for ALL /api routes, plus per-peer limits (including failures).

    Call before serving. Token defaults to LIM_API_TOKEN; absent token preserves
    local development. Multi-worker deployments need shared proxy rate limits.
    """
    from flask import jsonify, request
    if 'lim_security' in app.extensions:
        raise ValueError('API security is already installed')
    token = os.getenv('LIM_API_TOKEN', '') if token is None else token
    api_headers('https://localhost', token)  # Validate without exposing the token.
    expected = ('Bearer ' + token).encode('ascii')
    limiter = limiter or RateLimiter()
    app.extensions['lim_security'] = limiter

    @app.before_request
    def protect_api():
        if request.path != '/api' and not request.path.startswith('/api/'):
            return None
        if not limiter.allow(request.remote_addr or 'unknown'):
            return jsonify(error='Too many requests'), 429, {'Retry-After': str(math.ceil(limiter.window))}
        if token and not hmac.compare_digest(request.headers.get('Authorization', '').encode('utf-8'), expected):
            return jsonify(error='Authentication required'), 401, {'WWW-Authenticate': 'Bearer'}
        if request.view_args and 'job_id' in request.view_args:
            try:
                safe_component(request.view_args['job_id'])
            except ValueError:
                return jsonify(error='Invalid job id'), 400
        return None

    @app.after_request
    def secure_headers(response):
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
        return response


def create_secure_app(config=None, pipeline=None):
    """Runnable opt-in factory: flask --app server.security:create_secure_app run.

    Uses existing routes without mutating the default factory. See security.md
    for outstanding upload-handler integration and deployment restrictions.
    """
    from .api import create_app
    # Validate before the ordinary factory allocates workers/workspace locks.
    api_headers('https://localhost')
    app = create_app(config, pipeline)
    install_api_security(app)
    return app
