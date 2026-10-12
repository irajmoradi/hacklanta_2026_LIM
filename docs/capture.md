# Desktop auto-capture companion (EXT-23)

Run the companion on the desktop that writes OBS, NVIDIA ShadowPlay, or Medal
recordings. It recursively watches the output folder, streams completed files to
`POST /api/jobs` (multipart `video`), then sends your defaults to
`POST /api/jobs/{job_id}/analyze`. The current backend queues analysis **and planning**;
use the existing UI to review and render. Starting the companion enables automatic
analysis, which can incur the backend provider's normal API charges.

## Install and run

From the repository root, in your desktop Python 3.10+ environment:

```sh
python -m pip install -r full_app/capture/requirements.txt
cd full_app
python -m capture --watch "C:/Users/you/Videos" --api http://localhost:8000
```

Run the Flask app separately using its normal dependencies and provider environment
(`cd full_app && python app.py`). The companion needs no Gemini key and never reads
the server's `.env`. OBS and global hotkeys are optional; folder capture works without
either. Stop with Ctrl+C (SIGTERM also supported); an in-progress HTTP request can
take up to the configured client timeout (300 seconds of network inactivity).

Watchdog wakes the scan promptly on filesystem changes. Periodic reconciliation
catches missed events and new subdirectories. Without watchdog installed, the same
CLI falls back to periodic scans with a warning.

## JSON defaults

Save this example outside the repository as `capture.json`; change the paths:

```json
{
  "watch": "C:/Users/you/Videos/OBS",
  "api": "http://localhost:8000",
  "options": {
    "mode": "nice",
    "style": "hype_montage",
    "prompt": "Game: Valorant. Prefer complete clutch moments.",
    "splits": 1,
    "use_signals": true
  },
  "stable_seconds": 5,
  "poll_seconds": 1,
  "retry_seconds": 30,
  "include_existing": false,
  "obs": {
    "url": "ws://localhost:4455",
    "password_env": "OBS_WEBSOCKET_PASSWORD",
    "timeout": 10
  }
}
```

```sh
python -m capture --config /path/to/capture.json
```

`--watch`, `--api`, and `--hotkey` override JSON values. Relative paths resolve against
the working directory. Options use the existing server API schema; `game`/`profile`
belong in `prompt`. Unknown options and invalid numeric/boolean settings are rejected
before watching. Style names are validated by the server, so use a style it supports.
Credentials, job IDs, and edit plans are not accepted in `options`.

Supported extensions: MP4, MKV, MOV, FLV, AVI, WebM, M4V, TS (case insensitive).
Temporary suffixes such as `.part` are ignored; renaming into a supported extension
starts a fresh stability window. Files must be nonempty, readable, and have unchanged
size **and modification time** for `stable_seconds`, across at least two scans.
Changing files reset the window; deleted files are dropped. Symlinks are not uploaded.
Unchanged files present at startup are ignored unless `include_existing` is true;
files modified after startup are eligible. Use `include_existing` to ingest saves made
while the companion was stopped, or to include a recording paused at startup.

State defaults to `~/.lim-capture/<folder-and-api-hash>.json`, outside the repository.
Override with `"state": "/absolute/path/capture-state.json"`. It stores local paths,
size/mtime fingerprints, job IDs and submission status, never credentials. Writes use
an atomic rename. Completed submissions are skipped across restarts; uploaded jobs
awaiting analysis reuse their job ID. Failures retry after `retry_seconds` and do not
stop other files. State belongs to one watcher process: run only one companion per
folder/API/state file. To intentionally resubmit, stop capture, remove the relevant
state entry (or choose a new state file) and enable `include_existing`.

## OBS replay buffer, hotkeys, and event detectors

Enable OBS **Tools → WebSocket Server Settings**, set a password, and start the replay
buffer in OBS. Configure its replay output directory to be inside the watched folder.
The companion deliberately leaves starting/stopping the buffer under user control.
Set `OBS_WEBSOCKET_PASSWORD` in the environment (PowerShell example):

```powershell
$env:OBS_WEBSOCKET_PASSWORD = 'your-local-OBS-password'
python -m capture --config C:/path/capture.json --save-replay
python -m capture --config C:/path/capture.json --obs-context
```

`--save-replay` requests a save and exits; a separately running watcher uploads the
finished output. A successful reply means OBS accepted the save, not that disk writing
has finished. `--obs-context` prints JSON with the current program scene and enabled
game/window capture sources, including nested scenes/groups and configured window
targets. OBS does not provide a universal game-title API: fullscreen capture can have
an empty target. This output can contain window titles; it is not automatically sent
to the analysis API. Set the user's game preference in `options.prompt`.

For a companion-managed global hotkey:

```sh
python -m pip install -r capture/requirements-hotkey.txt
python -m capture --config /path/to/capture.json --hotkey '<ctrl>+<alt>+r'
```

Or add `"hotkey": "<ctrl>+<alt>+r"` to JSON. Missing pynput or unsupported desktop
backends degrade to folder watching with a warning. Desktop permissions, macOS input
monitoring, and Wayland restrictions may affect pynput; OBS's native Save Replay
Buffer hotkey is another option. Hotkeys enqueue a save on the main worker, so a large
upload can delay that save. Native OBS hotkeys or a separate `--event` process avoid
that delay.

An external game-event detector can invoke this command when it detects a kill,
death, or round win (the command is a one-shot integration, not an OCR detector):

```sh
python -m capture --config /path/to/capture.json --event round_win
```

Python integrations can call `capture.obs.trigger_replay(obs_config, reason="kill")`.
Debounce event bursts in the detector. No GPU, OCR, or ML dependencies are introduced.
Each trigger opens a fresh OBS connection, authenticates, checks `GetReplayBufferStatus`,
then requests `SaveReplayBuffer`; subsequent triggers can recover from disconnects.
Errors return exit code 2 for one-shot commands, or are logged by the running watcher.
Implementation follows the official [OBS WebSocket v5 protocol](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md)
and [watchdog observer pattern](https://python-watchdog.readthedocs.io/en/stable/quickstart.html).

## Reliability limits and checks

File stability is a heuristic, not a guarantee the recorder closed its handle. Increase
the quiet window for slow/network storage, or record under a temporary suffix and
rename after close. The API probes readability; rejected partial uploads retry.
Files changed during upload are not submitted for analysis; their next stable version
is uploaded again. This can leave an unused uploaded job for manual cleanup.

The server has no upload idempotency key: a lost upload response or crash between
server acceptance and saving the job ID can create a duplicate job on retry. A lost
analysis response is retried using the same job ID. The companion records queue
acceptance, not eventual analysis success; inspect job status/errors in the app.
Permanent API errors keep retrying until you fix the options/media/server. Deleting
server jobs while capture state references them requires resetting those entries.

Tests use synthetic bytes for filesystem/transport checks and ffmpeg `testsrc2`/`sine`
for a real upload → queued analysis/plan integration with a mocked pipeline. OBS
connections and HTTP transports are mocked; no Gemini calls or real media downloads.
From the worktree root:

```sh
tools/remote_run.sh "cd full_app && python -m pip install -q -r capture/requirements.txt && python -m pytest -q tests/test_capture.py"
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_jobs.py"
```

Physical OBS, global keyboard hooks and platform-specific recording locks require a
desktop smoke check. Use the native OBS replay-save hotkey, confirm one queued job,
then repeat through `--save-replay` and inspect `--obs-context` on that desktop.
