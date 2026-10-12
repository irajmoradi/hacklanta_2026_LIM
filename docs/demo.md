# DEMO-02: full-match scoring and filled, reviewed cuts

Run: October 12, 2026, branch `ext/DEMO-02`. The DEMO-01 and FIX-4 sections
below are historical; this section describes the new stock-API run.

## Result and evidence

The original 1,871.970-second, 1920x1080/60 fps Valorant source was uploaded
through the production UI to the stock Flask API. Job:
`1e3bd20b407f46cb87f201dd3f1418f4`. No combined-response adapter, provider mock,
forced game label, analysis replay, or demo-specific planner was used.

- **83 local candidates**, **40 Gemini-scored windows**, **15 player-not-alive
  vetoes**, **78 fused ranks**. Scored ranges span 24-1859 seconds, with ten
  candidate midpoints in each quarter of the complete recording.
- Window classifications: 19 highlights, four explicit lowlights, 17 neutral
  after the provider's dead-player normalization. All 15 vetoes were `false`,
  none unknown. Eleven death-caption candidates were recovered for mean-mode
  consideration; this is heuristic evidence, not eleven verified deaths.
- Retained provenance: 19 scored highlights, four explicit scored lowlights,
  eleven inferred death windows, 43 unscored local fallbacks, one whole-video
  observation. Two reviewed exclusions leave 76 candidates marked keep in the
  final job. Unscored candidates remain available but the final nice cuts use
  model-reviewed moments.
- **44 completed generation attempts out of 80**: 40 windows plus four stock
  whole-video chunks. Retries were disabled. Planning, revisions, all renders,
  share kits and recording added **zero** paid calls, checked against the same
  persistent SQLite ledger and `attempt_audit.json`.
- Auto game detection returned **generic, confidence 0.0**. The run retained that
  result and used the stock generic fallback. No supplied Valorant override was
  applied. OCR produced **zero** positive candidate windows. Other positive
  evidence: motion 82, RMS 79, onset 79, sustained audio 76, scene change 61.

Measured standalone exports (H.264/AAC, 30 fps):

| File in `demo_video/out/` | Duration | Dimensions | Bytes |
| --- | ---: | --- | ---: |
| `montage_landscape.mp4` | 60.000 s | 1920x1080 | 44,318,502 |
| `montage_vertical.mp4` | 30.000 s | 1080x1920 | 19,857,390 |
| `montage_mean_vertical.mp4` | 20.000 s | 1080x1920 | 14,064,905 |

The landscape plan has six distinct moments plus its repeated teaser; vertical
has three distinct moments plus teaser. Mean has a verified POV death, a failed
Phoenix ultimate, and a highlight setup, plus the repeated death teaser.
Reaction assets come from `/srv/packs/team`. Final reaction frames show team
faces in the landscape bottom-right and portrait top-right positions.

## Planner changes and source review

Stock local plans enable target filling and ten-second clip limits. They try
variety first, then relax repeated categories when needed to meet the target.
This removes the previous all-`play` category failure that stopped at an
eight-second teaser/climax pair. Reviewed observations precede unscored local
fallbacks without changing recorded scores. Explicit lowlights precede inferred
deaths; `editorial_review=True` can confirm a death while retaining its nice-mode
veto. Deselected clips never return as filler. Library callers retain the old
strict-variety default unless they request `fill_target=True`.

Grounded kill/death times anchor pre-roll and aftermath. Otherwise the longest
sustained-audio burst anchors a trim, with midpoint fallback. Early camera cuts
or ability sounds no longer automatically become the peak. Clip limits, source
bounds, playback speed and the requested output budget remain validated.
Absent an explicit target, pipeline defaults are 60 seconds landscape and 30
seconds vertical. Local detection retains up to three times the paid scoring
count, bounded to 500; scoring remains independently budgeted.

The initial automatic 60-second cut exposed real semantic/timing errors during
source-frame QA. `demo_video/review_decisions_v2.json` records the complete
source-specific intervention, applied through the ordinary clip PATCH API:

1. Exclude 58-66 seconds: the model claimed a player highlight, but the combat
   report and changing viewed agents show spectator footage.
2. Exclude 358-372 seconds: caption recovery claimed a death while source frames
   show the player alive at 100 health through the alleged event.
3. Confirm the POV death in 125-143 seconds, with a reviewed peak at 136.0;
   confirm the failed Phoenix ultimate in 256-273, peak 268.0. Supply accurate
   gameplay roast captions rather than reuse misleading death descriptions.

