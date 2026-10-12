---
id: THUMB-1
branch: ext/THUMB-1
allowed_paths: [full_app/social/**, full_app/services/gemini_client.py, full_app/tests/test_social*.py, full_app/tests/test_thumb*.py, demo_video/thumb/**, docs/social.md]
---
# THUMB-1: Nano Banana thumbnails for real

The share kit can call Gemini image generation (`services/gemini_client.py::generate_thumbnail`, model `gemini-3.1-flash-image-preview`,
"Nano Banana") but only when `options.gemini_image` is set; it is off everywhere, and failures are swallowed into a log warning
(`full_app/social/__init__.py` ~line 110). Every demo thumbnail so far was the local frame+text template. Make Nano Banana thumbnails real:
1. Verify the model works through Vertex express (`GOOGLE_API_KEY` env-only from /c/Users/mourn/Downloads/hacklanta/.env,
   `genai.Client(vertexai=True, api_key=...)`); if that model id is unavailable there, find the current Nano Banana image model id that is
   (list models or try the documented ids) and make it configurable (`GEMINI_IMAGE_MODEL`).
2. **YouTube-style thumbnail generation:** inputs = the best highlight frame(s) + optionally one matted reaction head from the team pack
   (`/srv/packs/team/*.alpha.webm` / mask files: extract a frame with a big expression; consented teammates only, from that pack) + mode
   (nice/mean) + game. Prompt for a bold gaming thumbnail: dramatic grade, subject pop, the reaction head large on one side with an
   exaggerated expression, arrows/circles at the action, 2-4 word punchy text ("NO SHOT", "1v4 CLUTCH", "SKILL ISSUE"...) rendered by us
   **locally** on top (do not trust model text), 16:9 + 9:16 + 1:1 variants (generate one image, recompose crops locally if possible).
   Generate 2 candidates per job and pick/offer both. Cap: 4 image calls per job; reuse the call budget machinery.
3. Never silently fall back: a failed/disabled generation must appear in the job's `warnings` and the share-kit metadata (`provider`,
   `reason`). Keep the local template as the fallback.
4. Tests with a fake client (no live calls in tests): option handling, budget, fallback warnings, composition sizes.
5. Live: generate thumbnails for the Valorant demo (frames from `/srv/demo_out/demo02/` montages on runner 1) and the Deadlock CC BY VOD
   (`/srv/demo_in/deadlock_ccby_aXZYyd4SoWM.mp4`) — at most 8 image calls total; save to `demo_video/thumb/out/` (gitignored) and report.
**Report** (do not edit outside your paths): exactly which line(s) in the Full experience preset (`full_app/pipeline/experience.py`) and the
UI should turn `gemini_image` on by default, so the integrator can apply it.
