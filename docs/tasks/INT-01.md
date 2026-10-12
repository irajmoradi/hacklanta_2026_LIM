---
id: INT-01
branch: ext/INT-01
allowed_paths: [full_app/app.py, full_app/server/**, full_app/pipeline/**, full_app/services/**, full_app/render/**, full_app/eval/**, full_app/tests/**, docs/pipeline.md]
---
# INT-01: Integrate the Extension modules into one working pipeline
Merged on `Extension`: EXT-01 `signals/`, EXT-02 provider layer + window scoring in `services/`, EXT-03 job queue/SSE API in `server/` + `app.py`,
EXT-04 `render/` v2, EXT-05 new frontend, EXT-06 `reactions/`, EXT-07 `sam/`, EXT-08 `eval/` + Docker/CI. Full suite on the runner:
160 passed, 4 failed: `eval/test_app_smoke.py::test_app_pipeline` (expects `app.WORKSPACE`, refactored by EXT-03) and
`tests/test_jobs.py::test_default_pipeline_mocked_gemini_and_real_render[square|vertical|landscape]`.
1. Fix those 4 failures at the root (update tests or code, whichever is correct; keep legacy routes working).
2. Build `full_app/pipeline/` as the single orchestrator the job queue calls, with feature flags and graceful fallback when a module is missing:
   ingest/probe → **signals** candidates (EXT-01) → **VLM window scoring** of candidates (EXT-02, REZE-style) fused with signal scores (Gemini can
   veto spectating) → plus the old whole-video Gemini pass as an extra candidate source → rank/merge → edit plan (keep the existing planner now;
   leave a clear hook `plan_edit(...)` for the upcoming EXT-12 planner) → **render v2** (EXT-04 presets, reframe using `sam.subject_track` when
   enabled, captions when enabled) → **reactions** overlays (EXT-06) when a pack is configured → **SAM spotlight** on top clips when enabled.
   Stage progress events feed the SSE stream. Per-stage timings logged.
3. Make the analyze/render options from docs/api.md map onto these flags; defaults: signals on, window scoring on, captions off, reactions on if a
   pack exists, SAM spotlight off, preset landscape.
4. Tests: the full mocked pipeline on a synthetic video for landscape and vertical, with and without each optional module; the 4 previous failures fixed.
   Run the **entire** suite on the runner (`tools/remote_run.sh "cd full_app && python -m pytest -q -m 'not live'"`); it must be green.
Write docs/pipeline.md (stage diagram, flags, fallbacks).
