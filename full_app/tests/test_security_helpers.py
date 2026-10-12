"""Offline security regression tests; hostile inputs never reach external APIs."""
from concurrent.futures import ThreadPoolExecutor
import subprocess

import pytest
from flask import Flask

from server.security import (RateLimiter, api_headers, escape_drawtext, https_url,
                             install_api_security, public_address, safe_component,
                             safe_path, validate_media_metadata)


@pytest.mark.parametrize('name', ['../a', '..', '.', '/etc/passwd', 'C:\\secret',
                                    'foo:bar', 'a/b', 'a\\b', '%2e%2e', 'NUL.mp4',
                                    'COM1', 'a.', '', 'x\x00y', '-option'])
def test_path_rejection(name, tmp_path):
    with pytest.raises(ValueError):
        safe_path(tmp_path, name)


def test_resolved_path_containment(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'link').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        safe_path(root, 'link', 'secret')
    assert safe_path(root, 'a.mp4') == root / 'a.mp4'
    assert safe_component('ab12') == 'ab12'


@pytest.mark.parametrize('url', ['https://youtu.be:bad/a', 'https://youtu.be:444/a',
                                  'https://youtu.be.evil/a', 'https://u:p@youtu.be/a',
                                  'https://youtu.be/\na', 'https://youtu.be\\@evil/a',
                                  'file:///tmp/a', 'http://youtu.be/a'])
def test_url_syntax(url):
    with pytest.raises(ValueError):
        https_url(url, {'youtu.be'})


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.1', '169.254.169.254',
                                      '192.168.1.1', '100.64.0.1', '::1', 'fc00::1',
                                      'fe80::1%eth0', '::ffff:127.0.0.1', '224.0.0.1',
                                      '2002:7f00:1::', '64:ff9b::a00:1', '0.0.0.0'])
def test_nonpublic_addresses(address):
    assert not public_address(address)


def test_api_auth_covers_legacy_read_and_mutation_routes():
    app = Flask(__name__)
    @app.route('/api/<path:path>', methods=['GET', 'POST', 'DELETE'])
    def endpoint(path):
        return 'ok'
    token = 'test-only-' + 'x' * 32
    install_api_security(app, token=token)
    client = app.test_client()
    for path in ('jobs', 'upload', 'download/a', 'stream/a', 'log/a', 'jobs/a/events'):
        for method in ('GET', 'POST', 'DELETE'):
            assert client.open('/api/' + path, method=method).status_code == 401
            response = client.open('/api/' + path, method=method,
                                   headers={'Authorization': 'Bearer ' + token})
            assert response.status_code == 200
            assert response.headers['Cache-Control'] == 'no-store'
    assert client.get('/api/jobs', headers={'X-API-Key': token}).status_code == 401


def test_rate_limits_ignore_forwarded_headers_and_expire():
    now = [0]
    limiter = RateLimiter(limit=2, window=10, max_clients=1, clock=lambda: now[0])
    app = Flask(__name__)
    app.add_url_rule('/api/info', view_func=lambda: 'ok')
    install_api_security(app, token='', limiter=limiter)
    client = app.test_client()
    assert client.get('/api/info').status_code == 200
    assert client.get('/api/info', headers={'X-Forwarded-For': '8.8.8.8'}).status_code == 200
    response = client.get('/api/info', headers={'X-Forwarded-For': '1.1.1.1'})
    assert response.status_code == 429 and response.headers['Retry-After'] == '10'
    assert not limiter.allow('new-client')
    now[0] = 10
    assert client.get('/api/info').status_code == 200


def test_rate_limit_is_atomic():
    limiter = RateLimiter(limit=7)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(lambda _: limiter.allow('same'), range(50))) == 7


def test_tokens_are_env_only_and_require_remote_tls(monkeypatch):
    monkeypatch.setenv('LIM_API_TOKEN', 'test-only-' + 'a' * 32)
    assert 'Authorization' in api_headers('https://api.example')
    assert 'Authorization' in api_headers('http://127.0.0.1:8000')
    with pytest.raises(ValueError, match='HTTPS'):
        api_headers('http://api.example')
    with pytest.raises(ValueError):
        api_headers('https://user:secret@api.example')
    monkeypatch.setenv('LIM_API_TOKEN', 'short')
    with pytest.raises(ValueError):
        api_headers('https://api.example')


@pytest.mark.parametrize('field,value', [('width', 100000), ('height', -1), ('fps', 10000),
                                        ('duration', float('inf')), ('duration', 50000)])
def test_decode_bomb_metadata(field, value):
    info = dict(width=1920, height=1080, fps=60, duration=10)
    info[field] = value
    with pytest.raises(ValueError):
        validate_media_metadata(info)


@pytest.mark.parametrize('payload', ["a'b:c\\d, [x];movie=/etc/passwd", '%{metadata:secret}',
                                      "hello;[in]null[out]", ' leading and trailing '])
def test_drawtext_matches_textfile_pixels(payload, tmp_path):
    # Compare to FFmpeg's literal textfile mode, not merely successful parsing.
    (tmp_path / 'literal.txt').write_text(payload, encoding='utf-8')
    base = ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=640x80:d=0.1',
            '-frames:v', '1', '-threads', '1']
    def render(text_option):
        return subprocess.run(base + ['-vf', 'drawtext=expansion=none:fontsize=16:fontcolor=white:' + text_option,
                                      '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'],
                              cwd=tmp_path, capture_output=True, check=True, timeout=15).stdout
    assert render('text=' + escape_drawtext(payload)) == render('textfile=literal.txt')


def test_drawtext_rejects_controls():
    with pytest.raises(ValueError):
        escape_drawtext('hello\nworld')
