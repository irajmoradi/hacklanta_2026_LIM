---
id: EXT-15
branch: ext/EXT-15
allowed_paths: [full_app/ingest/**, full_app/tests/**, full_app/requirements*.txt, docs/ingest.md]
---
# EXT-15: Ingest long VODs and stream chat signals
Build `full_app/ingest/` for real-world inputs:
- **Local uploads at scale:** probe, normalize (constant frame rate, sane GOP, audio resample) and make an analysis proxy (480p/720p, 30 fps) once,
  cached by content hash; chunk multi-hour VODs into overlapping segments for parallel analysis with global timestamps.
- **URL import (user's own content):** optional `yt-dlp` import for the user's own Twitch/YouTube VODs/clips (clearly documented as only for
  content the user owns or has rights to); size/duration limits; progress callbacks.
- **Twitch chat replay signal:** if a Twitch VOD id/chat log JSON is provided, compute per-second chat activity, emote spikes (PogChamp/LUL/KEKW
  etc.) and "clip it" mentions as an extra signal in the EXT-01 `signals{...}` shape (offline from a provided JSON in tests).
- `ingest.prepare(source) -> PreparedVideo{path, proxy, duration, fps, chunks[], chat_signal?}`.
Tests: synthetic VFR video normalized to CFR, chunk offsets correct, proxy cache hit, chat JSON to per-second signal; yt-dlp path mocked.
Write docs/ingest.md.
