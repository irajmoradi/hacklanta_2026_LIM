# LIM Editor desktop (EXT-28)

The Electron wrapper starts the existing Flask factory as a Python sidecar, serves
the production React build, and exposes EXT-23 capture in the system tray. Electron
was selected for its shared JavaScript tooling and straightforward native tray and
settings UI. It is larger than Tauri. Everything for this integration lives under
`desktop/`; the regular web app keeps its existing behavior.

## Run from source

Install Node.js 22+, Python 3.10+ with `venv`/pip, and ffmpeg **and ffprobe** on PATH.
Python 3.12 is the Linux-tested version. Linux also needs a graphical desktop with
Electron's shared libraries and an unlocked Secret Service (typically GNOME Keyring).
Windows uses Credential Manager; macOS uses Keychain.

```sh
cd desktop
npm ci
npm run stage
npm start
```

First launch creates `python/` under Electron's user-data directory and installs
the backend, capture and desktop requirements. Internet access is required the first
time and when requirements change. A requirements hash avoids reinstalling on every
launch. Set `LIM_PYTHON` to an absolute Python executable before starting to select
an interpreter; it is used only when creating the environment. No global Python
packages are changed. Install Python separately; the installer does not bundle it.

Use tray **Settings** to enter an API key, select AI Studio (default) or Vertex AI
Express, and choose the recordings folder and optional ffmpeg directory. Save,
quit from the tray, and reopen to apply changes. A blank key preserves the saved
key; **Remove saved key** deletes it. Restart also clears any old key from the
running backend. This wrapper deliberately does not read repository `.env` files
or use inherited provider keys. The ordinary production UI can still accept a
per-request key; use desktop Settings for persistent native credential storage.

The editor opens when Python and ffmpeg are ready. Upload, analyze, review, then
render through the existing production UI. Closing the editor hides it to the tray;
**Open editor** restores it. **Quit** stops backend and capture process trees.
Avoid quitting during a render; forced process shutdown may interrupt current work,
and the backend's existing recovery behavior applies on the next launch.

Capture is **off on every launch**, including after a previous enabled session.
Enable **Auto-capture** in the tray after selecting a recordings directory. It runs
EXT-23 with `include_existing=false` and its default analysis options. Only new or
changed stable recordings are uploaded, then automatically analyzed and planned;
normal provider charges apply. The tray checkmark reflects the running process;
unexpected exits clear it and show an error. Stopping capture stops future watching;
jobs already accepted by the backend continue. See [capture.md](capture.md) for
stability, retry and upload idempotency limits. Advanced OBS/hotkey/defaults editing
remains available through the standalone capture CLI.

## Storage and process boundary

Electron user data defaults to `%APPDATA%/LIM Editor` on Windows,
`~/Library/Application Support/LIM Editor` on macOS and
`~/.config/LIM Editor` on Linux in packaged builds (development can use the package
name `lim-desktop`). It contains settings JSON, the managed venv, job workspace,
capture defaults and capture deduplication state. API keys are stored directly in
the platform credential store under service `org.lim.editor`, account
`provider-api-key`. Native-backend selection prevents plaintext keyring fallback.
An unavailable or locked keychain produces an error; no disk fallback is used.
Deleting user data does not delete the OS credential; remove it in Settings first.

Keys are passed through a pipe to the credential helper and through the backend's
environment, never command arguments or settings JSON. The capture process receives
no provider key. Each launch uses a random session token; the server binds only
`127.0.0.1` on an OS-assigned port. Electron uses an HttpOnly session cookie and
capture uses a private header. Requests without the token and cross-origin requests
are rejected, including frontend requests. This protects against unrelated browser
pages, not other software with access to the same OS user. No remote debugging or
Node integration is enabled. The editor has no preload bridge; only the local
settings window has a narrow, sender-validated bridge. Navigation and new windows
are restricted. Settings take effect after restart to avoid silently interrupting
jobs. Sidecars exit if the parent pipe closes; normal Quit also kills descendants.
An abrupt OS/process crash can still leave an already spawned ffmpeg process alive.