The final mean cut uses source ranges 134.7-136.7 (teaser), 1684.975-1686.475
(highlight setup at 0.5x), 264.75-269.75 (ultimate failure), and 129.5-139.5
(death climax). Source and output sheets are delivered under `out/review/`.
Nice source sheets sample the start, selected anchor and end of every placement.
These are reviewed exports, not a claim that all 78 fused observations are
correct or that autonomous semantic accuracy is solved.

## Actual stage timings

| Stage | Seconds |
| --- | ---: |
| Auto profile detection | 19.1387 |
| Full-match local signals | 515.5394 |
| Forty window assessments | 223.1471 |
| Whole-video pass, including stock chunk/proxy encoding | 1091.7843 |
| Original local plan | 0.0389 |
| Final landscape plan / selected-range privacy / total render | 0.0190 / 98.0761 / 194.8700 |
| Final vertical plan / privacy / total render | 0.0210 / 11.0949 / 89.1758 |
| Final mean plan / privacy / total render | 0.0239 / 41.9740 / 91.5862 |

Timings are nested. The final revisions reused analysis and some privacy ranges.
Older reaction stage keys persist in later snapshots; the final plans each have
two reaction placements, rather than one new reaction for every inherited key.
Full-source OCR and double encoding of ten-minute provider chunks remain costly.

FIX-4's earlier 360-second smoke scored two windows using three calls and made
8.021-second nice/mean exports against 30-second targets. This run analyzes the
entire source and fills 60/30/20-second requests. The video comparison uses the
owner's `/srv/demo_in/final_v3.mp4` alongside the new landscape export. Different
budgets and reviewed inputs mean this is an illustrative comparison, not an
accuracy or speed benchmark.

## Stock API boundaries and remaining weaknesses

The only demo hosting change is serving the unchanged production React build
through Flask's `static_folder`. Source-specific review uses supported clip
edits, not a backend/provider adapter. Each shorter export first calls `/plan`,
then `/render`: `JobQueue.submit` currently validates the previous longer plan
against a new render limit before invalidating it. A direct 60-to-30-second
render therefore returned `Plan exceeds max_duration`. The queue is outside
this task's allowed paths; the two stock calls avoid that issue.

The UI walkthrough is the real first-pass upload/settings/progress/review/export
capture, with long waits removed. It predates the source-review corrections;
a card explicitly says so. Final comparison and montage sections use the reviewed
exports. No browser routes or API responses are mocked. `frontend.png` is a
frame from that actual review capture, not the empty resumed browser session.

Remaining weaknesses: generic auto detection on this full match; no OCR kill
recognition; model errors about viewpoint, death and clutch status; approximate
acoustic timing when grounded events are absent; and center crops that may lose
peripheral action. Mean-mode death-caption recovery is only fallback evidence.
Default region blur covers selected HUD areas, not every nameplate, combat
report or scoreboard, and does not promise uploader-name preservation. Source
preview and old-version comparison footage are not the privacy-blurred exports.

## Reproduce and inspect

Runner inputs are `/srv/demo_in/valorant_phoenix_44k.mp4`,
`/srv/demo_in/final_v3.mp4`, and `/srv/packs/team`. Runtime output root is
`/srv/demo_out/demo02/`; the persistent job marker and budget must not be deleted
to obtain a fresh call allowance. `launch_v2.py` reads only `GOOGLE_API_KEY` from
the owner-specified dotenv at runtime, passes it over SSH stdin into the process
environment, and selects Vertex Express with `gemini-3.5-flash-lite`. Credentials
are never written into source, artifacts, logs or command arguments.

```powershell
bash tools/remote_run.sh 'cd full_app/production_frontend && npm ci --silent && npm run build && npx playwright install chromium'
python demo_video/launch_v2.py
# Optional independent, read-only ledger audit while the server is running:
ssh -i "$env:USERPROFILE/.ssh/village_vultr" root@104.207.133.47 'cd /srv/lim/lim-demo02 && .venv/bin/python demo_video/audit_v2.py'
# After the live driver has shut down:
bash tools/remote_run.sh 'python demo_video/review_v2.py && python demo_video/assemble_v2.py && python demo_video/verify_v2.py'
python demo_video/collect_v2.py
```

`preview_v2.py` and `review_v2.py --planned` permit local-plan source inspection
from saved analysis with no paid calls. The review decisions are specific to this
source. As in DEMO-01, sync/test before starting the live backend or after it has
stopped: `remote_run.sh` replaces the disposable runner checkout. Tests and
assembly can run together after live work because authoritative media/jobs are
outside that checkout. All generated media, source sheets, snapshots, share kits,
checksums and evidence are ignored by git under `demo_video/out/`.

