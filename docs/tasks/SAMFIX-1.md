---
id: SAMFIX-1
branch: ext/SAMFIX-1
allowed_paths: [full_app/sam/**, full_app/reactions/**, full_app/tests/test_sam*.py, full_app/tests/test_reaction*.py, demo_video/samfix/**, docs/sam.md, docs/reactions.md]
---
# SAMFIX-1: Make the SAM spotlight good (or skip it) + truly big reaction heads

FINAL-1's final render (`demo_video/final/out/contact_sheet.jpg` on branch `ext/FINAL-1`; videos on runner 1 `/srv/demo_out/final/`)
shows two problems:
1. **SAM spotlight looks broken:** it outlines random scenery/floor/weapon with jagged cyan pixel edges and darkens the rest. Fix: prompt SAM
   with a **point/box on the actual target** (enemy near the crosshair at the kill timestamp: use the profile's crosshair centre, the kill
   event time, and a small search box; optionally a motion/person heuristic), reject masks that are too large (>25% of frame), too small,
   touch the frame edges/HUD/viewmodel (the player's own gun at the bottom-centre/right), or are unstable across frames (IoU tracking); smooth
   the mask (morphological close + feather) and render a clean effect (soft glow outline + slight background dim/desaturate, ≤ 0.6 s,
   or a cutout "pop-out" zoom). If no good mask: skip with a job warning. Tests for each rejection rule; visual QA stills.
2. **Reaction heads are still small** (~15% of frame height; target ~28-35% in 16:9, ~22-28% of width in 9:16). Make `reaction_size=large`
   (the default) actually that big, anchored bottom corner, slightly overlapping the edge like a streamer cam, still head-only with the
   existing shadow/bounce/bob/name tag. Tests on placement sizes for each preset.
Re-render the 30 s mean vertical and 60 s landscape on runner 1 from saved DEMO-02 analysis (zero Gemini calls, privacy off, SAM local:
`SAM_BACKEND=local`, `SAM2_CHECKPOINT=/srv/models/sam2.1_hiera_small.pt`; install CPU torch + `full_app/sam/requirements-local.txt` into your
runner venv if `import sam2` fails) into `/srv/demo_out/samfix/` + local `demo_video/samfix/out/` (gitignored) with a contact sheet of every
SAM moment and reaction. STYLE-1 (effects) and PARITY-UI (server/pipeline/frontend) run in parallel: stay inside your paths.
