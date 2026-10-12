# Offline end-to-end demo

Run from the repository root with the app requirements, FFmpeg and ffprobe installed:

```bash
bash full_app/demo/run_demo.sh --output /tmp/lim-demo
# Short fixture:
bash full_app/demo/run_demo.sh --output /tmp/lim-demo-short --duration 28 --budget 8
```

The default generates 150 seconds of original 640x360, 15 FPS arena footage with
moving targets, HUD text, colored event bars and procedural audio. No downloaded
media, credentials or model weights are needed. The harness blocks dotenv loading,
SDK construction and Python networking. There is no live mode.

`demo.pipeline.run` is the shared CLI/E2E entry point. It constructs
`server.api.create_app(config, pipeline=...)` with an isolated output workspace,
uses `app.extensions['job_store']`, and closes the queue in `finally`, including
failed runs. It never imports the side-effectful `app` module or opens the default
workspace. The older `pipeline/demo.py` adapter is outside FIX-3's allowed paths;
the CLI and E2E tests now both use `demo/pipeline.py`.

The flow uploads through `POST /api/jobs`, submits asynchronous analysis/planning,
polls public job snapshots for durable completion, renders landscape and vertical
presets, and downloads both results through the jobs API. Signal extraction,
ranking, validation, SQLite persistence, video/audio encoding and downloads are
real. A provider injected on the real `Pipeline` supplies deterministic clip and
plan responses. Thumbnail generation is disabled.

The mock provider reads fixture truth and selects up to three complete beats
within the duration budget. This is an **oracle integration test, not a perception
benchmark**. Signal candidates are recorded but their recall does not determine
oracle coverage. The demo does not exercise standalone ingest, audio AI, creative
planner, reactions or social libraries. It does not claim coverage of their
integration or of the SSE transport. No signature-based optional stage dispatch
is used by the active demo.

Outputs are `montage_landscape.mp4`, `montage_vertical.mp4`, the fixture video and
labels under `fixture/`, durable SQLite jobs/media under `jobs/`, and `report.json`.
The report records backend stage timings, candidates, clips, plan, source-event
coverage, output timestamps, dimensions and duration. Failures also write a report.
Generated media must remain outside git. Reusing an output directory overwrites
named demo artifacts and retains earlier jobs.

Tests decode every montage frame, verify audio/video streams and aspect ratios,
check exact download bytes, and sample the expected event colors at their planned
output times. Additional checks verify workspace isolation and lease release after
success and failure. Timing checks assume clean cuts without cards/transitions.

```bash
bash tools/remote_run.sh "cd full_app && python -m pytest -q tests/e2e"
bash tools/remote_run.sh "bash full_app/demo/run_demo.sh --output /tmp/lim-fix3-demo"
```

FIX-3 targeted validation: **20 passed**, remote exit **0** (2026-10-12).
Full-suite and benchmark evidence is recorded in [results.md](results.md).
Final combined default-demo/full-suite run exited **0**: **917 passed, 19 skipped,
1 deselected** in 422.40s. The default demo produced 7.221333-second montages at
1280x720 and 720x1280. The final prompt-handoff revision also passed all 20 E2E
tests independently (24.17s, exit **0**).