## Verified deliverables and test record

Open `demo_video/out/extension_demo_v2.mp4` for the complete 1080p walkthrough,
comparison and final cuts. `extension_demo_v2_discord.mp4` is the smaller share
copy. Both include the complete 20-second mean excerpt so its final roast
reaction is visible.

| Deliverable | Duration | Dimensions | Bytes |
| --- | ---: | --- | ---: |
| `extension_demo_v2.mp4` | 120.455 s | 1920x1080 | 31,964,062 |
| `extension_demo_v2_discord.mp4` | 120.467 s | 1280x720 | 5,973,940 |
| `ui_walkthrough.mp4` | 19.454 s | 1920x1080 | 1,073,743 |
| `comparison.mp4` | 18.000 s | 1920x1080 | 23,679,641 |

The Discord copy is **5,973,940 bytes**, below 20,000,000. `contact_sheet.jpg` is
1920x810. The three montage mean audio levels are -16.7, -16.2 and -19.9 dB.
All seven videos fully decoded with FFmpeg, passed H.264/AAC/dimension/30 fps
checks, and matched their runner SHA-256 after local collection. Files include
`verification.json`, `SHA256SUMS`, `output_manifest.json`, `evidence.json`,
per-clip CSV, original API analysis, export snapshots, source/output QA sheets,
review decisions, the attempt audit and three share kits.

Final Linux-runner verification:

```powershell
bash tools/remote_run.sh 'cd full_app && python -m pytest tests/test_planner_fill.py -q && python -m pytest -q && cd .. && PYTHONPATH=full_app python -m pytest demo_video/test_demo.py -q && cd full_app/production_frontend && npm test && npm run build'
# Exit 0: 16 focused tests; 1025 full-suite tests passed, 21 skipped (582.31 s);
# 8 demo tests; 27 Vitest tests; TypeScript check and production build passed.

bash tools/remote_run.sh 'python demo_video/review_v2.py && python demo_video/assemble_v2.py && python demo_video/verify_v2.py'
# Exit 0: source/output sheets, assembly and all seven media checks passed.

python demo_video/collect_v2.py
# Exit 0: allowlisted deliverables collected; all local video hashes matched.
```

Earlier commands and failures are retained here rather than reported as passes:

- Initial focused planner/pipeline/FIX-4 regression command exited 0:
  `bash tools/remote_run.sh 'cd full_app && python -m pytest tests/test_planner.py tests/test_planner_fill.py tests/test_planner_adapter.py tests/test_pipeline.py tests/test_pipeline_settings.py tests/test_fix4.py -q'`
  ? 128 passed in 192.45 seconds, before later source-review refinements.
- An earlier full verification passed 1,023 core tests with 21 skips, then
  exited 1 in the demo suite (one failed, seven passed). The historical
  `test_baseline_generic_profile_contract` still expected the generic-profile
  exception already fixed in FIX-4. Its assertion now checks the safe mapping.
- `python demo_video/launch_v2.py` first exited 1 at the shorter-render admission
  issue described above, after analysis and an automatic landscape export. The
  two resumed invocations exited 0, reused the same job/ledger, and produced the
  revised exports. Exactly 44 calls were used across all invocations combined.
- The first assembly command exited 1 during two-pass x264 Discord encoding
  (`Incomplete MB-tree stats file`); final media verification had not run.
  Packaging now uses a 30 fps CRF encode with a duration-derived bitrate cap and
  headroom. The final command above exited 0 and verified the actual file size.

Code milestones: `ce44698` (fill/death evidence), `27b14ad` (stock live/demo
tooling), `51251bc` (reviewed selection and action anchors), `901dedd` (review
provenance, stock replan flow and QA decisions). The final report commit adds
this measured handoff and the verified packaging adjustment. No push or merge
was performed.

Changed files are limited to the task's allowed paths:

```text
full_app/planner/models.py
full_app/planner/planner.py
full_app/pipeline/extensions.py
full_app/pipeline/orchestrator.py
full_app/pipeline/ranking.py
full_app/tests/test_planner_fill.py
demo_video/assemble_v2.py
demo_video/audit_v2.py
demo_video/collect_v2.py
demo_video/launch_v2.py
demo_video/live_v2.py
demo_video/preview_v2.py
demo_video/record_v2.cjs
demo_video/review_decisions_v2.json
demo_video/review_v2.py
demo_video/test_demo.py
demo_video/verify_v2.py
docs/demo.md
docs/planner.md
```

