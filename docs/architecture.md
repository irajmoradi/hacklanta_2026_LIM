# Extension architecture

This describes the DOC-01 checkout, using `server/validation.py`, `pipeline/`, and concrete module APIs as authority. Older sprint documents describe some pre-integration behavior: `use_signals` now defaults on, render v2 is the new job API default, and `ENABLE_RENDER_HOOK` is obsolete. See the [README diagram](../README.md) and [configuration](quickstart.md#configuration).

## Application path

1. `app.py` loads the repository-root `.env`, creates Flask through `server.api.create_app`, and runs one threaded process on port 8000. Local `/` serves `frontend/`; Docker replaces its index/assets with the React build. Vite proxies `/api` to port 8000 in development.
2. Multipart `POST /api/jobs` saves and probes video, then persists a job in SQLite. `server/store.py` stores snapshots/events, `server/queue.py` schedules work, and `server/ownership.py` enforces one process per workspace. Defaults: 2 worker threads, 32 active/queued jobs, 2 GiB request limit including multipart overhead.
3. `POST /api/jobs/<id>/analyze` queues analysis **and planning**. `pipeline/orchestrator.py` re-probes, calls `signals.detect_candidates`, scores windows, runs the whole-video pass, and merges results. Window scoring and discovery run sequentially; whole-video discovery is not merely an empty-candidate fallback.
4. `pipeline/ranking.py` clamps signal scores to [0,1]. Scored windows use `0.35 * signal + 0.65 * hype / 10`. Dead/unknown POV windows veto overlapping results from both sources. Alive neutral windows are omitted; whole-video clips default to 0.5. Ranking suppresses overlap covering at least half the shorter interval and regenerates IDs.
5. `Pipeline.plan_edit` formats `prompts/editor.txt` and requests the legacy segment schema. Local VLM analysis delegates planning to Gemini. Selected clip order reaches the planner, which may reorder it. An explicit `edit_plan` controls final order and skips AI stages.
6. `pipeline/rendering.py` converts compatible legacy segments into `render.plan.RenderPlan`. Legacy timing/effects requiring preparation are baked first and durations re-probed. Render v2 handles framing, captions, titles, transitions and supplied music. Reactions run per rendered clip with a configured pack; optional SAM spotlight adds a 0.6-second freeze to the top three scored segments. The final file is atomically published as `output.mp4` in the job directory.

Generated thumbnails and legacy source-sized output retain the compatibility render path. Missing render v2 imports fall back to the legacy renderer. V2-only options are not guaranteed in those paths.

## Job protocol and recovery

| Action | Endpoint / result |
| --- | --- |
| Upload | `POST /api/jobs`, multipart `video`; 201 with `id` |
| Analyze + plan | `POST /api/jobs/<id>/analyze`, JSON options; 202 |
| Replan | `POST /api/jobs/<id>/plan`; 202, analyzes if needed |
| Review | `GET /api/jobs/<id>`; snapshot with clips, candidates, plan, warnings and error |
| Edit | `PATCH /api/jobs/<id>/clips`, `{"clips":[...]}`; desired order, bounds, IDs and `keep` |
| Render | `POST /api/jobs/<id>/render`; 202, runs missing prerequisites unless explicit plan supplied |
| Progress | `GET /api/jobs/<id>/events`; SSE, resume with `Last-Event-ID` or `?after=N` |
| Download | `GET /api/jobs/<id>/download`; MP4 when `done` |
| Cancel | `POST /api/jobs/<id>/cancel`; cooperative at stage boundaries |
| Delete | `DELETE /api/jobs/<id>`; 204, or 409 while worker remains active |

Snapshots/events commit atomically. Restart resumes interrupted admitted jobs at the first missing checkpoint. Identical busy requests share work; conflicts/full admission return 409. Changing analysis invalidates downstream stages; editing clips/style invalidates plan/render; render flags invalidate rendering. A crash between response and checkpoint can repeat a provider call. Cancellation does not interrupt an in-flight provider/FFmpeg operation; its result is discarded before another stage starts.

SSE reports coarse progress plus `pipeline_stage` and `timings`, not an ETA. Streams remain open after completion to observe edits, send heartbeats, and close on deletion. Proxies must allow long-lived streams without buffering. Legacy blocking upload/analyze/plan/render and status/download/stream/log routes use the same queue; see [API](api.md).

Request keys stay in memory, not SQLite/SSE; resend after restart. Paths/credentials are excluded from public snapshots. Sources and outputs have no automatic expiry: delete jobs explicitly. Scratch files are cleaned after rendering. One workspace permits **one OS process**: no reloader, multi-worker Gunicorn or preload-before-fork. The API has no authentication/tenant isolation and is intended for trusted users.

## Integration boundaries

| Module / guide | Implementation | Current app boundary |
| --- | --- | --- |
| [Ingest](ingest.md) | CFR, proxy, chunks, owned URL downloads, replay chat | CLI/library preprocessing; Flask takes files |
| [Signals](signals.md) | Scene, RMS/onsets, motion, optional OCR | Cheap defaults wired; HTTP has no OCR/threshold option |
| [Profiles](game_profiles.md) | HUD geometry, vocabulary, detection, prompts | Shared registry not wired into default detector/provider |
| [Audio AI](audio_ai.md) | Activity/excitement proxies, optional Whisper/YAMNet | Needs explicit aggregation into candidates |
| [V-JEPA](vjepa.md) | Features, training, scoring scaffold | Provision weights/head and fusion adapter; disabled by default |
| [Video models](video_models.md) | Gemini chunking/cache/retries; local JPEG/schema adapter | `provider` selector; local server needs multi-image/schema support, no audio supplied |
| [Planner v2](planner.md) | Deterministic pacing/placements; wording refinement | Not automatic; planner and renderer schemas differ |
| [Rendering](rendering.md) | V2 timeline, presets, captions, framing, music | New job default; advanced fields need explicit plan |
| [FX](fx.md), [performance](performance.md) | Extended filters, encoder probes, caches, parallel helpers | Standalone APIs; no HTTP enable flag |
| [Reactions](reactions.md), [SAM](sam.md) | Pack overlays, subject tracks, segmentation effects | Integrated flags; SAM defaults to CV fallback |
| [Privacy](privacy.md) | OCR/manual boxes and source prepass | Explicitly sanitize before upload to protect source pixels sent to providers |
| [Music](music.md) | Procedural or licensed-library beds | Generate/select explicitly, supply `music.path` |
| [Narration](narration.md) | Script/TTS scheduling, ducking | Post-render hook; network off unless `allow_network=True` |
| [Multi-POV](multipov.md) | Audio alignment, shared highlights | Standalone timeline/render API; no multi-file job route |
| [Share kit](social.md) | MP4, covers, titles, chapters, optional SRT | Explicit post-render call; no kit endpoint or publishing |
| [Discord](discord_bot.md) | Allowed-channel submissions/progress/delivery | Separate process; allowlisted direct HTTPS video, not watch pages |
| [Capture](capture.md) | Stable-file watcher, OBS replay/hotkeys | Separate desktop process; upload + analyze/plan, then manual review/render |

Planner v2 emits `version: 2`, `clips`, effects and placements. Render v2 accepts `render_version: 2` and `segments`. They need a timeline/effect adapter, not a renamed version field. The share library defaults to old filenames: queued jobs need `plan["social"]["video_path"] = "output.mp4"` and the actual rendered timeline. Source overrides must stay within the job directory. Social expects a list of timed captions, not the renderer's caption-settings object.

## Clocks, fallback and quality

Source cuts are absolute seconds with exclusive ends. Render words/tracks are clip-local. SAM source times are converted to local times; prepared legacy clips are re-probed after speed changes. Reaction peaks are clip-local; narration reaction intervals and share-kit captions are final montage time. Freeze effects, cards, speed and overlaps change that timeline; exporters must account for actual durations.

Optional ML imports are lazy. Missing hooks/imports generally warn and fall back; exceptions from installed pipeline callables fail the stage with sanitized errors. Captions use cached faster-whisper weights, otherwise retain supplied words without transcription. SAM can fall back to CV masks. Inspect warnings: render success does not prove an optional model ran.

Synthetic tests validate contracts and FFmpeg output, not gameplay accuracy. OCR can miss or misattribute kills; motion/audio are heuristics; valid VLM JSON does not guarantee perception. See [research](RESEARCH.md), [evaluation](eval.md) and [offline demo](e2e.md). Ordinary tests need no weights or paid API calls.
