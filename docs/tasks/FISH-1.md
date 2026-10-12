---
id: FISH-1
branch: ext/FISH-1
allowed_paths: [full_app/cards/**, full_app/pipeline/rendering.py, full_app/pipeline/experience.py, full_app/tests/test_cards*.py, demo_video/fish/**, docs/cards.md]
---
# FISH-1: Bring back the Nano Banana intro + fish/car shitpost outro

The original app (`main:full_app/app.py` ~lines 560-610, `_generate_thumbnails` and its callers) made two **AI-generated cards** with Gemini
image editing (Nano Banana) and spliced them in as 4 s clips: an **intro** ("flashy TikTok thumbnail", bold corny title from `_generate_title()`,
energy effects, gameplay visible) and an **outro** ("meme-style outro screen", big "THANKS FOR WATCHING", **a random car and a fish somewhere**,
absurd shitpost). The owner loved it ("where is the fish theme"). On `Extension` it survives only in `server/legacy.py`; the new pipeline sends
`generate_thumbnails: false` everywhere and WIRE-1's intro/outro are plain generated cards. Restore it in the new pipeline:
1. `full_app/cards/`: intro + outro card generation via the merged Nano Banana client (`services/gemini_client.py::generate_thumbnail`;
   THUMB-1 found `gemini-3.1-flash-image` works on Vertex express; make the model configurable) from frames of the montage's top clip and last
   clip; keep the original prompts' spirit (corny hype intro with the montage title; absurd outro with THANKS FOR WATCHING + a random car + a
   fish), add variety (pick from a few prompt variants; the fish is mandatory, ha), mean mode gets a roast-flavored outro. Animate each card
   for ~3-4 s (slow zoom/shake, a whoosh/boom SFX from the library, music continues). 2 image calls per montage max, cached per job.
   Fallback when Gemini is unavailable: a local card (title + a drawn fish/car emoji via an OFL emoji font) **and** a visible job warning.
2. Hook it into the render path (`pipeline/rendering.py`, minimal, clearly separated) and turn it on in the Full experience preset
   (`pipeline/experience.py`) as `ai_cards: true`; the plain WIRE-1 cards remain the non-AI option. FINAL-1 is concurrently editing
   `pipeline/**`: keep your edits to those two files small and self-contained so the merge is trivial.
3. Tests with a fake image client (no live calls in tests): card generation, caching, fallback warning, timeline insertion.
4. Live: generate intro + outro for the Valorant montage (`/srv/demo_out/demo02/` on runner 1) and the Deadlock VOD
   (`/srv/demo_in/deadlock_ccby_aXZYyd4SoWM.mp4`): at most 6 image calls total. Save stills + a short preview mp4 to `demo_video/fish/out/`
   (gitignored). Full suite green on the runner.
