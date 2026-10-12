"""Small synchronous obs-websocket v5 adapter. One connection per operation."""
import base64
import hashlib
import json
import os
import time
import uuid


class OBSError(RuntimeError):
    pass


def digest(value):
    return base64.b64encode(hashlib.sha256(value.encode()).digest()).decode()


class OBSClient:
    def __init__(self, url='ws://localhost:4455', password_env='OBS_WEBSOCKET_PASSWORD',
                 timeout=10, connector=None):
        self.url, self.password_env, self.timeout = url, password_env, timeout
        self.connector = connector
        self.socket = None

    def __enter__(self):
        connector = self.connector
        if connector is None:
            try:
                from websocket import create_connection
            except ImportError:
                raise OBSError('Install capture/requirements.txt for OBS support') from None
            connector = create_connection
        self.socket = connector(self.url, timeout=self.timeout)
        try:
            hello = json.loads(self.socket.recv())
            if hello.get('op') != 0:
                raise OBSError('Expected OBS Hello')
            data = {'rpcVersion': 1, 'eventSubscriptions': 0}
            auth = hello['d'].get('authentication')
            if auth:
                password = os.environ.get(self.password_env)
                if not password:
                    raise OBSError('Set the OBS password environment variable')
                data['authentication'] = digest(digest(password + auth['salt']) + auth['challenge'])
            self.socket.send(json.dumps({'op': 1, 'd': data}))
            if json.loads(self.socket.recv()).get('op') != 2:
                raise OBSError('OBS identification failed')
            return self
        except BaseException:
            self.socket.close()
            raise

    def __exit__(self, *args):
        self.socket.close()

    def request(self, kind, data=None):
        request_id = uuid.uuid4().hex
        self.socket.send(json.dumps({'op': 6, 'd': {
            'requestType': kind, 'requestId': request_id, 'requestData': data or {}}}))
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            self.socket.settimeout(max(.001, deadline - time.monotonic()))
            message = json.loads(self.socket.recv())
            response = message.get('d', {})
            if message.get('op') != 7 or response.get('requestId') != request_id:
                continue
            if not response.get('requestStatus', {}).get('result'):
                raise OBSError(f'OBS {kind} failed (code {response.get("requestStatus", {}).get("code")})')
            return response.get('responseData', {})
        raise OBSError('OBS response timed out')

    def save_replay(self):
        if not self.request('GetReplayBufferStatus').get('outputActive'):
            raise OBSError('Start the OBS replay buffer before saving')
        self.request('SaveReplayBuffer')

    def context(self):
        scene = self.request('GetCurrentProgramScene')['currentProgramSceneName']
        captures = []
        visited = set()

        def collect(name, group=False):
            if (name, group) in visited:
                return
            visited.add((name, group))
            items = self.request('GetGroupSceneItemList' if group else 'GetSceneItemList',
                                 {'sceneName': name}).get('sceneItems', [])
            for item in items:
                if not item.get('sceneItemEnabled', True):
                    continue
                source = item['sourceName']
                if item.get('isGroup') or item.get('sourceType') == 'OBS_SOURCE_TYPE_SCENE':
                    collect(source, bool(item.get('isGroup')))
                elif item.get('inputKind') in {'game_capture', 'window_capture', 'xcomposite_input'}:
                    settings = self.request('GetInputSettings', {'inputName': source}).get('inputSettings', {})
                    captures.append({'source': source, 'kind': item['inputKind'],
                                     'window': settings.get('window', ''),
                                     'capture_mode': settings.get('capture_mode', '')})
        collect(scene)
        return {'scene': scene, 'captures': captures}


def trigger_replay(config, reason='hotkey', factory=OBSClient):
    """Event-detector integration hook: call on a kill/death/round event."""
    with factory(**config) as obs:
        obs.save_replay()
    return {'saved': True, 'reason': reason}
