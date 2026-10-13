---
id: IRAJ-DL2
branch: ext/IRAJ-DL2
allowed_paths: [full_app/reactions/**, full_app/pipeline/experience.py, full_app/pipeline/extensions.py, full_app/server/validation.py, full_app/server/capabilities.py, full_app/production_frontend/src/**, full_app/tests/**, demo_video/iraj_deadlock2/**, docs/reactions.md, docs/pipeline.md]
---
# IRAJ-DL2: Owner feedback on their Deadlock cuts — no generic narrator, only their own head

Owner feedback on the IRAJ-DL cuts (`demo_video/iraj_deadlock/out/{hype,meme,cinematic}/` on `Extension`; runner 1 `/srv/demo_out/iraj_deadlock/`):
"get rid of the generic narrator voice" and "only use my avatar for mine".
1. **Narration off by default:** Full experience currently sets `narration=True`, which adds a generic stock narrator voice. Make Full
   experience default `narration=False`; narration stays an explicit opt-in (UI toggle + persona). Update tests/docs.
2. **Reaction speaker filter:** add a `reaction_speakers` option (list of pack speaker names; empty = everyone) through API validation,
   capabilities and the UI (multi-select of the pack's speakers in edit settings, e.g. "Only me: Iraj"). The reaction picker must only use
   clips from the selected speakers (still varying labels/lines), and `cover_speakers` rotation must respect the filter. Tests.
3. **Re-render the owner's three cuts** (Hype 60 s landscape, Meme 30 s vertical, Cinematic 45 s landscape) from the saved IRAJ-DL job
   state/analysis on runner 1 (reuse plans/cards/thumbnails; **zero new Gemini calls**) with `reaction_speakers=["Iraj"]` and no narration.
   IRAJ-DL noted **Cinematic was too dark**: lift the Cinematic grade for this render if it can be done in your paths (otherwise report the
   exact change needed). Outputs `/srv/demo_out/iraj_deadlock2/` + local `demo_video/iraj_deadlock2/out/` (gitignored), Discord copies < 20 MB,
   contact sheets; verify by inspection that only Iraj's head appears and there is no narrator voice (ffprobe/stream list + plan JSON).
Full suite + frontend tests green on the runner.
