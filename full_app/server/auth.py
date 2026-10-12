"""Application identities, independent of model provider credentials."""
import hmac
import ipaddress
import json
import os

from flask import g, jsonify, request
from .security import api_headers, RateLimiter


def install_auth(app, store):
    tokens = app.config.get('API_TOKENS', json.loads(os.getenv('LIM_API_TOKENS') or '{}'))
    tokens = dict(tokens)
    single = app.config.get('API_TOKEN', os.getenv('LIM_API_TOKEN', ''))
    if single:
        tokens.setdefault('default', single)
    for owner, token in tokens.items():
        if not isinstance(owner, str) or not owner or owner == 'local' or not token:
            raise ValueError('Invalid application identity')
        api_headers('https://localhost', token)
    if len(set(tokens.values())) != len(tokens):
        raise ValueError('Application tokens must be unique')
    limiter = RateLimiter(limit=app.config.get('API_RATE_LIMIT', 600))

    def owned(job_id):
        job = store.get(job_id)
        if job.get('_owner', 'local') != g.owner:
            raise KeyError(job_id)
        return job

    @app.before_request
    def authenticate():
        if not request.path.startswith('/api/') or request.path == '/api/health':
            return None
        if not limiter.allow(request.remote_addr or 'unknown'):
            return jsonify(error='Too many requests'), 429, {'Retry-After': '60'}
        if request.is_json:
            request.max_content_length = app.config.get('MAX_JSON_BYTES', 2 * 1024**2)
        g.owner = None
        supplied = request.headers.get('Authorization', '').encode('utf-8')
        for owner, token in tokens.items():
            if hmac.compare_digest(supplied, ('Bearer ' + token).encode('ascii')):
                g.owner = owner
        if not tokens:
            try:
                if ipaddress.ip_address(request.remote_addr or '').is_loopback:
                    g.owner = 'local'
            except ValueError:
                pass
        if g.owner is None:
            return jsonify(error='Application authentication required'), 401, {'WWW-Authenticate': 'Bearer'}
        if request.view_args and 'job_id' in request.view_args:
            owned(request.view_args['job_id'])

    @app.after_request
    def headers(response):
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    return owned
