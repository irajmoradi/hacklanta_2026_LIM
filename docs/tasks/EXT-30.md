---
id: EXT-30
branch: ext/EXT-30
allowed_paths: [full_app/search/**, full_app/tests/**, docs/search.md]
---
# EXT-30: Natural-language clip search
Build `full_app/search/`: index every analyzed window (captions, labels, OCR events, transcript snippets, game, timestamps) in SQLite FTS5 plus
optional sentence embeddings (small local model, optional extra; fallback BM25 only) so users can search their library: "my Jett ace", "every time I
died to the Operator", "funny moments with Lance". Return ranked windows with thumbnails and jump links; a Flask blueprint endpoint (registered by the
integrator). Tests with synthetic indexed data (ranking sanity, filters by game/date/label). Write docs/search.md.
