# SEC-01 security review

Reviewed the Extension upload, ingest, URL import, job/download routes, render text,
Discord and capture boundaries. This is a code review plus offline regression tests,
not a penetration test or a claim that an Internet deployment is safe by default.
All changes stay in SEC-01's allowed paths. No paid API calls or credentials used.

## Fixed in this task

| Boundary | Change |
| --- | --- |
| Ingest media | Container signature sniffing before ffprobe; reject archives, images and playlists regardless of extension. Actual streams still validated. Probe timeout 30 seconds; encode timeout 3600 seconds; bounded probe analysis and individual FFmpeg allocations. Only local file protocol and listed video demuxers. Reject duration over 12 hours, over 4K pixels, over 240 FPS or over 4K60 pixel throughput before encoding. Existing byte/duration limits remain. These bounds are defense in depth, not a decoder sandbox. |
| URL syntax | Exact initial YouTube/Twitch hosts, HTTPS/443 only, no credentials, controls, whitespace, fragments or ambiguous backslashes. Invalid ports produce safe errors. Structured yt-dlp options, no shell command construction or caller-supplied arguments. |
| URL network | Private urllib transport validates provider/CDN suffixes at every request/redirect, rejects nonpublic and mixed DNS results, connects to the checked numeric address while retaining TLS hostname verification. No ambient proxy, cookies or Authorization forwarding. Reject HTTP compression before decompression. Streaming response byte budget, 8 MiB maximum whole-response read, 30-second socket timeout, 30-minute checked import deadline. DNS itself uses the OS resolver and is not covered by the socket timeout. |
| URL downloader fallback | Only a single progressive HTTPS format is accepted. HLS/DASH/RTMP are intentionally rejected because external downloader fallback could bypass the protected socket boundary. This reduces availability, especially Twitch VODs and high-resolution YouTube formats. Restore manifest support only with equivalent protection on every fragment/key/redirect and no unguarded subprocess networking. |
| Errors and cleanup | yt-dlp logger suppressed; user errors omit raw provider diagnostics and FFmpeg stderr. Each download has private staging, including direct adapter calls; failure removes partial files, successful publication rejects existing destinations. Existing ingest staging/cache locks remain. |
| Paths | Portable component validator rejects traversal, separators, drive/ADS syntax, device names, controls and option-like names. Resolved safe paths reject escaping symlinks. Capture/Discord validate returned job IDs; Discord strips both POSIX/Windows filename paths and checks containment at write time. Private roots must not be writable by hostile local users; resolve checks do not eliminate filesystem races against such users. |
| Discord | Public-address resolver also rejects multicast, transition and standard NAT64 addresses. Source fetch validates HTTPS and host allowlist even if invoked outside source selection. Compressed media refused, partial transfers removed. Global active-job cap defaults to 4 (`DISCORD_MAX_ACTIVE_JOBS`); cooldown identity state capped at 4096. Existing per-user cooldown/channel gates retained. Gateway intents are limited to guilds, guild messages and message content. |
| API clients | Capture and Discord send optional `LIM_API_TOKEN` as Bearer auth only to the configured API. Remote token-bearing connections require HTTPS; loopback HTTP remains supported. Tokens are not sent to source media/CDNs or placed in filenames, state or download URLs. Capture ignores ambient proxy configuration. |
| Capture state | Exclusive random temporary file and atomic replacement prevent a predictable `.tmp` symlink from redirecting state writes; failed staging is removed. |
| Text | `escape_drawtext` escapes both FFmpeg parser layers, for an **unquoted** `text=` argv filter value with `expansion=none`. Real FFmpeg tests compare pixels against literal `textfile=` rendering, including apostrophes, backslashes, colons, filter separators, percent expressions and edge spaces. |

The transport uses yt-dlp's Request/Response interface. Its built-in urllib handler
has other protocols, proxy support and whole-response decompression, motivating a
separate restricted transport ([upstream implementation](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/networking/_urllib.py)).
Optional dependencies remain optional; install yt-dlp to use URL import. No live
YouTube/Twitch compatibility claim is made; transport and orchestration tests are offline.

## Opt-in API authentication and rate limits

