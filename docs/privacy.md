# Local gameplay privacy (EXT-20)

`full_app/privacy/` provides an opt-in Python API, a JSON blur-track format, a
local OCR detector, and an FFmpeg renderer adapter. Existing app behavior is
unchanged. No Gemini requests, uploads, or credentials are needed.

## Try it

From `full_app`, with the normal requirements, FFmpeg and Tesseract installed:

```sh
python -m privacy gameplay.mp4 private.mp4 --options privacy-options.json --track blur-track.json
```

Example `privacy-options.json` (coordinates normalized to the source frame;
times in source seconds, start inclusive and end exclusive):

```json
{
  "game": "valorant",
  "keep_own_name": true,
  "own_name": "MyHandle",
  "blur_webcam": true,
  "manual_boxes": [
    {"x": 0.72, "y": 0.7, "width": 0.28, "height": 0.2, "start": 2, "end": 8}
  ]
}
```

The output must be a new path. Manual boxes beyond the source duration and
invalid coordinates/nonfinite numbers are rejected. Manual boxes are always
applied regardless of whitelist settings. Output audio is retained and encoded
as AAC; privacy processing applies to video, not spoken personal information.

## API and renderer integration

```python
from privacy import PrivacyOptions, detect_video, render_private_source, render_montage

# Pass a JSON-decoded API object directly; Pydantic rejects unknown fields.
options = PrivacyOptions(game="ow2", keep_own_name=True, own_name="MyHandle")
track = detect_video(source_path, options)
track_json = track.model_dump(mode="json")
render_private_source(source_path, private_path, track_json)

# Or use an existing services.ffmpeg_runner.FFmpegRunner instance and edit plan:
final_path, track = render_montage(runner, edit_plan, options)
```

`render_montage` renders the private source, then runs the existing renderer with
that source. It supports both legacy and v2 plans without changing the input
runner. Temporary private-source files are removed after rendering. Apply
privacy **before** source cuts, speed changes, transitions, scaling and reframing;
a source-time track cannot be applied directly to a finished montage. The
adapter does this ordering automatically. `sanitize(source, output, payload)`
is the equivalent standalone one-call API and returns `(output_path, track)`.

Flask endpoints and frontend controls are outside this task's allowed paths;
this module does not register an HTTP route. An integrating route should pass
its privacy JSON object to this API and surface `track.warnings` for review.
There is no new mandatory option or behavior on existing requests.

## Detection and profiles

Defaults cover Valorant, Overwatch 2 (`ow2`), Deadlock and League of Legends
(`league`, `lol`). They include kill feed, scoreboard, moving-nameplate area,
chat, party/voice overlay and likely Discord/OBS notification positions.
They are conservative starting regions for standard 16:9 layouts, not learned
game-specific detectors. All recognized words inside these regions are treated
as potentially identifying. OCR boxes are padded by 5 pixels. Webcam masking
is a continuous whole-region mask only when requested; it is not face detection.

EXT-09 profiles are absent in this checkout. The `regions` field is the explicit
profile adapter: supply a mapping of names to normalized `{x,y,width,height}`
objects. It **replaces** defaults. For example a profile provider can pass
`PrivacyOptions(regions=profile_privacy_regions)`. Include a `webcam` region if
requesting webcam blur. Use `{}` for manual-only processing; adjust regions for
custom HUD scale, ultrawide footage and custom stream layouts.

`backend="auto"` uses the local Tesseract executable, parsing word-level TSV.
No Python OCR dependency is necessary. `backend="rapidocr"` uses the optional
`pip install -r privacy/requirements-rapidocr.txt` extra with bundled ONNX models.
It runs offline and may return whole text lines instead of individual words.
`backend="none"`, missing OCR or an OCR runtime failure falls back to continuous
whole-region masks and records warnings. The fallback cannot preserve an own
name; explicit coverage wins. No OCR text is stored in tracks or warnings.

OCR is sampled at 2 FPS by default, with a one-sample lookback and 0.75-second
hold. Overlapping boxes with overlapping time windows are merged into their
spatial union to bridge missed samples and small positional changes. The
whitelist compares the entire OCR result using Unicode normalization and
case-insensitive exact matching, never substring matching: a line containing
both the uploader and another name stays masked. Manual/webcam masks, nearby
padded masks, or overlapping smoothed regions can still cover the uploader.

## Blur tracks and verification

`BlurTrack` contains `width`, `height`, `duration`, `boxes`, and `warnings`.
Each box has normalized coordinates, `start`, `end`, and a descriptive `kind`.
Recognized names and chat text are deliberately excluded. The filter builder
emits crop + repeated boxblur + overlay with timestamp enable expressions.
FFmpeg uses a temporary filter script to avoid command-line length limits.
Frames outside active windows and pixels outside masks are left unfiltered
(the normal output encode can introduce compression differences).

Run offline checks from the worktree root:

```sh
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_privacy.py"
tools/remote_run.sh "cd full_app && python -m pytest -q -m 'not live'"
```

Tests synthesize usernames/chat with FFmpeg drawtext, use real local Tesseract,
simulate missing/failed OCR, verify exact time/space masks in lossless frames,
check whitelist behavior, and exercise audio-preserving rendering. No live
Gemini calls are used.

Review the result before sharing: OCR can miss stylized, tiny or briefly visible
text between samples; default regions cannot cover every custom overlay.
Increase sample FPS, adjust profile regions, or add persistent manual boxes for
known sensitive areas. Blur is not a guarantee of irreversible redaction,
especially for tiny boxes. Conservative regions may obscure gameplay/UI.
The prepass costs an additional encode, and many OCR boxes increase graph size
and rendering cost. Inputs are expected to have a normal zero-based, constant
frame-rate timeline; normalize variable-frame-rate/rotated capture files before
detection, since OpenCV frame-count timing is used.
