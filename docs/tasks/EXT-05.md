---
id: EXT-05
branch: ext/EXT-05
allowed_paths: [full_app/production_frontend/**, docs/frontend.md]
---
# EXT-05: Frontend v2 (review timeline, presets, live progress)
Upgrade `full_app/production_frontend` (React + Vite + Tailwind) into a polished editor:
- Upload with drag-drop and a game/profile picker; mode (Nice hype reel / Mean roast), style, provider, toggles (signals, captions, reactions, SAM spotlight).
- **Live progress** via SSE (`/api/jobs/<id>/events`), falling back to polling.
- **Review timeline:** the source video with an interest curve and candidate/clip markers; a clip list where each clip shows thumbnail, caption, score, reaction label; keep/drop, trim handles, drag to reorder, preview playback of just that range.
- **Export presets:** landscape / vertical 9:16 / square; render; download + preview.
- Fast and clean; dark gaming theme; responsive to laptop widths; accessible controls.
Code against this API (EXT-03 implements it in parallel): POST /api/jobs, POST /api/jobs/:id/analyze, GET /api/jobs/:id, PATCH /api/jobs/:id/clips, POST /api/jobs/:id/render, GET /api/jobs/:id/download, GET /api/jobs/:id/events (SSE). Write a typed client in `src/api.ts` and a **mock mode** with fixture data so the UI runs without the backend; keep adapters for the old endpoints.
Tests: vitest component tests for the timeline and clip edits; `npm run build` must pass. Run on the runner: `tools/remote_run.sh "cd full_app/production_frontend && npm ci && npm run build && npx vitest run"`. Write docs/frontend.md.
