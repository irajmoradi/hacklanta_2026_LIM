---
id: FX-2
branch: ext/FX-2
allowed_paths: [full_app/planner/**, full_app/render/**, full_app/fx/**, full_app/models/effects.py, full_app/services/**, full_app/tests/test_planner*.py, full_app/tests/test_render*.py, full_app/tests/test_fx*.py, full_app/tests/test_effects*.py, demo_video/fx2/**, docs/fx.md, docs/planner.md, docs/rendering.md]
---
# FX-2: Bring back stacked meme VFX + SFX (owner: "same vfx, no sfx, no stacking")

Evidence from the DEMO-02 full-match plans (runner 1 `/srv/demo_out/demo02/planned_*.json`, field `edit_plan.segments`): `video_effects` is
empty everywhere; at most one `timed_effects` item (e.g. `text_bruh`) and one `sound_effects` item per segment in mean mode; **zero SFX in nice
mode**. The original app (`full_app/models/effects.py` VFX + SFX registries, `full_app/sfx/*.mp3`; see git history of the old planner/editor on
`main`) had Gemini assign several VFX and SFX per clip. Planner v2 lost that. Fix it so montages are fun again:
1. **Planner:** each segment gets a stack of timed effects tied to the clip's actual events (kill/headshot/multikill/clutch/death/whiff/ability
   from signals, kill-feed and Gemini window scores): e.g. kill → hitmarker + zoom punch + bass hit; multikill → stacked "another one"/airhorn +
   shake + flash; death/whiff → freeze frame + "bruh"/fail sound + deep fry; clutch → slow-mo + anime wow. 2-5 SFX and 1-4 VFX per clip,
   overlapping where it fits (stacking), **variety** across the montage (no SFX/VFX repeated back-to-back; cap repeats per montage), intensity by
   mode (nice = hype stack, mean = full chaos + roast texts). Use the **whole** registry (inventory it; add tags per effect: event type, mood,
   intensity, length). Gemini (planner v2 path) chooses from tagged options with event timestamps when enabled (cap 1 call per montage); a
   deterministic tagged chooser is the fallback and must already give rich, varied stacks.
2. **Renderer:** make sure render v2 actually renders every assigned VFX and mixes every SFX (multiple overlapping, per-SFX gain, ducking game
   audio slightly under SFX, no clipping/limiter at the end); add any registry VFX that render v2 cannot draw yet (zoom punch, shake, flash,
   freeze, slow-mo, deep fry, chromatic/glitch) using fast ffmpeg filters (keep the perf/ budget).
3. Tests: per-segment stacks, variety caps, mode intensity, renderer filter graph includes all effects and an amix with N inputs.
4. **Re-render on runner 1** from the saved DEMO-02 analysis (no re-analysis; at most 3 Gemini calls) the landscape, vertical and mean-vertical
   montages into `/srv/demo_out/fx2/` and copy them locally to `demo_video/fx2/out/` (gitignored), plus Discord copies under 20 MB each and a
   per-clip effects table (clip, events, VFX, SFX) in your report. Full suite green on the runner.
