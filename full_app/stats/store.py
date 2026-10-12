"""Durable, atomic one-vote-per-user/week storage using only stdlib SQLite."""

from contextlib import contextmanager
import sqlite3


class VoteConflict(ValueError):
    pass


class VoteStore:
    def __init__(self, path):
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("VoteStore requires a persistent SQLite path")
        with self.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS stats_votes (
                group_id TEXT NOT NULL, week TEXT NOT NULL, user_id TEXT NOT NULL,
                clip_id TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY (group_id, week, user_id))""")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def vote(self, group_id, week, user_id, clip_id, created_at):
        """Identical retries are idempotent; changing an existing vote conflicts."""
        with self.connection() as db:
            cursor = db.execute("INSERT OR IGNORE INTO stats_votes VALUES (?, ?, ?, ?, ?)",
                                (group_id, week, user_id, clip_id, created_at))
            previous = db.execute("SELECT clip_id FROM stats_votes WHERE group_id=? AND week=? AND user_id=?",
                                  (group_id, week, user_id)).fetchone()[0]
            if previous != clip_id:
                raise VoteConflict("already voted this week")
            return cursor.rowcount == 1

    def counts(self, group_id, week):
        with self.connection() as db:
            return dict(db.execute("SELECT clip_id, COUNT(*) FROM stats_votes WHERE group_id=? AND week=? GROUP BY clip_id",
                                   (group_id, week)))
