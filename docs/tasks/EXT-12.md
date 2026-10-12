---
id: EXT-12
branch: ext/EXT-12
allowed_paths: [full_app/planner/**, full_app/prompts/editor_v2.txt, full_app/tests/**, docs/planner.md]
---
# EXT-12: Edit planner v2 (story, pacing, effect placement)
Replace the one-shot "plan the edit" prompt with a planner that produces a great montage structure. Build `full_app/planner/`:
- Input: ranked clips (start/end, score, label highlight/lowlight, caption, reaction label, signals, game profile), mode (nice/mean), style
  (hype montage, clean edit, meme edit, cinematic), target length and aspect.
- **Structure:** hook in the first 3 seconds (best moment teaser), build-up, escalating highlights, climax (top clip last), outro; for mean mode,
  a "roast arc" (setup, fails, worst fail last). Enforce variety (don't stack 3 similar clips), length budget, min/max clip length, trims to the action.
- **Effect placement rules** (deterministic, then optionally refined by the LLM): which effects/SFX/text overlays go where (impact frame on the kill,
  slow-mo on clutches, zoom punch on multikills, meme text on fails), using `models/effects.py` names; reaction overlay slots (EXT-06) at peaks;
  caption/transition choices; music energy curve.
- Output the declarative `RenderPlan` shape (define a local Pydantic model mirroring EXT-04's planned `RenderPlan`: clips[], effects[], sfx[],
  text[], transitions[], reactions[], music); include `prompts/editor_v2.txt` for an optional Gemini refinement pass (mocked in tests).
Tests: given synthetic clip lists, the plan respects the length budget, hook/climax ordering, variety and effect rules; mean vs nice differ.
Write docs/planner.md.
