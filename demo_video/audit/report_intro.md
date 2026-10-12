# AUDIT-2: promise-by-promise feature audit

**The product is not feature-complete.** The offline suite is green, but the stock
Vertex model default fails on the supplied account, and several promised features
are absent, dependency fallbacks, library-only implementations, or work on other
branches. Do not use the promotional demo or a module's tests as proof that a
feature appears in the normal export.

Audited product snapshot: **`8db1f6d`**, the `Extension` HEAD when this task started
on 2026-10-12. Worker branch: **`ext/AUDIT-2`**. Product source was not modified,
merged, pushed or rebased. Later `Extension` movement is documented separately;
the live run and file:line references remain pinned to this reproducible snapshot.

## Highest-priority gaps and task splits

Ranked by what the owner would notice in the video or UI, with startup/export
failures first. Split IDs are defined below so overlapping fixes go to the same
owner rather than competing branches.

| Rank | Gap and concrete evidence | Exact fix / suggested split |
|---|---|---|
| 1 | Stock `gemini-3.1-flash-lite-preview` fails with “Gemini model unavailable”; six attempts reserved before the job fails. F59. | **PROVIDER**: choose a verified available model and stop model-not-found fan-out after the first response. **GLUE**: use the shared model resolver in app/API. |
| 2 | Full landscape fails at the FFmpeg transition join under the worker's 8 GiB address-space limit, reported falsely as a Gemini error. Same plan renders outside the limit. Share-kit chapters also use the wrong clock. F62/F31. | **RENDER**: bound transition memory and test six segments plus cards inside isolation. **SERVER**: preserve safe error categories. **GLUE/SOCIAL**: pass executed timeline including cards/overlaps. |
| 3 | Nice-mode filler can include unverified signal windows and misleading model captions; real scored caption calls Phoenix's Run It Back “Yoru”, another names “Omen”. Neutral scores only suppress exact candidates, not overlapping alternate proposals. F14/F58. | **GLUE**: preserve negative/neutral interval coverage across proposal sources and label unverified fill. **PLANNER**: require context/POV quality before filling; validate actor/event captions against evidence. |
| 4 | Visible VFX remain mostly short grades; freeze masks the planned RIP text at 2.517s in mean output. Bold effects are separate FX-3 work. F15/F17/F63. | **FX/RENDER**: integrate bold registry/placement minimums; composite text after temporal effects; assert >=3 visible effects/clip, >=2 at hit, >=0.35s, then inspect frames and motion. |
| 5 | Reactions have one-second maximum slots and fixed 65%-of-clip timing; longer speech can be cut off. F25. | **GLUE**: reserve slots around verified events using actual selected line duration; **REACTIONS**: preserve phrase/audio tail, expose effective timing. |
| 6 | Head-only mattes exist, but default size is small; readable streamer-sized heads remain FINAL-1 work. F26. | **REACTIONS**: integrate size/placement controls; inspect landscape and vertical readability and jaw/hair edges. **UI/SERVER/GLUE**: carry the option. |
| 7 | Chaos/seed are rejected over HTTP; no Reroll control in the audited UI. F16. | **SERVER/GLUE/UI**: integrate FINAL-1 and test reproducibility plus paid-call-free reroll against actual exported effects. |
| 8 | Nano Banana never executes in stock share kit; original AI intro and car/fish outro are replaced by plain black text cards in Full v2. F32/F61. | **SOCIAL/PROVIDER**: integrate THUMB-1; **SERVER/GLUE/UI**: finish option/budget/provenance plumbing. Coordinate new FISH-1 restoration within GLUE/RENDER ownership; a library merge alone is insufficient. |
| 9 | Full experience leaves Gemini window scoring unchecked and ordinary defaults do not select Full. F08. | **UI/GLUE**: share a single preset contract; show paid-call/dependency implications; assert the button's real serialized request. |
| 10 | SAM weights are present but no `sam2` in the audit environment; fallback motion crop is not SAM spotlight. F28. | **MODELS**: provide documented optional runtime/checkpoint/config and realistic CPU time budget; verify nondegraded masks and spotlight pixels in stock exports. |
| 11 | “Word captions” become animated editorial words without Whisper; audio AI also uses heuristic fallbacks. F12/F22. | **MODELS**: provision cached speech/VAD models; **CAPTIONS**: return transcript provenance and test real spoken-word timing. |
| 12 | Pack has 80 clips and nine explicit flags, but stock loader discards `explicit`/style; no clean option. F27. | **REACTIONS**: integrate FINAL-1 metadata/filtering; **SERVER/UI/GLUE**: forward clean policy and verify selection across label fallbacks. |
| 13 | Full rendering loses the promised speed advantages: reaction processing makes segments sequential and captions/heads/narration add encodes. F49. | **RENDER**: parallelize isolated segment postprocessing and consolidate safe passes; report a matched, idle-runner Full benchmark rather than small synthetic speedups. |
| 14 | React review shows 155.7s of candidates rather than the 29.312s executed edit. Default `python app.py` serves legacy UI; React lacks several enabled inputs/auth transport. F35/F39/F40/F52/F60. | **UI/SERVER**: separate candidate pool from planned timeline, ship a coherent authenticated entrypoint and implement asset/import routes; **DEPLOY**: test real Compose/API/UI and include frontend tests in CI. |
| 15 | Claimed advanced roast templates/local-VLM sampler/search-all-windows/friends stats are incomplete stock integrations. F11/F37/F42/F43. | **GLUE/SERVER**: wire explicit library adapters, preserve player/window/transcript data; **UI**: expose only implemented capabilities. Keep external publish/bot/capture/desktop labeled separate opt-ins. |

