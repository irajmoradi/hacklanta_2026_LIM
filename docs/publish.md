# Publishing scaffolding (EXT-27)

`full_app/publish/` consumes the directory returned by
`social.build_share_kit(...)`. It is an opt-in Python API, with no Flask routes
or automatic publishing in the render pipeline. Previewing needs neither
credentials nor network. Actual transfers require **both** `dry_run=False`
and the literal boolean `confirm=True`, supplied after the user reviews the
destination, video and metadata. OAuth consent alone is not upload consent.

## Install and preview

From `full_app`, install `python -m pip install -r publish/requirements.txt`
in addition to the normal app dependencies. Encryption is loaded lazily so
the normal app and offline previews do not require this optional dependency.

```python
from publish import YouTube, TikTok

preview = YouTube().upload("workspace/share/my-job")
print(preview)  # title, description, hashtags, vertical cover, private status
draft_preview = TikTok().upload("workspace/share/my-job")
```

The EXT-14 `platforms.shorts` and `platforms.tiktok` records are used, including
the first title option, description and hashtags; YouTube adds `#Shorts` if
missing. Assets must resolve inside the share kit. The vertical thumbnail is
included in the preview. YouTube uploads it via `thumbnails.set` after the video;
if that fails, the result preserves the video ID and reports a manual thumbnail
step, preventing an accidental duplicate video retry. Custom cover availability
depends on the channel and YouTube surface; verify the result in Studio.
The TikTok inbox upload API accepts no caption or thumbnail fields. Apply TikTok copy and cover during
the creator's final editing step. No claim of automatic Shorts classification
is made; prepare an eligible vertical/square video before uploading.
See [thumbnail upload](https://developers.google.com/youtube/v3/docs/thumbnails/set)
and [YouTube cover controls](https://support.google.com/youtube/answer/72431).

## OAuth apps

### YouTube

1. Create a Google Cloud project and enable **YouTube Data API v3**.
2. Configure the OAuth consent screen and add your test Google account while
   the app is in testing. Create a Desktop OAuth client for a local loopback
   callback, or a Web client with an exactly registered redirect URI for a
   hosted callback. Keep its client secret in an environment variable.
3. Use the `youtube.upload` scope. The helper requests offline access, consent,
   state and PKCE. Open its URL in a system browser, receive the callback in
   your own local/hosted application, and pass the code and state to `exchange`.
   Google does not support the old out-of-band copy/paste redirect flow.
4. A YouTube channel must exist on the authorized account. Testing and
   unverified applications may have restrictions; check the current project
   requirements in the linked API documentation. The adapter defaults to private;
   `privacy="unlisted"` or `"public"` must be chosen explicitly.

See [Google OAuth setup](https://developers.google.com/youtube/v3/guides/auth/installed-apps)
and [video insertion restrictions](https://developers.google.com/youtube/v3/docs/videos/insert).

### TikTok

1. Register an app in TikTok for Developers; configure Login Kit and an exact
   HTTPS web redirect URI. Store the client key and secret in the environment.
2. Add Content Posting API and request **video.upload** for upload-to-inbox.
   Configure sandbox/test accounts or obtain the necessary production approval.
3. Open the helper's Login Kit URL, handle the registered callback yourself,
   and exchange the code with its returned state using the same OAuth object.
4. After transfer the creator must open the TikTok inbox notification to edit
   and post. `draft_uploaded` means bytes were accepted, not a public post or
   completed processing. No Direct Post API is used.

See [Login Kit](https://developers.tiktok.com/docs/en/login-kit-web),
[draft upload](https://developers.tiktok.com/doc/content-posting-api-reference-upload-video)
and [token refresh](https://developers.tiktok.com/doc/oauth-user-access-token-management).

## Credentials and explicit upload

Generate a Fernet key once using `cryptography.fernet.Fernet.generate_key()`
and securely provision it as **PUBLISH_TOKEN_KEY**. Keep that key stable across
sessions and outside the repository; losing it requires reauthorization.
Do not store any token, authorization code, key or client secret in source,
shell history, diagnostic output or screenshots.

```python
import os
import httpx
from publish import OAuth, TokenStore, YouTube

store = TokenStore()  # ~/.lim-publish/youtube.enc and tiktok.enc, outside repo
with httpx.Client() as client:
    auth = OAuth("youtube", os.environ["YOUTUBE_CLIENT_ID"],
                 os.environ["YOUTUBE_CLIENT_SECRET"],
                 os.environ["YOUTUBE_REDIRECT_URI"], store, client)
    # First authorization only: open auth.authorization_url() in the browser.
    # Your callback handler invokes auth.exchange(code, returned_state).
    # Keep this auth object alive: state is single-use and expires in 10 minutes.
    uploader = YouTube(auth, client)
    preview = uploader.upload("workspace/share/my-job")
    # Display preview and video to the user, then obtain explicit confirmation.
    # Only after that confirmation:
    result = uploader.upload("workspace/share/my-job", dry_run=False, confirm=True)
```

For TikTok use `OAuth("tiktok", ...)`, `TIKTOK_CLIENT_KEY`,
`TIKTOK_CLIENT_SECRET`, `TIKTOK_REDIRECT_URI` and `TikTok(auth, client)`.
Access tokens refresh before expiry; rotated refresh tokens are persisted.
Credential files use authenticated Fernet encryption and atomic replacement,
with owner-only creation permissions on POSIX. On Windows, protect the token
directory with your account's ACL. One local account per provider is supported;
use separate store directories for additional accounts. Concurrent credential
writers are not supported.

Provider error bodies and signed upload URLs are excluded from errors/results.
The helper suppresses httpx/httpcore records during its requests; do not add
custom HTTP hooks or transports that log credentials, bodies or URLs.

## Transfer behavior and limits

YouTube sends 256-KiB-aligned chunks (8 MiB default), follows 308 Range
acknowledgments, and probes session status after transient errors. Recovery
is bounded to three failures within the call. No resumable session is persisted
across process restarts. Review the channel before retrying an ambiguous error
to avoid duplicates. See the [resumable protocol](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol).

TikTok sends sequential chunks, merging remainder bytes into the last chunk.
Transfers stop on errors rather than automatically creating another draft.
See the [media transfer requirements](https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide).
Callers must prepare compliant MP4 media: this scaffold does not transcode,
inspect codec/dimensions/duration, poll processing status or implement a consent
UI/callback server. Share-kit metadata does not prove platform media eligibility.
Existing render/analyze behavior is unchanged.

## Tests

From the worktree root:

```bash
tools/remote_run.sh "pip install -q -r full_app/publish/requirements.txt && cd full_app && python -m pytest -q tests/test_publish.py"
```

Tests generate synthetic video with ffmpeg, consume an actual EXT-14 share kit,
and mock every HTTP request, including OAuth, chunk acknowledgments and errors.
No real uploads, Gemini calls, or credentials are used.

### EXT-27 validation record

Executed from the worktree root on the Linux runner:

| Command | Result |
| --- | --- |
| `tools/remote_run.sh "pip install -q -r full_app/publish/requirements.txt && cd full_app && python -m pytest -q tests/test_publish.py"` | Initial milestone: 19 passed, exit 0 |
| `tools/remote_run.sh "pip install -q -r full_app/publish/requirements.txt && cd full_app && python -m pytest -q tests/test_publish.py tests/test_social.py tests/test_pipeline.py tests/e2e/test_e2e_pipeline.py"` | Intermediate regression: 94 passed, 1 failed, 2 errors, exit 1 |
| `tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_publish.py tests/test_social.py tests/test_pipeline.py"` | Final code: 83 passed, exit 0 |
| `tools/remote_run.sh "cd full_app && python -m pytest -q tests/e2e/test_e2e_pipeline.py::test_pipeline"` | Isolated existing harness: 1 setup error, exit 1 |

The end-to-end failures all originate from `demo/pipeline.py:192`, which
patches `app.WORKSPACE`; the current `app.py` delegates to `server.api` and has
no such attribute. Neither production file was modified by EXT-27, and neither
is in this task's allowed paths. The isolated run reproduces the error without
collecting or importing publishing tests. Integrator follow-up is required for
that existing demo harness. Final publishing coverage includes 29 tests.
