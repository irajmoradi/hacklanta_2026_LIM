import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
import urllib.error

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = Path(os.environ.get('LIM_TEST_RUNTIME', ROOT))
SIDECAR = ROOT / 'desktop/sidecar.py' if RUNTIME == ROOT else RUNTIME / 'sidecar.py'
spec = importlib.util.spec_from_file_location('desktop_sidecar', SIDECAR)
sidecar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sidecar)


@pytest.fixture
def app(tmp_path):
    frontend = tmp_path / 'frontend'
    frontend.mkdir()
    (frontend / 'index.html').write_text('production frontend')
    instance = sidecar.make_app(RUNTIME / 'full_app', frontend, tmp_path / 'jobs', 'test-token')
    yield instance
    instance.extensions['job_queue'].close()


def test_frontend_and_api_auth(app):
    client = app.test_client()
    assert client.get('/api/info').status_code == 403
    headers = {'X-LIM-Token': 'test-token'}
    assert client.get('/', headers=headers).data == b'production frontend'
    assert client.get('/api/info', headers=headers).status_code == 200
    assert client.get('/api/info', headers={**headers, 'Origin': 'https://evil.example'}).status_code == 403
    client.set_cookie('lim-session', 'test-token')
    assert client.get('/api/info').status_code == 200


def test_synthetic_upload(app, tmp_path):
    media = tmp_path / 'sample.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10', '-t', '1', '-c:v', 'mpeg4', str(media)], check=True)
    with media.open('rb') as stream:
        response = app.test_client().post('/api/jobs', data={'video': (stream, 'sample.mp4')}, headers={'X-LIM-Token': 'test-token'})
    assert response.status_code == 201
    assert response.json['status'] == 'uploaded'


def test_real_sidecar_ephemeral_port_and_parent_shutdown(tmp_path):
    frontend = tmp_path / 'frontend'
    frontend.mkdir()
    (frontend / 'index.html').write_text('ready')
    env = {**os.environ, 'LIM_BACKEND': str(RUNTIME / 'full_app'), 'LIM_FRONTEND': str(frontend), 'JOB_WORKSPACE': str(tmp_path / 'jobs'), 'LIM_TOKEN': 'test-token'}
    child = subprocess.Popen([sys.executable, str(SIDECAR), 'server'], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        import select
        assert select.select([child.stdout], [], [], 30)[0], 'sidecar readiness timeout'
        port = json.loads(child.stdout.readline())['port']
        url = f'http://127.0.0.1:{port}/api/info'
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(url, timeout=5)
        assert error.value.code == 403
        request = urllib.request.Request(url, headers={'X-LIM-Token': 'test-token'})
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
        child.stdin.close()
        assert child.wait(timeout=5) == 0
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)


def test_native_keychain_only(monkeypatch):
    import types
    saved = {}
    class FakeKeyring:
        def get_password(self, service, account):
            return saved.get((service, account))
        def set_password(self, service, account, value):
            saved[service, account] = value
        def delete_password(self, service, account):
            del saved[service, account]
    monkeypatch.setitem(sys.modules, 'keyring.backends.SecretService', types.SimpleNamespace(Keyring=FakeKeyring))
    monkeypatch.setattr(sys, 'platform', 'linux')
    sidecar.credential('set', 'test-key')
    assert sidecar.credential('get') == 'test-key'
    sidecar.credential('set', '')
    assert sidecar.credential('get') == ''


def test_capture_adds_private_token(monkeypatch):
    sys.path.insert(0, str(RUNTIME / 'full_app'))
    import capture.__main__ as capture
    original = capture.UploadClient
    def fake_main(argv):
        assert argv == ['--watch', '/recordings']
        with_client = capture.UploadClient('http://127.0.0.1:12345')
        try:
            assert with_client.http.headers['X-LIM-Token'] == 'private-token'
        finally:
            with_client.close()
        return 0
    monkeypatch.setattr(capture, 'main', fake_main)
    assert sidecar.run_capture('private-token', ['--watch', '/recordings']) == 0
    assert capture.UploadClient is original
