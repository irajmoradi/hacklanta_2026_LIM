---
id: DEMO-01
branch: ext/DEMO-01
allowed_paths: [demo_video/**, docs/demo.md]
---
# DEMO-01: Full-pipeline demo video on real Valorant gameplay

Owner wants a demo video of the **whole new pipeline** on real footage, showing the **frontend improvements** and the final result.
Inputs already on runner 1 (`tools/runner_ip` = 104.207.133.47; ssh as root with the same key the remote_run script uses):
- `/srv/demo_in/valorant_phoenix_44k.mp4`: 31 min, 1080p60 Valorant (Phoenix, Lotus, 44 kills).
- `/srv/demo_in/final_v3.mp4`, `/srv/demo_in/mean_meme_v2.mp4`: montages made by the **old** version (for before/after).
- `/srv/packs/team/`: real reaction pack (16 talking-head clips: Iraj + Stefanny, labels sick_kill/clutch/bruh/fail/funny/hype/roast/wholesome).
  Copy it into the run's `full_app/reaction_packs/team/` on the runner only; **never commit** these files or the gameplay.

Steps (scripts in `demo_video/`, outputs on the runner under `/srv/demo_out/`, then copy the final mp4s back locally to `demo_video/out/` which must
be gitignored):
1. Run the backend from the `Extension` code on the runner and process the Valorant video **through the API** (POST /api/jobs → analyze with
   profile auto (expect Valorant), signals on, Gemini window scoring on, reactions pack `team`, privacy on, captions off → render presets
   **landscape and vertical**, nice mode; then a mean-mode vertical cut) and build the share kit. Gemini: use `GOOGLE_API_KEY` from
   /c/Users/mourn/Downloads/hacklanta/.env with Vertex express (`GOOGLE_GENAI_USE_VERTEXAI=true`, model gemini-3.5-flash-lite); pass it to the
   runner process as an environment variable only (never write it to a file or log); cap total Gemini calls at 120. Record stage timings and
   which signals fired per clip.
2. **Screen-record the new frontend** with Playwright (headless Chromium video recording, 1920x1080) driving the real backend on the runner:
   upload → settings panel (game auto = Valorant, toggles) → live progress → review timeline with interest curve and "why this clip" chips → trim/
   reorder a clip → export presets → share kit view → play the result. Keep it under ~90 s of footage.
3. Assemble **`demo_video/out/extension_demo.mp4`** (1080p, 2-3 min) with ffmpeg: title card → "What's new" bullets → UI walkthrough recording →
   pipeline stage cards with real timings/signal counts → **old vs new** side by side (old final_v3 vs new landscape montage, 20-30 s) →
   the vertical Short → mean-mode roast snippet with reaction overlays → end card. Large readable captions. Also export the raw new montages
   (`montage_landscape.mp4`, `montage_vertical.mp4`, `montage_mean_vertical.mp4`) and a contact sheet of the demo.
4. Write docs/demo.md: how it was made, timings, Gemini calls used, and the paths of the outputs.
Report any pipeline bugs you hit with exact errors (fix only within your paths; describe needed core fixes in the report).