---

# DEMO-01: real Valorant walkthrough

This run uses the `ext/DEMO-01` worktree, based on Extension commit `2a7c565`.
Only `demo_video/**` and this document are changed. The production backend,
frontend and providers remain as checked out at that commit.

## Run design

- Source: runner `/srv/demo_in/valorant_phoenix_44k.mp4`, 1,871.970 seconds,
  1920 x 1080, 60 fps. The owner supplied the gameplay and old montages.
- Real multipart upload to `POST /api/jobs`; real React frontend and Flask
  durable queue. Playwright uses Chromium at 1920 x 1080, without mocked routes.
- Auto game detection, local gameplay signals, Gemini window scoring, local
  story planner, team reactions, privacy and share kit enabled. Speech captions
  and optional model downloads disabled.
- Motion is sampled at 2 fps; OCR is bounded to one sample every five seconds
  after an unbounded OCR attempt proved slow. This may miss brief kill-feed
  events. Audio still spans the full match. Neither aborted attempt made a
  Gemini call.
- The latest user instruction limits this run to **three live Gemini attempts**,
  overriding the task record's 120-call allowance. `budget.py` reserves attempts
  before SDK calls, persists across restarts and disables SDK/provider retries.
  Never delete the ledger to retry this task. Failed requests consume budget.
- The initial candidate request succeeded at source resolution, but its following
  full-match attempt hit a local SDK schema error. The final successful run uses
  one combined structured request for full-match clips plus assessment of the
  strongest candidate. A complete-match
  640-pixel, 2 fps, approximately 55 kb/s video + 16 kb/s mono audio proxy keeps
  the full-video request inside Vertex Express's inline size limit. Rendering
  uses the original 1080p source. Fine HUD details are weaker in this proxy.
  The `whole_video` stage reuses the combined response; its near-zero timing is
  not the model's inference time. That time is reported under `window_scoring`.
  After validation failures, the final UI recording resumes real cached
  candidates and the real model response. No UI responses are mocked.
  `cold_analysis_timings.json` preserves the actual scan/inference durations;
  the final API snapshot separately reports the cache-reuse timings.
- Mean mode is a local alternate story plan using valid lowlights from the same
  saved analysis plus one setup moment, submitted
  as an explicit plan to the render API. It is not a separate Gemini lowlight
  analysis. No additional paid calls are needed for renders or share kits.

## Demo-only adapters and discovered issues

These are in `demo_video/live_smoke_server.py`; none is a claimed core fix.

1. **Auto detection / signal profile mismatch.** On this source, the automatic
   detector returned `('generic', 0.0)` after 5.5072 seconds in the first attempt.
   `signals.ocr.regions_for('generic', None)` raises
   `ValueError: unknown game profile: generic`. The API reported exactly
   `analyze failed (ValueError); check configuration and retry`.
   That attempt made zero Gemini calls. The demo records the original detection
   and falls back to the owner-supplied Valorant label with an explicit warning.
   Core needs a safe generic mapping and improved real-footage detection.
2. **Frontend capability/option contract.** `/api/info` does not provide
   `frontend_capabilities`. The UI consequently disables privacy, story planner
   and share-kit controls although backend modules exist. The demo advertises
   only supported features and translates `planner_v2` → `planner`,
   `privacy_blur` → `privacy`, `share_kit` → `social`; game selection also enables
   `profiles`. Core needs matching discovery and option names.
3. **Review/share payload contract.** Backend status has no `interest_curve`,
   while `share_kit` is a directory marker string rather than the UI's object.
   The adapter derives a sparse curve from actual candidate midpoint scores and
   exposes actual generated metadata, chapters, covers and download links.
   This is candidate evidence, not a dense per-frame interest measurement. Raw
   candidate scores can exceed 1; the adapter normalizes them by the positive
   peak before sending 0–100 values, preventing the frontend clamp from flattening
   the entire curve. A regression test covers this scale mismatch.
4. **Privacy cost.** The core sanitizes the entire source before editing. The
   full-source attempt progressed only about 10 MB into the 1.34 GB input after
   roughly one minute, making three full-length passes impractical.
   The demo opts into the existing `backend=none` conservative region fallback
   and first extracts only reviewed ranges at source speed, at the final export's
   30 fps. It remaps the plan and reaction metadata, then applies the existing
   sanitizer before effects/framing. It restores original source-relative API
   state afterward. The selected-range result is cached by source path/size/mtime,
   ranges and privacy options. This is
   HUD-region blur, not precise name-only detection; it cannot preserve the
   uploader's name. The original fallback also blankets the center of gameplay.
   This demo explicitly restricts masks to kill feed, chat and party voice.
   Scoreboard/nameplate coverage is **not demonstrated**. Review before publishing.
   The UI source preview and old-version comparison are raw footage; these masks
   apply to the new montage exports, not every frame of the demonstration.