Non-overlapping implementation ownership (test paths should follow the same
ownership, with unique new test filenames):

| Split | Exclusive product paths |
|---|---|
| PROVIDER | `full_app/services/gemini_client.py`, `provider_config.py`, `provider_errors.py`, `call_budget.py`, `local_vlm.py` |
| GLUE | `full_app/pipeline/**` |
| SERVER | `full_app/server/**`, `full_app/app.py` |
| UI | `full_app/production_frontend/**` |
| FX | `full_app/fx/**`, `full_app/models/effects.py`, `full_app/planner/stacks.py`, `full_app/assets/vfx/**` |
| PLANNER | `full_app/planner/planner.py`, `models.py`, `adapter.py`, `refinement.py` (not `stacks.py`) |
| REACTIONS | `full_app/reactions/**`, `tools/matte_pack.py` |
| RENDER | `full_app/render/engine.py`, `graph.py`, `analysis.py`, `audio.py`, `plan.py`, `placements.py`, `contracts.py`, `full_app/perf/**`, `full_app/services/ffmpeg_runner.py` |
| CAPTIONS | `full_app/render/captions.py` |
| MODELS | `full_app/sam/**`, `full_app/audio_ai/**`, `full_app/vjepa/**`, `gpu/**` |
| SOCIAL | `full_app/social/**` |
| DEPLOY | `Dockerfile`, `docker-compose.yml`, `.github/**`, `desktop/**` |
| DOCS | `README.md`, `full_app/README.md`, `docs/**` |

## Real-output method and evidence

Runner 1: `104.207.133.47` from `tools/runner_ip`. Source:
`/srv/demo_in/valorant_phoenix_44k.mp4`. A **240-second trim, source seconds
1210–1450 (20:10–24:10)**, was selected by maximizing the number of top-30%-RMS
seconds in a sliding four-minute window. Source contact sheets show firefights,
kill-feed entries, deaths, spectator passages and round changes; this is useful
negative-control material as well as action footage. No downloaded fixtures or
product-code adapters were introduced.

The live driver uses real multipart HTTP upload, isolated stock worker stages,
asynchronous `/analyze`, `/plan`, `/render`, status polling and export downloads.
One job is reused for landscape nice (45s target), vertical nice (30s), and mean
vertical (30s). Full experience, explicit `window_scoring=true`, auto game,
`privacy=false` and share kit are requested. `/srv/packs/team` is copied only to
the runner's `full_app/reaction_packs/team`; all 80 entries have matte assets.
No faces, voices, videos, weights or keys are committed.

