# Job API (EXT-03)

Run `cd full_app && python app.py`; the API and simple frontend are on port 8000.
This is a local, trusted-user service with no authentication or tenant isolation.
Deploy one process per workspace, with multiple request threads. An OS file lock
rejects a second process sharing that workspace; do not use a Flask reloader,
multiple Gunicorn workers, or preload the app before forking.

## Workflow

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
plan can render without analyzing or calling a provider. Plans require 1–500
segments. There must be at least one selected clip for automatic planning.

New render routes default to `landscape` (1920×1080); `vertical` is 1080×1920 and
`square` is 1080×1080. The default renderer fits and pads to preserve source aspect
ratio. `generate_thumbnails` defaults to false for the new API and true for the
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

Cancellation is cooperative at stage boundaries: an already running provider or
FFmpeg operation can finish, but its result is discarded and no following stage
starts. A cancelled render's new output is removed. Wait until the worker exits
before retrying/deleting (otherwise 409). Sources and finished outputs remain
until explicit deletion. Intermediate render files, split files and failed
uploads are cleaned; startup also removes abandoned upload directories and
intermediate files owned by the backend. No automatic source expiry is enabled.

## Server-Sent Events

```text
id: 12
event: progress
data: {"id":"...","status":"planning","stage":"plan","progress":0.3333333333333333,"error":null,"updated_at":1791800000}

```

Events use database sequence IDs. Reconnect with `Last-Event-ID: 12` to receive
only later events for that job. The stream sends heartbeat comments when idle
and stays open at completed stages so the same connection can observe subsequent
edits/renders. Disconnect it when leaving the UI. Deleting a job closes its stream.
Reverse proxies should disable buffering and allow long-lived connections.

## Optional module contracts

Modules are loaded only when their flag is enabled. Missing imports, including
missing optional dependencies, fall back with a warning in the job snapshot.
Exceptions from an installed callable fail the stage with a sanitized error;
they are not silently ignored. Modules must return JSON-serializable metadata
and must not store credentials in the job.

| Flag / option | Import contract |
| --- | --- |
| `use_signals: true` | `signals.detect_candidates(source_path)` → candidate list, added to the analysis prompt |
| `provider` other than `gemini` | `services.providers.get_provider(name, api_key=key)` → client implementing `upload_video`, `find_clips`, `plan_edit`; optional `generate_thumbnail` |
| `captions: true` | `captions.apply(job=job, plan=plan, workspace=path)` → updated plan |
| `reactions: true` | `reactions.apply(job=job, plan=plan, workspace=path)` → updated plan |
| `sam: true` | `sam.apply(job=job, plan=plan, workspace=path)` → updated plan |
| Environment `ENABLE_RENDER_HOOK=1` | `render.render_job(job=job, plan=plan, workspace=path)` → path to rendered MP4 |

Missing custom providers fall back to the default Gemini client and record a
warning. Missing signals/effect hooks leave that feature inactive. No heavy ML
dependencies are added to the base installation. Hook adapters may be needed when
integrating other sprint branches with different function signatures.

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
