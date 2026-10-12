---
id: EXT-03
branch: ext/EXT-03
allowed_paths: [full_app/app.py, full_app/server/**, full_app/tests/**, full_app/requirements*.txt, full_app/README.md, docs/api.md]
---
# EXT-03: Robust backend (jobs, progress, API)
Refactor the Flask backend for reliability without breaking the current frontends:
- A **job model + queue** (threaded worker pool with a SQLite job store): upload, analyze, plan, render as resumable stages; job states persisted; idempotent restarts; cancel.
- **Live progress** via Server-Sent Events (`/api/jobs/<id>/events`), keeping the existing polling endpoints working.
- Clean API documented in docs/api.md: `POST /api/jobs` (upload), `POST /api/jobs/<id>/analyze` (options: mode nice/mean, style, provider, use_signals, captions, reactions, sam), `GET /api/jobs/<id>` (status, candidates, clips, plan), `PATCH /api/jobs/<id>/clips` (keep/drop/trim/reorder), `POST /api/jobs/<id>/render` (preset landscape/vertical/square), `GET /api/jobs/<id>/download`, `GET /api/jobs/<id>/events`.
- Pipeline hooks so other modules plug in by import when present (`signals.detect_candidates`, provider layer in `services/`, `render/`, `reactions/`, `sam/`), with feature flags and graceful fallback when a module is missing; keep the old routes as thin wrappers.
- Input validation, size limits, temp-file cleanup, structured logging.
Tests with the Flask test client and mocked analysis/render (no network): job lifecycle, SSE stream, clip edits, cancel. Update the README quick start.
