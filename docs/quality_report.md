# QA-3: Extension quality audit

Audit date: 2026-10-12. Branch: `ext/QA-3`. Audited checkout: `2899742` (the Extension snapshot supplied to this worktree). This is a report-only change; proposed fixes below are for the integrator, not changes made by this task. Other workers' unmerged changes are not included.

## Scope and evidence

Reviewed the HTTP/queue/provider/render path, React entry point and import graph, legacy frontend, optional packages, evaluation/demo/test boundaries, dependency manifests, Docker/Compose, CI, and feature documentation. Findings cite repository-relative files and lines in the audited snapshot. Caller searches included dynamic `Pipeline.hook` and demo adapters, not just static imports. Task records describe intended work, not implemented features.

Evidence labels: **R** = reproduced on the Linux runner without network/model calls; **S** = established by source and caller inspection; **T** = observed suite failure. A successful frontend build is not evidence that its requests work with the backend. No live Gemini calls were made and no key file was read.

## Ten highest-value fixes

1. Restrict default network exposure and protect every job/media/action endpoint before sharing the service (P1-01).
2. Prevent persistent SSE connections from exhausting all four production request threads (P1-02).
3. Repair the obsolete demo/E2E adapter to exercise `create_app` and `JobStore` (P1-03).
4. Send current render settings and map edited captions into the renderer's schema (P1-04).
5. Add square reaction composition and test every preset/feature combination (P1-05).
6. Use one typed plan boundary before queue admission; enforce source, effect and duration limits (P1-06).
7. Fix the real evaluation adapters and enforce the live-call budget at the generation boundary (P1-07, P1-08).
8. Centralize provider/key selection, including Vertex express, and reject unknown providers (P1-09).
9. Bound media subprocesses and upload/storage resource usage (P1-10).
10. Replace incompatible planner/render schemas with an explicit versioned adapter and test it end to end (P2-01).

## P1 — bugs, broken wiring, security and resource risks

### P1-01 — Trusted-local API is exposed on all interfaces [S]

**Evidence:** `full_app/app.py:15`, `docker-compose.yml:10`, `full_app/server/api.py:99`, `:128`, `:137`, `:182`, `:215`, `:224`, `:261`; `docs/api.md:4` explicitly documents no authentication. `X-API-Key` is a model credential, not application authentication. Anyone with network access can upload/queue work using the server's provider account; anyone who has a job ID can fetch its source/output, cancel, edit or delete it. UUIDs reduce guessing but do not establish ownership.

