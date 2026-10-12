"""Run from full_app: python -m capture --watch PATH --api URL."""
import argparse
import hashlib
import json
import logging
import math
import signal
import threading
from pathlib import Path
from urllib.parse import urlparse

from .client import UploadClient
from .obs import OBSClient, trigger_replay
from .watcher import FolderWatcher, start_observer

LOG = logging.getLogger(__name__)


def configuration(args):
    config = json.loads(Path(args.config).read_text(encoding='utf-8')) if args.config else {}
    allowed = {'watch', 'api', 'options', 'stable_seconds', 'poll_seconds', 'retry_seconds',
               'include_existing', 'state', 'obs', 'hotkey'}
    if not isinstance(config, dict) or set(config) - allowed:
        raise ValueError('Unknown capture configuration fields')
    config = {'api': 'http://localhost:8000', 'options': {}, 'stable_seconds': 5,
              'poll_seconds': 1, 'retry_seconds': 30, 'include_existing': False,
              'obs': {}, **config}
    for name in ('watch', 'api'):
        if getattr(args, name):
            config[name] = getattr(args, name)
    if args.hotkey:
        config['hotkey'] = args.hotkey
    for name in ('stable_seconds', 'poll_seconds', 'retry_seconds'):
        value = config[name]
        if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{name} must be a positive finite number')
    if type(config['include_existing']) is not bool:
        raise ValueError('include_existing must be boolean')
    if not isinstance(config['options'], dict):
        raise ValueError('options must be an object')
    # Use the server's existing validation so bad defaults cannot upload a backlog.
    from server.validation import options_valid
    if {'api_key', 'job_id', 'edit_plan'} & config['options'].keys():
        raise ValueError('options may not contain credentials, job_id or edit_plan')
    # Style names belong to the server; don't import the Gemini/render stack here.
    style = config['options'].get('edit_style', config['options'].get('style', 'hype_montage'))
    if not isinstance(style, str):
        raise ValueError('style must be a string')
    config['options'] = options_valid(config['options'], {style})
    if not isinstance(config['obs'], dict) or set(config['obs']) - {'url', 'password_env', 'timeout'}:
        raise ValueError('obs accepts url, password_env and timeout only')
    for url, schemes in ((config['api'], {'http', 'https'}),
                         (config['obs'].get('url', 'ws://localhost:4455'), {'ws', 'wss'})):
        parsed = urlparse(url)
        if parsed.scheme not in schemes or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Invalid API/OBS URL (credentials belong in the environment)')
    timeout = config['obs'].get('timeout', 10)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('obs.timeout must be a positive finite number')
    if not isinstance(config['obs'].get('password_env', ''), str):
        raise ValueError('obs.password_env must be a string')
    if 'hotkey' in config and (not isinstance(config['hotkey'], str) or not config['hotkey']):
        raise ValueError('hotkey must be a nonempty pynput key combination')
    if not (args.save_replay or args.event or args.obs_context):
        if not isinstance(config.get('watch'), str) or not Path(config['watch']).is_dir():
            raise ValueError('Supply an existing --watch directory or watch in JSON config')
        config['watch'] = str(Path(config['watch']).resolve())
        identity = config['watch'] + '\n' + config['api'].rstrip('/')
        token = hashlib.sha256(identity.encode()).hexdigest()[:16]
        config.setdefault('state', str(Path.home() / '.lim-capture' / f'{token}.json'))
    return config


def start_hotkey(combination, callback):
    try:
        from pynput.keyboard import GlobalHotKeys
        listener = GlobalHotKeys({combination: callback})
        listener.start()
        return listener
    except (ImportError, OSError) as exc:
        LOG.warning('Hotkey unavailable (%s); use OBS native hotkeys or --save-replay', type(exc).__name__)
        return None


def run(config):
    wake, stop = threading.Event(), threading.Event()
    replay = threading.Event()

    def shutdown(*_):
        stop.set()
        wake.set()

    def hotkey():
        replay.set()  # Keep socket I/O off the keyboard listener thread.
        wake.set()

    previous = {sig: signal.signal(sig, shutdown) for sig in (signal.SIGINT, signal.SIGTERM)}
    client = UploadClient(config['api'])
    observer = listener = None
    try:
        watcher = FolderWatcher(config['watch'], client, config['options'], config['state'],
                                stable_seconds=config['stable_seconds'],
                                retry_seconds=config['retry_seconds'],
                                include_existing=config['include_existing'])
        observer = start_observer(config['watch'], wake)
        if config.get('hotkey'):
            listener = start_hotkey(config['hotkey'], hotkey)
        LOG.info('Watching %s; Ctrl+C stops capture', config['watch'])
        while not stop.is_set():
            wake.clear()
            if replay.is_set():
                replay.clear()
                try:
                    trigger_replay(config['obs'])
                    LOG.info('OBS replay save requested')
                except Exception as exc:
                    LOG.warning('Replay save failed (%s)', type(exc).__name__)
            watcher.scan()
            wake.wait(config['poll_seconds'])
    finally:
        for worker in (observer, listener):
            if worker is not None:
                worker.stop()
                worker.join(timeout=5)
        client.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', help='JSON config file')
    parser.add_argument('--watch', help='OBS / ShadowPlay / Medal output directory (recursive)')
    parser.add_argument('--api', help='Local API base URL (default http://localhost:8000)')
    parser.add_argument('--hotkey', help='Optional global hotkey, e.g. <ctrl>+<alt>+r')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--save-replay', action='store_true')
    action.add_argument('--event', help='Save replay on an external detected event, e.g. kill')
    action.add_argument('--obs-context', action='store_true', help='Print scene and game/window capture sources')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        config = configuration(args)
        if args.obs_context:
            with OBSClient(**config['obs']) as obs:
                print(json.dumps(obs.context()))
        elif args.save_replay or args.event:
            print(json.dumps(trigger_replay(config['obs'], args.event or 'manual')))
        else:
            run(config)
        return 0
    except (OSError, ValueError, RuntimeError, TypeError) as exc:
        LOG.error('Capture stopped (%s): check configuration, dependencies and OBS connectivity', type(exc).__name__)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
