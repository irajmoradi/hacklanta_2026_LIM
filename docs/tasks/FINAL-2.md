---
id: FINAL-2
branch: ext/FINAL-2
allowed_paths: [demo_video/final2/**, full_app/pipeline/experience.py, full_app/pipeline/rendering.py, full_app/tests/test_cards*.py, full_app/tests/test_wire1.py, full_app/fx/**, full_app/planner/stacks*.py, full_app/tests/test_style*.py, full_app/tests/test_vfx*.py, docs/final_render.md]
---
# FINAL-2: The one combined final render (everything on), Valorant + Deadlock

`Extension` now has every merged feature: FX-2 stacks + chaos, FX-3 bold VFX, STYLE-1 styles + readable banners, REACT-2/SAMFIX-1 large
head-only reactions (80-clip team pack, gen-alpha/explicit lines, clean toggle), SAMFIX-1 strict SAM, WIRE-1 Full experience, FISH-1 AI
intro + fish/car outro (`ai_cards`), THUMB-1 Nano Banana thumbnails (`gemini_image`), PARITY-UI controls (70/30 mix, instructions),
DEADLOCK-1 Deadlock profile, RENDER-FIX (OOM-safe joins, speed), caption fix (no single-word editorial flashes), Gemini default model fix.
1. **Small polish first (your paths only):** the red `damage_pulse`/`damage_flash` on deaths still tints most of the frame red in the STYLE-1
   mean output (see branch history `demo_video/style1/out/contact_sheet_mean_vertical.jpg`). Limit to an edge vignette, centre peak tint
   ≤ 25%, ≤ 0.5 s; check every effect's max centre coverage/opacity in a test.
1b. **Duration caps:** RENDER-FIX reports saved outputs exceed the requested duration because intro/outro cards are added on top of the
   montage budget. Budget cards inside `max_duration` (shorten the montage accordingly) in `pipeline/experience.py`/`rendering.py`; test it.
2. **Final renders through the stock jobs API exactly as a user would** (POST /api/jobs → analyze → plan → render with `full_experience: true`),
   on runner 1, with Gemini via `GOOGLE_API_KEY` env-only from /c/Users/mourn/Downloads/hacklanta/.env (Vertex express; **max 60 calls total**
   across all jobs including image calls), reactions pack `team` (`/srv/packs/team` copied into the run's `full_app/reaction_packs/team/` on the
   runner only), SAM local (`SAM_BACKEND=local`, `SAM2_CHECKPOINT=/srv/models/sam2.1_hiera_small.pt`, install CPU torch + sam2 into your runner
   venv if needed), privacy off:
   - Valorant (`/srv/demo_in/valorant_phoenix_44k.mp4`; reuse the saved DEMO-02 analysis if the API supports importing it, otherwise analyze a
     fight-dense 10-minute trim): **nice landscape 60 s (Hype)**, **mean vertical 30 s (Meme)**, plus one **Reroll** of the mean cut.
   - Deadlock (`/srv/demo_in/deadlock_ccby_aXZYyd4SoWM.mp4`, keep the CC BY credit): **nice landscape 45 s**, **mean vertical 30 s**.
   Each must show: AI intro + fish outro cards, bold stacked VFX + SFX, big head-only reactions from all 4 speakers, music + beat sync, varied
   transitions, captions without single-word flashes, and the share kit with Nano Banana thumbnails. Record every job's `warnings` and say
   plainly which requested features did **not** appear and why.
3. Outputs: `/srv/demo_out/final2/` + local `demo_video/final2/out/` (gitignored): masters, Discord copies < 20 MB each, thumbnails, per-video
   contact sheets sampled at every planned effect/reaction/card, stage timings (wall time per stage, total), and a short `SUMMARY.md` table.
   Visually inspect everything before reporting. Full suite green on the runner.
