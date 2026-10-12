"""Atomic attempt reservations survive stage subprocesses, retries and restarts."""
import os
import sqlite3
import threading
import time
from services.provider_errors import ProviderFailure

class CallBudget:
    def __init__(self, path=None, limit=None):
        self.limit = int(limit if limit is not None else os.getenv('MAX_GEMINI_CALLS_PER_JOB', '80'))
        if self.limit < 0: raise ValueError('MAX_GEMINI_CALLS_PER_JOB must be nonnegative')
        self.path = str(path) if path else None
        self.used = 0
        self.lock = threading.Lock()
        self.next_call = 0.
        self.interval = float(os.getenv('GEMINI_REQUEST_INTERVAL_SECONDS', '0.25'))
        if self.path:
            with sqlite3.connect(self.path) as db:
                db.execute('CREATE TABLE IF NOT EXISTS budget (id INTEGER PRIMARY KEY, used INTEGER NOT NULL)')
                db.execute('INSERT OR IGNORE INTO budget VALUES (1, 0)')

    @property
    def remaining(self):
        if self.path:
            with sqlite3.connect(self.path) as db:
                used = db.execute('SELECT used FROM budget WHERE id=1').fetchone()[0]
        else: used = self.used
        return max(0, self.limit - used)

    def reserve(self):
        with self.lock:
            if self.path:
                with sqlite3.connect(self.path, timeout=30) as db:
                    db.execute('BEGIN IMMEDIATE')
                    used = db.execute('SELECT used FROM budget WHERE id=1').fetchone()[0]
                    if used >= self.limit: raise ProviderFailure('budget')
                    db.execute('UPDATE budget SET used=used+1 WHERE id=1')
            else:
                if self.used >= self.limit: raise ProviderFailure('budget')
                self.used += 1
            delay = max(0., self.next_call - time.monotonic())
            self.next_call = time.monotonic() + delay + self.interval
        if delay: time.sleep(delay)
