# Agentic editor (AGENT-01)

The editor refines a planner v2 draft using stored analysis and explicit Gemini function calls. It is opt-in: existing analyze → plan → render behavior stays the default. Implementation is in `full_app/editor_agent/`; queue/API integration is in `full_app/server/`.

## Try it

Set `GOOGLE_API_KEY` in the server environment. The editor uses Vertex express through the existing `services/provider_config.py` credential selector, with model `gemini-3.5-flash-lite`. No credential is stored in jobs, logs, traces, or source files.

1. Upload a video and analyze it as usual. To include an agent pass after planning, send `{"planner":true,"editor_agent":true,"mode":"nice","max_duration":60,"preset":"landscape"}` to `POST /api/jobs/<id>/analyze` (or `/plan` after analysis). `editor_agent` enables planner v2 automatically.
2. For chat edits, send `POST /api/jobs/<id>/agent` with `{"instruction":"make it 30 s; cut the slow buy phase"}`. The request waits for the bounded worker and returns the plan and trace. Open the job's SSE stream concurrently to show progress.
3. Render the stored result through the existing `POST /api/jobs/<id>/render` with `{"preset":"landscape"}`. Agent edits invalidate the old output.
4. `POST /api/jobs/<id>/agent/undo` restores the previous plan and its render settings. It invalidates output; render again to view it. Up to 20 previous versions are retained.

Existing application bearer authentication and job ownership apply to both endpoints. Provider keys are separate from application tokens. Empty/oversized instructions return 400; busy jobs, queue capacity, no analysis, and unavailable undo return 409. The instruction limit is 8,000 characters. Requests are serialized per job, but SSE and cancellation remain available while the model runs.

## Response and SSE contract for AGENT-02

Successful HTTP delivery returns 200 even when the model falls back. Inspect `fallback` and `reason` before telling the user an edit was applied:

```json
{
  "plan": {"render_version": 2, "segments": [{"source_start": 1, "source_end": 4}]},
  "trace": [],
  "settings": {"music": false, "reactions": false},
  "summary": "Tightened the opening",
  "fallback": false,
  "reason": null,
  "calls_remaining": 9,
  "version": 1
}
```

`version` is a monotonically increasing integer for applied chat edits and undo. Undo returns `{plan, trace, version}`. Job status also exposes `agent_trace`, `agent_result`, and `agent_version`. An in-flight chat uses status `editing` and stage `agent`. Cancellation prevents publication; the prior plan remains stored. After a process restart, an interrupted chat is marked planned/analyzed with a recovery message, without automatically making paid calls.

`GET /api/jobs/<id>/events` retains existing `event: progress` messages and adds:

```text
id: 42
event: agent_step
data: {"event":"agent_step","step":2,"tool":"trim_clip","args":{"clip":0,"t0":1,"t1":4,"rationale":"Cut quiet setup"},"rationale":"Cut quiet setup","diff":{"plan":{"before":{"render_version":2,"segments":[{"source_start":0,"source_end":5}]},"after":{"render_version":2,"segments":[{"source_start":1,"source_end":4}]}}},"error":null,"result":{"plan":{"render_version":2,"segments":[{"source_start":1,"source_end":4}]},"settings":{"music":false,"reactions":false}}}
```

The SSE id is the existing globally increasing database sequence; `step` restarts at 1 for each agent run. Replay with `Last-Event-ID` or `?after=<id>`. Tool failures include `error`; successful reads have an empty `diff`. Changes use whole before/after values for changed `plan`/`settings` keys, not JSON Patch operations. `result` holds tool output, including structured video critiques. A step shows a *tentative* edit: use the final HTTP response/job result to determine whether the run committed or rolled back. Undo emits an `agent_step` with `tool: "undo"` and the restored plan. Existing event retention is 1,000 events per job.

## Tools and clocks

Every argument model rejects unknown fields and nonfinite times. Each mutation validates the entire plan against the existing admission rules, source bounds, placement clocks, and max duration. Invalid edits roll back atomically and return an actionable error to the model.

| Tool | Arguments and behavior |
|---|---|
| `list_candidates` | Optional `filter` string; searches stored clip metadata, falling back to raw candidates; at most 500 rows. |
| `inspect_window` | `t0`, `t1` in absolute source seconds; overlapping candidates, clips, scores and transcript, plus stored audio signals. No paid analysis. |
| `add_clip` | `t0`, `t1` inside the source; appends a clip. |
| `remove_clip` | `clip`, the current zero-based segment index; cannot leave an empty plan. |
| `trim_clip` | `clip`, `t0`, `t1`; must shrink within the existing clip. Retimes/clips text, reaction, effect, word and sound placements. Trimming tracked/FX clips is rejected. |
| `reorder` | `order`, a permutation of all current segment indices. |
| `set_transition` | Global `name`: cut, fast_zoom, whip, flash, glitch; optional `duration` (0.05–1 seconds). |
| `add_reaction` | `clip`, supported `label`, optional `speaker`, `start`, `duration`. Speaker creates visible attribution text; no generated speech or speaker identity inference. |
| `add_caption` | `clip`, `text`, optional `start`, `duration`; enables captions. |
| `set_music` | `enabled` boolean; toggles the trusted built-in bed provider. Model-selected filesystem paths are forbidden. |
| `render_preview` | Renders the current revision at 360p/15fps using the performance renderer and `perf.Cache.proxy`. Cached by plan/settings. |
| `watch_preview` | Requires a current preview. Sends the proxy to Gemini once per revision, caches its structured critique, and rejects stale previews after edits. |
| `finish` | Required `summary`; publishes the validated plan at the end of the run. |

