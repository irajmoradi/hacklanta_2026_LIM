---
id: INT-02
branch: ext/INT-02
allowed_paths: [full_app/app.py, full_app/server/**, full_app/pipeline/**, full_app/services/**, full_app/render/**, full_app/perf/**, full_app/tests/**, docs/pipeline.md]
---
# INT-02: Integration pass 2: green suite + wire every new module
Everything is merged on `Extension` (EXT-01..23 + INT-01). Full suite on the runner: 597 passed, 8 failed, 2 errors:
```
FAILED tests/e2e/test_e2e_pipeline.py::test_optional_stages_chain_when_modules_land
FAILED tests/test_capture.py::test_synthetic_video_flows_through_real_api
FAILED tests/test_jobs.py::test_default_pipeline_mocked_gemini_and_real_render[square|vertical|landscape]
FAILED tests/test_perf.py::test_single_pass_streams_duration[effects3-1|effects4-2|effects5-0.25]
ERROR tests/e2e/test_e2e_pipeline.py::test_pipeline (AttributeError)
ERROR tests/e2e/test_e2e_pipeline.py::test_top_events_are_in_encoded_pixels
```
1. Fix all of them at the root (the render path changed again after INT-01; the EXT-10 perf toolkit and the EXT-16 e2e harness expect older or newer APIs).
2. Wire the newly merged modules into `full_app/pipeline/` behind flags with graceful fallback, exposed through the analyze/render options in
   docs/api.md: `profiles` (EXT-09: auto game detection + per-game OCR, alive rules and prompt fragments; Valorant, Overwatch 2, Deadlock, League),
   `audio_ai` (EXT-11 signals into fusion), `planner` (EXT-12 replaces the old plan step; keep the old one as fallback), `vjepa` (EXT-13 signal only
   when a trained head exists), `social` (EXT-14 share kit after render), `ingest` (EXT-15 proxies/chunks for long VODs + Twitch chat signal),
   `fx` (EXT-18 effects registry used by planner and renderer), `narration` (EXT-19, off by default), `privacy` (EXT-20 blur track applied in render,
   on by default for other players' names), `multipov` (EXT-21 team mode when multiple uploads share a job), `music` (EXT-22 bed when no user track),
   and apply `perf` (EXT-10: encoder auto-select, single-pass per-clip filtergraph, parallel clip renders, SFX cache) in the actual renderer.
3. The **entire** suite must be green on the runner: `tools/remote_run.sh "cd full_app && python -m pytest -q -m 'not live'"`. Report the final counts
   and an end-to-end timing for the demo video (`full_app/demo/run_demo.sh`) before vs after perf.
Update docs/pipeline.md.
