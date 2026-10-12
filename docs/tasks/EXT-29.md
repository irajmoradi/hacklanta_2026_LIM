---
id: EXT-29
branch: ext/EXT-29
allowed_paths: [full_app/roast/**, full_app/tests/**, docs/roast.md]
---
# EXT-29: Roast mode v2
Build `full_app/roast/` to make Mean mode hilarious but not cruel: per-fail roast captions and meme-template overlays (top/bottom text, Drake-style
two-panel, "wasted" banner, fake stat cards like "Aim: 3%"), timed comedic beats (freeze + zoom on the whiff, record-scratch SFX from the existing
library), a "roast intensity" setting with a safety filter (no slurs, no attacks on identity; only gameplay), Gemini-written lines with a
deterministic template fallback (mocked in tests). Output overlay specs the renderer/FX can apply. Tests: safety filter, timing, template rendering
on synthetic clips. Write docs/roast.md.
