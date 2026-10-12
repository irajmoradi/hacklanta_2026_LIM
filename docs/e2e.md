# Offline end-to-end demo (EXT-16)

From the repository root, with the application requirements installed and `python`,
FFmpeg and ffprobe on PATH (FFmpeg needs libx264, AAC and drawtext):

```bash
bash full_app/demo/run_demo.sh --output full_app/demo/demo_out
```

The default generates **150 seconds** of original 640x360, 15 fps training-arena
footage: moving targets/crosshair, HUD boxes, health/ammo, elimination feed, ACE,
PENTAKILL, KILLED BY banners, gunfire-like bursts and harmonic voice-like tones.
There are no downloaded assets, intelligible speech, real faces, or copyrighted
sound effects. A generated colored face with an animated mouth and a beep supplies
the synthetic reaction pack. The demo does not load `.env`, use a key, or need an account.
It blocks SDK client creation and Python socket connections; optional modules
must also run locally without spawning network/download tools.

For a quick run use `--duration 28 --budget 8`. Duration may be 14–180 seconds;
the normal presentation fixture should use 120–180. Budget defaults to 12 seconds.
The output directory is relative to the invoking working directory (default
`demo_out/`). Prefer the explicit ignored path above; never commit generated media.
Paths containing spaces work. A run reuses its output directory and overwrites
named demo artifacts; old job subdirectories are retained.

Outputs:

- `montage_landscape.mp4` and `montage_vertical.mp4`, downloaded through Flask.
- `fixture/gameplay.mp4` and `fixture/ground_truth.json`, with event intervals,
  labels, priorities and the two expected top events.
- `synthetic_pack/pack.json` and `beep.mp4` (generated, not committed).
- `report.json`: stage start/terminal progress, stage timings, skip reasons,
  scored candidates, chosen source intervals vs ground truth, output timestamps,
  stream dimensions/durations and share-kit paths when available. Failure also
  writes a report before exiting nonzero.
- `jobs/`: actual upload, stage logs, intermediate clips and rendered outputs.

Generate just the fixture, without importing Flask:

```bash
cd full_app
python -m demo.make_demo_gameplay --output demo/demo_out/fixture --duration 150
```

## Pipeline and integration boundaries

The harness calls the real legacy-compatible Flask routes: `/api/upload`,
`/api/analyze`, `/api/plan`, `/api/render` and `/api/download/<id>`. The current
backend is imported with Gemini construction patched out, its job store and
workspace isolated, and its model getter replaced with a deterministic mock.
Analysis and planning HTTP responses, file probing, clipping, encoding, audio,
concatenation and download bytes are exercised. Generated thumbnails are disabled
to avoid image-model calls. No bundled meme SFX are selected.

`demo/pipeline.py` supplies thin adapters for the sprint APIs read from the task
records. Missing modules are **skipped individually**, leaving the baseline
pipeline running. Each skip identifies the module/reason in the report and on
stdout. A present module with no recognized export or incompatible required
parameters is reported as **adapter needed**. Errors *inside* a callable or missing
transitive dependencies fail the run; these are not hidden as absent modules.

| Stage | Recognized exports / supplied inputs | Absent-module behavior |
| --- | --- | --- |
| Ingest | `ingest.prepare(source)`; `path` from dict/dataclass/Pydantic result | Uploaded source |
| Signals | `signals.detect_candidates(video_path, profile='auto')` | Six-second windows every three seconds |
| Audio | `audio_ai.analyze(video_path)`; disables `use_whisper`, `use_classifier`, `transcribe` when accepted | No audio intelligence; source audio still rendered |
| VLM | Ground-truth window-scoring mock injected through existing `GeminiVideoClient` boundary | Always mocked; zero paid calls |
| Planner | `planner.plan_edit`, `build_plan` or `plan`; clips/ranked_clips, mode, style, duration aliases, aspect, audio_signals, use_llm/refine false | Deterministic top-three clean plan through mocked legacy planning response |
| Renderer | `render.render_plan` or `render`; source/video_path, plan, preset, output_path, workspace; returns path | Real `FFmpegRunner`, landscape 640x360 / vertical 360x640 letterbox |
| Reactions | `reactions.render_overlay(base_clip, reaction, preset)`; synthetic manifest entry with absolute file path | No overlay |
| Social | `social.build_share_kit(job_dir, clips, plan, game)`; montage.mp4 present in job_dir | No share kit |

