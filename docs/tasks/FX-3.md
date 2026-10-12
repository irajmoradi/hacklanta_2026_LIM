---
id: FX-3
branch: ext/FX-3
allowed_paths: [full_app/models/effects.py, full_app/fx/**, full_app/render/effects*.py, full_app/render/vfx*.py, full_app/render/overlays*.py, full_app/assets/vfx/**, full_app/planner/stacks*.py, full_app/planner/catalog*.py, full_app/tests/test_fx*.py, full_app/tests/test_vfx*.py, full_app/tests/test_render_stacks.py, full_app/tests/test_planner_stacks.py, demo_video/fx3/**, docs/fx.md]
---
# FX-3: Bold, obvious visual effects (owner: "very little visual effects")

FX-2 (merged; read `demo_video/fx2/REPORT.md` and its per-clip table) restored stacked SFX, but visible VFX are weak: the visual half of the
registry (`full_app/models/effects.py` VIDEO_EFFECTS) is mostly subtle grades (tints, grain, blur/sharpen, saturation) fired for a fraction of a
second at the event instant, so montages look almost unedited. Make the edits **loud and obvious**, meme-montage style:
1. **New bold VFX** (procedural via ffmpeg filters and/or overlay PNGs/animations you generate yourself with PIL/drawtext; no copyrighted
   images; emoji only via an OFL font such as Noto Emoji, which you may vendor if small, or draw shapes): zoom punch-in with motion blur,
   earthquake shake, heavy RGB split/chromatic glitch, VHS/datamosh-style glitch burst, freeze-frame + white outline/circle + arrow
   pointing at the kill, speed lines/radial zoom blur, red damage-flash vignette on deaths, "WASTED"/"MISSION FAILED"-style banner (your
   own wording/design, e.g. "ELIMINATED", "SKILL ISSUE", "CLIPPED"), big kinetic word pops ("SHEESH", "NO SHOT", "BRUH", "-1000 AURA",
   "+1000 AURA", "COOKED", "W", "L") with bounce/shake, hitmarker X bursts + screen flash on each kill, 💀/🔥/😂 emoji bursts/rain,
   letterbox bars slam-in for clutches, camera-roll tilt, deep-fry + lens flare, "to be continued"-style yellow arrow (own design) on fails,
   confetti on aces. Each tagged in the catalog (event types, mood nice/mean, intensity, min visible duration).
2. **Timing:** effects must be visible: build-up before the event (slow push-in / tilt), the hit at the event (punch + flash + shake +
   word pop + hitmarker), aftermath for 0.4-1.5 s (freeze, banner, emoji, grade). Minimum visible duration 0.35 s for any VFX; **at least 3
   clearly visible VFX per clip** (subtle grades do not count toward that) and stacking of 2+ at the hit. Chaos (FX-2 seed) still applies.
3. Render v2 must draw all of them fast (keep perf/ budget; precompute overlay sprites; one filter graph per segment). Tests: catalog tags,
   minimum visible VFX per clip, filter graph contains each chosen effect, durations.
4. Re-render the mean vertical (30 s) and landscape (60 s) on runner 1 from the saved DEMO-02 analysis (no re-analysis; zero Gemini calls),
   **privacy off**, into `/srv/demo_out/fx3/` + local `demo_video/fx3/out/` (gitignored), Discord copies < 20 MB, and a contact sheet sampled
   at hit moments. Visually inspect: if a viewer could miss an effect, it is too weak. Full suite green on the runner.
FINAL-1 runs in parallel (chaos over HTTP, reaction sizing, SAM, final render) and may touch `render/**` and `planner/**` generally:
keep your changes inside your allowed paths so merges stay clean.
