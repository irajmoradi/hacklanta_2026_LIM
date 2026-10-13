---
id: IRAJ-DL
branch: ext/IRAJ-DL
allowed_paths: [demo_video/iraj_deadlock/**, full_app/profiles/**, full_app/signals/**, full_app/prompts/games/deadlock.txt, full_app/tests/test_deadlock*.py, docs/deadlock.md]
---
# IRAJ-DL: Montages from the owner's own Deadlock recording

The owner recorded their own Deadlock match with GeForce NOW: runner 1 `/srv/demo_in/deadlock_iraj_gfn_20261012.mp4` (9.47 GB, 43.3 min, 2560x1440 60 fps H.264; the
owner's own gameplay, so no third-party credit is needed; still never commit it). Make the best montages the current `Extension` can.
1. **Check detection on this footage** (GeForce NOW stream: may have a GFN overlay/stats, different bitrate or resolution than the CC BY VOD):
   `detect_game` must return `deadlock`, and kill feed/events should fire. If the DEADLOCK-1 calibration does not transfer, fix it within your
   paths (profiles/signals/deadlock prompt) with tests, using small generated HUD fixtures (no player names).
2. Run through the **stock jobs API exactly as a user would** with `full_experience: true` on runner 1 (Gemini via `GOOGLE_API_KEY` env-only
   from /c/Users/mourn/Downloads/hacklanta/.env, Vertex express; **max 60 calls total** including image calls), reactions pack `team`
   (`/srv/packs/team` copied into the run's `full_app/reaction_packs/team/` on the runner only), SAM local if importable
   (`/srv/models/sam2.1_hiera_small.pt`), privacy off. For a ~45-minute source use the app's chunked analysis; if a single job is too slow,
   analyze the match in a few sections but keep it as one job if the API allows.
   Deliver: **nice landscape 60 s (Hype)**, **mean vertical 30 s (Meme)**, and a **Cinematic landscape 45 s**, each with AI intro + fish
   outro cards, Nano Banana thumbnails and the share kit.
3. Outputs: `/srv/demo_out/iraj_deadlock/` + local `demo_video/iraj_deadlock/out/` (gitignored): masters, Discord copies < 20 MB, thumbnails,
   contact sheets at every planned effect/reaction/card, stage timings, job warnings. **Visually inspect** every contact sheet; list plainly any
   requested feature that did not appear and why. Full suite green on the runner if you changed code.
