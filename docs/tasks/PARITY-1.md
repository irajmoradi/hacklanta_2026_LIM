---
id: PARITY-1
branch: ext/PARITY-1
allowed_paths: [docs/parity_audit.md]
---
# PARITY-1: Everything the ORIGINAL app did — is it still in the new pipeline?

The owner keeps finding original features that the Extension's new pipeline silently dropped (latest: the Nano Banana intro card and the
"THANKS FOR WATCHING" outro with a random car and a fish, which survive only in `server/legacy.py`; FISH-1 is restoring that one).
**Report only.** Enumerate every user-visible behavior of the original app on `main` (`git show main:<path>`; especially `full_app/app.py`,
its prompts `full_app/prompts/**`, `full_app/models/effects.py`, sfx usage, styles/modes (nice/mean, hype_montage etc.), titles
(`_generate_title`), thumbnails/intro/outro, transitions, text overlays, speed ramps, music, captions, the original `full_app/frontend/`
controls and flows, export options, any Gemini prompt instructions about humor/memes/editing style) and for each check whether the stock
**new** path on `Extension` (production_frontend → server jobs API → pipeline/orchestrator → planner v2 → render v2) still does it, by
reading code paths and by checking real outputs on runner 1 (`/srv/demo_out/demo02/` plans and renders, and `/srv/demo_out/fx2/` if
present; `/srv/demo_in/final_v3.mp4` and `/srv/demo_in/mean_meme_v2.mp4` are ORIGINAL-app outputs: sample frames/audio to see what the old
app actually produced and compare with new outputs). Write `docs/parity_audit.md`: original feature · original code (main path:line) ·
new-path status (✅ same or better / 🟠 weaker (how) / 🔴 dropped / 🟡 legacy-only) · evidence · exact fix and which file(s).
End with a prioritized fix list grouped into non-overlapping path sets. Note: FINAL-1 (pipeline/server/render/planner/frontend), FX-3
(VFX), FISH-1 (cards), DEADLOCK-1 (profiles/signals) are running now; mark items they already cover.