`server.security.create_secure_app` is an immediately usable factory wrapping the
existing API. Configure a random `LIM_API_TOKEN` of at least 32 visible ASCII
characters in the process environment (not JSON/config files, CLI arguments or
URLs). Capture and Discord read the same variable at runtime. From `full_app`:

```sh
python -m flask --app server.security:create_secure_app run --host 127.0.0.1 --port 8000 --no-reload
```

Use the project's production WSGI deployment and TLS reverse proxy for remote
use, with one queue-owning process. Without a token, this factory preserves local
unauthenticated behavior. Setting the token alone does **not** change `app.py` or
`server.api:create_app`; select the secure factory or integrate the hook below.

All `/api` routes (including legacy APIs, reads, video streams, logs and SSE) require
`Authorization: Bearer <token>` when configured. `X-API-Key` remains a Gemini
provider credential and does not authenticate the application. Auth uses constant
time comparison. API responses are no-store and nosniff. The in-process limiter
allows 120 requests per peer per 60-second fixed window, counts failed auth too,
caps identity memory at 4096, and returns 429/Retry-After. It deliberately ignores
forwarded headers; configure rate limiting at a trusted reverse proxy for deployments
behind one. SSE connections and global disk usage require separate proxy quotas.
This shared token grants access to every job; it is not per-user ownership.

For default-factory integration, the owner of `server/api.py` should call this
after `app.config.update(config or {})` and before handling requests:

```python
from .security import install_api_security
install_api_security(app)
```

Browser fetches, video tags, native EventSource and direct download links currently
do not supply Bearer headers. The production frontend owner must add an authenticated
session/proxy or header-capable fetch/blob/SSE handling before enabling auth there.
Discord file attachments continue to work; its oversized-file link requires an
authenticated download client. Never append the shared token to a public link.

## Findings requiring owners outside allowed paths

| Priority | Location | Finding / required follow-up |
| --- | --- | --- |
| High | `full_app/app.py`, `server/api.py` | Default entry point binds all interfaces and has no API auth/rate limiting. Use the secure factory now; integrate the hook before advertising a remote deployment. Restrict access at the proxy pending integration. |
| High | `services/probe.py`, `server/api.py:upload` | HTTP upload currently bypasses `ingest.media.probe`, so the new ingest protections do **not** protect that route yet. The request size cap (2 GiB default) exists, but ffprobe has no timeout/protocol/dimension limits. Wire signature sniffing and the protected probe into upload; preserve video/audio codec fields needed by downstream callers. Check metadata before persisting or queueing. Apply body/time/concurrent-upload/disk quotas at the proxy. |
| High | `services/*`, `render/engine.py`, other render helpers | Other FFmpeg/probe subprocesses lack the new ingest timeouts and resource policy. Enforce process deadlines/cancellation and use OS/container CPU, memory, disk and egress isolation for hostile media. `-max_alloc` limits an allocation, not total memory. Ingest normalization still needs an output/disk quota. |
| Medium | `server/api.py:stream/download`, `server/store.py` | Route IDs are SQL parameters, not directly joined to disk; filenames are generated UUIDs and original upload names are unused. No direct request path traversal found. Stream/download still trust persisted absolute paths; resolve them beneath the job workspace with `safe_path` before serving to defend against corrupted state/symlinks. Deletion already checks resolved directory parent. |
| Medium | `server/queue.py` | Queue sanitizes provider exceptions to type names before persistence/logging, but per-job provider keys remain in memory after success/error until cancellation/deletion/close. Clear keys in terminal cleanup when retries no longer need them. Cancellation marks state but does not interrupt running FFmpeg/provider work. |
| Medium | frontend / API integration | Shared token is not authorization between users. Add per-job ownership for multi-tenant use; authenticated browser transport and download behavior must be addressed as above. |
| Medium | job/cache retention | Upload and ingest staging have cleanup paths, but completed jobs, cache entries, lock files and events have no total quota/retention policy. Add bounded retention outside active work and monitor free disk. |
| Low | render text | Existing legacy drawtext labels are fixed allowlisted strings; reactions use generated `speaker.txt` plus `expansion=none`. No current user-text drawtext interpolation found there. Keep textfile mode for new labels, or use the tested helper exactly as documented. Never interpret user text as filter options. |
| Test | `tests/test_capture.py:test_synthetic_video_flows_through_real_api` | Its unrestricted `Mock()` synthesizes `run_stage`, which `JobQueue.run` detects with `hasattr`; intended analyze/plan callbacks are therefore never called. Replace with `SimpleNamespace`/a spec or delete `run_stage` on the mock. The new authenticated end-to-end regression uses explicit methods. |

