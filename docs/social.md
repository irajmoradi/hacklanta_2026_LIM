# Montage share kits

`social.build_share_kit(job_dir, clips, plan, game, *, client=None, job=None) -> pathlib.Path` creates a
posting kit at `job_dir.parent/share/job_dir.name/`. It is an opt-in library;
the Flask routes and existing render defaults are unchanged. Run it after render.

From `full_app/`, install the small image dependency once:

```sh
python -m pip install -r social/requirements.txt
```

FFmpeg and ffprobe must be on PATH. No torch, OCR, SAM weights, or network access
is needed. A bold system font is used when available, with a Pillow font fallback.

```python
from social import build_share_kit

# Use the same clips and edit plan already returned by the application.
kit = build_share_kit(job["dir"], job["clips"], job["edit_plan"], "Valorant")
print(kit)
```

The directory contains:

- `video.mp4`: a byte-for-byte copy of the rendered montage.
- `thumbnail_youtube.jpg`: 1280 x 720 (16:9).
- `thumbnail_vertical.jpg`: 1080 x 1920 (9:16), shared Shorts/TikTok cover.
- `thumbnail_square.jpg`: 1080 x 1080 (1:1).
- `thumbnail_candidate_{1,2}_{youtube,vertical,square}.jpg`: both candidates,
  each recomposed locally. The first successful generated candidate is selected;
  the conventional filenames above are aliases of it (candidate 1 if both fail).
- `metadata.json`: three title options per platform, descriptions, game hashtags,
  structured montage chapters, frame scores, text layout bounds and provider status.
- `chapters.txt`: full montage-relative chapter list, including an intro if present.
- `captions.srt`: optional existing SRT or captions serialized from the plan.

Exports are staged in a temporary sibling directory and published after all files
are complete. Failures clean up staging. An existing kit is rejected with
`FileExistsError`; archive or remove that kit explicitly before rebuilding. No
upload or publishing happens. Video and caption file overrides must resolve inside
the job directory. Do not place credentials in the plan or metadata.

## Input and timeline conventions

The default video is `final_with_thumbs.mp4` if present, otherwise
`final_edit.mp4`. The default frame source is `source.mp4`; if absent, frames come
from the matching interval in the rendered montage. Override paths are relative
to `job_dir`. The caller must supply the plan used for this render, since the
package cannot infer edits from the finished video.
Explicit source/caption overrides must exist; only missing default filenames
trigger the montage-frame fallback or omission of an SRT.

Clips accept application dictionaries or Pydantic models, with `start_seconds` /
`end_seconds`, `start` / `end` (seconds or colon-delimited timestamps), or
`source_start` / `source_end`. Plans accept an `EditPlan` or a dictionary with
`segments` in render order. Without `segments`, the clip list defines the sequence.
An explicitly empty segment list is an error.

Descriptions are matched by greatest overlap with each selected source interval.
The top included clip is selected by `score`, then `highlight_score`; when scores
are absent, `type="good"` gets priority, followed by stable montage order.
Eight interior frames are sampled. Normalized edge variance (65%) plus
frame-difference motion energy (35%) chooses the final frame. This is a lightweight
visual heuristic, not a semantic assessment of the play. Sampling is bounded and
FFmpeg commands have timeouts.

Chapter starts accumulate `(source_end - source_start) / speed`, multiplied by
the renderer's `slow_motion` and `speed_2x` effects. A segment's explicit
`output_duration` overrides that calculation for future renderers. Fade/flash
transitions do not overlap in the current renderer. For `final_with_thumbs.mp4`,
`intro.mp4` is probed automatically; supply `intro_duration` for other intros.
The exporter rejects a timeline extending more than 250 ms beyond the montage.
Chapters use whole seconds, with `HH:MM:SS` after one hour. Sub-second duplicate
starts are collapsed in chapter text; exact starts remain in JSON. Platform
automatic chapter recognition has additional rules; the export remains a useful
timestamp list even for short montages.

Plan captions are `{start, end, text}` objects in **rendered-video seconds**,
including any intro offset. They are sorted and written with millisecond SRT
timestamps; invalid intervals raise an error. Source-relative transcript timing
must be remapped by the caller. If the plan has no `captions` field, an existing
`captions.srt` is copied unchanged and is assumed to already match the montage.
An explicitly empty caption list suppresses the SRT.

## Options and provider adapters

Optional settings live under `plan["social"]`:

```python
plan["social"] = {
    "video_path": "final_edit.mp4",
    "source_path": "source.mp4",
    "intro_duration": 0,
    "captions_path": "captions.srt",
    "thumbnail_text": "LAST SECOND SAVE",
    "mode": "nice",  # nice or mean
    "reaction_head": "iraj-hype.alpha.webm",  # optional, only /srv/packs/team
    "subject_cutout": True,
    "gemini_metadata": False,
    "gemini_image": False,
}
```

