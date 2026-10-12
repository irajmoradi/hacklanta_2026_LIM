---
id: FIX-4
branch: ext/FIX-4
allowed_paths: [full_app/**, docs/**]
---
# FIX-4: Make the pipeline work on real footage (issues found by the Valorant demo)

The DEMO-01 run on a real 31-minute Valorant VOD (`docs/demo.md`, "Demo-only adapters and discovered issues") found bugs the mocked tests miss.
The demo worked around them in `demo_video/live_smoke_server.py`; fix them **in core** so the stock app works end to end on real footage:
1. **Game detection / generic profile:** `profiles.detect_game` returned `('generic', 0.0)` on real Valorant footage and `signals.ocr.regions_for('generic')`
   raised `unknown game profile: generic`. Add a safe generic mapping everywhere, and make detection work on real HUDs (sample more frames across
   the match, use HUD-layout cues + OCR keywords per profile, optional cheap VLM check of 2-3 frames when enabled; report confidence).
2. **Frontend capability contract:** `/api/info` must advertise `frontend_capabilities` for every available backend module, and option names must
   match between UI and API (`planner_v2`/`planner`, `privacy_blur`/`privacy`, `share_kit`/`social`, game selection enabling profiles). Fix both sides
   (`full_app/production_frontend/src/api.ts` and the server) and test the contract.
3. **Review/share payloads:** status should include a real dense `interest_curve` (from the fused signal curve, normalized 0-100) and `share_kit` as a
   structured object (metadata, chapters, covers, downloads), matching the UI types.
4. **Privacy cost:** do not sanitize the whole source before editing. Apply privacy blur only to the selected ranges at render time (cache per range),
   restricted to profile HUD regions (kill feed, chat, party/voice) by default; make the expensive name-detection opt-in.
5. **Mode change:** switching nice/mean should not discard analysis; reuse candidates/scores and re-run only planning (no new paid calls).
6. **Gemini schema:** build response schemas the google-genai SDK accepts (no `exclusiveMinimum`; use inclusive bounds) while keeping strict Pydantic
   validation of responses; surface actionable error messages instead of `Video analysis failed`.
7. **Out-of-range timestamps:** clamp or drop model ranges outside [0, duration] (log them) instead of failing the job; never let one bad item fail analysis.
8. **Live-call budget:** the hard 3-call budget (FIX-3) must be a test-only default; production default configurable (e.g. `MAX_GEMINI_CALLS_PER_JOB=80`)
   and enforced per job, with the window-scoring stage scoring the top-N candidates within budget (parallel, rate-limited).
Add regression tests for each (use saved fixtures from the demo's shapes; no real footage committed). Full suite must stay green on the runner.
Then do a **real smoke run** on the runner with the stock API (no demo adapters) on the first 6 minutes of `/srv/demo_in/valorant_phoenix_44k.mp4`
(ffmpeg trim to a temp file), Gemini via `GOOGLE_API_KEY` from /c/Users/mourn/Downloads/hacklanta/.env with Vertex express, env-only, max 30 calls;
report results. Update docs/pipeline.md and docs/demo.md (mark which demo adapters are now unnecessary).