5. **Mode changes invalidate analysis.** Changing `mode` clears clips and
   candidates. An explicit local mean-mode plan avoids another paid analysis;
   the prior selected-clip evidence is retained in `mean_editorial_input.json`.
   Mean rendering then chooses roast reactions without per-clip classification.
6. **Gemini SDK schema construction fails before transport.** The original
   `ClipList` request raised `ValidationError: 2 validation errors for Schema`:
   `properties.clips.items.properties.end.exclusiveMinimum` and
   `properties.clips.items.properties.end_seconds.exclusiveMinimum`, each with
   `Extra inputs are not permitted [type=extra_forbidden, input_value=0, input_type=int]`.
   The core then hid this as `Video analysis failed`. `diagnose_schema.py`
   reproduced it with a mocked transport. The demo sends a JSON schema with
   inclusive minimum constraints and retains strict original Pydantic response
   validation, including rejection of zero-length or nonpositive-ending clips.
   Core needs an SDK-compatible schema and safe, actionable error reporting.
7. **Out-of-bounds model ranges.** The final response proposed 2636–2640 and
   2802–2807 seconds for a 1871.970-second source. The pipeline reported
   `start_seconds must be a finite number between 0 and 1871.969524`.
   The demo rejects both ranges, retains the original response in
   `combined_result.json`, and saves rejected ranges separately. It does not
   reinterpret, clamp or invent model timestamps. Source-hashed cached local
   candidates allow recovery without further paid calls. Core should preserve
   valid observations and actionable range diagnostics for long-video drift.
8. **Semantic quality / spectating.** Source-frame review showed that 38–42 and
   47.5–53 seconds were spectator footage despite "good" descriptions; 448–453
   was buy phase; 215–218 showed a headshot despite being labeled "bad".
   The single assessed end-of-match window correctly reported the player not
   alive and was vetoed, but this budget did not allow assessment of every
   candidate. Final nice/mean ranges and captions are manually curated from the
   actual candidate set in `demo_video/editorial_selection.json` and submitted
   through the real clip-edit/render API. `review_frames.py` generates the source
   QA sheets. This run demonstrates an **editor-reviewed workflow**, not reliable
   unattended highlight accuracy on a compressed 31-minute video.

## Reproduction

From the Windows task worktree, with the configured SSH key and runner inputs:

```powershell
bash tools/remote_run.sh "python -m pytest demo_video/test_demo.py -q && cd full_app/production_frontend && npm ci --silent && npm run build && npx playwright install chromium"
python demo_video/launch_live.py
ssh -i "$env:USERPROFILE/.ssh/village_vultr" root@104.207.133.47 "cd /srv/lim/lim-demo01 && node demo_video/record_ui.cjs"
ssh -i "$env:USERPROFILE/.ssh/village_vultr" root@104.207.133.47 "cd /srv/lim/lim-demo01 && .venv/bin/python demo_video/finish_run.py && .venv/bin/python demo_video/assemble.py"
python demo_video/collect.py
```

For the final UI recapture after visual QA, the exact additional commands were:

```powershell
python demo_video/launch_live.py --replay-exports
ssh -i "$env:USERPROFILE/.ssh/village_vultr" root@104.207.133.47 "cd /srv/lim/lim-demo01 && DEMO_UI_REPLAY=1 node demo_video/record_ui.cjs"
```

This is a real backend export cache, not a mocked browser response. It refuses
reuse unless the uploaded source SHA-256, full edit plan and export options
match the already decoded/verified exports. It creates real job output/share
files and returns normal API state; the original render timing snapshots remain
unchanged. `ui_replay.json` on the runner records the cache-backed UI job.
The original full render walkthrough also completed successfully before recapture.
The editorial anchors are specific to this source and saved analysis; scripts
fail explicitly if a different analysis no longer matches them.

`launch_live.py` is explicitly a live smoke launcher. It reads only
`GOOGLE_API_KEY` at runtime from `C:/Users/mourn/Downloads/hacklanta/.env` and
passes it over SSH stdin into the backend process environment. No credential is
written to files, command arguments or logs. The provider explicitly selects
Vertex Express and `gemini-3.5-flash-lite`. The service binds runner loopback
port 8011; SSH forwarding can expose it locally for review.

