# RENDER-FIX benchmark and integration notes

`python -m perf.bench_full` replays the saved DEMO-02 planned landscape (60 s
target) and vertical (30 s target) jobs from `/srv/demo_out/demo02/`. It enables
Full experience, disables privacy, and does not analyze or plan again. The
offline guard blocks SDK clients, Python network connections and dotenv loading;
there are zero Gemini calls and no key is read. Local narration, reaction pack,
music, captions, cards, social export and SAM fallback remain enabled. The report
includes actual durations, warnings, stage timings, input fingerprints, CPU
count, and start/end load averages.

To repeat a matched comparison, export the starting engine at
`f791dd34ef952a303a8f3613577b157e55f56233` into the allowed artifact directory:

```sh
git show f791dd34ef952a303a8f3613577b157e55f56233:full_app/render/engine.py > demo_video/renderfix/baseline_engine.py
tools/remote_run.sh "cd full_app && python -u -m perf.bench_full --output /srv/demo_out/renderfix_before --baseline-engine ../demo_video/renderfix/baseline_engine.py --idle-cpu-percent 15"
tools/remote_run.sh "cd full_app && python -u -m perf.bench_full --output /srv/demo_out/renderfix_after --idle-cpu-percent 15"
```

Use new output directories each run; the harness refuses to overwrite results.
The optional `--memory-gib 8` applies the production address-space limit to the
benchmark and its children. `--idle-cpu-percent` requires five consecutive CPU
samples below the threshold before each format, and fails after 900 seconds if
the runner does not settle. Historical load averages can stay high after a busy
render; current CPU samples are recorded separately. This is a single matched
pair, not a statistical performance guarantee. The frozen baseline engine runs
against the same current dependencies and pipeline so unrelated sprint changes
do not enter the comparison.

## Work owned by other paths

The current `pipeline/rendering.py` reaction callback still owns a mutable
`ReactionSelector` and shared stage metadata. Base segment rendering now overlaps
even with that callback, but callback execution stays ordered. The pipeline
owner should select reactions in `prepare`, return isolated workers, and
eventually expose reaction graphs via `compose`; see `docs/rendering.md`.
This preserves speaker rotation and deterministic seeds without unsafe closure
copies or concurrent selector mutation. Existing reaction/SAM/narration passes
are not falsely reported as fused.

The saved jobs' current card/transition budgeting produces outputs slightly over
their requested targets (the exploratory baseline yielded 60.608 s and 31.018 s).
The benchmark measures rendering directly, so it does not bypass or change the
API's final max-duration check. Card/plan budget correction belongs to the
pipeline owner. Optional SAM model absence remains a reported fallback.
