"""SQLite snapshots and replayable events committed in the same transaction."""
import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager


class JobStore:
    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.RLock()
        with self.connection() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_job ON events(job_id, seq);
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, job_id):
        with self.connection() as db:
            row = db.execute('SELECT data FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return json.loads(row[0])

    def all(self):
        with self.connection() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT data FROM jobs')]

    def save(self, job):
        with self.lock, self.connection() as db:
            job['updated_at'] = time.time()
            data = json.dumps(job, allow_nan=False)
            db.execute('INSERT OR REPLACE INTO jobs VALUES (?, ?)', (job['id'], data))
            event = {k: job.get(k) for k in ('id', 'status', 'stage', 'progress', 'error', 'updated_at', 'pipeline_stage', 'timings')}
            db.execute('INSERT INTO events(job_id,data) VALUES (?,?)', (job['id'], json.dumps(event)))
            db.execute('DELETE FROM events WHERE job_id=? AND seq NOT IN '
                       '(SELECT seq FROM events WHERE job_id=? ORDER BY seq DESC LIMIT 1000)',
                       (job['id'], job['id']))
        logging.getLogger('jobs').info(json.dumps(event))

    def events(self, job_id, after):
        with self.connection() as db:
            return db.execute('SELECT seq,data FROM events WHERE job_id=? AND seq>? ORDER BY seq LIMIT 100',
                              (job_id, after)).fetchall()
