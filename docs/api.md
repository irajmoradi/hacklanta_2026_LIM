# Job API (EXT-03)

Run `cd full_app && python app.py`; the API and simple frontend are on port 8000.
The development server binds `127.0.0.1`. Without application tokens, only literal
loopback peers can call the API; forwarded headers are not trusted. Configure
`LIM_API_TOKEN` (one identity named `default`) or `LIM_API_TOKENS` (a JSON object
mapping stable owner names to distinct tokens) for shared use. Tokens must have
32-4096 visible ASCII characters and come from the runtime environment. Send
`Authorization: Bearer <token>` on every API request except `/api/health`.
Each job belongs to its uploader; other identities receive 404 on every job,
media, SSE and action route, including legacy aliases. Existing ownerless jobs
remain local-only. Provider keys do not authenticate application users.

Compose publishes `127.0.0.1:8000:8000`. Container bridge peers are not loopback,
so Compose clients must use an application token. The browser UI does not yet
supply bearer headers for fetch/video/EventSource/download; use authenticated
API clients or an authenticated proxy until frontend transport support lands.
See [security.md](security.md) for deployment and resource limits.
Deploy one process per workspace, with multiple request threads. An OS file lock
rejects a second process sharing that workspace; do not use a Flask reloader,
multiple Gunicorn workers, or preload the app before forking.

## Workflow

FINAL-1 planning options: `chaos` is a finite number from 0 to 1 (defaults .35
nice / .6 mean); `seed` is an integer from 0 to 4294967295 (default 0). Changing
either invalidates the plan and rendered output while retaining analysis. Status
returns `seed` and the full plan with VFX/SFX assignments. To reroll without paid
calls after analysis, POST `/api/jobs/<id>/plan` with
`{"planner":true,"editor_agent":false,"chaos":0.6,"seed":2027}`.
Keep other options unchanged to reuse analysis. A failed local replan does not
fall back to a paid provider.

Reaction options: `reaction_size` is `small`, `medium`, or `large` (default);
`clean` is boolean (default false). These invalidate rendering only. Clean
excludes pack clips marked explicit. Nice prefers non-explicit; mean allows both.

| Method / path | Input | Result |
| --- | --- | --- |
| `POST /api/jobs` | Multipart `video` | 201, job snapshot with `id`, `job_id`, metadata |
| `POST /api/jobs/<id>/analyze` | JSON options below | 202; queue analysis and planning |
| `POST /api/jobs/<id>/plan` | JSON options | 202; plan from selected clips, analyzing if needed |
| `GET /api/jobs/<id>` | None | 200, current snapshot |
| `PATCH /api/jobs/<id>/clips` | `{"clips": [...]}` | 200; replace selection/order and invalidate plan/output |
| `POST /api/jobs/<id>/render` | `{"preset":"vertical"}` | 202; queue missing analysis/plan stages and render |
| `GET /api/jobs/<id>/download` | None | MP4 attachment when status is `done`; otherwise 404 |
| `GET /api/jobs/<id>/events` | Optional `Last-Event-ID` header or `?after=N` | Replayable SSE stream |
| `POST /api/jobs/<id>/cancel` | No body required | 200; persist cancellation immediately |
| `DELETE /api/jobs/<id>` | None | 204; remove job, events, source and outputs; 409 while worker is active |

Analysis options (all optional):

```json
{
  "mode": "nice",
  "style": "hype_montage",
  "provider": "gemini",
  "use_signals": false,
  "captions": false,
  "reactions": false,
  "sam": false,
  "prompt": "Find the best clutches",
  "splits": 1,
  "max_duration": 180
}
```

`mode` is `nice` or `mean`. Styles are `hype_montage`, `clean_edit`, `meme_edit`,
and `cinematic` (also returned by `/api/info`). Splits must be integers 1–4;
maximum planned duration is 1–3600 seconds. Boolean flags require JSON booleans.
Unknown fields, invalid timestamp bounds and nonfinite numbers are rejected.
JSON bodies must be objects; use `{}` for defaults. Keys come from
`GEMINI_API_KEY` or `X-API-Key` (legacy `api_key` body also accepted). Request keys
are held in memory for subsequent stages and never written to the job database
or included in status/events. They must be supplied again after a process restart.

Snapshot fields include `status`, `stage`, `target`, `completed`, `progress`,
`meta`, `options`, `candidates`, `clips`, `plan` (alias `edit_plan`), `warnings`,
`error`, `elapsed`, timestamps, `has_clips`, `has_plan`, `has_output` and
`download_url`. Filesystem paths and credentials are excluded. `progress` is a
coarse stage fraction (0–1), not an estimate of remaining time. `elapsed` records
worker time through its most recent completed stage. Statuses are `uploaded`,
`queued`, `analyzing`, `analyzed`, `planning`, `planned`, `rendering`, `done`,
`error`, and `cancelled`.

## Editing and rendering

