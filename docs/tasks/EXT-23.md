---
id: EXT-23
branch: ext/EXT-23
allowed_paths: [full_app/capture/**, full_app/tests/**, docs/capture.md]
---
# EXT-23: Auto-capture companion (OBS replay buffer / folder watch)
Build `full_app/capture/`: a small desktop companion so clips flow in automatically. (1) **Folder watcher** (watchdog) on the OBS / NVIDIA
ShadowPlay / Medal output folder: when a new recording or replay-buffer save appears and finishes writing, upload it to the local API and start
analysis with the user's default options; (2) **OBS WebSocket** (obs-websocket v5) integration: trigger "save replay buffer" on a hotkey or when
an in-game event is detected, and read the active scene/game; (3) a tray-less CLI `python -m capture --watch <dir> --api http://localhost:8000`
with a JSON config. Tests: watcher detects completed files only (size stable), upload client mocked, OBS client mocked (request/response shapes).
Write docs/capture.md.
