# Natural-language clip library search (EXT-30)

`full_app/search/` is a standalone SQLite FTS5 index and read-only Flask blueprint.
Default operation uses no model, paid API, network, or new dependencies. SQLite
must have FTS5 enabled (the Linux test runner does). The existing upload → analyze
→ plan → render pipeline is unchanged. Register the blueprint and ingestion hook
in the integrator's task; EXT-30's allowed paths exclude the server and pipeline.

## Quick start / integrator contract

Run from `full_app/`, or put that directory on `PYTHONPATH`:

```python
from pathlib import Path
from flask import Flask
from search import SearchIndex, SearchWindow, create_blueprint

app = Flask(__name__)  # In production, use the existing server application.
index = SearchIndex(Path("workspace") / "search.sqlite3")
app.register_blueprint(create_blueprint(index))

index.index_windows([
    SearchWindow(
        video_id="example", window_id="10.5-20", start=10.5, end=20,
        game="Valorant", recorded_at="2026-10-10T14:00:00Z",
        caption="Jett ace wins the round", labels=["highlight", "ace"],
        ocr_events=[{"text": "ACE", "time": 18}],
        transcript="Lance: that was unbelievable!",
        media_url="/api/stream/example",
        thumbnail_url="/thumbnails/example/10.5.jpg",
    ),
], replace_video="example")

print(index.search("my Jett ace"))
app.run(port=8001)
```

Try `GET http://localhost:8001/api/search?q=my%20Jett%20ace`. The synthetic example
is searchable immediately; its example media URLs require actual hosted assets
to display/play. In the real application, `/api/stream/<job_id>` already serves
the source video with range requests. Use that source URL, not the rendered
montage: timestamps refer to the original recording.

After analysis, pass **every analyzed window**, including neutral and lowlight
windows, not just selected montage clips. `job['window_scores']` contains the
scored windows; where scores are missing, retain the candidate windows too.
Map each window's `start`, `end`, `caption`, `events` → `ocr_events`, and
`kind`/`reaction` → `labels`. Join transcript snippets whose times overlap the
window. Supply game and recording date from the library's video metadata (use the
upload date when the recording date is unknown, consistently). Use a stable
`window_id`, e.g. the source start/end pair, and `video_id=job['id']`.

`index_windows(windows, replace_video=job_id)` atomically replaces a complete
analysis, removing stale windows, FTS entries, labels, and vectors. Invalid
batches leave the previous analysis intact. Without `replace_video`, batches
upsert by `(video_id, window_id)` and preserve other windows. Duplicate identities
in one batch are rejected. `index_windows([], replace_video=job_id)` clears the
analysis; `delete_video(job_id)` removes it on library deletion and returns the
number of deleted windows. Reindex existing analyses to backfill a library.

Generate/cache thumbnails in the media pipeline and supply their served URLs.
Search does not open arbitrary filesystem paths or generate thumbnails during a
request. `thumbnail_url` is nullable when unavailable; the UI should display a
placeholder. Root-relative and HTTP(S) media/thumbnail URLs are accepted; script,
protocol-relative, backslash, and control-character URLs are rejected. Every
result includes `jump_url`, an HTML media fragment such as
`/api/stream/example#t=10.5,20`, plus numeric `start` and `end` for a custom player's
seek action. No thumbnail-serving route is introduced by this task.

Keep the database in the ignored workspace directory. Indexes contain transcripts
and other potentially private recording text. The blueprint assumes the existing
single-user library; mount it behind the same access controls as the media library.
There is no tenant isolation inside this index. Do not mount one shared instance
as an unauthenticated multi-user search service.

## HTTP and Python search contract

`GET /api/search` accepts:

| Parameter | Meaning |
| --- | --- |
| `q` | Natural-language text, at most 1,000 characters. Empty text browses newest first. |
| `game` | Exact case-insensitive game identifier/name. |
| `date_from` | Inclusive ISO date or datetime. |
| `date_to` | Inclusive ISO date or datetime; a date includes the entire UTC day. |
| `label` | Exact case-insensitive label; repeat to require **all** supplied labels. |
| `limit` | Integer 1–100, default 20. |
| `offset` | Integer 0–10,000, default 0. |

All filters are ANDed and apply to lexical and semantic retrieval. Datetime offsets
are normalized to UTC; timezone-free datetimes mean UTC. Dates are recording/upload
dates, not relative clip seconds. The Python equivalent is
`index.search(q, game=..., date_from=..., date_to=..., labels=[...], limit=..., offset=...)`.

Successful responses contain `results`, `total` (before pagination), and `mode`
(`bm25`, `hybrid`, or `browse`). Each result contains the complete `SearchWindow`
record plus `score` and `jump_url`. Higher scores rank first; scores are not
probabilities and must not be compared across queries or ranking modes. Ties
break by video/window ID. Invalid queries/filters return HTTP 400 with `error`;
no matches return HTTP 200 with an empty list. No HTTP indexing/deletion API is
exposed. Blank queries browse; punctuation-only and stopword-only queries return
no matches. Pagination is deterministic for an unchanged index.

## Ranking and optional embeddings

FTS5 uses Unicode tokenization with English Porter stemming. Natural-language
filler words are removed and remaining tokens are ORed, so partial matches remain
visible. User text is never interpreted as FTS operators or raw SQL. BM25 weights
caption/labels/OCR/transcript/game at 4/3/2/1/1. Structured OCR JSON is retained
and searchable, including its text values. Example queries include `my Jett ace`,
`every time I died to the Operator`, and `funny moments with Lance`. BM25 cannot
infer unnamed people, events, synonyms, negation, or facts absent from metadata.

For optional local semantics, explicitly install:

```sh
python -m pip install -r search/requirements-embeddings.txt
```

Provision a small Sentence Transformers model separately, then enable it:

```python
from search.embeddings import LocalSentenceEncoder
index = SearchIndex("workspace/search.sqlite3",
                    encoder=LocalSentenceEncoder("/models/all-MiniLM-L6-v2-pinned"))
```

The default encoder identifier is `sentence-transformers/all-MiniLM-L6-v2`.
Models load lazily on CPU with `local_files_only=True`; search never downloads
weights. The extra may install large ML dependencies and is intentionally absent
from core requirements. Missing dependencies/weights, invalid vectors, or encoder
exceptions log a generic warning and preserve BM25 indexing/search. No text or
exception contents are logged. Tests use a deterministic fake encoder.

Normalized vectors and model identity persist in SQLite. Reindex all windows
after enabling embeddings or changing model weights; change the model identifier
when weights change. Old/different-model vectors are ignored. Semantic retrieval
scans the filtered vectors with compatible dimensions, accepts cosine similarity
at least 0.25, then combines semantic and BM25 ranks using reciprocal rank fusion
with constant 60. Missing vectors remain lexically searchable. Empty queries do
not invoke the encoder. This is a small-library implementation: semantic scans
and lexical result sorting are linear in candidate count and pagination does not
cap that work. Large libraries need a vector index and bounded candidate retrieval.

## Validation

From the worktree root:

```sh
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_search.py"
```

Synthetic tests cover ranking for the three example queries; caption, labels,
OCR, transcript and game retrieval; game/date/label intersections; UTC boundaries;
pagination and media links; safe handling of FTS punctuation; idempotent updates;
atomic replacement, deletion and persistence; concurrent reads; Flask validation;
optional semantic ranking, model identity, and failure fallback. No API keys,
Gemini calls, model downloads, or copyrighted media are needed.
