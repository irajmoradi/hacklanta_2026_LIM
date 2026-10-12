# DOC-01 verification record

Snapshot: `ext/DOC-01`, 2026-10-12. Changes are restricted to README, architecture, quickstart and documentation verification assets. No application code, dependencies, task records or other sprint documents were changed. No credential file was read and no paid call was made.

## Commands actually run

All Python/Node checks below ran on the Linux runner via the repository script, from the worktree root.

| Command | Result | Exit |
| --- | --- | --- |
| `bash tools/remote_run.sh "cd full_app && python -m pytest -q -m 'not live'"` | 597 passed, 14 skipped, 1 deselected, 8 failed, 2 errors; 289.52 seconds | 1 |
| `bash tools/remote_run.sh "python -m pytest -q docs/README_ASSETS/test_documentation.py && cd full_app/production_frontend && npm ci && npm test && npm run build"` | Documentation: 16 passed; frontend: 14 passed in 3 files; TypeScript/Vite production build succeeded | 0 |
| `bash tools/remote_run.sh "python -m pytest -q docs/README_ASSETS/test_documentation.py"` (final documentation) | 16 passed in 7.03 seconds | 0 |
| `git diff --check` (local) | No whitespace errors | 0 |

The documentation tests check relative links, inventory every literal Python environment read and every accepted HTTP option, run all 12 argparse entry points with `--help`, and compare their switches to the quickstart table. The final test executes the two published Bash render-check blocks verbatim except for substituting an ephemeral loopback server port. It uses real Flask/SQLite/FFmpeg, asserts no provider can be constructed/called, and verifies the downloaded H.264/AAC video is 1280×720. All media is synthetic and generated in temporary directories.

## Existing failures outside DOC-01 allowed paths

| Tests | Finding |
| --- | --- |
| `tests/e2e/test_e2e_pipeline.py::test_pipeline`, `::test_top_events_are_in_encoded_pixels` (2 setup errors), `::test_optional_stages_chain_when_modules_land` (1 failure) | Demo harness patches removed `app.WORKSPACE` |
| `tests/test_capture.py::test_synthetic_video_flows_through_real_api` (1 failure) | Mock expects `pipeline.analyze` once but sees zero calls; queue dispatch uses the mock's `run_stage` surface |
| `tests/test_jobs.py::test_default_pipeline_mocked_gemini_and_real_render` (3 presets) | Tests patch `server.pipeline.importlib`, absent from the compatibility import module |
| `tests/test_perf.py::test_single_pass_streams_duration` (slow_motion, speed 2, speed .25) | Standalone perf helper duration differs from updated legacy renderer: about 1.979/0.567/3.967 seconds versus 1 second |

These results are not a green-suite claim. The documented no-key app render works independently of the broken demo. Fixing the harnesses and reconciling performance timing belong to integration tasks, outside the documentation allowlist.

## Choices and remaining validation

- Code is authoritative where old sprint docs conflict. In particular: signals/window scoring default on; new job rendering uses v2; `ENABLE_RENDER_HOOK` is obsolete; the automatic planner remains legacy Gemini.
- The diagram explicitly marks standalone library/integration edges. Planner v2 and render v2 schemas differ; privacy, narration, audio AI/chat/V-JEPA fusion and automatic share-kit export are not advertised as wired UI features.
- Every environment name and CLI switch was checked against source; arbitrary SDK variables and every third-party library parameter are not repository configuration flags.
- Docker/Compose commands were checked against Dockerfile/Compose configuration. No Docker image build or container startup was performed in DOC-01. Optional packages, pretrained model inference, desktop OBS/hotkeys, Discord delivery and hosted provider availability were not exercised.
- No current pricing or blanket license claims are made. Costs are described by request/compute sources; model terms depend on exact weights. Bundled meme SFX remain third-party assets, and no top-level project LICENSE exists in this snapshot.
- User-required current-branch commits were used; no branch switch, push or merge was performed.