The runner worktree is disposable. `remote_run.sh` uses `rsync --delete`, so run
it before launching the backend, or after the recordings/renders finish: it can
remove the runner-only reaction pack and frontend build. Launching copies the
owner's reaction pack into `full_app/reaction_packs/team/` on the runner only.
The pack, source footage, keys, caches and final media are never committed.

## Outputs and evidence

Runner output root: `/srv/demo_out/demo01/`. Local deliverables:
`demo_video/out/` (gitignored). `collect.py` copies only an explicit allowlist;
it does not copy the source gameplay, job workspaces or full-source privacy cache.

- `extension_demo.mp4`: assembled 1080p walkthrough, comparison and output cuts.
- `montage_landscape.mp4`, `montage_vertical.mp4`, `montage_mean_vertical.mp4`.
- `ui_walkthrough.mp4`: edited UI recording with long processing waits removed.
- `contact_sheet.jpg`, `frontend.png`.
- `share_landscape/`, `share_vertical/`, `share_mean_vertical/`.
- `evidence.json`: stage timings, candidate counts and positive signal counts.
- `clip_signals.csv`: per-clip source ranges, descriptions, scores, signals/events.
- `analysis.json`, `landscape.json`, `vertical.json`, `mean_vertical.json`:
  actual API snapshots; `profile_detection.json`: original automatic result.
- `live_calls.json`: persistent attempt ledger; `output_manifest.json`: actual
  output durations, dimensions and sizes; `ui_scenes.json`: recording edit list.

## Measured results

| Local deliverable (`demo_video/out/`) | Duration | Video |
| --- | ---: | --- |
| `extension_demo.mp4` | 152.398 s (2:32) | 1920 × 1080, 30 fps |
| `ui_walkthrough.mp4` | 34.397 s | 1920 × 1080, 30 fps |
| `montage_landscape.mp4` | 53.421 s | 1920 × 1080, 30 fps |
| `montage_vertical.mp4` | 53.421 s | 1080 × 1920, 30 fps |
| `montage_mean_vertical.mp4` | 17.000 s | 1080 × 1920, 30 fps |

All use H.264/AAC. `contact_sheet.jpg` is 1920 × 810. The five local MP4s were
SHA-256 compared with their runner originals after collection: all matched;
`SHA256SUMS` is included locally. The live backend was stopped after recording.

There were **3 reserved generation attempts**, of which **2 reached Gemini and
returned responses**. Attempt 2 failed locally during SDK schema construction;
it still consumed a budget reservation. No provider calls occurred during tests,
manual review, rendering, share-kit generation or UI recapture. SDK logs recorded
297,287 total input tokens and 738 output tokens across the two responses. No
dollar cost is inferred.

| Stage | Measured seconds | Scope |
| --- | ---: | --- |
| Cold game-profile detection | 5.9374 | Inconclusive; supplied Valorant label used |
| Cold full-match local signals | 294.1198 | 2 fps motion, OCR every 5 seconds |
| Combined Gemini request stage | 78.2323 | Full-match clips + one candidate assessment |
| Local story plan | 0.0375 | Nice analysis plan |
| Landscape privacy/extraction | 91.7974 | Reviewed source intervals only |
| Landscape render, total | 155.4656 | Includes privacy, reactions and share kit |
| Landscape share kit | 4.7628 | Included in total |
| Vertical render, total | 71.5030 | Privacy cache hit: 0.0082 seconds |
| Vertical share kit | 6.9573 | Included in total |
| Mean vertical render, total | 102.2539 | Includes 30.0561 seconds privacy and 19.5163 effects |
| Mean share kit | 6.0809 | Included in total |

The initial failed full-video stage, dominated by proxy encoding, took 266.7056
seconds; later runs reused the proxy. Final cache-replay stage timings are
separately retained in API snapshots. Timings are nested, so do not add every
row. Backend snapshots retain older stage keys; mean mode executed reaction
stages 0–3, while its inherited `reactions_4` value belongs to the earlier nice cut.

30 candidate windows were produced. Positive signal values occurred in 30 motion,
30 RMS, 30 onset, 29 sustained-audio and 25 scene windows; **OCR fired in 0**.
The one assessed window was vetoed as player-not-alive. Two out-of-range model
clips were rejected. The final five nice moments and three mean candidates were
editor-reviewed, with a real UI trim of 212.5 → 212.6 seconds and a reorder.
These are counts of positive candidate evidence, not verified kill counts.

## Verification and task handoff

