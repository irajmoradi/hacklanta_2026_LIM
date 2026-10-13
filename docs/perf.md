# RENDER-FIX benchmark and integration notes

`python -m perf.bench_full` replays the saved DEMO-02 planned landscape (60 s
target) and vertical (30 s target) jobs from `/srv/demo_out/demo02/`. It enables
Full experience, disables privacy, and does not analyze or plan again. The
offline guard blocks SDK clients, Python network connections and dotenv loading;
there are zero Gemini calls and no key is read. Local narration, reaction pack,
music, captions, cards, social export and SAM fallback remain enabled. The report
includes actual durations, warnings, stage timings, input fingerprints, CPU
count, and start/end load averages.

## Measured Full-experience results

Runner 1, 12 CPU cores; identical source size/mtime, plan hashes, reaction-pack
manifest hash and options were verified. Five pre-run CPU samples were between
0% and 0.17% for every measured case. Both timing runs used unrestricted address
space; the separate 8 GiB stress regression covers isolation correctness.

| Saved job | Before wall time | After wall time | Time reduction | Before/after output duration |
| --- | ---: | ---: | ---: | ---: |
| Landscape, 60 s target | 142.993 s | 89.322 s | 37.53% | 60.608 / 60.621 s |
| Vertical, 30 s target | 101.458 s | 73.705 s | 27.35% | 31.018 / 31.021 s |

These are total `Pipeline.render` wall times, including subject tracking,
reactions, captions, music, cards, local narration and social export. Renderer
stage time alone fell from 123.089 to 68.944 s for landscape and from 91.480 to
63.224 s for vertical. SAM used the same reported fallback in both runs. This
does not measure real SAM-model inference or network narration.

The old engine executed eight/five xfades in one graph. The new engine executed
eight/five graphs with one xfade each, with **no fallback joins**. Both completed
MP4s also passed a complete FFmpeg decode, exit 0. The small output-duration
differences are under one frame; the existing card-budget excess remains an
integration issue below.

Raw evidence: [before](../demo_video/renderfix/before.json),
[after](../demo_video/renderfix/after.json), and the
[validation report](../demo_video/renderfix/README.md).
Earlier contention-affected runs are retained as `exploratory_*_before.json` and
are excluded from this table. A diagnostic updated run exposed mismatched color
tags between cards and gameplay; normalizing SDR join chunks fixed its slow
fallback before the final pair was measured.

To repeat a matched comparison, export the starting engine at
`f791dd34ef952a303a8f3613577b157e55f56233` into the allowed artifact directory:

```sh
git show f791dd34ef952a303a8f3613577b157e55f56233:full_app/render/engine.py > demo_video/renderfix/baseline_engine.py
tools/remote_run.sh "cd full_app && python -u -m perf.bench_full --output /srv/demo_out/renderfix_before_final --baseline-engine ../demo_video/renderfix/baseline_engine.py --idle-cpu-percent 15"
tools/remote_run.sh "cd full_app && python -u -m perf.bench_full --output /srv/demo_out/renderfix_after_final --idle-cpu-percent 15"
```

Use new output directories each run; the harness refuses to overwrite results.
The recorded commands above completed with exit 0, chained after the final full
test suite. The four final MP4s remain in their respective
`/srv/demo_out/renderfix_{before,after}_final/{landscape,vertical}/output.mp4`
directories on runner 1. The temporary baseline source is not committed; recreate
it with the `git show` command and remove it after benchmarking.
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

The saved jobs' current card/transition budgeting produces outputs over
their requested targets (final updated outputs are 60.621 s and 31.021 s).
The benchmark measures rendering directly, so it does not bypass or change the
API's final max-duration check. Card/plan budget correction belongs to the
pipeline owner. Optional SAM model absence remains a reported fallback.
