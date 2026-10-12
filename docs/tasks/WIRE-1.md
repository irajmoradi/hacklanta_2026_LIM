---
id: WIRE-1
branch: ext/WIRE-1
allowed_paths: [full_app/pipeline/**, full_app/server/**, full_app/app.py, full_app/sam/**, full_app/music/**, full_app/narration/**, full_app/multipov/**, full_app/reactions/**, full_app/planner/**, full_app/render/**, full_app/production_frontend/src/**, full_app/tests/**, docs/wiring_audit.md, docs/pipeline.md]
---
# WIRE-1: Find and fix silent feature drops (owner: "are you sure all the new stuff is actually in it?")

Many Extension features were built as modules by separate agents; some never reach real output. Known evidence (runner 1,
`/srv/demo_out/demo02/planned_{landscape,vertical,mean_vertical}.json`, `edit_plan`): `music` off, `sam` null on every segment,
`transition` always `cut`, no intro/outro, `fx` empty, only 2 reactions per montage, `words` empty, no narration, `video_effects` empty and
almost no SFX (the VFX/SFX part is owned by FX-2, running in parallel: do NOT change effect selection or the effects registry; coordinate by
keeping your planner/render edits to the fields listed below).
1. **Audit (docs/wiring_audit.md):** for every Extension feature (each module under full_app/ added on `Extension` vs `main`: signals incl.
   OCR/audio AI/V-JEPA/Twitch chat, profiles, window scoring, planner v2, render v2 presets/reframe/captions/word captions, transitions,
   intro/outro, reactions, SAM spotlight/cutout, privacy, music + beat sync, narration/caster, multi-POV, share kit, social/publish, stats,
   search, roast mode, editor agent, local VLM, capture, desktop, discord bot, share page) produce a matrix: default on/off, which UI control
   and API option enable it, whether the stock API path (POST /api/jobs → analyze → plan → render) actually calls it, whether its output reaches
   the plan and the rendered file, test that proves it, verdict (works / opt-in only / wired but no-op / dead). Verify by reading call paths
   AND by checking real output (the demo02 JSONs; small local renders).
2. **Fix** every "wired but no-op" and "dead" item that should be in the product: e.g. planner sets transitions (varied, beat-aligned when
   music on), intro/outro cards, more reactions (scale with clip count, all speakers in the pack, varied labels by event), SAM spotlight/cutout
   on the key kill when SAM is available (graceful skip otherwise, but say so in the job warnings), music with beat sync when enabled,
   narration/caster option, word-level captions when captions are on; and make sensible **defaults** for the "full experience" preset in the
   UI and API (document each). Never silently skip: anything requested but unavailable must appear in the job's `warnings`.
3. Add an end-to-end **feature-coverage test** (fake model, tiny synthetic video) asserting each enabled feature leaves a trace in the plan
   and in the render filter graph / output metadata.
4. Re-render the mean-vertical montage on runner 1 from the saved DEMO-02 analysis with the full-experience preset (at most 3 Gemini calls)
   into `/srv/demo_out/wire1/` + local `demo_video/wire1/out/` (gitignored, add .gitignore) and report what is visible in it.
Full suite green on the runner. No new paid calls beyond the cap above.
5. **Privacy blur off by default (owner request: "get rid of privacy blur"):** default `privacy=false` in the API, UI and every preset
   (including the full-experience preset and the demo/re-render scripts); keep it as an explicit opt-in toggle in the UI settings (off).
   Your re-render in step 4 must have no privacy blur.
