---
id: EXT-28
branch: ext/EXT-28
allowed_paths: [desktop/**, docs/desktop.md]
---
# EXT-28: Desktop app packaging
Create `desktop/`: a Tauri (preferred, small) or Electron wrapper that starts the Python backend as a sidecar (bundled with PyInstaller or a
managed venv), bundles or detects ffmpeg, opens the production frontend, shows a tray icon with the auto-capture watcher (EXT-23 `capture`) on/off,
and stores settings (API keys entered by the user go to the OS keychain). Provide build scripts for Windows/macOS/Linux and CI-friendly docs. Tests:
config/sidecar launcher unit tests where feasible; a build dry run on the Linux runner if toolchains install quickly, otherwise document. Write docs/desktop.md.
