"""Resource admission and isolated production stage execution (Linux)."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager


def disk_bytes(root):
    total = 0
    for path in Path(root).rglob('*'):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except FileNotFoundError:
            pass
    return total


def bounded_process(command, payload, *, timeout, cancelled=lambda: False, check=lambda: None):
    """Deadline/cancellation owns the entire process group, including ffmpeg."""
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.monotonic() + timeout
    pending = payload
    try:
        while True:
            if cancelled():
                raise RuntimeError('Stage cancelled')
            check()
            if time.monotonic() >= deadline:
                raise TimeoutError('Media execution deadline exceeded')
            try:
                output, _ = process.communicate(pending, timeout=min(.2, max(.001, deadline - time.monotonic())))
                check()
                if process.returncode:
                    raise RuntimeError('Isolated media process failed')
                return output
            except subprocess.TimeoutExpired:
                pending = None
    finally:
        if os.name == 'posix':
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.poll() is None:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            process.kill()
        process.communicate()


class Resources:
    def __init__(self, workspace, store, config):
        self.workspace, self.store, self.config = workspace, store, config
        self.lock = threading.RLock()
        self.reserved = {}

    @contextmanager
    def upload(self, owner, size):
        with self.lock:
            jobs = self.store.all()
            if size > self.config['JOB_BYTES']:
                raise ValueError('Upload exceeds job storage quota')
            if len(jobs) + len(self.reserved) >= self.config['MAX_JOBS']:
                raise ValueError('Job storage is full; delete old jobs')
            workspace_used = disk_bytes(self.workspace)
            owner_used = sum(disk_bytes(j['dir']) for j in jobs if j.get('_owner', 'local') == owner)
            if (workspace_used + sum(v[1] for v in self.reserved.values()) + size > self.config['WORKSPACE_BYTES'] or
                    owner_used + sum(v[1] for v in self.reserved.values() if v[0] == owner) + size > self.config['OWNER_BYTES'] or
                    shutil.disk_usage(self.workspace).free < 2 * (size + sum(v[1] for v in self.reserved.values())) + self.config['DISK_HEADROOM_BYTES']):
                raise ValueError('Upload storage quota exceeded')
            key = object()
            self.reserved[key] = (owner, size)
        try:
            yield
        finally:
            with self.lock:
                self.reserved.pop(key, None)

    def check_stage(self, job):
        if disk_bytes(job['dir']) > self.config['JOB_BYTES'] or disk_bytes(self.workspace) > self.config['WORKSPACE_BYTES']:
            raise ValueError('Stage storage quota exceeded')
        owner = job.get('_owner', 'local')
        if sum(disk_bytes(j['dir']) for j in self.store.all() if j.get('_owner', 'local') == owner) > self.config['OWNER_BYTES']:
            raise ValueError('Owner storage quota exceeded')

    def reap(self, queue):
        with queue.lock:
            cutoff = time.time() - self.config['JOB_TTL_SECONDS']
            for job in self.store.all():
                if job['id'] in queue.active or job.get('updated_at', job['created_at']) >= cutoff:
                    continue
                directory = Path(job['dir']).resolve()
                if directory.parent != self.workspace:
                    continue
                shutil.rmtree(directory, ignore_errors=True)
                with self.store.connection() as db:
                    db.execute('DELETE FROM events WHERE job_id=?', (job['id'],))
                    db.execute('DELETE FROM jobs WHERE id=?', (job['id'],))
                queue.keys.pop(job['id'], None)


class IsolatedPipeline:
    def __init__(self, resources):
        self.resources = resources

    def run_stage(self, stage, job, key, report):
        config = self.resources.config
        payload = json.dumps(dict(stage=stage, job=job, key=key,
                                  memory=config['STAGE_MEMORY_BYTES'], file_bytes=config['JOB_BYTES'])).encode()
        progress = Path(job['dir']) / '.stage-progress.json'
        last = None
        def check():
            nonlocal last
            self.resources.check_stage(job)
            try:
                raw = progress.read_text()
            except FileNotFoundError:
                return
            if raw != last:
                report(json.loads(raw))
                last = raw
        try:
            output = bounded_process([sys.executable, '-m', 'server.stage_worker'], payload,
                                     timeout=config['STAGE_TIMEOUT_SECONDS'],
                                     cancelled=lambda: self.resources.store.get(job['id'])['status'] == 'cancelled',
                                     check=check)
            result = json.loads(output)
            if '_stage_error' in result:
                from services.provider_errors import ProviderFailure
                raise ProviderFailure(result['_stage_error'])
            job.update(result)
            report(job)
        finally:
            progress.unlink(missing_ok=True)
            progress.with_suffix('.part').unlink(missing_ok=True)



def probe(path, config):
    payload = json.dumps(dict(path=str(path), memory=config['PROBE_MEMORY_BYTES'],
                              file_bytes=config['JOB_BYTES'])).encode()
    result = bounded_process([sys.executable, '-m', 'server.stage_worker'], payload,
                             timeout=config['PROBE_TIMEOUT_SECONDS'])
    return json.loads(result)