The first stock run failed at the default model; the failed snapshot is retained.
A publisher-model-list request also failed (401: listing requires OAuth rather
than an express key). The same job and durable attempt ledger were resumed with
`GEMINI_MODEL=gemini-2.5-flash`, six top windows and one attempt each. The global
cap is 25 calls including the failed requests and metadata call; no ElevenLabs,
image, local-GPU-service or other paid provider is invoked. Changing this env var
is a documented configuration workaround, not a product fix or a passing default.

Real retry analysis: **Valorant 0.911 confidence; 32 candidates, six scored
windows, eleven retained clips**. Candidate lists contain eleven kill-event
records (unknown attribution), not a verified count of POV kills. Audio fallbacks
explicitly report absent WebRTC VAD and Whisper. One scored dead-player window is
kept only as a mean-mode lowlight; other unscored windows remain eligible filler.

Evidence root is both `demo_video/audit/out/` locally and
`/srv/lim/lim-audit2/demo_video/audit/out/` on runner 1. `out/` is gitignored.
Important files: `analyzed_default_model.json`, `analyzed.json`,
`requested_options.json`, `model_override.json`, `calls.json`, per-export status,
plans, segment tables, MP4s, ffprobe/PCM measurements, contact sheets and share
metadata. `environment.json` records SAM availability. All frame labels use
**executed output time** from `render_evidence.timeline`, not source time.

`inspect_outputs.py` samples every timed effect at start/middle/end, each planned
reaction, every word/text caption, every segment join and both cards; it writes
individual frames plus paginated contact sheets. A complete decode check is run
for each media file. FFprobe verifies streams, codecs, dimensions and duration;
PCM RMS/peak plus placement/filter graphs verify audio routing. **A nonempty AAC
stream alone cannot prove a particular SFX, music bed, voice identity or audible
mix quality.** No such claim is made here.

Browser evidence includes the legacy root and React default/Full settings,
all control values/disabled states, review timeline, Director and export.
The app lacks resume-by-job-ID, so the audit browser maps only the upload response
to the existing real job; subsequent status, media and share requests are real.
This session-attachment shim is recorded in `ui_result.json`, and is not a fake
analysis/render. No Director inference is spent merely to obtain a screenshot.
Reroll and Chaos absence are recorded as zero matching controls.

## Verification record

Commands run from this worktree root. `remote_checks.sh` calls the required
`tools/remote_run.sh`, adding rsync exclusions only for active audit outputs and
the runner-only reaction pack. It does not change the product or test source.

| Command | Result / exit |
|---|---|
| `bash tools/remote_run.sh "bash demo_video/audit/checks.sh"` | **1,132 passed, 19 skipped**, 711.10s, exit **0**. Runs `cd full_app && python -m pytest -q --disable-warnings --ignore=tests/test_video_live.py`. No live credentials in test process. |
| `bash demo_video/audit/remote_checks.sh "bash demo_video/audit/frontend_checks.sh"` | TypeScript/Vite build, **35 Vitest**, **3 Playwright** passed, exit **0**. Browser tests are mocked, separate from real-job screenshots. |
| `bash demo_video/audit/remote_checks.sh "python demo_video/audit/probes.py"` | Contract/capability/pack/library/artifact probes, exit **0**; zero inference. |
| `bash demo_video/audit/remote_checks.sh "PYTHONPATH=.:full_app python -m pytest -q gpu/tests && PYTHONPATH=.:full_app python -m pytest -q desktop/tests && python -m pytest -q demo_video/v3/test_v3.py && node --test desktop/tests/runtime.test.cjs"` | **30 GPU**, **5 desktop Python**, **10 demo**, **7 desktop Node** passed, exit **0**, after installing `gpu/requirements-test.txt`. No deployment/GUI proof. |
| `ssh` stdin-key launch of `.venv/bin/python demo_video/audit/resume_live.py` | Driver exit **0**; analysis and two vertical variants succeeded; landscape status **error**. **14/25** total attempts. Driver completion is not a claim that all variants passed. |
| `bash demo_video/audit/remote_checks.sh "python demo_video/audit/diagnose_render.py landscape"` and the same with `--bounded` | Both diagnostic harness exits **0**. Unbounded stock renderer succeeded at 44.053s; bounded run captured FFmpeg `Cannot allocate memory` at the join. No paid calls; neither substitutes for API acceptance. |
| `bash demo_video/audit/remote_checks.sh "python demo_video/audit/download_check.py && python demo_video/audit/inspect_outputs.py && node demo_video/audit/browser.cjs"` | Exit **0**; four HTTP 200 downloads, three complete video decodes, 369 event frames, real-job UI screenshots. |
| `bash demo_video/audit/remote_checks.sh "node demo_video/audit/browser.cjs && python -m pytest -q demo_video/audit/test_evidence.py"` | **5 passed**, 0.53s, exit **0**; validates artifact coverage, provenance separation, call ceiling, UI controls and all code/test references. |
| `bash demo_video/audit/remote_checks.sh "python -m pytest -q demo_video/audit/test_evidence.py && python demo_video/audit/stop_servers.py"` | Final **5 passed**, 0.40s, exit **0**; stopped only the recorded audit API/Vite processes after checking ownership. Evidence remains on disk. |
| `python -X utf8 demo_video/audit/build_report.py`; `python -X utf8 demo_video/audit/verify_scope.py`; `git diff --check` | Local exit **0** each; report references generated, all 20 changed files in allowed paths, nonprinting runtime-key scan clean. |