Use clip IDs returned by analysis. Supply the desired clips in the desired order;
omitting an ID drops it, and `keep: false` retains it in the UI but excludes it
from planning. Every supplied clip needs `id`, `start_seconds`, `end_seconds`;
metadata from the existing clip is preserved. Bounds must fit the source duration.

```json
{
  "clips": [
    {"id": "1", "start_seconds": 22.5, "end_seconds": 27.8, "keep": true},
    {"id": "0", "start_seconds": 4.0, "end_seconds": 8.0, "keep": false}
  ]
}
```

Planning receives selected clips in this order; the AI planner may reorder them
according to the chosen style. For exact final sequence control, render accepts
an explicit `edit_plan` with ordered `segments` (`source_start`, `source_end`,
optional `speed` between 0.1 and 8, and the existing effects fields). An explicit
plan can render without analyzing or calling a provider. Plans require 1-100
segments. There must be at least one selected clip for automatic planning.

New render routes default to `landscape` (1920×1080); `vertical` is 1080×1920 and
`square` is 1080×1080. The v2 renderer defaults to crosshair-centered reframing (cropping to the output
aspect ratio); select `reframe: "blur"` in an explicit v2 plan for a fitted foreground.
The legacy renderer fits and pads. `generate_thumbnails` defaults to false for the new API and true for the
legacy render route, preserving the old checkbox behavior. Thumbnails make extra
provider calls; disable them in offline tests. The legacy route retains source
dimensions unless a preset is provided.

## Queue, restart, and cancellation semantics

SQLite atomically saves each job snapshot and its progress event. Completed
analysis, plan and render stages are checkpointed. Repeating an unchanged request
reuses its checkpoints; identical requests while busy share the existing task.
Conflicting actions or a full queue return 409. Changing analysis inputs
invalidates downstream checkpoints; changing style invalidates plan/render;
changing render options invalidates only render. Clip edits invalidate plan/render.

On startup, queued or interrupted jobs resume at their first missing stage.
External provider calls cannot be guaranteed exactly once: a crash between the
provider response and the SQLite checkpoint can repeat that call. Render output
is atomically published to a fixed job path. Failed jobs keep completed
checkpoints; resubmit the appropriate endpoint to retry. Cancelled jobs stay
cancelled across restarts; explicitly resubmitting an endpoint resumes them.

Injected-pipeline cancellation is cooperative at stage boundaries: an already running provider or
FFmpeg operation can finish, but its result is discarded and no following stage
starts. A cancelled render's new output is removed. Wait until the worker exits
before retrying/deleting (otherwise 409). Sources and finished outputs remain
until deletion or inactive-job retention expiry. Intermediate render files, split files and failed
uploads are cleaned; startup also removes abandoned upload directories and
intermediate files owned by the backend. Inactive jobs expire after seven days.

## Server-Sent Events

```text
id: 12
event: progress
data: {"id":"...","status":"planning","stage":"plan","progress":0.3333333333333333,"error":null,"updated_at":1791800000}

```

Events use database sequence IDs. Reconnect with `Last-Event-ID: 12` to receive
only later events for that job. Active streams heartbeat once per second and
close after 30 seconds; inactive and terminal streams close after replay. Reopen
on actions and use snapshot polling while disconnected. Proxies should disable
buffering; they must permit the bounded connection lifetime.

## Optional module contracts

Modules are loaded only when their flag is enabled. Missing imports, including
missing optional dependencies, fall back with a warning in the job snapshot.
Exceptions from an installed callable fail the stage with a sanitized error;
they are not silently ignored. Modules must return JSON-serializable metadata
and must not store credentials in the job.

| Flag / option | Current application contract |
| --- | --- |
| `use_signals: true` | `signals.detect_candidates` proposes windows; optional VLM scoring contributes to ranking |
| `provider: local` or `local_vlm` | `pipeline.providers.LocalClient`; planning still uses Gemini |
| `captions: true` | v2 `render.captions` transcribes/renders clip-local words |
| `reactions: true` | `REACTION_PACK`, `ReactionSelector`, `apply_reaction` |
| `sam: true` / `sam_reframe: true` | `sam.render_effect` / `sam.subject_track` |
| Default rendering | `render.engine.Renderer`, with legacy preparation when needed |

There is no installed `services.providers` factory. Unknown provider names still
fall back to Gemini in the current pipeline; fixing that provider-resolution
contract belongs to P1-09 outside this server task. Do not advertise a custom
provider extension API. Heavy ML dependencies remain optional.

## Legacy compatibility and errors

`/api/upload`, `/api/analyze`, `/api/plan`, `/api/render`, `/api/status/<id>`,
`/api/download/<id>`, `/api/stream/<id>`, `/api/log/<id>` and `/api/info` remain.
The three legacy stage POSTs take `job_id` and block until their requested stage
finishes, returning the existing `clips`, `edit_plan`, `elapsed`, `splits` and
`download_url` fields as applicable. `attitude` maps to `mode`; `edit_style` maps
to `style`. Log output is structured JSON lines of persisted state transitions.
Original in-memory jobs from the old server cannot be recovered; upload again.

