---
id: DEADLOCK-1
branch: ext/DEADLOCK-1
allowed_paths: [full_app/profiles/**, full_app/signals/**, full_app/prompts/games/deadlock.txt, full_app/privacy/profiles.py, full_app/tests/test_deadlock*.py, full_app/tests/test_game_profiles.py, demo_video/deadlock/**, docs/game_profiles.md, docs/deadlock.md]
---
# DEADLOCK-1: Make Deadlock work on real footage

Deadlock support exists only on paper (profile `full_app/profiles/data/deadlock.json`, prompt `prompts/games/deadlock.txt`), tested on synthetic
fixtures. Real footage is now on runner 1: `/srv/demo_in/deadlock_ccby_aXZYyd4SoWM.mp4` (18.6 min, 1080p60, VP9; **CC BY**, credit "No Copyright
Gameplay" — see the `.ATTRIBUTION.txt` next to it; never commit the footage).
Do for Deadlock what FIX-4/FIX-5 did for Valorant (read their reports in docs/signals.md and docs/game_profiles.md; follow the same structure):
1. **Detection:** `detect_game` must return `deadlock` with a solid confidence on this VOD (HUD layout cues: Deadlock's bottom-centre
   health/ability bar, souls counter, minimap, top team bar/score and lane/objective markers; plus OCR keywords); add small generated HUD fixtures
   (no player names) and regression tests; make sure it does not confuse Valorant/OW2/League fixtures.
2. **Events:** fix the Deadlock kill-feed region and parser (and any other cheap signals: kill/death banners, souls spikes, objective/guardian/
   walker/patron kills, ultimate use) so real events fire; measure on the full VOD and report counts with a few verified timestamps.
3. **Scoring prompt + weights:** tune `prompts/games/deadlock.txt` and profile weights for Deadlock highlights (team fights, picks, multikills,
   objective steals, clutch escapes, souls-orb denies; lowlights for mean mode: deaths, whiffed ults, getting ganked).
4. **Full stock-API run** on the VOD (POST /api/jobs → analyze (auto game) → plan → render) with Gemini window scoring
   (`GOOGLE_API_KEY` env-only from /c/Users/mourn/Downloads/hacklanta/.env, Vertex express, max 50 calls), **privacy off**, reactions pack `team`
   (`/srv/packs/team`, copy into the run's `full_app/reaction_packs/team/` on the runner only), nice landscape 45 s + mean vertical 30 s.
   Outputs to `/srv/demo_out/deadlock/` and local `demo_video/deadlock/out/` (gitignored; add .gitignore), Discord copies under 20 MB, and a
   contact sheet. Add a lower-third credit "Gameplay: No Copyright Gameplay (CC BY)" in the rendered montages or note how it is credited.
Other agents (FX-2 effects, WIRE-1 wiring, REACT-2 head mattes) are landing in parallel: do not edit their paths; just use whatever is on your branch.
Full suite green on the runner. Report detection/OCR before → after and the stage timings.