Failed attempts are retained: an initial inline shell command failed quoting
before pytest (remote 2/local 1); the initial optional-suite collection lacked
FastAPI (remote 2/local 1); a combined GPU/demo/desktop process had 43 passes and
two desktop setup errors (exit 1) because the demo test's `render` module shadows
the production `render` package. Separate processes passed. This is a test
namespace collision, not evidence of a desktop product runtime failure.
The first audit-evidence check had **4 passed, 1 failed**, exit **1**: its broad
`/chaos/i` label locator counted the Profile option “Comedy & chaos”. Narrowing
that audit-only locator to a label beginning with Chaos fixed the false positive;
the rerun above passed. No product test or implementation was changed.

Reproduce offline checks with the commands above. Reproduce live evidence only
with an explicit budget and an env/stdio key: `live_run.py` records the initial
stock behavior; `resume_live.py` preserves the ledger after that specific failure.
Do not blindly rerun the live scripts to view artifacts. Use `inspect_outputs.py`
and `browser.cjs` for no-inference review of the existing job.

## Reading limitations and branch state

Historical agent reports were read as claims, not imported as proof of current
integration. Their old test counts, merge reports, pricing and demo videos do not
override new evidence. The source ledger includes all task specs, finished
reports, the supplied Discord owner/integrator transcript, README and docs.
Pure Village hosting/billing conversations are outside this editor's acceptance.

FINAL-1, FX-3, DEADLOCK-1 and THUMB-1 branches were read without checkout or edits.
`branches.json` records heads/diffs. FINAL-1 adds chaos/size/filtering but still
caps reaction slots at one second. FX-3 has new procedural effects and tests.
DEADLOCK-1 documents real detection/OCR gains but calls objectives and POV
attribution unverified. THUMB-1 documents generated image candidates and an
explicit outstanding pipeline/UI integration handoff. The integrator merged
THUMB-1 into `Extension` during this audit (`3b95965`); it is **not** in the
audited `8db1f6d` snapshot, and that merge alone does not enable its stock caller.
By the final read-only check, FX-3 was at `123963e` with its QA report, while
FINAL-1 remained `ad69b76`, DEADLOCK-1 `4e3001c` and THUMB-1 `bf56b57`.
`Extension` had additionally dispatched FISH-1 (`12f42e8`) and PARITY-1 (`e449a17`)
after this snapshot; F61 records the original-card regression they address.
These moving branches were inspected as ongoing work, never merged into this
audit or substituted for its real-output evidence.

No real OW2/League, multi-POV recordings, V-JEPA trained head, local VLM server,
external publishing, bot delivery, OBS device, desktop GUI/keychain, Modal
deployment or Docker launch was exercised. These limitations stay explicit in
the matrix; an optional library passing mocks is not mislabeled a live feature.
