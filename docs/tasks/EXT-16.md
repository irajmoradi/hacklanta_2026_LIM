---
id: EXT-16
branch: ext/EXT-16
allowed_paths: [full_app/tests/e2e/**, full_app/demo/**, docs/e2e.md]
---
# EXT-16: End-to-end harness and demo generator
Build an end-to-end test + demo path that exercises the **whole** pipeline as modules land (import each module if present; skip with a clear
message if not yet merged):
- `full_app/demo/make_demo_gameplay.py`: generates a synthetic but convincing 2-3 minute "gameplay" video with ffmpeg (moving crosshair, HUD
  boxes, kill-feed text pops like "Player ELIMINATED Enemy", "ACE", "PENTAKILL", death banners "KILLED BY", gunfire-like audio bursts,
  a synthetic voice-like tone track) and a ground-truth JSON of its events. No copyrighted assets.
- `full_app/tests/e2e/test_e2e_pipeline.py`: upload → (ingest) → signals → (audio_ai) → mocked VLM window scoring → planner → render (landscape and
  vertical) → (reactions with the synthetic pack) → (social share kit) → download; asserts the output video exists, duration within budget,
  contains the top ground-truth events, and every stage reported progress. Mark slow tests; total under 5 minutes on the runner.
- `full_app/demo/run_demo.sh`: one command that produces `demo_out/` with the montage and a JSON report (stage timings, chosen clips vs ground truth).
Write docs/e2e.md. Coordinate by reading the task specs in docs/tasks/ for module APIs; adapt with thin shims inside your own paths when APIs differ.
