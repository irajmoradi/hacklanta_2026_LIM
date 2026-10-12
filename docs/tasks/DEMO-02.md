---
id: DEMO-02
branch: ext/DEMO-02
allowed_paths: [full_app/planner/**, full_app/pipeline/**, full_app/tests/test_planner*.py, full_app/tests/test_pipeline*.py, demo_video/**, docs/demo.md, docs/planner.md]
---
# DEMO-02: Fill the montage properly, then re-cut the demo with full Gemini scoring

FIX-4 made the stock app work on real footage, but its smoke run (`docs/FIX-4-report.md`) produced only an **8-second** montage from 6 minutes:
only 3 Gemini calls were allowed, both scored windows were vetoed (player not alive), and the deterministic planner **underfilled** its 30-second target.
1. **Planner fill:** when vetoes/low scores leave few validated clips, fill the target length from the next-best local candidates (signals score, kill-feed
   events, audio spikes), extend clips to natural boundaries (pre-roll before the kill, post-roll after), and respect the target length (default 45-60 s
   for a 30-min VOD, 30 s for Shorts). Mean mode should prefer lowlight/death windows (veto means "died", which is exactly roast material). Tests.
2. **Live budget:** you may use up to **80 Gemini calls** for the real run (Vertex express, `GOOGLE_API_KEY` from /c/Users/mourn/Downloads/hacklanta/.env,
   env-only, never written to disk). Score the top ~40 candidate windows across the **full 31-minute** `/srv/demo_in/valorant_phoenix_44k.mp4` with the stock
   API (no demo adapters unless strictly needed, and say which).
3. **Re-cut the demo** using DEMO-01's `demo_video/` scripts: new montages (landscape ~60 s, vertical ~30 s, mean vertical ~20 s) with reaction overlays
   from `/srv/packs/team`, refreshed stage numbers (candidates, windows scored, vetoes, fused ranks, timings, calls used), old-vs-new comparison, UI walkthrough.
   Outputs to `demo_video/out/` (gitignored): `extension_demo_v2.mp4` (1080p) + `extension_demo_v2_discord.mp4` (under 20 MB), the three montages, contact sheet.
4. Update docs/demo.md with real numbers and what is still weak.
