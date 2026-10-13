# RENDER-FIX validation report

Branch: `ext/RENDER-FIX`. Starting revision:
`f791dd34ef952a303a8f3613577b157e55f56233`.

Implementation milestones:

- `40fe94f`: bound transition memory, move text after temporal effects, share
  caption/video encoding, isolate segments and cache builds.
- `29ef389`: short boundary-window joins, prepared parallel processors and graph
  composition, safe render error transport, benchmark harness and documentation.

Changed implementation files: `full_app/render/{engine,contracts,placements}.py`,
`full_app/services/ffmpeg_runner.py`, and `full_app/perf/{cache,media,bench_full}.py`.
Tests: `full_app/tests/test_render_fix.py` and `test_perf_render_fix.py`.
Documentation: `docs/rendering.md`, `docs/perf.md`, and this artifact directory.
No videos, keys, model weights or environment files are committed. No pushes or
merges were performed. No Gemini/live API calls were made.

## Linux validation

Full suite (implementation at `29ef389`):

```sh
tools/remote_run.sh "cd full_app && OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m pytest -q"
```

Result: **1,270 passed, 20 skipped in 586.61 s**, pytest exit **0**. This command
ran as the first command in the final `&&` chain before the two benchmarks.

Expanded focused suite, including the subsequently added 60-second stress case:

```sh
tools/remote_run.sh "cd full_app && OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m pytest -q tests/test_render_fix.py tests/test_perf_render_fix.py tests/test_render_v2.py tests/test_perf.py"
```

Result: **60 passed in 92.81 s**, remote exit **0**. Both six-segment/card cases
(6.3 s and 60.3 s final timelines) run at 1920x1080 with inherited 8 GiB address
space and 4 GiB file limits. Tests also decode pixels to confirm that RIP, BRUH
and SKILL ISSUE text appears and expires during a freeze, validate caption pass
consolidation and processor concurrency, and exercise actual worker error JSON.

The earlier full-suite run was deliberately interrupted after a newer committed
run superseded it: 691 passed, 9 skipped, remote exit **2** (KeyboardInterrupt).
It is not counted as a completed suite. Earlier focused milestones passed
(57, 57 and 59 tests); final focused coverage is the 60-test result above.

## Try it and remaining integration

Normal render-v2 calls use the bounded join and overlay ordering automatically.
Run the focused command above to exercise everything with synthetic media. The
saved-demo benchmark commands and comparison methodology are in `docs/perf.md`.

The pipeline's stateful reaction/SAM callback still needs adaptation to
`prepare`/`compose` for concurrent reaction post-processing and reaction graph
fusion. Existing callbacks preserve deterministic order; their base segment
renders now run concurrently. Narration remains a separate pipeline-owned pass.
Optional SAM absence produces a documented fallback. The saved plans' card
budgeting still exceeds the 60/30-second requested maxima slightly, so the
pipeline owner must correct that before these exact jobs pass the API duration
guard. No changes outside the task's allowed paths were made.
