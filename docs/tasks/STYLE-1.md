---
id: STYLE-1
branch: ext/STYLE-1
allowed_paths: [full_app/models/effects.py, full_app/fx/**, full_app/assets/vfx/**, full_app/planner/stacks*.py, full_app/planner/catalog*.py, full_app/render/effects*.py, full_app/render/vfx*.py, full_app/render/overlays*.py, full_app/tests/test_fx*.py, full_app/tests/test_vfx*.py, full_app/tests/test_planner_stacks.py, full_app/tests/test_render_stacks.py, full_app/tests/test_style*.py, demo_video/style1/**, docs/fx.md]
---
# STYLE-1: Style-sensitive stacks (parity) + tone down opaque flashes

Read `docs/parity_audit.md` (PARITY-1) rows for Hype Montage / Clean Edit / Meme Edit / Cinematic and fix item 2 of its prioritized list
inside your paths. Today `decorate_stacks` ignores `plan.style` and always builds the same multi-VFX/multi-SFX stacks.
1. **Style policies** (from the original app's style rules, `main:full_app/app.py` ~437-490 and `main:full_app/prompts/editor.txt`):
   - Hype Montage: heavy 2-3+ VFX and dramatic stacked SFX per clip (FX-3 bold set), strongest at the climax.
   - Clean Edit: subtle sharpen/grain/vignette only, sparse text, only 1-2 tasteful SFX **total**, no memes/emoji/banners.
   - Meme Edit: maximum chaos: fail sounds, grayscale/desaturate/shake/BRUH/RIP, over-the-top successes, invert/glitch shocks, emoji, banners.
   - Cinematic: sustained vignette/dark mood/grain, warm/cold story grades, rare climax text, cinematic SFX only, quiet→escalation, fades.
   Chaos/seed (FX-2) still applies within each style's allowed set. Tests per style (allowed/forbidden effect sets, counts).
2. **Readability:** FX-3's `damage_flash` and full-screen banners (e.g. `banner_eliminated`, `banner_skill_issue`) cover the whole frame
   with opaque red for a beat (see `demo_video/fx3/out/contact_sheet.jpg` on branch history / runner `/srv/demo_out/fx3/`). Make damage flash a
   red edge vignette + brief tint (gameplay always visible, peak opacity ≤ 45% in the centre), banners a band (≤ 30% of frame height) over
   the gameplay, never a full-frame fill. Check every FX-3 effect for the same problem. Tests on max opacity/coverage.
3. Re-render the mean vertical (Meme Edit) and landscape (Hype) plus a 30 s Cinematic and a Clean Edit landscape on runner 1 from the saved
   DEMO-02 analysis (zero Gemini calls; privacy off) into `/srv/demo_out/style1/` + local `demo_video/style1/out/` (gitignored), Discord copies
   < 20 MB and a contact sheet at hit moments. Full suite green on the runner.
FINAL-1 (pipeline/server/frontend/planner core) and FISH-1 (cards) are running: stay inside your paths.