Discord installation should request only bot/application-command scopes and channel
View Channel, Send Messages, Attach Files (Read Message History only where reply
behavior needs it), never Administrator, Manage Guild or member/presence intents.
Message Content is currently used for automatic attachment/link submission; scope
the bot to configured channels and do not log message bodies. Bot token repr is
already suppressed. OBS passwords come from their named environment variable;
use a local websocket or WSS for remote OBS. Do not enable verbose HTTP/Discord
diagnostics with credentials in a shared log.

## Verification

Tests generate synthetic video/audio locally, mock provider work and prohibit
network connections. Security tests cover paths, symlinks, DNS rebinding/mixed
answers, redirects, size/deadline limits, malformed URLs, real yt-dlp response
adaptation, media signatures/timeouts, auth/rate limits, token separation, cleanup
and the protected upload/analyze/plan/render/download flow. No Gemini smoke test
was needed. Commands below were executed from the worktree root via Git Bash on
Windows; the wrapper runs pytest on the Linux runner.

Optional test dependencies were installed on the runner with:

```sh
tools/remote_run.sh "python -m pip install -q -r full_app/discord_bot/requirements.txt -r full_app/capture/requirements.txt yt-dlp && cd full_app && python -m pytest -q tests/test_security_helpers.py tests/test_security_ingest.py tests/test_ingest_media.py tests/test_ingest_urls.py tests/test_capture.py tests/test_discord_bot.py"
```

That intermediate run exited 1 (150 passed, 5 failed). Four failures revealed
edge-space escaping, timeout error wrapping, response adapter compatibility, and
audio-only error compatibility; all were fixed. The fifth was the capture mock
issue described above. No optional ML packages were required.

The focused regression command:

```sh
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_security_helpers.py tests/test_security_ingest.py tests/test_security_clients.py tests/test_ingest_media.py tests/test_ingest_urls.py tests/test_ingest_chat.py tests/test_capture.py tests/test_discord_bot.py -k 'not test_synthetic_video_flows_through_real_api'"
```

Exited **0: 167 passed, 1 deselected** (23.17 seconds). Only the demonstrated
capture mock defect was deselected. The same failing test was also run using the
original `capture/client.py` retrieved from Git and executed into its module in
memory: **exit 1, 1 failed**, with the identical missing analyze call. No baseline
files were overwritten to perform that diagnostic.

After the final NAT64 and minimal Discord intent changes:

```sh
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_security_helpers.py tests/test_security_ingest.py tests/test_security_clients.py tests/test_discord_bot.py"
```

Exited **0: 103 passed** (4.37 seconds), including 77 SEC-01 security regressions.

The broader offline check (started before the final small cleanup/intent changes):

```sh
tools/remote_run.sh "cd full_app && python -m pytest -q tests eval -m 'not live'"
```

Exited **1: 677 passed, 8 failed, 5 skipped, 1 deselected, 2 errors** (286.50 seconds).
The failed/error cases are outside SEC-01's writable tests:

- `tests/e2e/test_e2e_pipeline.py`: two setup errors and
  `test_optional_stages_chain_when_modules_land` fail because `demo/pipeline.py`
  patches the removed `app.WORKSPACE` attribute.
- `tests/test_capture.py::test_synthetic_video_flows_through_real_api`: unrestricted
  mock advertises `run_stage`; baseline reproduction described above.
- `tests/test_jobs.py::test_default_pipeline_mocked_gemini_and_real_render`: all
  three presets patch missing `server.pipeline.importlib`.
- `tests/test_perf.py::test_single_pass_streams_duration`: slow-motion, 2x and
  0.25x cases disagree with the reference renderer on duration (approximately
  1.979/0.567/3.967 seconds versus 1 second). Neither renderer was changed here.

No full-suite pass is claimed. These integration/test defects need their owning
tasks. `git diff --check` also exited 0. Nothing was pushed or merged.