**Exact fix:** bind local defaults to `127.0.0.1` (including Compose's host port); require application authentication and owner checks on all job, source, download, event and mutation routes for shared deployment. Keep provider credentials separate. Add cross-owner tests, including streaming/downloads. This is a deployment exposure, not a claim that the documented local service already promises tenancy.

### P1-02 — Four idle SSE subscribers can starve the entire container API [S]

**Evidence:** `Dockerfile:34` runs one Gunicorn process with four threads. `full_app/server/api.py:243` loops indefinitely even for idle/completed jobs; `:257` sleeps while occupying the request. `full_app/production_frontend/src/api.ts:313` opens one connection per active editor and also fetches snapshots. Four tabs can hold all threads, leaving upload/status/cancel and the health check waiting.

**Exact fix:** retain one queue owner but serve SSE through an appropriately configured concurrent streaming server or separate event service. As a minimal bounded mitigation, close terminal/idle streams and have the client reopen on actions; cap subscribers and verify four-plus tabs plus a timely health/status request. Merely adding Gunicorn worker processes violates the workspace lease contract.

### P1-03 — Demo and E2E harness target removed application globals [S]

**Evidence:** `full_app/demo/pipeline.py:192` patches `backend.WORKSPACE`, `:193` patches `backend.jobs`, `:200` reads that dict, `:231` patches `_get_gemini`, and `:270` patches `backend.FFmpegRunner`. `full_app/app.py:8`–`:10` only imports the factory and creates `app`; those globals no longer exist. The first patch raises `AttributeError`; importing `app` also acquires the default workspace lease before isolation. The E2E fixture calls this harness (`full_app/tests/e2e/test_e2e_pipeline.py`).

**Exact fix:** build a temporary-workspace app with `create_app(config, pipeline=...)`, inject a mocked provider on the real pipeline, access `app.extensions['job_store']`, close its queue in `finally`, and wait for asynchronous stages. Replace signature-guessing stage dispatch with adapters to current package APIs. Keep real synthetic upload/render/pixel checks and add a test asserting no default workspace is touched.

### P1-04 — Export silently ignores changed settings and edited caption text [S]

**Evidence:** `full_app/production_frontend/src/App.tsx:442` passes current `options` to `EditorApi.render`; jobs-mode rendering in `src/api.ts:248` sends only `preset` and `edit_plan`. Changing captions/reactions/SAM/style after analysis therefore does not update server options. Each segment receives `caption` at `src/api.ts:262`, but `full_app/pipeline/rendering.py:55` retains only a whitelist including `title`/`words`, not `caption`. `full_app/render/plan.py:38` defines `title` and `words`; `render/captions.py:59` burns `title`. Existing overlapping effects are reused even after a style change.

**Exact fix:** send supported render flags explicitly; track analysis/planning settings separately and replan when style changes. Decide whether the editable text is a title or transcript, then send `title` or timed `words` through a documented adapter. Preserve the version/top-level settings of explicit v2 plans instead of rebuilding only `segments`. Test changing a toggle after analysis and verify burned text in a synthetic export.

### P1-05 — Square export with a configured reaction pack fails [R, S]

**Evidence:** `full_app/pipeline/rendering.py:105` passes `validated.preset` to reactions; `full_app/render/plan.py:103` accepts square. `full_app/reactions/render.py:9` defines only landscape/vertical and `:20` indexes `PRESETS[preset]`. Runner probe `layout(1080, 1080, 'square')` raises `KeyError`. This occurs when an actual reaction is selected, not when reactions are disabled or a pack is absent.

**Exact fix:** define a square safe-area layout and validate preset at the public overlay boundary; parameterize the real pipeline reaction test across all three presets.

### P1-06 — HTTP accepts plans the worker cannot render; duration cap is prompt-only [R, S]

**Evidence:** `full_app/server/validation.py:31` checks segment time ranges and speed only, accepting 500 segments, unknown fields/effects and unvalidated SFX. `full_app/render/plan.py:102` permits 100 segments and rejects extras/unsupported effects. Runner probes accepted an invalid effect through `plan_valid` and rejected it through `RenderPlan`. `pipeline/orchestrator.py:149` inserts `max_duration` into the prompt but `:155` only validates source bounds; aggregate output duration is not enforced. A caller can also supply a v2 `music.path` read by `render/engine.py:65` without job/asset containment, inappropriate for a shared HTTP boundary even if trusted local Python use allows paths.

**Exact fix:** introduce a discriminated legacy/v2 request schema and validate the converted render plan synchronously before queue mutation. Set one segment limit, bound effect/SFX/text collections, validate offset types and names, compute speed/transition/card-adjusted duration, and enforce the configured output cap. Resolve music through authorized asset IDs within permitted roots. Return a clear 400 rather than a later generic worker error. Test both schemas and malformed nested inputs.

### P1-07 — Real signals-only evaluation crashes on successful detections [R, S]

**Evidence:** `full_app/eval/pipelines.py:23` returns `signals.detect_candidates` results unchanged. `full_app/signals/models.py:12` defines a dataclass `Candidate`. `full_app/eval/metrics.py:15` handles `model_dump` but then calls `.get`, which dataclasses lack. Runner `interval(Candidate(0, 1, 1, {}), 2)` raises `AttributeError`; `evaluate` records an error instead of metrics. Empty candidate lists and CI's `--mock` path hide the mismatch. `eval/pipelines.py:29` additionally defaults to nonexistent `services.eval_adapter.score_windows`.

**Exact fix:** normalize dataclasses with `asdict` (or their `to_dict`) at the common interval boundary; test the actual signal adapter with generated bursts and nonempty candidates. Supply a real local/replay scoring adapter explicitly; distinguish a deliberately unavailable scorer from a working comparative pipeline.

### P1-08 — Evaluation's advertised three-call live budget counts videos, not requests [S]

**Evidence:** `full_app/eval/pipelines.py:49` checks `self.calls`, incremented once at `:58` before `find_clips`. `services/video_understanding.py:25` defaults to three attempts and `:125` iterates chunks (600 seconds with overlap). One long input can exceed three generation calls; retries further multiply them. `eval/runner.py:67` limits only dataset length. The comment at `eval/pipelines.py:60` claims `find_clips` owns cleanup, while `services/gemini_client.py:119` performs cache cleanup in `close`, which this evaluation adapter never calls.

**Exact fix:** share a generation-attempt budget enforced immediately before every SDK inference; set application and SDK attempts to one for smoke tests, restrict source duration/chunk count before calls, and close the provider in `finally` after evaluation. Add an offline fake-SDK test for long videos and retryable failures proving at most three invocations and file cleanup. Do not validate this by spending live calls.

### P1-09 — Provider/key configuration diverges between service and app [R, S]

**Evidence:** `full_app/services/gemini_client.py:36`–`:40` supports `GOOGLE_API_KEY` for Vertex express. `full_app/pipeline/orchestrator.py:75`–`:78` requires `GEMINI_API_KEY` or a request key first; `/api/info` checks only that env var (`server/api.py:94`). Compose exports both configurations. A dummy GOOGLE-only runtime probe fails at the pipeline gate before client creation. Unknown provider names are accepted by `server/validation.py:67`; `pipeline/orchestrator.py:72` looks for nonexistent `services.providers`, then falls back to Gemini. The local provider still uses Gemini for planning (`pipeline/providers.py:20`), as documented. The React jobs request helper (`src/api.ts:77`) has no key header and the current App has no key-entry flow, unlike the README's generic browser-key promise.

**Exact fix:** centralize provider resolution and configuration reporting; let the Gemini client resolve Vertex/AI Studio credentials consistently; validate provider IDs and fail explicitly rather than invoking a different paid provider. Implement a memory-only key-entry flow if promised, or clearly require backend configuration in React. Keep the documented hybrid local/Gemini mode explicit until the offline planner is integrated. Use fake clients in tests.

### P1-10 — Unbounded media execution/storage can consume server capacity [S]

**Evidence:** `full_app/services/probe.py:17`, `services/ffmpeg_runner.py:47`, `render/engine.py:43`, `signals/detector.py:102` and `:142` have no execution deadline; queue cancellation only checks between whole stages (`server/queue.py:99`, `:123`). `server/api.py:101` admits uploads outside the bounded work queue; the 2 GiB request cap does not bound duration/pixels/frame count, retained jobs or aggregate disk. No job TTL/retention scheduler appears in the app/queue/store callers. `ingest/models.py` has separate limits, but upload does not call ingest.

**Exact fix:** add configurable probe/stage deadlines, process-group termination with cancellation, and finally cleanup; enforce media duration/resolution/fps and per-owner/workspace byte quotas before scheduling. Reserve space during upload and add retention for inactive jobs/events/artifacts. Test a hung subprocess, exhausted quota and cancellation without consuming real large media. Preserve the documented cooperative behavior until a tested stronger contract replaces it.

## P2 — duplication, inconsistent contracts, stale documentation and coverage

### P2-01 — Two incompatible types both named RenderPlan [S]

`full_app/planner/models.py:138` uses `version`, `clips`, absolute output placements and space-separated styles; `full_app/render/plan.py:100` uses `render_version`, `segments`, clip-local words and different transitions. `pipeline/orchestrator.py:142` still calls Gemini's legacy edit planner; no caller imports `planner.plan_edit` in the application path. The demo's `legacy_plan` (`demo/pipeline.py:133`) discards rich placements. **Fix:** define an explicit versioned adapter, including speed-retimed placements, caption/reaction/SFX timing and empty-plan handling; share style/aspect enums. Do not merely rename one type or pass `model_dump()` to the renderer.

### P2-02 — Signal strength and UI scores use incompatible scales [R, S]

`signals/fusion.py:17` produces an unbounded weighted z-score; `pipeline/ranking.py:24` clamps it to [0,1], flattening all values above one. The runner confirmed scores 2 and 8 both become 1. Scored windows then mix this with hype/10. React `src/api.ts:51` forwards raw scores while its demo uses 82–96 and `docs/frontend.md:29` promises 0–100. Reaction labels from fusion (`label`, `suggested_reaction_label`) are ignored by `normalizeClip` (`:52`, which reads other aliases). **Fix:** specify score provenance and scale, apply a monotonic normalization before fusion, convert to UI percent only at display, and normalize actual reaction-label fields. Test rankings with multiple >1 signal scores and real wire snapshots.

### P2-03 — Legacy preparation loses supported segment metadata [S]

`pipeline/rendering.py:26` constructs timestamp-only segments; `:69` replaces the entire segment list whenever any segment needs speed/unsupported-effect/transition preparation. Supplied `words`, `title` and `sam` metadata on even unchanged segments disappear. Docs explicitly acknowledge lost word timing (`docs/pipeline.md:72`), but titles need no such loss. **Fix:** preserve titles, transform word/track clocks using the actual speed map, and invalidate only data that cannot be transformed, with per-feature warnings. Test mixed segments rather than only a single slowed clip.

### P2-04 — Advertised fade-out is a no-op; complex legacy effects are fragile [S]

`models/effects.py:90` sets `fade_out.filter=None` with “applied dynamically”; `build_vf_chain` skips it, and `services/ffmpeg_runner.py` has no corresponding dynamic implementation. `perf/graph.py:77` explicitly preserves the no-op. The chromatic branch in `services/ffmpeg_runner.py:97` returns before applying `af_extra`; its complex graph also bypasses the final geometry normalization used by the normal branch. **Fix:** implement duration-aware fade-out and explicit labelled complex graphs that retain audio effects and target dimensions, or remove unsupported effects from the prompt catalog. Verify mixed slow-motion/chromatic effects with duration and stream-dimension assertions.

### P2-05 — Optional modules exist but application integration is incomplete [S]

No application-path callers were found for `ingest.prepare`, `profiles.detect_game`, `audio_ai.analyze`, `vjepa.inference.fusion_signals`, `planner.plan_edit`, `music.pick_or_generate`, `privacy.sanitize`, `narration.build`, `multipov.render_montage`, or `social.build_share_kit`. `signals.detect_candidates` is integrated, but is called without the profile/OCR/audio-AI/V-JEPA adapters. These are useful libraries, not inherently dead code; several docs honestly mark the boundary. **Fix:** publish a single capability matrix (library/CLI/API/UI), then add typed opt-in adapters in dependency order. Do not present a task's standalone library tests as integrated app coverage.

### P2-06 — Share-kit defaults do not match the integrated output [S]

`social/__init__.py:73` searches `final_with_thumbs.mp4`/`final_edit.mp4`; `pipeline/rendering.py:121` publishes `output.mp4`. `social/__init__.py:40` expects `plan['captions']` to be a list of timed text, while the renderer uses a captions options object. `social/thumbnails.py:107` asks for nonexistent `sam.cutout`; `sam/__init__.py` exports masks/tracks/effects instead. **Fix:** provide an adapter taking the published job output, measured output timeline and exported subtitle events; implement an explicit mask-to-Pillow cutout adapter or label this hook unavailable. Preserve library opt-in behavior rather than guessing file names or silently swallowing contract mismatches.

### P2-07 — Frontend component/dependency residue [S]

`src/main.tsx:2` reaches `App.tsx`, which imports only `ReviewTimeline` as a component. The old `Header`, `PipelineStepper`, `VideoPreview`, `FileDropZone`, `ProgressDisplay`, `ClipsReview`, `AttitudeSelector`, `ErrorDisplay`, `DownloadButton`, and `components/ui/*` have no path from the current app entry point. Their mutual imports are not proof of live usage. **Fix:** remove the unreachable tree after confirming there is no external consumer, then remove its Radix/CVA/clsx/lucide/tailwind-merge dependencies and regenerate the lockfile. Keep `legacyApi.ts`, which `EditorApi` actively uses. Tailwind scans the dead files, so their utility classes can also add CSS.

### P2-08 — CI omits all frontend tests and optional dependency coverage [S]

`.github/workflows/extension.yml:43` runs install/build only; neither Vitest nor Playwright runs. `:33` installs only root Python requirements; `test_discord_bot.py` and `test_capture.py` skip optional installed-adapter tests via `importorskip`. **Fix:** add `npm test`, the synthetic Playwright test, and separate lightweight optional-extra jobs for Discord/capture/scene detection; retain a base-install fallback job. Keep large ML downloads out of normal CI and mock their boundaries. Add one actual browser-to-Flask mock-provider flow; the current browser test deliberately uses `/?mock=1` and asserts zero API requests (`e2e/editor.spec.ts:45`, `:102`).

### P2-09 — Test evidence has limits; do not call assertions meaningless [S]

The audited tests contain meaningful schema, timing, pixel, failure and payload checks; no blanket claim that the suite “asserts nothing” is warranted. Specific weak evidence: demo scoring reads fixture truth (`demo/pipeline.py:98`), so top-event coverage proves plumbing rather than perception; the evaluation CI mock uses fixture IDs (`eval/pipelines.py:65`), not actual detectors. `test_perf.py:84` compares duration with the legacy implementation even though `perf/graph.py:24` retains the old output-time default and the production renderer now uses input-time cuts (`ffmpeg_runner.py:59`). **Fix:** keep clearly labelled oracle fixtures, add real adapter tests, and assert independently specified expected media timing instead of assuming two different timing modes agree. Do not weaken a failing regression to restore green CI.

### P2-10 — Helper duplication is already causing semantic drift [S]

See the consolidation table below. **Fix:** share narrow, typed primitives with explicit timeline and error contracts; avoid a universal helper with dozens of flags. Migrate one caller group at a time and retain synthetic cross-platform media tests.

### P2-11 — Stale documentation describes branch-local history as current state [S]

See the documentation matrix below. **Fix:** rewrite feature docs around the merged snapshot; move historical task validation into clearly dated appendices and link one authoritative API/capability reference. Preserve honest limitations rather than upgrading library claims into app promises.

### P2-12 — Dependency specifications drift across extras and builds [S]

Base Pillow allows `>=10` while social requires `>=10.4,<13`; caption and speech extras specify different faster-whisper floors. SAM's Git requirement has no revision; Docker installs the package by another spec. Docker installs unused `pytesseract`; implemented OCR executes Tesseract directly. Base and container dependencies are not locked. **Fix:** centralize compatible constraints, pin the SAM revision used in verification, remove unused Docker imports/packages, and generate reproducible constraints per supported Python/platform. Do not move heavy extras into base requirements. Details below.

## P3 — naming, comments and maintenance noise

1. **Dead helpers/imports:** `server/legacy.py:64` `_fmt_time` has no callers; `services/ffmpeg_runner.py:8` imports executor helpers although `render` is sequential. Remove after caller grep; retain `_seconds_to_mmss`, which is used by timestamp offsetting.
2. **Outdated infrastructure comment:** `Dockerfile:33` says “legacy in-memory job store,” but `server/store.py:10` persists SQLite. Replace with the actual reason for one worker: one queue owner and workspace lease.
3. **Task IDs as lasting architecture:** `pipeline/orchestrator.py:143`, `pipeline/providers.py:21` and many module docs refer to future EXT tasks already present in the tree. Describe the actual contract and link the integration issue rather than embedding sprint ownership in runtime code.
4. **Over-permissive frontend wire type:** `src/api.ts:40` uses `Record<string, any>` throughout normalization, allowing incompatible score/plan aliases to escape compile-time checks. Introduce small explicit wire DTOs, parse unknown JSON at the boundary, and keep compatibility conversions centralized.

## Dependency audit

This is a direct-dependency/import-reachability audit, not a Python vulnerability scan or a claim about licenses/model accuracy. The frontend install's npm audit result is recorded with validation below. Transitive packages are not mislabeled unused merely because application code does not import them.

### Python manifests and build/runtime additions

| Manifest / requirement | Used where | Needed / disposition |
| --- | --- | --- |
| `full_app/requirements.txt:1` Flask >=3 | `server/api.py:10`, app factory | Keep core. |
| `:2` google-genai >=2.29,<3 | `services/gemini_client.py`, optional narration/refinement | Keep for current Gemini default; isolate only when an offline app mode is truly wired. |
| `:3` httpx >=0.28,<1 | `services/video_understanding.py` TransportError; `capture/client.py` | Direct core import, not merely an SDK transitive dependency. Keep. |
| `:4` python-dotenv >=1 | `app.py:4`, CLI/live-smoke configuration | Keep. |
| `:5` pydantic >=2 | schemas, render/planner/privacy/audio models | Keep core; lock tested release. |
| `:6` numpy >=1.26,<3 | signals/fusion; audio/music/SAM/V-JEPA/multipov | Keep while signals default on. No unused core dependency finding. |
| `:7` opencv-python-headless >=4.10,<5 | `signals/detector.py`, OCR, privacy and SAM | Keep for current signal default; headless avoids GUI stack. |
| `:8` pillow >=10 | `social/*`; Gemini thumbnail uses PIL | Needed by thumbnail path; align floor/cap with social and tested font APIs. |
| `capture/requirements.txt:1` httpx >=0.28,<1 | `capture/client.py:4` | Needed; duplicates compatible base spec, useful for standalone capture. |
| `:2` watchdog >=4,<7 | `capture/watcher.py:102` lazy observer | Optional; polling fallback exists. Keep in capture extra. |
| `:3` websocket-client >=1.8,<2 | `capture/obs.py` lazy websocket connection | Optional OBS feature; keep out of base. |
| `capture/requirements-hotkey.txt:1` -r requirements.txt | Includes capture dependencies | Intentional composition, not a package. |
| `:2` pynput >=1.7,<2 | `capture/__main__.py` hotkey path | Optional hotkey extra; retain. |
| `discord_bot/requirements.txt:1` discord.py >=2.6,<3 | `discord_bot/bot.py:4` | Needed for optional bot, not web app. |
| `:2` aiohttp >=3.12,<4 | `discord_bot/api.py:6` | Direct dependency even though Discord also uses it. |
| `privacy/requirements-rapidocr.txt` rapidocr-onnxruntime >=1.3,<2 | `privacy/ocr.py:48` lazy engine | Optional OCR; retain outside base. |
| `render/requirements-captions.txt` faster-whisper >=1,<2 | `render/captions.py:11` | Optional captions; fallback warns. Align with audio speech extra. |
| `sam/requirements-local.txt` Git SAM2, unpinned | `sam/backends.py:107` local segmenter | Heavy optional extra; pin tested commit and document separately provisioned torch/checkpoint. |
| `social/requirements.txt` Pillow >=10.4,<13 | `social/thumbnails.py:7`, `social/__init__.py:9` | Needed standalone; currently duplicated/drifted base constraint. |
| `audio_ai/extras/speech.txt` faster-whisper >=1.1,<2 | `audio_ai/backends.py:21` | Optional, lazy, cached models by default. |
| Same: webrtcvad-wheels >=2.0.14,<3 | `audio_ai/backends.py:33` imports `webrtcvad` | Optional VAD; energy fallback exists. Distribution/import names differ intentionally. |
| `audio_ai/extras/events.txt` tensorflow >=2.16,<3 | Runtime needed by TF Hub SavedModel | Optional heavyweight runtime; not unused just because import is indirect. |
| Same: tensorflow-hub >=0.16,<1 | `audio_ai/backends.py:46` | Optional YAMNet backend; keep separate. |
| `vjepa/pyproject.toml` setuptools >=68 | Build backend | Needed to install package, not runtime. |
| Same: numpy >=1.24 | `vjepa/features.py`, `heads.py`, `train.py` | Needed standalone; align shared constraints if installed alongside app. |
| `[hf]` torch >=2.6 | `vjepa/features.py:83` | Heavy optional; keep lazy. |
| `[hf]` torchvision >=0.21 | AutoVideoProcessor ecosystem, no direct repo import | Retain until real processor dependency is checked; do not declare unused from grep alone. |
| `[hf]` transformers >=4.56,<6 | `vjepa/features.py:84` | Heavy optional; pin tested compatible model API. |
| `[modal]` modal >=1 | `vjepa/modal_app.py:6` | Optional cloud scaffold; no deployment performed. |
| `[test]` pytest >=8 | V-JEPA tests | Dev extra, not runtime. |
| `prototyping/requirements.txt` Flask >=3 | `prototyping/app.py`, `stage2.py` | Used by standalone prototypes; keep separate/archive as experimental. |
| Same: google-genai >=1 | Both prototype clients | Used; divergent from production constraint. Test separately if retained. |
| Same: python-dotenv >=1 | Both prototype env loaders | Used. |
| Same: imageio-ffmpeg >=0.5 | `prototyping/app.py:48` fallback | Used, but bundled ffmpeg does not guarantee ffprobe. Optional prototype convenience. |
| Docker-only gunicorn | `Dockerfile:20`, `:34` | Needed production server; pin in deploy constraints. |
| Docker-only pytesseract | `Dockerfile:22` | No repo import; OCR shells out to Tesseract. Remove. |
| Docker-only faster-whisper / rapidocr-onnxruntime / sam2 | `Dockerfile:21`–`:23` | Used optional backends; install shared extra manifests/constraints rather than divergent unbounded specs. |
| CI pytest / pytest-socket | `.github/workflows/extension.yml:34` | Needed dev tooling and offline enforcement; keep out of runtime. |

Optional dependencies documented/imported without dedicated manifests: `scenedetect` (`signals/detector.py:39`), `librosa` (`music/analysis.py:19`), `yt_dlp` (`ingest/urls.py:21`), `chat_downloader` (`ingest/chat.py`, lazy import). Add named extras/constraints for reproducible opt-in installs. Demucs is a user-supplied separator hook, not an implemented dependency; do not add it speculatively. System executables ffmpeg/ffprobe are required; Tesseract and espeak are optional feature/test tools. No torch/whisper/TensorFlow requirement is currently forced into the core manifest.

### Every direct frontend package

`full_app/production_frontend/package.json:13`–`:40`:

| Package | Import/use | Disposition |
| --- | --- | --- |
| @radix-ui/react-checkbox | `components/ui/checkbox.tsx` only | Unreachable UI tree; remove with P2-07. |
| @radix-ui/react-label | `components/ui/label.tsx` | Same. |
| @radix-ui/react-progress | `components/ui/progress.tsx` | Same. |
| @radix-ui/react-select | `components/ui/select.tsx` | Same. |
| @radix-ui/react-slot | `components/ui/button.tsx`, `badge.tsx` | Same. |
| class-variance-authority | UI button/badge variants | Same. |
| clsx | `components/ui/utils.ts` | Same. |
| lucide-react | Legacy components and UI wrappers | Same; current editor uses text symbols. |
| react | `App.tsx`, ReviewTimeline, JSX runtime | Keep runtime. |
| react-dom | `src/main.tsx` createRoot | Keep runtime. |
| tailwind-merge | UI `utils.ts` | Remove with unreachable UI tree. |
| tw-animate-css | `styles/tailwind.css:4` | Imported, but current editor does not use its animation utilities; remove only after CSS inspection. |
| @playwright/test | `e2e/editor.spec.ts`, playwright config | Keep dev; add CI execution. |
| @tailwindcss/vite | `vite.config.ts` | Keep build while Tailwind remains. |
| @testing-library/jest-dom | `src/testSetup.ts` | Keep dev. |
| @testing-library/react | Component/App tests and cleanup | Keep dev. |
| @testing-library/user-event | App/ReviewTimeline tests | Keep dev. |
| @types/react | TS React declarations | Keep dev. |
| @types/react-dom | createRoot declarations | Keep dev. |
| @vitejs/plugin-react | Vite and Vitest config | Keep dev. |
| jsdom | Vitest environment | Keep dev. |
| tailwindcss | CSS import and Vite plugin pipeline | Keep build; reassess after dead components are removed. |
| typescript | `build` invokes tsc | Keep dev. |
| vite | dev/build/preview scripts, Vitest integration | Keep dev. |
| vitest | test script and tests | Keep dev. |

## Duplicated helpers to consolidate

| Family | Concrete definitions/callers | Consolidation boundary |
| --- | --- | --- |
| Probe/metadata | `services/probe.py:8`, `signals/detector.py:21`, `render/engine.py:15`, `ingest/media.py:28`, `reactions/render.py:12`, `multipov/sync.py:23`, `fx/preview.py:19`, `perf/media.py`, `social/__init__.py:24`, `vjepa/features.py:45` | One timeout-bounded raw ffprobe helper plus typed adapters; preserve stream selection, attached-picture exclusion, frame-rate and duration distinctions. |
| Timestamp parsing/formatting | `server/legacy.py:9`, `:59`, unused `:64`; `social/metadata.py:20`, `:42`; frontend `src/api.ts:41`; render ASS and social SRT formatters | Share numeric/source parsing per language; keep distinct output formats explicit. Do not unify ASS/SRT rounding blindly. |
| Chunking/slicing | `services/video_understanding.py:52`, `:68`; `ingest/__init__.py:15`; `server/legacy.py:20`; prototype splitter | Shared interval math with explicit frame quantization and offset ownership; ingest's 30fps rounding is not interchangeable with arbitrary source seconds. |
| Subprocess execution | `FFmpegRunner._run`, `ingest.media.run`, `perf.media.run`, `multipov.sync.run`, `fx.preview.run`, renderer encode loop | Common timeout/cancel/stderr-redaction process runner; encoder fallback stays at encoding layer. |
| Encoder selection | `services/ffmpeg_runner.py:14`, `render/engine.py:34`, `perf/encoders.py:44` | One lazy cached capability probe with per-execution CPU fallback; avoid import-time ffmpeg execution. |
| Audio decoding/onsets/beats | `signals/detector.py:127`, `audio_ai/analyzer.py:18`, `render/analysis.py`, `music/analysis.py`, `multipov/sync.py:32` | Share bounded PCM decoding/configuration, not algorithms with different sample-rate and timing requirements. |
| OCR/name/region models | `signals/ocr.py`, `profiles/detection.py`, `privacy/ocr.py`; `privacy/profiles.py` and `profiles/registry.py` | Shared reader/geometry adapters; keep privacy masking's conservative failure policy separate from event proposal. |
| Atomic cache publication | `ingest/media.py:94`, `perf/cache.py`, `vjepa/features.py:102`, `narration/providers.py:62`, `sam/tracking.py:39` | Share atomic-file utility/retention hooks; distinguish process locks, content hashing and in-memory caches. |
| JSON response/error handling | React `src/api.ts:77`, `src/legacyApi.ts:87`; simple frontend request helpers | One browser transport with provider-key policy and abort/deadline support; keep explicit legacy endpoint adapters. |
| Plan/clip DTOs | `models/schemas.py`, `planner/models.py`, `render/plan.py`, `server/validation.py`, React legacy/review types | Versioned contracts and tested conversions rather than duplicate similarly named models. |

## Documentation and feature-claim reconciliation

| Document/claim | Current evidence | Exact correction |
| --- | --- | --- |
| `README.md:29`, `full_app/README.md:136`: split analysis in parallel | `pipeline/orchestrator.py:124` iterates segments sequentially | Say sequential; distinguish the signal detector's audio/video concurrency. |
| `README.md:46`, `full_app/README.md:110`: browser asks for API key | Simple frontend supports keys; current React App has no such control/header path | Scope promise to simple frontend or implement React key configuration. |
| `docs/api.md:83`: default preserves source by fitting/padding | New API uses v2 crosshair reframing (`render/plan.py:106`, `render/graph.py`); legacy renderer pads | Document each path, especially vertical crop, and test representative aspect ratios. |
| `docs/signals.md:27`: pipeline unchanged/unintegrated | `pipeline/orchestrator.py:88` enables candidates by default | Describe integrated defaults and the separate optional OCR/profile limitations. |
| `docs/video_models.md:165`: candidate scoring belongs to future route work | `pipeline/orchestrator.py:95` already scores candidates | Retain the still-real GOOGLE-only gate issue, remove stale scoring claim. |
| `docs/privacy.md:73`, `docs/vjepa.md:214`: profiles/signals absent | Both packages are present but not connected to these adapters | Replace “absent” with the exact missing contract/wiring. |
| `docs/e2e.md` runnable whole-pipeline demo | Harness still patches removed globals (P1-03) | Mark currently broken until the factory-based harness passes; keep oracle-quality caveat. |
| `docs/pipeline.md:35`: custom provider factory supported | Factory module `services.providers` does not exist | Name only installed providers; document an extension interface separately if retained. |
| `docs/planner.md:3` deterministic RenderPlan | Library exists; app still Gemini-plans; renderer type incompatible | Keep library claim and prominent integration boundary; add adapter version/schema before advertising app support. |
| `docs/social.md:43` final filename; SAM composition hook | Published filename differs; `sam.cutout` absent | Document job-output adapter and unavailable cutout contract (P2-06). |
| `docs/performance.md:60` legacy timing compatibility | Production legacy extraction now trims input time; perf default preserves old output time | Rename timing modes around semantics and update comparisons/expected-duration tests. |
| Privacy, narration, music generation, multi-POV, ingest URLs/chat, game profiles, V-JEPA and advanced FX | Implemented as standalone libraries/CLIs; not exposed by current route/options schema | Preserve honest standalone labels. No claim that these libraries themselves do not exist. |
| `docs/tasks/EXT-24.md` onward | Task proposals are not implementations or product documentation | Link as roadmap only; do not include proposed capabilities in current feature list. |

## Validation and remaining limits

All execution is through `tools/remote_run.sh` on the Linux runner. Commands/results will be finalized after the full suite completes. Tests generate synthetic media; no downloaded gameplay, credentials or generated media are committed.

* `bash tools/remote_run.sh "cd full_app/production_frontend && npm ci && npm run build && npm test"` — **exit 0**; strict TypeScript/Vite build passed, **14 tests passed** across three files. Install reported **0 npm vulnerabilities** for this lockfile at execution time.
* An inline Python probe run via `bash tools/remote_run.sh` — **exit 0** (probe intentionally catches failures): dataclass evaluation raised `AttributeError`; square layout raised `KeyError`; HTTP validator accepted invalid v2 effect while renderer raised `ValidationError`; dummy GOOGLE-only configuration raised the pipeline key-gate `ValueError`; raw scores 2 and 8 both became 1. No provider was created for this check.

No Docker build, real GPU/model execution, paid provider call or public-service security penetration test has been performed by this audit. Source-established risks are identified as such. All fixes remain for the integrator; this task changes only this report.