Only explicitly accepted keyword parameters are passed. New public APIs with
different model inputs or names need a small explicit adapter in this file;
the harness does not guess arbitrary signatures. The compatibility routes and
legacy `jobs` dictionary are currently required; if EXT-03 removes those internals,
adapt the upload/job lookup in this harness to its new job store. It does not yet
test the future SSE transport. Harness progress covers every attempted stage,
including skips, rather than pretending the legacy backend emits SSE.

V2 `clips[].start/end` and `source_start/source_end` can be translated into legacy
segments. If the v2 renderer is absent, only interval/speed information survives
this shim; v2 effects, transitions, captions and reaction slots need the v2 renderer.
The reaction API is exercised once per montage using the synthetic pack entry.
Audio intelligence is included in the report and passed to planners that accept
`audio_signals`; optional internal audio fusion remains the signals module's job.

Mock scoring uses ground truth **only for candidates containing a complete event**;
it never fabricates a candidate when the real signals module misses an event.
This makes missed ACE/PENTAKILL events fail coverage. The mock is an oracle for
integration testing, **not evidence of VLM or detection accuracy**. Ground-truth
coverage is computed from the final plan's source intervals, independently of
model-supplied labels. Tests additionally decode event-colored pixel bars from
both actual outputs, check audio/video streams and aspect ratios,
decode all output frames, and verify exact download bytes. Current clean-plan
timing assertions assume no v2 intro/outro or transition duration changes; such
features require updating the output timeline adapter.

## Linux tests

From the worktree root:

```bash
tools/remote_run.sh "cd full_app && python -m pytest tests/e2e -q -ra"
tools/remote_run.sh "bash full_app/demo/run_demo.sh --output full_app/demo/demo_out"
```

The `slow` marker is registered in the scoped E2E conftest. To omit media tests,
add `-m 'not slow'`; the normal suite shares a 28-second generated source across
both preset checks and targets less than five minutes total. All files are
generated in pytest temporary directories, and networking is prohibited in every
test. Unit checks also cover future module dispatch, unavailable APIs, error
propagation, invalid fixture durations, coverage, budget enforcement and SDK blocking.
Do not use this harness as a live smoke test; there is no live mode.

Validated on the Linux runner on 2026-10-12:

- `tools/remote_run.sh "cd full_app && python -m pytest tests/e2e -q -ra"`:
  **19 passed in 13.59s**, remote exit **0**.
- `tools/remote_run.sh "bash full_app/demo/run_demo.sh --output full_app/demo/demo_out"`:
  default **150-second** input, both montage downloads produced, remote exit **0**.
- Final visual-check run of the same demo followed by
  `ffmpeg -v error -y -ss 65 -i full_app/demo/demo_out/fixture/gameplay.mp4 -frames:v 1 full_app/demo/demo_out/preview.png`:
  remote exit **0**; demo took **17.731s**, both montages measured **7.354362s**
  against the 12-second budget, at **640x360** and **360x640**. The extracted
  frame was visually inspected for HUD, crosshair and ACE announcement placement.
- No live API calls. Optional sprint modules were absent and explicitly reported
  as skipped. A separate test installs contract stand-ins to verify the complete
  optional-stage handoff, including prepared media, audio/planner inputs, native
  render plans, generated reaction assets and share-kit/download paths. Those
  stand-ins do not establish correctness of the unmerged implementations.