Each tool accepts an optional `rationale`. Clip indices change after removal/reordering. Caption/reaction placement seconds are local to the speed-adjusted clip. Rendering reuses effects, captions, transitions, audio, and configured reaction packs. There is no optional keyframe strip yet; window inspection returns stored evidence. Reaction assets require `REACTION_PACK`, as in the existing renderer. Without it, reaction placements remain in the plan and speaker attribution captions can still render.

Vertex express does not offer the Developer File API. The proxy is sent inline once per revision, respecting the existing provider's 20 MiB inline limit. Repeated watches return the cached critique without another upload or paid critique. The cache also persists across chat requests, keyed by the proxy's SHA-256 digest. Critiques contain exactly `pacing`, `dead_air`, `repeated_kills`, `missing_context`, and `reaction_timing` strings. They are model judgments, not measured correctness guarantees.

## Budgets, fallback, and limits

`EDITOR_AGENT_CALL_BUDGET` defaults to 12 (0–100). Calls use the existing job `gemini-budget.sqlite3`, so prior analysis/planning calls count against the editor's ceiling; retrying chat, undoing, or restarting never resets it. This is the editor's admission ceiling against the shared ledger; it does not retroactively change the analysis provider's separately configured limit. Configure `MAX_GEMINI_CALLS_PER_JOB` consistently when requiring the same ceiling across every pipeline stage.

One decision costs one reservation; a new video critique costs another. SDK automatic tool execution and request retries are disabled. Exhaustion, provider/render failure, cancellation, or failure to call `finish` retains the exact starting plan. When there is only stored analysis, a deterministic planner v2 draft is created first and retained as the fallback. The existing current plan takes precedence on chat follow-ups. Incompatible legacy effects fail closed and preserve their original plan.

Automatic runs allow 16 decision steps, chat 8; Flask config `EDITOR_AGENT_CHAT_STEPS` changes chat's bound. `run_agent(..., max_steps=..., call_limit=...)` supports direct callers. `EDITOR_AGENT_MODEL` changes the model. Flask config `EDITOR_AGENT_MODEL_FACTORY` injects a scripted model for tests. Preview rendering runs within the queue worker; cancellation is checked at model/tool boundaries, not mid-FFmpeg command. Full production isolation of preview FFmpeg and privacy/multipov preview composition are future work. The final production render still uses its normal pipeline. No frontend changes are included.

## Live smoke evidence — runner 1, 2026-10-12

Ran the explicit live entrypoint `EDITOR_AGENT_LIVE=1 ../.venv/bin/python -m editor_agent.smoke` from `/srv/lim/lim-agent01/full_app` on runner `104.207.133.47`; exit **0**. Code/dependencies were synced through `tools/remote_run.sh`. The local authorized `.env` was sourced only at launch; `GOOGLE_API_KEY` was piped over SSH into the runner process environment without a credential file or command-line value. No key is included in evidence. The smoke made **10 calls total**: 8 tool decisions plus 2 critiques. It reused `/srv/demo_out/demo02/analysis.json` and `/srv/demo_in/valorant_phoenix_44k.mp4`, making no new source-analysis calls. The full before/after plans, trace and budget ledger are local ignored artifacts in `full_app/editor_agent/smoke_artifacts/`.

Trace:

1. `list_candidates`: inspect stored candidates and identify repeated opening/ending clutch.
2. `remove_clip {clip:0}`: remove the repeated opening clutch teaser.
3. `render_preview`: render the first revision.
4. `watch_preview`: critique reported no dead air/repeated kills, but an abrupt pistol-round context change near output 00:09.
5. `trim_clip {clip:0,t0:647,t1:655}`: tighten the opening of the revised draft.
6. `render_preview`: render the second revision.
7. `watch_preview`: critique reported no pacing, dead-air, repeated-kill, context, or reaction-timing issues.
8. `finish`: publish the tightened draft. No invalid tool calls; no fallback.

The model's second critique approved the draft; this is evidence that the watch/revise loop ran, not proof that every editorial judgment is accurate.

| Before source cut | After source cut | Speed |
|---|---|---|
| 1676.4–1678.4 | removed | 1× |
| 646–656 | 647–655 | 1× |
| 58–66 | unchanged | 1× |
| 564–574 | unchanged | 1× |
| 912.5–917.5 | unchanged | 0.5× |
| 1404–1414 | unchanged | 1× |
| 1675–1680 | unchanged | 0.5× |

Output duration: **60 → 56 seconds**. Music and reaction-pack overlays were disabled for this smoke. Tests use only scripted models and synthetic FFmpeg video.

## Validation

Commands and final results are recorded below after the runner suite completes.