All commands below ran on the Linux runner. Unit/integration tests use mocked
providers or blocked transports and synthetic ffmpeg sources.

```powershell
bash tools/remote_run.sh "PYTHONPATH=full_app python -m pytest demo_video/test_demo.py full_app/tests/test_jobs.py -q && cd full_app/production_frontend && npm test && npm run build"
# Exit 0: 35 Python tests, 21 Vitest tests, production build passed.

bash tools/remote_run.sh "PYTHONPATH=full_app python -m pytest demo_video/test_demo.py full_app/tests/test_jobs.py -q && cd full_app/production_frontend && npm run build"
# Exit 0 after curve/replay changes: 36 Python tests, production build passed.

bash tools/remote_run.sh "python demo_video/verify_outputs.py"
# Exit 0: all five videos fully decoded, expected H.264/AAC dimensions and 30 fps,
# demo 2–3 minutes, UI under 90 seconds, audible montage tracks, contact-sheet size.
```

Both the full real-render recorder and final cache-backed UI recorder exited 0.
`finish_run.py` and `assemble.py` completed successfully. The final assembly was
also decoded again by `verify_outputs.py`; its measured results are delivered in
`verification.json`. Visual QA inspected original candidate frames, three points
per mean candidate, reaction overlays, the timeline recording and the contact
sheet. Earlier recorder attempts exited 1 on the documented pipeline failures
and an export-dropdown selector timeout (fixed in the recorder); slow OCR/full-
source privacy attempts were intentionally stopped, not reported as passes.

Changed files are confined to `docs/demo.md` and `demo_video/`: the runtime-only
launcher, live backend adapter, persistent budget guard, Playwright recorder,
editorial selection, source-frame reviewer, schema diagnostic, evidence-cache
helper, mean renderer, assembler, output verifier, collector, tests and `.gitignore`.
No production code, gameplay, reaction media, credentials or model weights are
committed. Open `demo_video/out/extension_demo.mp4` to try the completed demo;
the raw exports and share kits are alongside it. Core fixes listed above remain
for the integrator; these adapters are intentionally limited to this demo.

Tracked file inventory:

```text
demo_video/.gitignore
demo_video/assemble.py
demo_video/budget.py
demo_video/cache_evidence.py
demo_video/collect.py
demo_video/diagnose_schema.py
demo_video/editorial_selection.json
demo_video/finish_run.py
demo_video/launch_live.py
demo_video/live_smoke_server.py
demo_video/record_ui.cjs
demo_video/review_frames.py
demo_video/test_demo.py
demo_video/verify_outputs.py
docs/demo.md
```

Branch: `ext/DEMO-01`. Milestones before the final verified handoff:
`1fddaa7`, `d359922`, `56b30b1`, `2d42249`. The final handoff commit is reported
in the task completion message and is the branch tip.


## FIX-4 core replacement (October 12, 2026)

The historical DEMO-01 results above remain unchanged. FIX-4 moves the following
workarounds into the stock pipeline; `demo_video/live_smoke_server.py` is no
longer needed for these behaviors:

| Demo adapter | Core replacement |
| --- | --- |
| Generic-to-Valorant forced fallback | Generic mappings in signal OCR/privacy; 16-frame OCR and HUD detection, confidence, optional budgeted three-frame VLM fallback |
| Capability and option translation | `/api/info` discovery, canonical frontend flags plus validated API aliases, game selection enables profiles |
| Candidate-midpoint curve | Dense per-second fused-signal curve normalized to 0-100 |
| Share-directory wire adapter | Structured metadata, posting copy, chapters, covers and download links |
| Whole-source privacy workaround | Per-selected-range source-speed extraction and privacy cache before effects/crops; kill feed/chat/party masks by default |
| Manual mode workaround | Mode changes preserve analysis and use local planning with no new generation calls |
| SDK schema override | Inclusive request bounds with strict per-item response validation |
| Manual timestamp filtering | Logged clamp/drop at chunk and source boundaries; malformed clips do not discard valid siblings |
| Demo-only three-call wrapper | Persisted per-job attempt budget, configurable production default 80; explicit smoke default 3 |
| Demo-only Vertex compression | Stock provider makes a size-bounded inline proxy when needed |

The combined-response adapter is unnecessary for stock operation. With this
run's three-call ceiling, two top-ranked windows and one full-video request fit
without combining schemas. This does not assess every candidate. Editorial
review, semantic accuracy checks, reaction-pack assets and demonstration video
assembly remain distinct from these infrastructure fixes. Default privacy does
not claim scoreboard/nameplate coverage or uploader-name preservation.

