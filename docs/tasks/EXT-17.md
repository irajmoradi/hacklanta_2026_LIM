---
id: EXT-17
branch: ext/EXT-17
allowed_paths: [full_app/discord_bot/**, full_app/tests/**, docs/discord_bot.md]
---
# EXT-17: Discord bot: drop a clip, get a montage
Build `full_app/discord_bot/` (discord.py, optional extra): a bot where a user posts a gameplay video file or a link to their own VOD in an allowed
channel (or uses a `/montage` slash command with options mode nice/mean, preset landscape/vertical, game, length). The bot calls the local API
(`POST /api/jobs`, analyze, render via docs/api.md), shows live progress by editing one status message, then replies with the montage (or a
download link if over the upload limit) plus the share-kit title. Config via env (token, allowed channel ids, API base URL, size limits); per-user
rate limit; no secrets in code. Tests: mocked Discord client + mocked API (command parsing, progress edits, oversize fallback, rate limit). Write docs/discord_bot.md with setup.
