---
id: REACT-2
branch: ext/REACT-2
allowed_paths: [full_app/reactions/**, full_app/render/reaction*.py, full_app/tests/test_reaction*.py, tools/matte_pack.py, docs/reactions.md]
---
# REACT-2: Head-only reaction overlays (no white box)

Owner: "for the reaction I just want the head, no white background." The team reaction pack (runner 1 `/srv/packs/team/`, `pack.json`
clips with `background: "light"`) are LAM Gaussian-splat talking heads rendered on a plain light background, composited today as a rectangle.
1. `tools/matte_pack.py`: produce an alpha version of every pack clip: background removal per frame (the background is a near-uniform light
   color: use a fast color/distance key with edge refinement + temporal smoothing; if quality is poor, use the SAM module (`full_app/sam/`)
   or a small matting model as an option). Output `<id>.alpha.webm` (VP9 with alpha) **and/or** `<id>.mask.mp4` (grayscale matte, same timing);
   add `alpha_file`/`mask_file` to pack.json (keep the original). Idempotent; skips clips already matted. Check that hair, glasses and beards
   are kept and no light halo remains (save a few still checks on a dark and a bright gameplay frame).
2. Renderer: composite reactions **head-only** using the alpha/mask (fall back to the old box when absent), with a subtle drop shadow or thin
   outline for readability, a pop/bounce-in, a small idle bob, and a name tag; correct audio sync. Works in all presets (16:9, 9:16, 1:1). Tests.
3. Run the matte on runner 1 for the current pack. A batch of **48 new clips** (12 per person; same speakers Iraj/Lance/Stefanny/Mario) will be
   appended to `/srv/packs/team/pack.json` in the next ~30-40 minutes: poll every 5 minutes for up to 45 minutes until the pack has at
   least 80 clips, then matte the new ones too. Report timings per clip and show before/after stills (local `demo_video/react2/` gitignored).
Never commit the clips, mattes, or any faces/voices. Full suite green on the runner.
