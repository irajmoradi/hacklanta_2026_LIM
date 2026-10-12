# Frontend v2 (EXT-05)

Run `npm ci` and `npm run dev` in `full_app/production_frontend`, then open the Vite URL (normally http://localhost:5173). The development proxy sends `/api` to Flask on port 8000. For deployment, serve `dist/` behind the same origin as `/api`; the backend serving configuration is outside this task.

- Default `/`: new EXT-03 jobs API.
- `/?mock=1`: deterministic, network-free fixture analysis and simulated render. Upload any local gameplay video to review playback. The fixture describes a 60-second source, so use a source at least that long for all three demo ranges. No sample copyrighted media is bundled. Demo mode intentionally offers no fake montage download.
- `/?legacy=1`: original upload/analyze/plan/render/status endpoints. Source playback uses the uploaded local file. Rendering calls the planner for effects, then enforces reviewed ranges/order in its segments. Only landscape and Gemini are supported; advanced feature controls are disabled. Captions are review metadata in this mode, not a burned-in caption guarantee. The backend must have its API key configured.

## Workflow

Drop or choose a video (up to 2 GB); choose game/profile, nice hype or mean roast, style, provider and feature flags. Analyze, then use interest/candidate markers or the seek slider to navigate. Each clip has a thumbnail (server image or a muted source-video frame), editable caption, score, reaction label, reversible keep/drop checkbox, separate in/out trim sliders and range preview. Slider handles have keyboard support. Reorder by dragging, or use the up/down buttons. Edits survive incoming progress snapshots. Save explicitly or render to save automatically. Landscape, vertical 9:16 and square presets are sent to the backend; completed renders have preview and download controls.

Uploading a new source creates a new job and replaces the local review; reanalysis replaces clip edits. Rendering disables editing. Browser support for source codecs varies; H.264 MP4 is the most portable. Local object URLs and progress subscriptions are cleaned up when replaced/unmounted. Job reload/resume selection is not implemented.

## API contract and integration assumptions

The typed client is `src/api.ts`; original endpoint helpers remain in `src/legacyApi.ts` and are re-exported for existing components. Mode selection is explicit and never silently switches a paid analysis to another backend.

| Request | Payload / expected response |
| --- | --- |
| `POST /api/jobs` | Multipart `video`; response job snapshot or `{job_id, meta}` |
| `POST /api/jobs/:id/analyze` | `{game, profile, mode, style, provider, use_signals, captions, reactions, sam}` |
| `GET /api/jobs/:id` | Job snapshot (optionally wrapped in `job`) |
| `PATCH /api/jobs/:id/clips` | `{clips: [...]}` including stable `id`, `keep`, `start`, `end`, `start_seconds`, `end_seconds`, `caption` and zero-based `order`; array order is export order |
| `POST /api/jobs/:id/render` | `{preset: 'landscape' \| 'vertical' \| 'square'}` |
| `GET /api/jobs/:id/events` | SSE; default messages and named progress/status/job/complete/done events trigger authoritative snapshot fetches |
| `GET /api/jobs/:id/download` | Rendered video, also used for preview unless `download_url` is supplied |

Normalized snapshots use `id` or `job_id`, `status`, `duration` or `meta.duration`, optional 0–100 numeric `progress`, `clips`, `candidates`, `interest_curve` (or `interest`) as `{time, score}` points, optional `source_url`, `download_url`, and `error`. Clips accept `start_seconds`/`end_seconds` or numeric/colon-delimited `start`/`end`, `caption` or `description`, `reaction_label` or `reaction`, `thumbnail_url` or `thumbnail`, numeric `score` and boolean `keep`. Score/interest display assumes 0–100. Stable server clip IDs are preferred; index IDs are a compatibility fallback. Status `done` exposes the output; queued/analyzing/planning/rendering states lock controls. Empty clips/signals render explicit empty states. Optional backend modules determine which feature flags actually affect the result.

SSE is preferred; an error or unavailable EventSource closes the connection and polls every 1.5 seconds. A five-second snapshot watchdog covers silent connections or unknown named events. Only one snapshot request runs per subscription at a time; cleanup prevents late updates. Legacy and mock modes poll. HTTP errors are surfaced without automatically retrying POST requests.

The parallel EXT-03 implementation was not present in this worktree: payload conventions above are integration assumptions, isolated in the client. No backend files were changed. Local VLM is sent as provider `local`; game/profile strings are hints (`auto`, `valorant`, `cs2`, `fortnite`, `other`; `balanced`, `competitive`, `comedy`). Confirm these identifiers against the integrated backend.

## Validation

Required runner command, from worktree root:

```sh
tools/remote_run.sh "cd full_app/production_frontend && npm ci && npm run build && npx vitest run"
```

Build includes strict TypeScript checking. Vitest/Testing Library tests cover markers and seeking, empty signals, keep/drop, captions, trim persistence through reordering, drag reorder, exact preview ranges, busy controls, wire payloads, structured failures, SSE fallback/cleanup, and the mock upload-to-export flow. Tests use mocked network/media APIs; no Gemini calls or secret files are used. They do not prove actual video decoding or FFmpeg export; those require integrated browser/backend smoke testing.
