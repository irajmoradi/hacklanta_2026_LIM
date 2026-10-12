---
id: EXT-26
branch: ext/EXT-26
allowed_paths: [full_app/stats/**, full_app/tests/**, docs/stats.md]
---
# EXT-26: Player stats + clip of the week
Build `full_app/stats/`: from analyzed jobs (candidates, OCR events, window scores, game profile), compute per-player stats over time: kills/deaths
per hour from the kill feed, multikill counts, best plays, most common agent/hero/champion when detectable, roast-worthy fails. A friends "clip of
the week" vote (SQLite; one vote per user per week; tie-breaks by hype score). JSON endpoints in a Flask blueprint for the frontend (registered by the
integrator). Tests with synthetic job data. Write docs/stats.md.
