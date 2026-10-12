---
id: FIX-5
branch: ext/FIX-5
allowed_paths: [full_app/profiles/**, full_app/signals/**, full_app/server/**, full_app/tests/**, docs/game_profiles.md, docs/signals.md, docs/pipeline.md]
---
# FIX-5: Real-footage weak spots from DEMO-02

DEMO-02 (`docs/demo.md`, "remaining weaknesses") ran the stock API on the full 31-min Valorant VOD and found:
1. **Game detection still returns `generic`** on real Valorant footage. Sample frames across the match, match per-profile HUD layout cues
   (ability bar, minimap position, round timer/score strip, kill-feed position) and OCR keywords; report confidence. Must return `valorant` on
   the demo source. Add fixtures (small cropped HUD frames you generate on the runner from `/srv/demo_in/valorant_phoenix_44k.mp4`, a few KB
   each, no player names visible; or synthetic) and regression tests.
2. **Kill-feed OCR detected zero events.** Fix the Valorant kill-feed region (1080p and scaled), preprocessing, and the OCR keyword/event
   parser so kill events fire on the demo source; measure detections on the full VOD and report the count vs the ~44 kills.
3. **Shorter-render admission issue** (see docs/demo.md): a render shorter than the plan target is rejected; accept and clamp sensibly.
4. **Flaky** `tests/test_server_limits.py::test_stream_capacity_lifetime_and_idle_close` fails under full-suite load (passes alone):
   make it deterministic without weakening what it checks.
No paid calls needed (OCR/HUD are local). Full suite green on the runner; report before/after detection numbers.