Local thumbnails use an edge-saliency crop, outlined white text in a dark panel,
and a bright outlined arrow. Text is measured, wrapped (including long unbroken
strings), and shrunk inside the safe rectangle: x=8–88%, y=12–38%. These deliberately
generous margins help avoid overlays, but preview the cover in the target app.
Share-kit titles use 2-4 words, defaulting to `NO SHOT` (nice) or `SKILL ISSUE`
(mean); supplied titles are uppercased and limited to four words. The low-level
renderer caps text at 160 characters. Fonts without a requested glyph may show a
replacement glyph; install a suitable system font for the intended language.

When `subject_cutout=True`, an optional importable `sam` adapter is called as
`sam.cutout(pillow_rgb_image) -> pillow_rgba_image`. It should return the subject
on transparency. A successful cutout is composited with a cyan glow; missing,
incompatible or failing adapters retain the saliency composition. This contract
avoids assuming a particular SAM package or downloading a model.

To enable Gemini, explicitly pass `client=existing_gemini_video_client` **and**
enable the corresponding flag. The client follows the existing
`services.gemini_client.GeminiVideoClient` pattern:

- Metadata: `client.client.models.generate_content(model=client.model, ...)`.
- Image: `client.generate_thumbnail(reference_path_or_list, prompt, output_path,
  image_budget=ledger)`. Custom adapters must honor the supplied `CallBudget` by
  reserving each transport attempt, as `GeminiProvider` does.

Image generation requires the literal boolean `gemini_image=True` and an explicit
client. Two candidate requests use different color treatments and include game,
mode and the best scored gameplay frame. The optional reaction comes only from a
resolved `.alpha.webm` inside `/srv/packs/team`; arbitrary portraits and symlinks
outside the pack are rejected. Four frames are sampled from the chosen expressive
reaction clip; visible motion chooses a frame, not a facial-expression detector.
Missing/invalid reactions warn and continue with gameplay. No new ML dependency.

The model is `GEMINI_IMAGE_MODEL` (default `gemini-3.1-flash-image`). For Vertex
express set `GOOGLE_GENAI_USE_VERTEXAI=true` and `GOOGLE_API_KEY` in the process
environment, or construct `GeminiVideoClient(vertexai=True)` explicitly. The SDK
uses `genai.Client(vertexai=True, api_key=...)`. API keys alone never enable image
generation. See Google's [express-mode model list](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/start/express-mode/overview).

Each candidate uses exactly one attempt, with SDK and application image retries
disabled. Each attempt reserves both the client's shared job budget and a durable
`thumbnail-budget.sqlite3` ledger capped at **four image calls per job**. Failed
transport attempts count. Supply the existing pipeline client with its
`gemini-budget.sqlite3` budget; when calling the library independently, bind that
shared budget yourself if it must survive process restarts. The image ledger is
always durable. Reservations are conservative: if the global budget refuses a
call, its image reservation stays spent. Repeated builds/restarts do not reset
the image ledger. Normal successful builds use two image calls, and metadata
generation remains independently opt-in.
Direct legacy intro/outro calls also use the same image ledger when the client's
shared budget is bound to the job directory, so they cannot bypass the four-call cap.

Generation never supplies the title: prompts request no text, then Pillow adds
measured text and an arrow. Landscape retains the master; square retains the full
scene on a blurred background; portrait with a reaction stacks the action and
reaction crops so both remain visible. No extra model calls for aspect ratios.

Every disabled/missing-client/failed candidate has `provider="local"`, a safe
`reason`, and a warning in `metadata.json`. Success uses `provider="gemini"` and
`reason=null`. All candidates and variants are in `thumbnail_candidates`; selected
variants remain in `thumbnails` for compatibility. The top-level `provider`
continues to describe posting-copy generation, not image generation. Provider
exception text is never serialized. Local frames remain usable when generation
fails. Pass the mutable `job=job_state` to also append warnings to its `warnings`
list and inherit `job_state['options']`; `plan['social']` explicitly overrides
those options. The job directory owns the image ledger even if export uses a
temporary scratch directory. Callers must persist the updated job as usual.

```python
from services.gemini_client import GeminiVideoClient
from services.call_budget import CallBudget
from pathlib import Path

job['options'].update(gemini_image=True, mode='nice')
with GeminiVideoClient(vertexai=True) as client:
    client.budget = CallBudget(Path(job['dir']) / 'gemini-budget.sqlite3')
    kit = build_share_kit(job['dir'], job['clips'], job['edit_plan'], 'Valorant',
                          client=client, job=job)
```

