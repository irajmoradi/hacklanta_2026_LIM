"""Watchdog wakeups plus periodic reconciliation and a size/mtime quiet window."""
import json
import logging
import time
import tempfile
from pathlib import Path

LOG = logging.getLogger(__name__)
EXTENSIONS = {'.mp4', '.mkv', '.mov', '.flv', '.avi', '.webm', '.m4v', '.ts'}


def fingerprint(path):
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns]


class FolderWatcher:
    def __init__(self, folder, client, options, state, *, stable_seconds=5,
                 retry_seconds=30, include_existing=False, clock=time.monotonic):
        self.folder = Path(folder).resolve()
        if not self.folder.is_dir():
            raise ValueError('Watch folder must exist')
        self.client, self.options = client, options
        self.state = Path(state).expanduser()
        self.records = json.loads(self.state.read_text()) if self.state.exists() else {}
        if not isinstance(self.records, dict):
            raise ValueError('Capture state must be a JSON object')
        self.stable_seconds, self.retry_seconds = stable_seconds, retry_seconds
        self.clock = clock
        self.pending = {}
        self.baseline = {} if include_existing else self.snapshot()

    def snapshot(self):
        result = {}
        for path in self.folder.rglob('*'):
            try:
                if (path.suffix.lower() in EXTENSIONS and path.is_file()
                        and not path.is_symlink() and path.resolve().is_relative_to(self.folder)):
                    result[str(path)] = fingerprint(path)
            except OSError:
                continue
        return result

    def persist(self):
        self.state.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive random staging avoids following a pre-planted .tmp symlink.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                             dir=self.state.parent, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(self.records, stream)
            temporary.replace(self.state)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def scan(self):
        now = self.clock()
        snapshot = self.snapshot()
        for missing in self.pending.keys() - snapshot.keys():
            del self.pending[missing]
        for name, stamp in snapshot.items():
            record = self.records.get(name, {})
            if record.get('stamp') == stamp and record.get('done'):
                continue
            if self.baseline.get(name) == stamp and not record:
                continue
            prior = self.pending.get(name)
            if prior is None or prior['stamp'] != stamp:
                self.pending[name] = dict(stamp=stamp, since=now, retry=now)
                continue
            if not stamp[0] or now - prior['since'] < self.stable_seconds or now < prior['retry']:
                continue
            path = Path(name)
            try:
                # Opening catches Windows sharing violations; re-stat catches late writes.
                with path.open('rb'):
                    if fingerprint(path) != stamp:
                        continue
                if record.get('stamp') != stamp:
                    record = dict(stamp=stamp, done=False)
                    self.records[name] = record
                    self.persist()
                if not record.get('job'):
                    record['job'] = self.client.upload(path)
                    self.persist()  # Never re-upload a known job when analysis fails.
                if fingerprint(path) != stamp:
                    LOG.warning('File changed during upload; waiting again: %s', path.name)
                    continue
                self.client.analyze(record['job'], self.options)
                record['done'] = True
                self.persist()
                LOG.info('Analysis queued: %s (job %s)', path.name, record['job'])
            except Exception as exc:
                # Avoid logging response bodies, credentials or capture window titles.
                prior['retry'] = now + self.retry_seconds
                LOG.warning('Capture retry in %ss: %s (%s)', self.retry_seconds, path.name, type(exc).__name__)


def start_observer(folder, wake):
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        LOG.warning('watchdog missing; using periodic folder scans')
        return None

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):
            if event.event_type in {'created', 'modified', 'moved', 'closed', 'deleted'}:
                wake.set()

    observer = Observer()
    observer.schedule(Handler(), str(folder), recursive=True)
    observer.start()
    return observer
