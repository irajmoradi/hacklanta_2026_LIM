---
id: EXT-19
branch: ext/EXT-19
allowed_paths: [full_app/narration/**, full_app/tests/**, docs/narration.md]
---
# EXT-19: AI caster narration
Build `full_app/narration/`: optional esports-caster voiceover. From the ranked clips + captions, generate a short script (Gemini, mocked in
tests; deterministic template fallback) in a chosen persona (hype caster, deadpan roast, nature documentary), timed to clip peaks without talking
over reaction overlays; synthesize with ElevenLabs TTS (stock voices by default; cloned voices only when a consented voice id is configured) with a
per-job character cap and caching by (voice, text); duck game audio under the narration. `narration.build(clips, plan, persona) -> NarrationTrack`
(segments with times + audio files). ElevenLabs key comes from env at runtime only (`ELEVENLABS_API_KEY`); live calls only in a `-m live` test (max 2).
Tests: script timing fits gaps, cache hits, ducking filter present, fallback without keys. Write docs/narration.md.
