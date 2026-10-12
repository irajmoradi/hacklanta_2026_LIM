# EVAL-02 results: synthetic benchmark, mocked VLM

Rerun for FIX-3 on the Linux runner, 2026-10-12 (Python 3.12.3, Linux 6.8 x86_64).
**These numbers evaluate a designed synthetic experiment, not real gameplay or
Gemini accuracy.** No paid calls were made, and no credential file was read.

Eight original videos total 19 minutes: four training videos and four held-out
videos, 9.5 minutes per half. Each half contains Valorant (120s), OW2 (135s),
Deadlock (150s), and League (165s) style HUD/audio patterns. Each video contains
four highlights, two deaths, two spectator segments, and two distractors.
Thus the test set has 16 positives and 16 forbidden intervals. Train seeds are
731-734, test seeds 831-834; mock seed is 2026, score noise amplitude 0.30.
Splits are fixed before tuning. The four styles appear in both halves, so this
is not an unseen-game generalization test.

See [method and reproduction instructions](eval.md#eval-02-eight-video-split-benchmark),
[complete predictions and metrics](../full_app/eval/benchmark_results.json),
[manifest and labels](../full_app/eval/benchmark_manifest.json), and
[loadable tuned weights](../full_app/eval/tuned_weights.json). The manifest's
relative media paths resolve in the generated dataset, not in this repository.

## Held-out detection and ranking

Precision/recall/F1 are micro averages. mAP is the mean of ranked per-video AP,
computed over selected clips. Each threshold matches predictions one-to-one to
labels. All four pipelines completed all four held-out videos without skips.

| Pipeline | IoU | TP / FP / FN | Precision | Recall | F1 | mAP |
|---|---:|---:|---:|---:|---:|---:|
| Signals only | 0.3 | 2 / 14 / 14 | 0.1250 | 0.1250 | 0.1250 | 0.0491 |
| Signals only | 0.5 | 1 / 15 / 15 | 0.0625 | 0.0625 | 0.0625 | 0.0089 |
| VLM only, whole video | 0.3 | 16 / 12 / 0 | 0.5714 | 1.0000 | 0.7273 | 0.8110 |
| VLM only, whole video | 0.5 | 8 / 20 / 8 | 0.2857 | 0.5000 | 0.3636 | 0.2039 |
| Signals + window VLM | 0.3 | 13 / 4 / 3 | 0.7647 | 0.8125 | 0.7879 | 0.7438 |
| Signals + window VLM | 0.5 | 9 / 8 / 7 | 0.5294 | 0.5625 | 0.5455 | 0.4750 |
| Fusion + audio AI + chat | 0.3 | 13 / 4 / 3 | 0.7647 | 0.8125 | 0.7879 | 0.7271 |
| Fusion + audio AI + chat | 0.5 | 10 / 7 / 6 | 0.5882 | 0.6250 | 0.6061 | 0.4958 |

Mean mAP over the two IoUs: **0.0290 / 0.5074 / 0.6094 / 0.6115**, respectively.
The whole-video mock has the strongest mAP at 0.3, but its designed timestamp
jitter lowers its score at 0.5. Fusion's temporal boundaries come from the real
signal detector. Audio/chat improve F1 at 0.5 by 0.0606 over basic fusion in this
single split; the very small mAP gain does not establish statistical superiority.

## Forbidden picks, runtime, and illustrative cost

A forbidden pick is any selected clip with positive-duration overlap with a
death or spectator interval. It is counted once in the combined column even if
it overlaps more than one interval. Touching boundaries does not count.

| Pipeline | Death picks | Spectator picks | Combined / selected | Seconds per footage minute | Mean first clip (s) | Estimated API USD / footage minute |
|---|---:|---:|---:|---:|---:|---:|
| Signals only | 7 | 4 | 11 / 16 (68.75%) | 0.4248 | 1.0088 | 0.000000 |
| VLM only, whole video | 2 | 8 | 10 / 28 (35.71%) | 0.2853 | 0.6775 | 0.001931 |
| Signals + window VLM | 0 | 0 | 0 / 17 (0%) | 0.7100 | 1.6863 | 0.002703 |
| Fusion + audio AI + chat | 0 | 0 | 0 / 17 (0%) | 0.9580 | 2.2752 | 0.002703 |

Actual API cost is **$0 for every pipeline**. Estimated costs assume 100 input
tokens/video-second, 200 input tokens/request, 100 output tokens/request,
$0.30/million input tokens, and $2.50/million output tokens. These are hypothetical
accounting constants, not current provider prices. Whole-video uses one request;
window scoring charges every proposed window, including rejected windows. Under
this model, request overhead makes window scoring about 40% more expensive here.
Batching windows would change the estimate and was not evaluated.

Runtime includes real local video decode and relevant signal/audio/chat extraction,
plus mock scoring; reused component times are charged to each applicable pipeline.
Generation and tuning are excluded. Mock window scoring scans the full media.
These measurements say nothing about real VLM inference or upload latency and are
single-run measurements on shared hardware. The FIX-3 rerun overlapped the
offline regression suite; runtime differences do not establish a performance regression. First clip means batch completion;
all four videos returned clips for every pipeline.

## Tuned defaults

Grid search used only the four training videos. It maximized mean micro F1 at
IoU 0.3 and 0.5, breaking exact ties by grid order. Basic fusion evaluated 27
settings (training objective 0.7576); full fusion evaluated 99 (0.7419).
No weights or thresholds were changed after seeing the held-out result.

```json
{
  "signals-vlm": {
    "signals": 0.6, "vlm": 0.4, "audio": 0.0, "chat": 0.0,
    "death_penalty": 0.2, "threshold": 0.45
  },
  "fusion-audio-chat": {
    "signals": 0.2, "vlm": 0.6, "audio": 0.1, "chat": 0.1,
    "death_penalty": 0.2, "threshold": 0.55
  }
}
```

The benchmark pipeline loads this JSON with `eval.benchmark.load_weights` or
`--weights eval/tuned_weights.json`. These defaults belong to the benchmark
adapter; wiring them into the application is outside EVAL-02's allowed paths.

## Interpretation and limits

The VLM substitute reads a visible color barcode, then injects deterministic
score noise, missed death recognition, and whole-video timestamp errors. It does
not read labels, but the barcode gives it artificial semantic evidence. Real
signal extraction has OCR disabled; signals-only therefore reacts to loud deaths
and spectator combat. Its fixed normalized-confidence threshold also rejects
some positive windows that fusion retains. This baseline weakness should not be
interpreted as a general comparison of tuned real-world signal detectors.

Audio AI uses the shipped heuristic fallback, with ASR off and energy VAD. It is
not a learned speech/audio classifier benchmark. Procedural tones and synthetic
chat share the authored event schedule, with intentionally imperfect reactions.
There are only four test videos and one mock seed. Zero forbidden picks in this
run is not a guarantee: the mock deliberately misses some death state evidence.
Real captures, human labels, multiple seeds, OCR, learned audio, measured token
usage, and a real-provider evaluation remain follow-up work.

## Historical EVAL-02 validation (before later integration fixes)

- `bash tools/remote_run.sh "cd full_app && python -m eval.benchmark_data /tmp/lim-eval02-benchmark && python -m eval.benchmark /tmp/lim-eval02-benchmark/labels.json --output /tmp/lim-eval02-results"`
  exited 0: eight videos generated, weights tuned on four, all four pipelines
  evaluated on four held-out videos. Published JSON is from this run.
- First `bash tools/remote_run.sh "cd full_app && python -m pytest -q eval"`
  caught a missing closing parenthesis during collection (remote exit 2; wrapper
  exit 1). After correction the same command exited 0: **27 passed**.
- Final targeted regression: `bash tools/remote_run.sh "cd full_app && python -m pytest -q eval"`
  exited 0: **28 passed**, including a check that published metrics and forbidden
  counts recompute from the checked-in predictions and held-out labels.
- Frozen rerun: `python -m eval.benchmark /tmp/lim-eval02-benchmark/labels.json --weights eval/tuned_weights.json --output /tmp/lim-eval02-frozen`
  completed on the runner. A PowerShell JSON comparison of IDs, predictions,
  metrics, and forbidden counts against the published report exited 0: exact
  equality for all four pipelines. Runtime was excluded from equality checks.
  An initial local comparison used the wrong Git Bash temporary-directory path
  and exited 1; resolving `/tmp` with `cygpath -w` corrected that check.
- Broader offline validation was run as:
  `bash tools/remote_run.sh "cd full_app && python -m eval.benchmark /tmp/lim-eval02-benchmark/labels.json --weights eval/tuned_weights.json --output /tmp/lim-eval02-frozen && python -m pytest -q -m 'not live'"`.
  The frozen benchmark completed; pytest and the wrapper exited **1**:
  **605 passed, 14 skipped, 1 deselected, 8 failed, 2 errors** in 258.69s.
  This run preceded addition of the final saved-report regression test.
  Failures/errors are in unmodified files outside allowed paths:
  - `tests/e2e/test_e2e_pipeline.py`: two setup errors and one failed optional-stage
    test because `demo.pipeline` patches missing `app.WORKSPACE`.
  - `tests/test_capture.py::test_synthetic_video_flows_through_real_api`:
    expected one `pipeline.analyze` call, observed zero.
  - `tests/test_jobs.py::test_default_pipeline_mocked_gemini_and_real_render`:
    three parameter cases patch missing `server.pipeline.importlib`.
  - `tests/test_perf.py::test_single_pass_streams_duration`: slow-motion and speed
    2 / 0.25 cases compare baseline durations 1.979 / 0.566667 / 3.966667 seconds
    against a 1-second render, exceeding the 0.15-second tolerance.

These integration/render issues remain for their owners; no files outside
`full_app/eval/**`, `docs/eval.md`, or `docs/results.md` were changed.

Independent failure reproduction (without collecting `eval/`):
`bash tools/remote_run.sh "cd full_app && python -m pytest -q tests/e2e/test_e2e_pipeline.py tests/test_capture.py::test_synthetic_video_flows_through_real_api tests/test_jobs.py::test_default_pipeline_mocked_gemini_and_real_render tests/test_perf.py::test_single_pass_streams_duration --tb=short"`
exited 1: **19 passed, the same 8 failed and 2 errors**, in 11.61s. This confirms
the failures also occur without the new benchmark tests executing.


## FIX-3 validation and disposition (2026-10-12)

The eight-video benchmark was regenerated and rerun, including training-only tuning:

```sh
bash tools/remote_run.sh "cd full_app && python -m eval.benchmark_data /tmp/lim-fix3-benchmark && python -m eval.benchmark /tmp/lim-fix3-benchmark/labels.json --output /tmp/lim-fix3-results"
```

Exit **0**. A comparison through `tools/remote_run.sh` exited **0**, asserting exact
agreement with the previous report for all held-out predictions, metrics,
forbidden/death/spectator counts, weights and tuning results. Only timing changed;
the runtime table and published JSON now reflect this rerun. Mean mAP remains
**0.0290 / 0.5074 / 0.6094 / 0.6115**. Actual API spend was **$0**; no key file was read.
An initial Git Bash `scp` command failed with a quoting error (exit **1**); the
subsequent direct `scp.exe` artifact transfer succeeded (exit **0**).

- **P1-03 fixed:** the CLI and E2E tests share `demo.pipeline.run`, which uses
  `create_app`, the real `Pipeline`, asynchronous jobs and `JobStore`. Synthetic
  media is really rendered/downloaded. Queue/lease cleanup and default-workspace
  isolation are tested. Optional library stage guessing was replaced by the
  production pipeline's current adapters. The demo explicitly limits its claims
  to enabled stages; unrelated standalone optional libraries are not exercised.
- **P1-07 fixed:** common interval normalization accepts signal dataclasses. A
  generated-burst regression exercises nonempty real detector output. Comparative
  scoring requires explicit replay/scorer selection; the shipped local adapter
  calls the real local VLM provider and maps its typed results. A fake transport
  test still runs actual frame extraction and structured response validation.
- **P1-08 fixed:** at most three SDK generation attempts, including failures, are
  counted immediately before inference. SDK/application attempts are one, agentic
  inference is disabled, and actual source duration must fit one 600-second chunk.
  Every provider invocation closes in `finally`, clearing uploaded files. Fake-SDK
  tests cover long-source rejection, retryable failures, boundary exhaustion,
  cleanup and Vertex express construction. No paid verification was performed.
- **P2-09 / P2-11 partially fixed across repository, fixed in this scope:** oracle
  limitations are explicit, real adapter tests were added, and demo/eval docs now
  describe current persistent jobs and providers. Historical benchmark failures
  above are dated evidence, not a claim about this checkout's current status.
- **P2-10 partially fixed:** active CLI/E2E callers now share one demo adapter.
  `full_app/pipeline/demo.py` remains an older duplicate outside allowed paths;
  consolidating/removing it is left to its owner. Other audit P2/P3 items require
  changes outside this task's paths and were not modified.

Commands and observed results:

- `bash tools/remote_run.sh "cd full_app && python -m pytest -q tests/e2e --tb=short"`
  exited **0**, **20 passed** (initial 18.89s; final planner-handoff revision 24.17s).
- `bash tools/remote_run.sh "cd full_app && python -m pytest -q eval --tb=short"`
  exited **0**, **37 passed** in 13.85s.
- The default demo in the combined command below completed its 150-second source
  in 16.458s. Both real montages measured 7.221333s, at 1280x720 and 720x1280.
  Artifacts are in `/tmp/lim-fix3-demo` on the runner.
- `bash tools/remote_run.sh "bash full_app/demo/run_demo.sh --output /tmp/lim-fix3-demo && cd full_app && python -m pytest -q -m 'not live'"`
  exited **0**: **917 passed, 19 skipped, 1 deselected** in 422.40s. The final
  mock-planner prompt handoff change was independently covered by the later
  20-test E2E run above. Skipped optional/live coverage is not claimed as tested.
- `bash tools/remote_run.sh "cd full_app && python -m pytest -q eval/test_benchmark.py::test_published_report_recomputes_from_heldout_labels"`
  exited **0**, **1 passed**, verifying the refreshed benchmark artifact.
- Local `git diff --check` exited **0**. All changed files are within FIX-3's
  allowed paths. No pushes or merges were performed.

Try the repaired flow with
`bash full_app/demo/run_demo.sh --output /tmp/lim-demo --duration 28 --budget 8`,
or reproduce on Linux through `tools/remote_run.sh` as above. Inspect the two
montages and `report.json`. The real local evaluation scorer requires a configured
local VLM server; its transport was mocked for automated validation. Actual Gemini
quality, optional ML models and unrelated feature integration remain untested.