Reproduce the explicit smoke only after syncing/testing, since rsync replaces
the runner checkout:

```powershell
bash tools/remote_run.sh 'cd full_app && python -m pytest tests/test_fix4.py -q'
python full_app/tests/launch_fix4_live.py
```

The launcher reads `GOOGLE_API_KEY` from the owner-specified dotenv at runtime
and sends only that key plus nonsecret configuration over SSH stdin. It does
not copy the dotenv, persist credentials or put credentials in process arguments.
The runner launches the stock `create_app` with its normal isolated worker and
serves real loopback HTTP requests. It trims the first 360 seconds with ffmpeg,
uploads via multipart, analyzes with automatic profiles/signals/window scoring,
then renders nice and mean 30-second targets with privacy and share kits.
No demo adapters, provider mocks, pre-curated ranges or response replays are used.

The user message's **at-most-three live calls** takes precedence over FIX-4.md's
30-call smoke allowance. The launcher fixes retries to one and the per-job
budget to three. `/srv/demo_out/fix4/job-id.txt` resumes the same job on restart;
never remove its job ledger to obtain a fresh budget. Runtime media, status
snapshots and results remain under `/srv/demo_out/fix4/`, outside the checkout.
Both exports are fully decoded by ffmpeg, and the script asserts that rendering
and the mode change do not increase the generation count.


### FIX-4 measured stock-API smoke result

`python docs/fix4_launch_live.py` exited **0** on October 12 (the launcher is now
`full_app/tests/launch_fix4_live.py`; only its repository-root lookup changed). The input was exactly
360.000 seconds; output evidence is also saved in `docs/fix4_smoke_results.json`.
The normal API job was `139b8b0ac9a04cb5999a429eea01b54a`.

- Auto profile: **valorant**, heuristic confidence **0.909**; no forced profile
  or VLM identification fallback.
- **14** local candidates, **2** Gemini window assessments, **13** retained clips,
  and **360** dense fused-curve points.
- Both assessed windows were vetoed as player-not-alive. Retained evidence was
  **12 unscored signal clips and 1 whole-video clip**, all labeled good; the
  three-call ceiling leaves their semantic quality incompletely verified.
- Exactly **3 generation attempts**, all completed. Nice rendering, mean local
  replanning and mean rendering added **zero** calls.
- Nice and mean exports: **8.021333 seconds**, **1920x1080**, **30 fps**, H.264/AAC.
  Both fully decoded with ffmpeg. Each share kit exposed **5** real downloads.
- Both plans used the same source intervals (132.7-134.7 and 130.1-136.1), with a
  different closing caption. No validated lowlights survived this run. This
  demonstrates analysis reuse and a mode-specific local plan, not a distinct
  verified roast selection. The 30-second target was underfilled by the existing
  deterministic planner's eligible selection; the smoke did not force ranges.
- One exported frame was visually inspected: the center gameplay remained
  visible with region masks at top-left, top-right and lower-left. Central
  teammate nameplates remain outside default coverage. This is a limited
  region-mask check, not a privacy guarantee or full semantic review.

| Stage | Seconds |
| --- | ---: |
| Game detection | 17.1420 |
| Local signals | 93.0453 |
| Two parallel window assessments | 13.4315 |
| Whole-video analysis including inline proxy | 55.8527 |
| Nice planning | 0.0247 |
| Nice selected-range privacy | 18.8055 |
| Nice render including privacy/share kit | 29.0768 |
| Mean planning | 0.0253 |
| Mean privacy with range-cache hits | 1.0485 |
| Mean render including privacy/share kit | 11.5536 |

Timings are nested; do not sum render totals with their child stages. Analysis
keys retained in the mean snapshot are inherited, not repeated work. Media and
raw status snapshots remain on the runner under `/srv/demo_out/fix4/`; no source
footage, output videos, credentials or model weights are committed. The smoke
server was shut down by its launcher after verification.


Final FIX-4 regression verification on the Linux runner:

```powershell
bash tools/remote_run.sh 'cd full_app && python -m pytest -q > /tmp/fix4-pytest-final.log 2>&1; result=$?; tail -n 100 /tmp/fix4-pytest-final.log; exit $result'
# Exit 0: 1009 passed, 21 skipped in 521.19 seconds.
bash tools/remote_run.sh 'cd full_app/production_frontend && npm test && npm run build'
# Exit 0: 27 Vitest tests, TypeScript check and production build passed.
```

See `docs/FIX-4-report.md` for the file inventory, earlier failed runs and fixes,
configuration, reproduction instructions and remaining limitations.
