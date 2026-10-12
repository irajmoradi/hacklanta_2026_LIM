# Discord montage bot (EXT-17)

The optional `full_app/discord_bot` process submits videos to the existing local
job API. The Flask application does not import Discord or require its dependencies.
Only configured guild channels accept submissions; DMs and bot messages are ignored.

## Setup

1. Start the API as described in [api.md](api.md). Configure its provider key on
   the API process (`GEMINI_API_KEY`); the bot never reads or sends a Gemini key.
2. Create a Discord application and bot in the Developer Portal. Enable **Message
   Content Intent** on its Bot page for automatic attachment/link submissions.
3. Invite it with the `bot` and `applications.commands` scopes. In the allowed
   channels grant View Channel, Send Messages, and Attach Files. No administrator
   permission is needed. Slash commands are synced globally at startup and may
   take time to become visible. Threads are allowed only if their exact IDs are
   configured, and need Send Messages in Threads.
4. Install and run from `full_app` (use environment variables or your process
   manager for secrets; do not commit them):

   ```bash
   python -m pip install -r discord_bot/requirements.txt
   export DISCORD_BOT_TOKEN='your-bot-token'
   export DISCORD_ALLOWED_CHANNEL_IDS='123456789012345678'
   export DISCORD_API_BASE_URL='http://127.0.0.1:8000'
   export DISCORD_PUBLIC_BASE_URL='https://your-download-host.example'
   export DISCORD_VOD_HOSTS='your-video-storage.example'
   python -m discord_bot
   ```

   PowerShell uses `$env:DISCORD_BOT_TOKEN = '...'` for environment variables.
   Missing optional dependencies or invalid configuration produce a startup error
   with setup guidance. Installing this extra does not modify the app's base requirements.

| Environment variable | Default / meaning |
| --- | --- |
| `DISCORD_BOT_TOKEN` | Required; Discord bot credential |
| `DISCORD_ALLOWED_CHANNEL_IDS` | Required; comma-separated positive channel IDs, deny by default |
| `DISCORD_API_BASE_URL` | `http://127.0.0.1:8000`; trusted backend URL |
| `DISCORD_PUBLIC_BASE_URL` | API base URL; user-reachable base for oversized montage links |
| `DISCORD_VOD_HOSTS` | Empty; exact, lowercase DNS hostnames permitted for user VOD links (no wildcards) |
| `DISCORD_MAX_INPUT_BYTES` | `104857600` (100 MiB); download byte cap, also checked against attachment metadata |
| `DISCORD_MAX_UPLOAD_BYTES` | `10485760` (10 MiB); conservative bot output upload cap, further limited by the guild's limit |
| `DISCORD_USER_COOLDOWN_SECONDS` | `300`; minimum interval between accepted requests per Discord user |
| `DISCORD_POLL_SECONDS` | `3`; API status polling interval |
| `DISCORD_JOB_TIMEOUT_SECONDS` | `1800`; total time budget for download, upload, processing, and delivery |

All numeric settings must be positive and finite. Ensure the input cap is below
the API's upload limit with room for multipart overhead. The bot's input download
has a 300-second HTTP timeout; individual API requests have a 120-second timeout.

## Usage

Post a single MP4, MOV, MKV, WebM, or AVI attachment in an allowed channel, or send
a message containing only an HTTPS direct link to **your own** video. Defaults are
nice mode, landscape, and a maximum planned duration of 60 seconds. Alternatively:

```text
/montage video:<attachment> mode:mean preset:vertical game:Halo length:30
/montage url:https://your-video-storage.example/my-vod.mp4 mode:nice length:90
```

Provide exactly one of `video` and `url`. Mode is nice/mean, preset is
landscape/vertical, game is optional (100 characters), and length is 1–3600 seconds.
Length maps to the planner's maximum duration; the source and selected clips may
produce a shorter montage. Game becomes prompt context because the current API
does not accept a separate game field.

The bot edits one progress message through download, upload, analysis/planning,
and rendering, then sends the video and a share-kit title. Repeated identical
snapshots do not trigger edits. Percentages are coarse API stage progress, not
remaining-time estimates. Slash requests get an immediate private acknowledgement;
progress and results use ordinary channel messages so long jobs can finish after
the interaction webhook expires. Other people in the channel can see these results.

The workflow is multipart `POST /api/jobs`, `POST /analyze`, polling until
`planned`, `POST /render`, polling until `done`, and `GET /download`. Render uses
the requested preset and disables optional generated thumbnails. If a snapshot
contains `share_kit.title`, it is used. This branch has no share-kit endpoint, so
otherwise the bot creates a deterministic title such as `Halo — Highlights` or
`Gameplay — Funny fails`, without an extra provider call.

If the montage exceeds the configured/guild upload cap, download stops and the
bot sends its API download link. Discord HTTP 413 / error 40005 also falls back
to the link. Set `DISCORD_PUBLIC_BASE_URL` to a URL users can reach: localhost is
only useful on the server itself. The current API has no authentication or tenant
isolation; keep it private and use a controlled download gateway/private network
for shared downloads rather than exposing the entire API publicly.

## Limits and operations

- Direct VOD links must serve video bytes. Twitch/YouTube watch pages, playlists,
  expiring redirects, and authenticated browser downloads are not supported. Export
  your VOD to an attachment or configured storage host first. The bot does not
  verify ownership; submit only your own or authorized footage.
- Attachment downloads are restricted to Discord CDN hosts; VOD hosts require an
  explicit allowlist. URLs require HTTPS, port 443, and no embedded credentials.
  Media connections reject literal IP URLs and DNS results containing non-public
  addresses. Redirects are rejected to prevent bypasses. Streamed bytes are capped
  even without Content-Length. Internal API requests use a separate HTTP session.
- One active request per user, plus cooldown across all allowed channels. Failed
  accepted submissions consume cooldown too. Limits are in memory and reset on
  restart; run one bot process per token. The API separately controls its queue.
- Temporary input/output files are removed after success or failure. On timeout,
  cancellation, or processing/delivery failure the bot attempts API cancellation.
  API jobs and outputs remain for download; operators manage deletion through the
  documented job API. A crashed bot does not resume delivery after restart.
- Remote error bodies and exception details are not posted to Discord. Titles
  cannot trigger mentions; generated Markdown is escaped. No live provider calls
  were needed for the offline tests.

## Tests

From the worktree root on the configured Linux runner:

```bash
tools/remote_run.sh "pip install -q -r full_app/discord_bot/requirements.txt && cd full_app && python -m pytest -q tests/test_discord_bot.py"
tools/remote_run.sh "cd full_app && python -m pytest -q"
```

The focused tests mock Discord and HTTP, exercising slash option parsing,
attachment/link routing, progress edits, option validation, rate limiting,
bounded streaming, error cleanup, title fallback, and oversize delivery. SDK-specific
tests skip when the optional dependency is absent; the first command installs it
so those tests run too. No Discord connection or Gemini request occurs in tests.

Discord integration follows the official [discord.py API](https://discordpy.readthedocs.io/en/stable/api.html)
and [application command API](https://discordpy.readthedocs.io/en/stable/interactions/api.html).
