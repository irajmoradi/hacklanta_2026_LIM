# FISH-1 implementation and live evidence

Branch: `ext/FISH-1`. No push or merge performed.

Changes are restricted to `full_app/cards/**`, the two allowed pipeline files,
`full_app/tests/test_cards.py`, `docs/cards.md`, and `demo_video/fish/**`.

- `8f05ec7`: cached image generation, local OFL fish/car cards, native timeline
  adapter, Full preset default, tests and documentation.
- `5d5858f`: Full preset HTTP option registration, safe provider failure codes,
  merged-client mock coverage, bounded live scripts and offline preview tool.

## Live evidence

Runner 1: `104.207.133.47`, `/srv/lim/lim-fish1/demo_video/fish/out/`.
All outputs were also copied to this worktree's ignored `demo_video/fish/out/`.
The authorized credential was read at runtime and sent over SSH stdin; no key
was written into an artifact or committed.

`python demo_video/fish/launch_live.py` exited **1**: four image attempts,
all falling back. Both source previews nevertheless rendered successfully:

| Source | Mode | Preview | Duration |
| --- | --- | --- | --- |
| Valorant `automatic_montage_landscape.mp4` | nice | `out/valorant/output.mp4` | 11.008 s |
| Deadlock CC BY VOD, 120–122 / 126–128 s | mean | `out/deadlock/output.mp4` | 11.008 s |

Each preview has a 3.5-second intro, two two-second gameplay clips, a
3.5-second outro, boom SFX, and continuous locally synthesized music. Output is
1280×720, 24 fps, H.264/AAC. Fallback stills and the contact sheet were visually
checked: readable titles, cyan fish, pink car, and a gameplay roast on the mean outro.

`python demo_video/fish/launch_live.py --diagnose` exited **0**: the final two
authorized image attempts both succeeded with `gemini-3.1-flash-image` on Vertex
express. `out/diagnostic_intro.png` has the neon PHOENIX DIFF title and visible
gameplay; `out/diagnostic_outro.png` has THANKS FOR WATCHING, a flying taxi and a
large fish. Both were visually inspected. `out/diagnostics.json` records the
shared ledger total: **6 paid attempts**, with no further calls made.

`RUNNER_IP=104.207.133.47 tools/remote_run.sh "python demo_video/fish/render_saved.py"`
exited **0**, rendering `out/valorant_ai_preview.mp4` from those stills without
provider access. The original fallback caches and reports are preserved.

The first four fallbacks preceded the addition of safe failure-code recording;
their underlying provider errors were not retained, so no cause is asserted.
**Remaining live limitation:** Deadlock has verified fallback cards, not a
successful AI-generated pair. The six-call allowance is exhausted.

## Verification

Commands were launched from PowerShell using `bash tools/remote_run.sh ...`;
the `RUNNER_IP` override below denotes the environment variable set at launch.

| Command | Result |
| --- | --- |
| `tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_thumb.py"` | 19 passed; exit 0 |
| `tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_cards.py"` (initial) | 6 passed; exit 0 |
| `RUNNER_IP=104.207.133.47 tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_cards.py tests/test_wire1.py"` | 11 passed; exit 0 |
| `RUNNER_IP=104.207.133.47 tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_cards.py tests/test_thumb.py"` (final targeted) | 27 passed; exit 0 |
| `tools/remote_run.sh "cd full_app && python -m pytest -q"` (before option registration fix) | 3 failed, 1157 passed, 21 skipped; exit 1. All failures rejected the new `ai_cards` option. Fixed in `5d5858f`. |
| `RUNNER_IP=104.207.133.47 tools/remote_run.sh "cd full_app && python -m pytest -q"` (after fix) | **1162 passed, 20 skipped**, 617.80 s; **exit 0** |

The final targeted run includes the additional merged-client transport test
added after the full-suite run began collection; all eight card tests and all
19 thumbnail tests passed together. `git diff --check` exited 0. `ffprobe` of
the saved AI preview exited 0 and confirmed 11.008 s, 1280×720, 24 fps, H.264/AAC.

## Try it and limits

Use the Full experience UI/API preset with Vertex credentials in the server
environment (`GOOGLE_GENAI_USE_VERTEXAI=true`, `GOOGLE_API_KEY`). To retain plain
cards, send `full_experience: true, ai_cards: false`. `GEMINI_IMAGE_MODEL` changes
the image model. Per-job cards and failures are durable; a new job is required
for fresh cards. See `docs/cards.md` for the cache and budget contract.

AI cards add approximately seven seconds to gameplay; the planner's existing
duration budget is unchanged. Landscape cards are padded in portrait/square
output to preserve generated lettering. Gemini may still omit requested visual
details; this module does not spend extra calls to judge or regenerate images.
The preset registers its boolean in the shared validator from the allowed
experience module; HTTP callers should include `full_experience: true`.

Deadlock source attribution: No Copyright Gameplay, CC BY, video
`aXZYyd4SoWM` (the provided runner asset). No source footage is committed.
