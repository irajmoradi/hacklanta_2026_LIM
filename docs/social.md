# Montage share kits

`social.build_share_kit(job_dir, clips, plan, game) -> pathlib.Path` creates a
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
    "thumbnail_text": "LAST-SECOND SAVE",
    "subject_cutout": True,
    "gemini_metadata": False,
    "gemini_image": False,
}
```

Local thumbnails use an edge-saliency crop, outlined white text in a dark panel,
and a bright outlined arrow. Text is measured, wrapped (including long unbroken
strings), and shrunk inside the safe rectangle: x=8–88%, y=12–38%. These deliberately
generous margins help avoid overlays, but preview the cover in the target app.
Text is capped at 160 characters. Fonts without a requested glyph may show a
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
- Image: `client.generate_thumbnail(reference_path, prompt, output_path)`.

Each enabled pass makes at most one call, without retries (two total). API keys
alone never enable network access. Metadata errors or malformed JSON use the
deterministic title/description templates. Image errors keep the local frame.
Fallbacks log generic messages without provider exception text.
Generated imagery is composed locally afterward so output sizes and text bounds
remain fixed. Provider exceptions are not serialized because they may contain
credentials. The task tests mock both calls; no live calls were needed.

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
tools/remote_run.sh "cd full_app && python -m pip install -q -r social/requirements.txt && python -m pytest -q tests/test_social.py"
```

Tests generate synthetic `testsrc2` video with `sine` audio, block socket
connections, and mock Gemini/SAM. They cover full kit contents, safe text bounds,
aspect ratios, scoring, ordering/speed/intro timing, limits/tags, fallback behavior,
caption export, path containment, and cleanup after an unsuccessful export.

Call this library after rendering. Install `social/requirements.txt` when
enabling share-kit exports.
