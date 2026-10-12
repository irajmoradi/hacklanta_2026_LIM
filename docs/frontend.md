# Gameplay editor frontend (UI-02)

Run `npm ci && npm run dev` in `full_app/production_frontend`. Open the Vite URL
(normally http://localhost:5173). `/api` proxies to Flask on port 8000. Deploy
`dist/` on the same origin as the API.

- `/`: jobs API, with feature discovery from `GET /api/info`.
- `/?mock=1`: all controls, fixture analysis, simulated export, original demo
  cover, and copyable share text. No API calls, URL downloads, or paid calls.
  Upload your own 60-second video for local playback, select two team recordings,
  or use a Twitch/YouTube URL to exercise the import UI. Team preview shows the
  first recording. Demo exports deliberately have no video/asset download links.
- `/?legacy=1`: original endpoints, Gemini and landscape output. Extensions are
  disabled; existing upload/analyze/plan/render remains available.

## Workflow

Choose single recording, team recordings, or VOD URL. Single recordings upload
immediately; team uploads wait until player names and layout are selected.
Player names must be nonempty and unique ignoring case/outer whitespace. Team
files retain the selected order; layouts are best POV, side by side, and picture
in picture. Videos must total less than 2 GiB (the server's multipart limit can
be slightly lower). Upload errors preserve the existing job.

URL import accepts HTTPS Twitch/YouTube hosts and requires the own-VOD/permission
checkbox. The server remains responsible for URL/network validation, rejecting
live streams and playlists, download limits, ownership policy, and media checks.
The UI never downloads a VOD directly. Importing/syncing/queued jobs lock editing.

The Edit settings panel includes:

- Game auto/override: generic, Valorant, Overwatch 2, Deadlock, League of Legends;
  moment profile, nice/mean mode, four edit styles, provider and canvas preset.
- Gameplay signals, Audio AI, Gemini window scoring, planner v2, captions,
  reactions, SAM spotlight, subject-aware crop, privacy blur, narration,
  Twitch chat signals and share-kit generation, each with a short explanation.
- Stock narration personas: hype caster, deadpan roast, nature documentary.
- Original energetic/chill music, gameplay audio only, or an uploaded audio file.
- Privacy enabled by default **when supported**, with an exact keep-my-name field.
  An unsupported server displays blur as inactive. Detection is not a guarantee;
  review the result before sharing.
- FX intensity 0–1; optional Twitch VOD ID or JSON/JSONL replay and signed offset.

Music/chat attachments need an existing job and are limited to 100 MiB by the
UI. Failed uploads preserve the prior attachment. Replacing a source clears
job-scoped asset IDs. Missing selected music or missing chat inputs block analysis
and rendering with an actionable error. Music selection is opt-in; narration,
Audio AI, planner v2, chat and share generation also default off.

Analyze, then trim, reorder, keep/drop and caption clips. Why-this-clip chips use
positive numeric/boolean signal evidence, including EXT-01 `ocr`, `rms`, `onset`,
EXT-11 `audio_laugh`/`audio_shout`, and chat-emote spikes/clip requests. Gemini hype
is shown only from `hype`/`gemini_hype`, never inferred from the fused score.
Missing evidence shows “No signal details supplied”; signals are cues, not proof.

Analysis/planning setting changes require Analyze again before export. Render
saves reviewed clips and enforces their order, preserving overlapping segment
FX and top-level plan metadata. Captions/reactions/SAM and supported finishing
options are resent on render. Preset controls in settings and export stay in sync.
Incoming snapshots do not overwrite unsaved clip edits. Warnings and errors remain
visible; object URLs and subscriptions are cleaned up on source replacement.

Completed jobs show a Share kit section with covers, title ideas, description and
chapters, copy buttons, and server-supplied download links. Clipboard failure
leaves selectable text and an explicit fallback message. No publication occurs.
An empty kit explains that generation needs to be enabled on a supported server.

## Integration status and capability contract

**This worktree's server does not yet expose most new modules over HTTP.**
`server/validation.py` still rejects unknown options, `/api/jobs` only accepts a
single `video`, and ingestion/music/multipov/social are standalone libraries.
Backend changes are outside UI-02's allowed paths. UI-02 therefore implements the
following frontend contract for INT-02 and disables unadvertised extensions.
These new routes/fields are integration requirements, not claims that they exist
in this checkout. Mock mode implements all workflows for review and tests.

Existing backend options (`mode`, `style`, `provider`, `use_signals`, `captions`,
`reactions`, `sam`, `window_scoring`, `sam_reframe`, `preset`) remain compatible.
Game/profile remain prompt hints unless structured `game` support is advertised.
Missing/failed discovery preserves baseline editing and never retries a paid POST.
Legacy and mock modes do not request discovery.

The integrator should add `frontend_capabilities` to the existing `/api/info`:

```json
{
  "frontend_capabilities": {
    "options": [
      "game", "audio_ai", "planner_v2", "window_scoring", "sam_reframe",
      "narration", "narration_persona", "privacy_blur", "keep_my_name",
      "music", "music_asset_id", "chat", "chat_asset_id", "chat_offset",
      "twitch_vod_id", "fx_intensity", "share_kit", "team_mode"
    ],
    "team_upload": true,
    "url_import": true,
    "music_upload": true,
    "chat_upload": true
  }
}
```

Only advertise working integrations. Advertise related option groups together
(e.g. narration + persona, chat + input fields, music + asset ID, team + layout).
Options are sent as flat JSON fields on analyze and render. `music` is
`off|energetic|chill|upload`; `team_mode` is `best|split|pip`; persona values are
listed above with underscores. Other flags are booleans, `fx_intensity` is 0–1,
`chat_offset` is seconds, and game uses the canonical profile names above.
The server must validate these values and persist them with invalidation rules.

| New endpoint | Request | Response |
| --- | --- | --- |
| `POST /api/jobs/team` | multipart repeated `videos`, `players` JSON string array in the same order | job snapshot |
| `POST /api/jobs/import` | JSON `{url, owns_content: true}` | job snapshot, optionally queued/importing |
| `POST /api/jobs/:id/assets/music` | multipart `music` | `{asset_id: "opaque-id"}` |
| `POST /api/jobs/:id/assets/chat` | multipart `chat` | `{asset_id: "opaque-id"}` |

Asset IDs are opaque, job-scoped references; the browser never sends filesystem
paths or credentials. The backend resolves uploads and validates content.
Team creation must accept the full batch atomically, returning one shared job.
Team rendering must consume `team_mode` and reviewed clip provenance. Source
preview is the first local POV; synchronized multi-player preview is not provided.

Retained endpoints: `POST /api/jobs` multipart `video`,
`POST /api/jobs/:id/analyze`, `GET /api/jobs/:id`,
`PATCH /api/jobs/:id/clips`, `POST /api/jobs/:id/render`,
`GET /api/jobs/:id/events`, `GET /api/jobs/:id/download`.
Snapshots accept `id|job_id`, `duration|meta.duration`, 0–1 progress, clips,
candidates, interest curve, source/download URLs, warnings, error and plan.
SSE events refresh snapshots; errors fall back to 1.5-second polling. A five-second
watchdog covers silent streams. No automatic POST retries occur.

Expose share output on a completed job as:

```json
{
  "share_kit": {
    "titles": ["Round saved", "Our best plays"],
    "description": "Posting copy and hashtags",
    "chapters": "00:00 Opening\n00:09 Clutch",
    "thumbnails": [{"url": "/api/jobs/ID/share/cover.jpg", "label": "YouTube cover"}],
    "downloads": [
      {"url": "/api/jobs/ID/share/kit.zip", "label": "Download full kit"},
      {"url": "/api/jobs/ID/share/captions.srt", "label": "Download captions"}
    ]
  }
}
```

The integrator maps `social` metadata's platform titles/descriptions and structured
chapters to this view, and exposes generated files through guarded HTTP routes.
Filesystem filenames from `social` are not usable browser URLs. Include only
available downloads; ZIP is optional. The frontend filters unsafe link schemes.
For why-chips, return per-clip `signals` and optional `hype` (0–10); do not discard
these metadata during plan/review. No heuristic candidate-to-clip join is performed.

## Validation record (UI-02)

All commands below ran from this worktree through the Linux runner, with mocked
network/media in Vitest and synthetic ffmpeg media in Chromium. No Gemini calls
were made, no credentials were read, and no copyrighted media was downloaded.

1. `tools/remote_run.sh "cd full_app/production_frontend && npm ci && npm run build && npm test"`
   — exit 1: build passed; 13 tests passed, one old assertion assumed no discovery
   GET. Updated that assertion to verify no upload request. Install audit: zero vulnerabilities.
2. `tools/remote_run.sh "cd full_app/production_frontend && npm run build && npm test"`
   — exit 0: build and 21 tests passed.
3. `tools/remote_run.sh "cd full_app/production_frontend && npm run test:browser"`
   — exit 1: Chromium binary was absent on the runner.
4. `tools/remote_run.sh "cd full_app/production_frontend && npx playwright install --with-deps chromium && npm run test:browser"`
   — exit 0: installed the browser and passed the original synthetic playback smoke.

5. `tools/remote_run.sh "cd full_app/production_frontend && npm run build && npm test && npm run test:browser"`
   ? exit 1: build and all 21 Vitest tests passed; original browser test passed,
   new browser test timed out on an exact-label selector. Corrected the selector.
6. `tools/remote_run.sh "cd full_app/production_frontend && npm run test:browser"`
   ? exit 0: both browser tests passed. Desktop editor and desktop/mobile share-kit
   screenshots were retrieved and visually inspected; controls and text fit.

Tests cover capability filtering, payloads/order, ownership gating, unsupported
operations, asset attachment, URL validation, evidence chips, safe links, copy
success/failure, source/settings interactions and mock network isolation. Browser
checks include actual synthetic video playback, desktop/mobile overflow, import,
changed-settings gating, share-cover decoding and screenshots under ignored
`browser-artifacts/`. Live new-module integration and real team renders await the
backend contract above; mock mode does not validate their output quality.