The implementation follows [Electron security guidance](https://www.electronjs.org/docs/latest/tutorial/security/)
and uses [keyring's native platform backends](https://pypi.org/project/keyring/).

## Build Windows, macOS and Linux

Build on the destination OS and architecture with Node.js 22+. Python is needed on
the installed user's machine; packaging itself does not create or copy a venv.

```powershell
# Windows PowerShell, repository root: creates desktop/release/*.exe (NSIS)
./desktop/scripts/build.ps1
```

```sh
# macOS: creates desktop/release/*.dmg
# Linux: creates desktop/release/*.AppImage
bash desktop/scripts/build.sh
```

Both scripts accept `--dry-run` to produce an unpacked application without an
installer. Equivalently run `npm ci && npm run build:dry` inside `desktop/`.
The dry run is a real frontend compilation and Electron directory build, not just
configuration validation. The staging directory is rebuilt from source. Frontend
dependencies/build outputs live inside `desktop/stage`, never in the original
frontend. Backend source, profiles, prompts and SFX are copied using filters;
workspaces, videos, model weights, `.env` files and test trees are excluded.

By default ffmpeg/ffprobe are detected from PATH or the saved directory. To bundle
them, set `LIM_FFMPEG_DIR` to a folder containing both executables for the target
OS/architecture before building. They are copied into `resources/runtime/bin`.
Use self-contained binaries or deploy their required shared libraries separately;
this script does not discover those libraries or download binaries. Include the
appropriate FFmpeg notices/source offer for the chosen distribution before release.

For CI, run the same native script in Windows/macOS/Linux matrix jobs. Preserve the
lockfile and cache npm downloads; archive `desktop/release`. Do not cache user-data
directories or supply API keys. Use `--dry-run` for unsigned PR validation. Production
releases need platform signing/notarization configuration through electron-builder's
standard environment variables; signing credentials must remain CI secrets. Linux
unpacked builds do not require FUSE; running AppImages may require it. A display is
not needed for the build. Tray/keychain/GUI checks require a logged-in desktop.

## Validation and remaining release checks

From the worktree root, all tests use the prescribed Linux runner:

```sh
tools/remote_run.sh "node --test desktop/tests/*.test.cjs && python -m pytest -q desktop/tests && cd desktop && npm ci && npm run build:dry"
```

The desktop suite has 7 Node tests and 5 Python tests. Linux x64 unpacked packaging
also succeeded. Tests cover settings validation/persistence, environment
isolation, staging exclusions, launcher failure/readiness/shutdown, real loopback
authentication, synthetic ffmpeg upload and mocked native credentials. No live
Gemini calls were made. The capture-header test is also fully offline.
To exercise the packaged backend and sidecar rather than repository modules, build
and check in the **same** runner invocation:

```sh
tools/remote_run.sh "node --test desktop/tests/*.test.cjs && python -m pytest -q desktop/tests && cd desktop && npm ci && npm run build:dry && cd .. && LIM_TEST_RUNTIME=desktop/release/linux-unpacked/resources/runtime python -m pytest -q desktop/tests"
```

Each runner invocation syncs with deletion, removing remote-only build artifacts.
Never run two runner sync commands concurrently.
The combined packaged-resource command above completed with **exit 0**: 7 Node
tests, 5 source-sidecar tests, production frontend compilation, Linux x64 unpacked
packaging, and 5 packaged-sidecar tests all passed. Local `git diff --check` and
`node --check` for `main.cjs`, `runtime.cjs` and `scripts/build.cjs` also returned 0.
Windows/macOS installers, native keychain prompts, tray behavior and actual user
recordings require platform smoke checks. Check save/read/remove of a disposable
key, upload/render, capture on/off, close-to-tray, quit during idle, and restart.
No signing, notarization, publishing, or paid provider smoke is performed by these
scripts. Runtime Python requirement ranges come from the existing app; they are
not a hermetic wheel lock, so first-run installation remains network-dependent.

Broader regression check (run on Linux):

```sh
tools/remote_run.sh "node --test desktop/tests/*.test.cjs && python -m pytest -q desktop/tests && cd desktop && npm run build:dry && cd .. && LIM_TEST_RUNTIME=desktop/stage python -m pytest -q desktop/tests && cd full_app && python -m pytest -q tests/test_jobs.py tests/test_capture.py"
```

Desktop tests, build, and staged tests passed; the final existing regression suite
returned exit 1: **50 passed, 4 failed, 1 skipped**. Three failures in
`test_default_pipeline_mocked_gemini_and_real_render` patch the removed
`server.pipeline.importlib` attribute. `test_synthetic_video_flows_through_real_api`
expects `pipeline.analyze` to be called, but the queue uses the newer pipeline
interface. These files are unchanged and outside EXT-28's allowed paths.

`npm audit --json` in `desktop/` returned exit 1 with 8 moderate advisories in the
electron-builder development dependency chain, rooted in `sprintf-js` (latest
published version remains affected). No runtime npm dependencies are shipped.
`npm audit --omit=optional --json` returned exit 0, but this does not clear the full
build-tool audit. Track the upstream fix before production release; no forced
builder downgrade or unsupported dependency override was applied.
