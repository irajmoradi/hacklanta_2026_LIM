---
id: EXT-27
branch: ext/EXT-27
allowed_paths: [full_app/publish/**, full_app/tests/**, docs/publish.md]
---
# EXT-27: Publish to YouTube Shorts / TikTok (scaffolding)
Build `full_app/publish/`: OAuth-based upload adapters for **YouTube** (Data API v3 resumable upload, Shorts metadata, privacy status default
private/unlisted) and **TikTok** (Content Posting API draft upload), using the share kit (EXT-14) for title/description/hashtags/thumbnail. Tokens stored
locally encrypted (key from env), never logged; dry-run mode by default; explicit user confirmation flag required to actually publish. Tests with mocked
HTTP (resumable upload chunks, error handling, dry run). Write docs/publish.md with the OAuth app setup steps. No real uploads in tests.
