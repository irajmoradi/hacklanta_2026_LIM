"""Desktop-only adapters; never load a repository .env file."""
import hmac
import json
import os
from pathlib import Path
import sys
import threading


def credential(action, value=None):
    # Select only native credential stores; never accept a plaintext fallback.
    if sys.platform == 'win32':
        from keyring.backends.Windows import WinVaultKeyring
        store = WinVaultKeyring()
    elif sys.platform == 'darwin':
        from keyring.backends.macOS import Keyring
        store = Keyring()
    else:
        from keyring.backends.SecretService import Keyring
        store = Keyring()
    service, account = 'org.lim.editor', 'provider-api-key'
    if action == 'get':
        return store.get_password(service, account) or ''
    if action == 'set':
        if value:
            store.set_password(service, account, value)
        elif store.get_password(service, account):
            store.delete_password(service, account)
        return ''
    raise ValueError('Unknown credential action')


def make_app(root, frontend, workspace, token):
    sys.path.insert(0, str(root))
    from flask import request, abort
    from server.api import create_app
    app = create_app({'WORKSPACE': str(workspace)})
    app.static_folder = str(frontend)

    @app.before_request
    def authorize():
        supplied = request.headers.get('X-LIM-Token') or request.cookies.get('lim-session', '')
        if not token or not hmac.compare_digest(supplied, token):
            abort(403)
        if request.headers.get('Origin') and request.headers['Origin'] != request.host_url.rstrip('/'):
            abort(403)

    return app


def run_capture(token, argv):
    import capture.__main__ as capture
    original = capture.UploadClient

    class AuthenticatedClient(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.http.headers['X-LIM-Token'] = token

    capture.UploadClient = AuthenticatedClient
    try:
        return capture.main(argv)
    finally:
        capture.UploadClient = original


def main():
    mode = sys.argv[1]
    if mode == 'credential':
        data = json.load(sys.stdin)
        print(json.dumps(credential(data['action'], data.get('value'))))
        return
    root = Path(os.environ['LIM_BACKEND'])
    token = os.environ['LIM_TOKEN']
    sys.path.insert(0, str(root))
    # Parent pipe closure also shuts down after an Electron crash.
    def parent_closed():
        sys.stdin.read()
        os._exit(0)
    threading.Thread(target=parent_closed, daemon=True).start()
    if mode == 'capture':
        raise SystemExit(run_capture(token, sys.argv[2:]))
    from werkzeug.serving import make_server
    app = make_app(root, Path(os.environ['LIM_FRONTEND']), Path(os.environ['JOB_WORKSPACE']), token)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    print(json.dumps({'port': server.server_port}), flush=True)
    try:
        server.serve_forever()
    finally:
        app.extensions['job_queue'].close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Provider exceptions can contain credentials; report type only.
        print(type(exc).__name__ + ': desktop sidecar failed', file=sys.stderr)
        raise SystemExit(1)
