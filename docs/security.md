# Server security boundaries

The default `create_app` now installs application authentication and ownership.
`create_secure_app` is a compatibility alias. Run `python app.py` for loopback-only
local use. Compose also binds its published port to loopback, but its bridge peer
requires a configured application token. Use TLS and an authenticated client for
shared deployment. The browser frontend does not yet attach bearer headers.

Configure `LIM_API_TOKEN` for a single owner or `LIM_API_TOKENS` as a JSON object
of stable owner names to distinct random tokens. Tokens have 32-4096 visible ASCII
characters. Provision them through the runtime environment, never committed files,
command-line arguments, URL query strings or download links. All API routes except
`GET /api/health` require auth when tokens are configured. With no tokens, only
literal loopback peers are accepted; forwarded headers never grant access.
`X-API-Key` and the legacy `api_key` field are provider credentials, not auth.

Every new job persists its owner identifier (never its token). Every job/media/SSE
route and mutation checks that identity, including legacy POST body job IDs.
Cross-owner access returns the same 404 as a nonexistent job. Ownerless existing
jobs remain local-only when authentication is enabled; there is no implicit
migration to whichever user first accesses them. Tokens can rotate without
changing ownership by keeping the same owner name. Snapshots omit owner and
private filesystem fields. Downloads resolve inside the authorized job directory.

The limiter allows 600 API requests per peer per minute, including failed auth,
with bounded identity memory. API responses use no-store and nosniff. Configure
trusted-proxy rate limits separately; forwarded peer headers are intentionally
ignored. Native video tags, links and EventSource need an authenticated proxy or
frontend fetch/blob transport; never put a bearer token in a URL.

## Resource and input controls

See [api.md](api.md#admission-streaming-and-resource-bounds-fix-1) for the full
configuration table. Uploads reserve Content-Length before multipart parsing,
cap concurrent admission, and check per-owner/workspace bytes, free disk and job
count. All recordings use signature-checked, local-protocol, container-allowlisted
probing under a process-group deadline and memory limit. Duration, resolution,
frame rate, pixel rate and total frame count are checked before storing a job.
Action JSON is limited to 2 MiB. Unknown nested plan/effect/SFX fields, malformed
clocks, excessive collections, source overruns and overlong output plans fail
before queue mutation. Client-controlled music paths are rejected; no authorized
music asset-ID API is currently exposed.

The production pipeline runs each stage in a fresh child process group. Provider
keys travel only over stdin. Linux address-space and per-file limits are inherited
by media subprocesses. Deadline, cancellation and storage-limit failures terminate
the process group and clean scratch/partial output. Compose caps total memory and
PIDs. Stage progress is published through an atomic file containing only stage,
timings and warnings; it is removed after the stage. Injected/test pipelines keep
their cooperative contract so offline mocks remain effective. Forced termination
can interrupt remote provider cleanup; external provider retention is separate.

Eight SSE slots and 16 Gunicorn threads preserve request capacity under streams;
heartbeats, idle/terminal closure and 30-second lifetimes bound occupation. There
is one queue owner and one workspace lease; never increase Gunicorn workers.
Retention expires inactive jobs after seven days and caps replay to 1000 events
per job. Active jobs are excluded. Capture/Discord credentials remain separate
from source-media downloads and source CDN requests.

## Remaining deployment limits

These controls are not a decoder sandbox. Linux per-process address-space limits
do not bound aggregate process memory outside a container/cgroup. Windows tree
termination uses taskkill and has not been verified on the Linux runner; it has
no RLIMIT memory enforcement. Library callers outside the HTTP production stage
wrapper retain their own subprocess policies. Stage disk checks run every 0.2
seconds and can overshoot between polls; use filesystem/project quotas for a hard
aggregate disk ceiling. Shared optional library caches outside the job workspace
need their own retention. Long request-body reads need proxy timeouts. Enabling
auth does not supply the missing browser transport or provider configuration fix.

The ingest URL transport continues to use allowlisted HTTPS hosts, public-address
checks at connection time, bounded reads, and no token propagation to CDNs.
Optional ML backends remain optional. Model providers are mocked in non-live tests.
FIX-1 makes no paid calls and does not read the supplied Gemini key.

## FIX-1 audit disposition

- P1-01: fixed for server routes, local binding and Compose port exposure. Browser
  authentication transport remains outside allowed paths.
- P1-02: fixed with bounded streams/subscribers and single-owner concurrent server.
- P1-06: fixed admission and duration enforcement; unsafe music paths fail closed.
  Authorized music asset IDs are not implemented because no asset service exists.
- P1-10: production Linux deadlines, cancellation, quotas and retention implemented.
  Strict aggregate filesystem quotas and non-HTTP library subprocess migration
  remain deployment/out-of-scope work; Windows memory enforcement is not supplied.
- P2-11: API/security docs reconciled for this server scope. P2-12: unused Docker
  pytesseract removed and Gunicorn pinned; cross-project dependency locking remains
  outside scope. P2-13 jobs tests already patch the correct lookup in this checkout.
- P3: removed uncalled `_fmt_time`; corrected Docker's queue ownership comment.

## Historical SEC-01 evidence

The following is the earlier SEC-01 validation ledger, not the current FIX-1 suite
result. Its failure descriptions refer to that earlier snapshot.

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
