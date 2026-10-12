"""Small durable store; creation is a trusted Python API, never a public route."""
import json
from contextlib import contextmanager
import math
from pathlib import Path
import re
import secrets
import sqlite3
import time

EMOJIS = ("🔥", "😂", "👏", "❤️", "😮")
SHARE_ID = re.compile(r"[A-Za-z0-9_-]{43}\Z")


class ShareStore:
    def __init__(self, database):
        self.database = str(Path(database).resolve())
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS shares (
                    id TEXT PRIMARY KEY, data TEXT NOT NULL, expires_at REAL
                );
                CREATE TABLE IF NOT EXISTS reactions (
                    share_id TEXT NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
                    emoji TEXT NOT NULL, count INTEGER NOT NULL,
                    PRIMARY KEY (share_id, emoji)
                );
            """)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, *, video_path, poster_path, title, description="", chapters=(),
               width=1920, height=1080, expires_at=None):
        """Return a random 256-bit ID. Chapter starts are montage seconds.

        Assets must remain available at their resolved paths for the link lifetime.
        expires_at is an optional UTC Unix timestamp (seconds).
        """
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValueError("title must contain 1–200 characters")
        if not isinstance(description, str) or len(description) > 2000:
            raise ValueError("description must contain at most 2000 characters")
        if any(type(n) is not int or not 1 <= n <= 16384 for n in (width, height)):
            raise ValueError("width and height must be positive pixel dimensions")
        if expires_at is not None:
            expires_at = float(expires_at)
            if not math.isfinite(expires_at):
                raise ValueError("expiry must be finite")
        assets = {}
        for name, value, extensions in (
            ("video_path", video_path, {".mp4"}),
            ("poster_path", poster_path, {".jpg", ".jpeg", ".png", ".webp"}),
        ):
            path = Path(value).resolve(strict=True)
            if not path.is_file() or path.suffix.lower() not in extensions:
                raise ValueError(f"unsupported {name}")
            assets[name] = str(path)
        normalized = []
        for chapter in chapters:
            start = float(chapter["start"])
            label = chapter["title"]
            if not math.isfinite(start) or start < 0:
                raise ValueError("chapter start must be finite and nonnegative")
            if not isinstance(label, str) or not label.strip() or len(label) > 200:
                raise ValueError("chapter title must contain 1–200 characters")
            normalized.append(dict(start=start, title=label,
                                   timestamp=f"{int(start) // 60:02}:{int(start) % 60:02}"))
            if len(normalized) > 200:
                raise ValueError("at most 200 chapters are supported")
        data = dict(**assets, title=title, description=description,
                    chapters=sorted(normalized, key=lambda item: item["start"]),
                    width=width, height=height)
        share_id = secrets.token_urlsafe(32)
        with self._connect() as db:
            db.execute("INSERT INTO shares VALUES (?, ?, ?)",
                       (share_id, json.dumps(data), expires_at))
        return share_id

    def get(self, share_id):
        if not SHARE_ID.fullmatch(share_id):
            return None
        with self._connect() as db:
            row = db.execute("SELECT data FROM shares WHERE id = ? AND "
                             "(expires_at IS NULL OR expires_at > ?)",
                             (share_id, time.time())).fetchone()
        return json.loads(row[0]) if row else None

    def counts(self, share_id):
        with self._connect() as db:
            counts = dict(db.execute("SELECT emoji, count FROM reactions WHERE share_id = ?",
                                     (share_id,)))
        return {emoji: counts.get(emoji, 0) for emoji in EMOJIS}

    def react(self, share_id, emoji):
        if emoji not in EMOJIS:
            raise ValueError("unsupported emoji")
        # Lock before checking expiry so concurrent increments cannot lose updates.
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id FROM shares WHERE id = ? AND "
                             "(expires_at IS NULL OR expires_at > ?)",
                             (share_id, time.time())).fetchone()
            if row is None:
                return False
            db.execute("INSERT INTO reactions VALUES (?, ?, 1) "
                       "ON CONFLICT(share_id, emoji) DO UPDATE SET count = count + 1",
                       (share_id, emoji))
        return True