Errors are JSON `{"error":"..."}`: 400 validation, 404 unknown job/unavailable
output, 409 conflicting state/full queue, 413 upload limit, 415 non-JSON body.
Asynchronous stage failures are reported via status/SSE with `status: "error"`;
legacy stage failures return 500. Provider exception details are not persisted
because they can include credentials. The default upload limit is 2 GiB including
multipart overhead; configure `MAX_UPLOAD_BYTES`. `JOB_WORKSPACE` selects durable
storage; `JOB_WORKERS` selects worker threads (default 2); admission is limited to
32 active/queued jobs, except recovery of already admitted jobs.

Tests (Linux runner, synthetic media, no paid calls):

```bash
tools/remote_run.sh "cd full_app && python -m pytest -q"
```


## Admission, streaming and resource bounds (FIX-1)

`edit_plan` accepts legacy `segments` (optional `render_version: 1`) or an explicit
`render_version: 2` renderer plan. The boundary rejects unknown fields, invalid
nested types/effects/SFX names/offsets, source overruns and excessive collections
before the queue or checkpoints change. The shipped review UI alias `caption`
is normalized to `title`; conflicting values are rejected. Per segment: at most 16 unique video
effects, 32 sounds, 1000 words, 500 track points and 20 advanced FX. Titles and
individual words are at most 200 characters. Legacy speed effects are validated
through their prepared v2 metadata representation. Both schemas use at most 100
segments. The separate planner `version`/`clips` schema is not an HTTP schema.

The effective `max_duration` defaults to 180 seconds and accepts 1-3600. Admission
accounts for speed effects, frame quantization and v2 card/transition duration;
generated plans pass the same boundary before their checkpoint/render. Production
also measures the final output (0.1-second codec tolerance) and rejects optional
processing that exceeds the cap. Client music filesystem paths are rejected;
`music: true` at the **request options** level uses the server's generator. There
is no authorized music asset-upload/ID API yet.

SSE drains replay then closes inactive/terminal jobs. Active streams send heartbeats
every second and close after 30 seconds. At most eight streams are admitted;
excess subscribers receive 429/Retry-After. Clients should reopen when actions
start, resume using Last-Event-ID, and poll snapshots after disconnects. Events
are limited to the newest 1000 per job, so clients must fetch a snapshot when
resuming an old cursor. Docker uses one Gunicorn queue owner and 16 request
threads; keep request threads strictly above the configured SSE limit.

Uploads require Content-Length, reserve the full multipart length before parsing,
and allow two concurrent uploads. All team recordings pass bounded probing,
container signature, duration, pixel, FPS, pixel-rate and frame-count checks.
JSON action bodies are limited to 2 MiB. Default limits (override through
`LIM_<NAME>` integer environment variables or factory config):

| Config name | Default |
| --- | --- |
| MAX_CONTENT_LENGTH | 2 GiB (`MAX_UPLOAD_BYTES` also supported) |
| MAX_MEDIA_DURATION / MAX_MEDIA_FRAMES | 43200 seconds / 3000000 frames |
| MAX_MEDIA_PIXELS / MAX_MEDIA_FPS / MAX_MEDIA_PIXEL_RATE | 3840x2160 / 120 / 3840x2160x60 |
| MAX_JOBS / MAX_UPLOADS | 200 / 2 |
| WORKSPACE_BYTES / OWNER_BYTES / JOB_BYTES | 20 / 10 / 4 GiB |
| DISK_HEADROOM_BYTES | 512 MiB |
| JOB_TTL_SECONDS / RETENTION_INTERVAL | 7 days / 60 seconds |
| PROBE_TIMEOUT_SECONDS / PROBE_MEMORY_BYTES | 20 seconds / 1 GiB |
| STAGE_TIMEOUT_SECONDS / STAGE_MEMORY_BYTES | 1800 seconds / 8 GiB |
| SSE_MAX_SECONDS / SSE_MAX_SUBSCRIBERS / SSE_INTERVAL | 30 / 8 / 1 |

Retention removes inactive jobs, artifacts and events; active workers are excluded.
Production stages execute in isolated child process groups. Deadline, cancellation
or monitored storage exhaustion kills the group, including FFmpeg descendants;
scratch/partial published output is removed. Linux applies per-process address-space
and per-file limits; Compose additionally caps aggregate memory at 12 GiB and PIDs
at 256. Quota monitoring can overshoot between 0.2-second polls; provision a volume
hard quota for strict aggregate storage guarantees. Windows lacks the Linux memory
limits and its taskkill tree cleanup has not been verified on the Linux runner.
Injected pipelines keep cooperative cancellation; `TESTING=True` preserves offline
mocks in-process unless `ISOLATE_STAGES=True` is explicitly selected. Isolated
progress reports contain only stage, timings and warnings; keys travel over stdin,
never through the progress file or command line. A forced stop may prevent a
provider's remote-file cleanup; configure provider-side retention separately.
