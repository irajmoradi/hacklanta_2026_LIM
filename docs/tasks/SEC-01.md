---
id: SEC-01
branch: ext/SEC-01
allowed_paths: [full_app/ingest/**, full_app/discord_bot/**, full_app/capture/**, full_app/server/security.py, full_app/tests/test_security*.py, docs/security.md]
---
# SEC-01: Security and abuse review + fixes
Review the Extension for security issues and fix them in your paths (write findings for other paths in docs/security.md): upload validation
(size, type sniffing, ffprobe timeouts, decompression bombs), path traversal in job ids/filenames/downloads, SSRF and command injection in URL import
(yt-dlp args, allowed hosts, no local/internal URLs), ffmpeg filter injection from user text (drawtext escaping), Discord bot token handling and
permission scope, rate limits, an API auth option (simple token for non-local deployments), secrets never logged, temp-file cleanup. Add
`server/security.py` helpers (validators, safe paths, escaping) with tests (`tests/test_security_*.py`).
