"""SQLite FTS5 window index with optional local semantic retrieval."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

from .embeddings import normalized

log = logging.getLogger(__name__)
STOPWORDS = set("a an and are at by every for i in is it me my of on or that the time times to was with".split())


def utc_timestamp(value):
    """ISO dates and datetimes; naive inputs mean UTC."""
    if not isinstance(value, str):
        raise ValueError("Date must be an ISO date or datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc).timestamp()
    except (ValueError, OverflowError) as exc:
        raise ValueError("Date must be an ISO date or datetime") from exc


def safe_url(value):
    if not isinstance(value, str) or any(ord(c) < 32 for c in value) or "\\" in value:
        raise ValueError("Media URLs must be root-relative or HTTP(S)")
    parts = urlsplit(value)
    if not ((value.startswith("/") and not value.startswith("//")) or
            (parts.scheme in ("http", "https") and parts.netloc)):
        raise ValueError("Media URLs must be root-relative or HTTP(S)")
    return value


@dataclass
class SearchWindow:
    video_id: str
    window_id: str
    start: float
    end: float
    game: str
    recorded_at: str
    media_url: str
    caption: str = ""
    labels: list[str] = field(default_factory=list)
    ocr_events: list = field(default_factory=list)
    transcript: str = ""
    thumbnail_url: str | None = None

    def validated(self):
        for name in ("video_id", "window_id", "game"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be a nonempty string")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in (self.start, self.end)) or not 0 <= self.start < self.end:
            raise ValueError("Window timestamps must satisfy 0 <= start < end")
        for name in ("caption", "transcript"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} must be text")
        if not isinstance(self.labels, list) or any(not isinstance(v, str) or not v.strip() for v in self.labels):
            raise ValueError("labels must be a list of nonempty strings")
        if not isinstance(self.ocr_events, list):
            raise ValueError("ocr_events must be a JSON list")
        json.dumps(self.ocr_events, allow_nan=False)
        utc_timestamp(self.recorded_at)
        safe_url(self.media_url)
        if self.thumbnail_url is not None:
            safe_url(self.thumbnail_url)
        return self


class SearchIndex:
    def __init__(self, path, encoder=None):
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("Use a persistent SQLite path (connections are per operation)")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.encoder = encoder
        with self._connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS windows (
                    id INTEGER PRIMARY KEY, video_id TEXT NOT NULL, window_id TEXT NOT NULL,
                    game TEXT NOT NULL, recorded REAL NOT NULL, payload TEXT NOT NULL,
                    vector TEXT, model TEXT, UNIQUE(video_id, window_id));
                CREATE INDEX IF NOT EXISTS windows_filters ON windows(game, recorded);
                CREATE TABLE IF NOT EXISTS labels (
                    window INTEGER REFERENCES windows(id) ON DELETE CASCADE,
                    label TEXT NOT NULL, PRIMARY KEY(window, label));
                CREATE INDEX IF NOT EXISTS labels_filter ON labels(label, window);
                CREATE VIRTUAL TABLE IF NOT EXISTS window_fts USING fts5(
                    caption, labels, ocr, transcript, game,
                    tokenize='porter unicode61');
                CREATE TRIGGER IF NOT EXISTS windows_delete AFTER DELETE ON windows BEGIN
                    DELETE FROM window_fts WHERE rowid=old.id;
                END;
            """)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _encode(self, texts):
        if self.encoder is None or not texts:
            return None
        try:
            vectors = [normalized(v) for v in self.encoder.encode(texts)]
            if len(vectors) != len(texts) or len({len(v) for v in vectors}) != 1:
                raise ValueError("Encoder returned incompatible vectors")
            if not isinstance(self.encoder.model_id, str) or not self.encoder.model_id:
                raise ValueError("Encoder requires a stable model_id")
            return vectors
        except Exception:
            log.warning("Local search embeddings unavailable; using BM25")
            return None

    def index_windows(self, windows, *, replace_video=None):
        """Upsert ALL analyzed windows, or atomically replace one video's analysis.

        A failed validation leaves the previous analysis intact. An empty replacement
        removes every window for that video. Stable window IDs make retries idempotent.
        """
        windows = [w.validated() for w in windows]
        if replace_video is not None and (not isinstance(replace_video, str) or not replace_video.strip()):
            raise ValueError("replace_video must be a nonempty video ID")
        if replace_video is not None and any(w.video_id != replace_video for w in windows):
            raise ValueError("Replacement windows must belong to replace_video")
        if len({(w.video_id, w.window_id) for w in windows}) != len(windows):
            raise ValueError("Duplicate window IDs in batch")
        fields = [(w.caption, " ".join(w.labels), json.dumps(w.ocr_events, ensure_ascii=False),
                   w.transcript, w.game) for w in windows]
        vectors = self._encode(["\n".join(parts) for parts in fields])
        with self._connect() as db:
            if replace_video is not None:
                db.execute("DELETE FROM windows WHERE video_id=?", (replace_video,))
            for i, w in enumerate(windows):
                db.execute("DELETE FROM windows WHERE video_id=? AND window_id=?", (w.video_id, w.window_id))
                cursor = db.execute(
                    "INSERT INTO windows(video_id,window_id,game,recorded,payload,vector,model) VALUES(?,?,?,?,?,?,?)",
                    (w.video_id, w.window_id, w.game.casefold(), utc_timestamp(w.recorded_at),
                     json.dumps(asdict(w), allow_nan=False), json.dumps(vectors[i]) if vectors else None,
                     self.encoder.model_id if vectors else None))
                rowid = cursor.lastrowid
                db.execute("INSERT INTO window_fts(rowid,caption,labels,ocr,transcript,game) VALUES(?,?,?,?,?,?)",
                           (rowid, *fields[i]))
                db.executemany("INSERT INTO labels(window,label) VALUES(?,?)",
                               [(rowid, label) for label in sorted({v.casefold() for v in w.labels})])
        return len(windows)

    def delete_video(self, video_id):
        with self._connect() as db:
            return db.execute("DELETE FROM windows WHERE video_id=?", (video_id,)).rowcount

    def search(self, query="", *, game=None, date_from=None, date_to=None, labels=(), limit=20, offset=0):
        if not isinstance(query, str) or len(query) > 1000:
            raise ValueError("Query must be text of at most 1000 characters")
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 10000:
            raise ValueError("limit must be 1..100 and offset 0..10000")
        if isinstance(labels, str) or not isinstance(labels, (list, tuple)) or any(not isinstance(v, str) or not v.strip() for v in labels):
            raise ValueError("labels must be a list of nonempty strings")
        clauses, params = [], []
        if game is not None:
            if not isinstance(game, str) or not game.strip():
                raise ValueError("game must be nonempty text")
            clauses.append("w.game=?")
            params.append(game.casefold())
        lower = utc_timestamp(date_from) if date_from else None
        upper = utc_timestamp(date_to) if date_to else None
        # Date-only upper bounds include the entire UTC day; datetime bounds are inclusive.
        whole_day = bool(date_to and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_to))
        if lower is not None and upper is not None and (lower >= upper + 86400 if whole_day else lower > upper):
            raise ValueError("date_from must not follow date_to")
        if lower is not None:
            clauses.append("w.recorded>=?")
            params.append(lower)
        if upper is not None:
            clauses.append("w.recorded<?" if whole_day else "w.recorded<=?")
            params.append(upper + (86400 if whole_day else 0))
        for label in set(v.casefold() for v in labels):
            clauses.append("EXISTS(SELECT 1 FROM labels l WHERE l.window=w.id AND l.label=?)")
            params.append(label)
        where = " AND ".join(clauses) or "1"
        tokens = list(dict.fromkeys(t for t in re.findall(r"[^\W_]+", query.casefold()) if t not in STOPWORDS))
        match = " OR ".join('"' + t + '"' for t in tokens)
        vectors = self._encode([query]) if tokens else None
        with self._connect() as db:
            if not query.strip():
                rows = db.execute(f"SELECT w.* FROM windows w WHERE {where} ORDER BY recorded DESC,video_id,window_id LIMIT ? OFFSET ?",
                                  (*params, limit, offset)).fetchall()
                total = db.execute(f"SELECT count(*) FROM windows w WHERE {where}", params).fetchone()[0]
                return self._results(rows, {}, total, "browse")
            if not match:
                return self._results([], {}, 0, "bm25")
            lexical = db.execute(f"""SELECT w.*, bm25(window_fts,4,3,2,1,1) AS rank
                FROM window_fts JOIN windows w ON w.id=window_fts.rowid
                WHERE window_fts MATCH ? AND {where} ORDER BY rank,video_id,window_id""", (match, *params)).fetchall()
            scores = {r["id"]: -r["rank"] for r in lexical}
            rows = {r["id"]: r for r in lexical}
            semantic = []
            if vectors:
                candidates = db.execute(f"SELECT w.* FROM windows w WHERE {where} AND model=? AND vector IS NOT NULL",
                                        (*params, self.encoder.model_id)).fetchall()
                for row in candidates:
                    vector = json.loads(row["vector"])
                    if len(vector) == len(vectors[0]):
                        similarity = sum(a*b for a, b in zip(vectors[0], vector))
                        if similarity >= 0.25:
                            semantic.append((similarity, row))
                semantic.sort(key=lambda pair: (-pair[0], pair[1]["video_id"], pair[1]["window_id"]))
            if semantic:
                # Reciprocal rank fusion avoids comparing BM25 and cosine scales.
                scores = {r["id"]: 1/(60+i) for i, r in enumerate(lexical, 1)}
                for i, (_, row) in enumerate(semantic, 1):
                    rows[row["id"]] = row
                    scores[row["id"]] = scores.get(row["id"], 0) + 1/(60+i)
            ordered = sorted(rows.values(), key=lambda r: (-scores[r["id"]], r["video_id"], r["window_id"]))
            return self._results(ordered[offset:offset+limit], scores, len(rows), "hybrid" if semantic else "bm25")

    @staticmethod
    def _results(rows, scores, total, mode):
        results = []
        for row in rows:
            window = json.loads(row["payload"])
            window["jump_url"] = window["media_url"].split("#", 1)[0] + f'#t={window["start"]:g},{window["end"]:g}'
            window["score"] = scores.get(row["id"], 0.0)
            results.append(window)
        return {"results": results, "total": total, "mode": mode}