Game aliases include Valorant, Overwatch/Overwatch 2, Deadlock, and
League/League of Legends/LoL; unknown games receive generic gaming hashtags.
Copy uses conservative export budgets (Python character counts), not a guarantee
about changing publishing APIs:

| Platform | Title | Description including chapters and hashtags |
| --- | ---: | ---: |
| YouTube | 100 | 5000 |
| Shorts | 100 | 2200 |
| TikTok | 150 | 2200 |

Hashtags remain intact; descriptions include only complete chapter lines that
fit. The full chapter list remains in `chapters.txt`. Gemini copy is prompted to
avoid invented achievements, but review generated copy and imagery before posting.

## Verification

From the worktree root, run on the Linux runner:

```sh
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_social.py tests/test_thumb.py"
```

Tests generate synthetic `testsrc2` video with `sine` audio, block socket
connections, and mock Gemini/SAM. They cover full kit contents, safe text bounds,
aspect ratios, scoring, ordering/speed/intro timing, limits/tags, fallback behavior,
caption export, path containment, and cleanup after an unsuccessful export.

Call this library after rendering. Install `social/requirements.txt` when
enabling share-kit exports.

## THUMB-1 integration handoff (outside this task's allowed paths)

Line numbers refer to the unmodified files on this task branch. **Preset/UI flags
alone are insufficient**: the existing caller does not pass a client or job.
These changes belong to the integrator:

1. `full_app/pipeline/experience.py:7`: add `gemini_image=True` next to
   `social=True` in `FULL_EXPERIENCE`.
2. `full_app/production_frontend/src/features.ts:7`: add `gemini_image: false`
   to `extensionDefaults` so manual mode stays opt-in. In
   `full_app/production_frontend/src/components/EditSettings.tsx:32`, add
   `"gemini_image"` to the Full experience button's list set to `true`. Add
   `["gemini_image", "AI thumbnails", "Generate two covers for your share kit."]`
   alongside the share-kit toggle at line 26.
3. `full_app/server/validation.py:24`: include `gemini_image` in
   `EXTENSION_FLAGS`; `full_app/server/capabilities.py:10`: include it in the
   `social` controls list. Without capability advertising,
   `production_frontend/src/api.ts:205-208` filters the UI option out.
4. `full_app/pipeline/extensions.py:309-310`: keep the executed share plan, but
   call `build(..., client=image_client, job=job)`. Construct the image client
   only when requested, using the existing runtime credentials/backend and
   `CallBudget(Path(job['dir']) / 'gemini-budget.sqlite3')`; close it in `finally`.
   A missing key should warn and pass `client=None` so this library records
   `client_unavailable`. For local video providers, use a dedicated Gemini image
   client only if explicitly requested; `LocalClient` has no image method.
   Passing `job` propagates `gemini_image`, mode and warnings and anchors the
   four-call ledger outside the temporary export directory.
5. `full_app/pipeline/extensions.py:318`: optionally build covers from each
   `metadata['thumbnail_candidates'][i]['variants']` to expose both candidates
   in the UI. All candidate files already appear in the existing download list.

The simple frontend's `generate_thumbnails` checkbox and the legacy API flag
control video intro/outro cards, a separate feature; they do not enable share-kit
Nano Banana images. This branch does not change their defaults.

## Explicit live smoke

`demo_video/thumb/live_smoke.py` is an opt-in executable, never a pytest test.
It probes the old model ID once, then generates two candidates each for the
Valorant montage and the specified Deadlock CC BY VOD. It has a durable eight-call
run ledger, two candidate requests per job, and the production four-call job
ledger. The `--retry-failed` option reuses those ledgers. The PowerShell launcher
reads `GOOGLE_API_KEY` from the user's existing external `.env` at runtime and
sends only the key over SSH stdin; it never writes the key to disk or arguments.

```powershell
bash tools/remote_run.sh 'python -m py_compile demo_video/thumb/live_smoke.py'
powershell -NoProfile -ExecutionPolicy Bypass -File demo_video/thumb/run_live.ps1
# Only after a quota cooldown, and without resetting either ledger:
powershell -NoProfile -ExecutionPolicy Bypass -File demo_video/thumb/run_live.ps1 -RetryFailed
```

Retrieve `demo_video/thumb/out/` from the runner before another remote sync
(the sync uses `--delete`). Outputs are ignored by `demo_video/thumb/.gitignore`.
The report records the exact model, sources, frame timestamps, attempts, warnings,
and all output files. Local recomposition of existing masters costs no API calls:
`python demo_video/thumb/live_smoke.py --compose-only`.
