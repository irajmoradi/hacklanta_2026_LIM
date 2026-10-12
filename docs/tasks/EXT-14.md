---
id: EXT-14
branch: ext/EXT-14
allowed_paths: [full_app/social/**, full_app/tests/**, docs/social.md]
---
# EXT-14: Thumbnails, titles and share kit
Build `full_app/social/` that makes a montage ready to post:
- **Thumbnail:** pick the best frame of the top clip (sharpness + action score), optional subject cutout (call `sam` module if present, else
  saliency crop), big outlined text, glow/arrow; variants for YouTube 16:9 and Shorts/TikTok cover 9:16; optional Gemini image generation pass
  (existing `generate_thumbnail` pattern; mocked in tests).
- **Metadata:** title options (clickable, not spammy), description with timestamps/chapters from the clip list, hashtags per game
  (Valorant/Overwatch 2/Deadlock/League), per-platform length limits; Gemini-generated with a deterministic template fallback.
- **Share kit export:** `share/<job>/` with video, thumbnails, `metadata.json`, a chapters `.txt`, and an SRT of captions if present.
`social.build_share_kit(job_dir, clips, plan, game) -> path`.
Tests: thumbnail sizes/aspect, text layout within safe areas, chapter timestamps, platform limits, fallback without network. Write docs/social.md.
