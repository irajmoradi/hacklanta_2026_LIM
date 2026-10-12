# AI intro/outro cards

Full experience enables `ai_cards: true`. Set `ai_cards: false` to retain the
plain WIRE-1 cards, or `cards: false` to disable automatic cards entirely.
The v2 pipeline uses the highest-scoring selected clip's midpoint for the intro
and the last selected clip's midpoint for the outro, after privacy processing.
The title comes from `options.title`, `job.title`, or `edit_plan.title`, then a
corny local default. Prompt variants are stable within a job; mean mode roasts
the gameplay. Every generated outro requests THANKS FOR WATCHING, a car and fish.

`GEMINI_IMAGE_MODEL` selects the image model (client default:
`gemini-3.1-flash-image`). Existing provider credentials apply, including
`GOOGLE_API_KEY` for Vertex express. No extra title-generation call is made.
Set `GOOGLE_GENAI_USE_VERTEXAI=true` for that backend. HTTP callers should send
`full_experience: true` alongside `ai_cards`; the preset registers the new boolean
with the existing shared option validator without editing server files.
There are at most two image transport attempts per job, also charged to its
shared Gemini budget. SDK retries are disabled by the existing thumbnail client.
The persistent `cards/` directory contains frames, stills, prompt metadata,
attempt markers and the image-budget ledger. Both successes and failures are
cached. Re-editing a job deliberately reuses those cards; start a new job to
regenerate them. Do not remove the attempt markers or budget ledger to retry.

Missing credentials, failed images or exhausted budgets produce local cards and
visible job warnings (including on cached rerenders). The bundled Noto Emoji
font draws fish/car glyphs offline; its SIL OFL license is in `cards/fonts/OFL.txt`.
Font source: https://github.com/google/fonts/tree/main/ofl/notoemoji

Cards last 3.5 seconds each, slowly zoom, and use the registered cinematic boom.
Music is mixed by the native renderer over the complete timeline. Existing
transition overlaps, caption offsets and narration segment offsets are preserved.
Cards add approximately seven seconds to the selected gameplay duration, less
transition overlaps; the planner's existing duration budget is unchanged.
Portrait/square output pads the generated landscape image to preserve lettering.
Legacy rendering reports AI cards as unsupported rather than silently claiming
to have generated them.

Offline verification: `tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_cards.py"`.
The explicitly live demo script is `demo_video/fish/live_smoke.py`; it makes two
image calls per input montage, reads credentials only from the environment, and
writes ignored stills and previews to `demo_video/fish/out/`.
`launch_live.py` reads the authorized local environment file at runtime and
passes only the key over SSH stdin. `diagnose_live.py` is an explicitly live
two-attempt diagnostic sharing a six-call run ceiling. `render_saved.py` builds
a preview from saved diagnostic stills with zero API calls.
