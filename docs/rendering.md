# Render engine v2 (EXT-04)

V2 is opt-in. Existing edit plans still use the original renderer. Submit a plan
with `render_version: 2` through the existing render endpoint's `edit_plan`, or
call `FFmpegRunner.render(RenderPlan(...))` directly. No Gemini call is needed.
The planner can consume `RenderPlan.model_json_schema()`; its prompt and frontend
are outside this task's allowed paths, so automatic planner selection is not changed.

From `full_app/`, a minimal local render is:

```python
from pathlib import Path
from render import RenderPlan
from services.ffmpeg_runner import FFmpegRunner

plan = RenderPlan.model_validate({
    "render_version": 2,
    "preset": "vertical",
    "resolution": 720,
    "fps": 30,
    "reframe": "motion",
    "segments": [
        {"source_start": 0, "source_end": 2, "title": "Clean play",
         "video_effects": ["text_gg"],
         "words": [{"start": 0.2, "end": 0.7, "text": "Nice!"}]},
        {"source_start": 2, "source_end": 4}
    ],
    "captions": {"enabled": True, "mask_profanity": True},
    "transition": "flash",
    "transition_duration": 0.15,
    "intro": {"text": "Match highlights", "duration": 1},
    "outro": {"text": "GG", "duration": 1}
})
runner = FFmpegRunner(Path("workspace/demo"), Path("gameplay.mp4"), 1920, 1080, 30)
print(runner.render(plan))  # workspace/demo/final_edit.mp4
```

The source must be at least four seconds for this example. Paths are local
server paths, resolved relative to the process working directory. Workspaces
should remain per-job, as in the existing application.

## Export and timing contract

| Preset | 720 | 1080 |
| --- | --- | --- |
| landscape | 1280×720 | 1920×1080 |
| vertical | 720×1280 | 1080×1920 |
| square | 720×720 | 1080×1080 |

Outputs are constant-frame-rate H.264, yuv420p, square pixels, AAC stereo at
48 kHz, and MP4 faststart. FPS defaults to 30. The existing hardware probe selects
NVENC; each v2 encode retries with libx264 if NVENC fails. Silent sources get
silent stereo audio. Scratch files are isolated and cleaned on success/failure;
the previous final output is replaced only after successful rendering.

Source intervals are validated against ffprobe duration. Times must be finite,
nonnegative, and ordered. Durations and overlaps are rounded to output frames.
Output duration is the sum of effective clip/card durations minus overlaps.
Extremely short clips that cannot support the selected transition are rejected.
The final boundary can differ by one frame plus AAC padding.

## Reframe

`crosshair` (default) fixes the crop at the center, appropriate for FPS footage.
`motion` samples grayscale frames at 4 Hz, ignores the outer HUD band, estimates
a frame-difference centroid, exponentially smooths it, and interpolates the pan.
The graph clamps the crop inside the image. Both x and y are supported; the
crop fills the chosen preset. `blur` keeps the full foreground image over a
blurred, filled background and does not use tracks.

An external per-segment track overrides motion/crosshair estimation:

```json
{"source_start": 10, "source_end": 13,
 "sam": {"subject_track": [
   {"time": 0, "x": 0.4, "y": 0.5},
   {"time": 1.5, "x": 0.7, "y": 0.5}
 ]}}
```

Times are relative to the extracted clip, coordinates are normalized image
centers in [0,1], and times must strictly increase. This is a data adapter, not
a dependency on a SAM package. External tracks are limited to 500 points;
motion analysis retains at most 120 points. Motion saliency cannot distinguish
camera shake from a subject; use crosshair or an external track for those clips.

## Captions, titles, and effects

`captions.enabled` burns supplied segment `words` into ASS subtitles, one word
at a time with a short scale pop. Word times are clip-local. Words are clipped
to the effective segment duration. Bottom margins are 20% for vertical, 10%
otherwise, with 10% horizontal margins. Titles use the top safe area. Input
text cannot inject ASS override tags. `mask_profanity` uses case-insensitive
whole-word matching; customize the `profanity` list for your language/policy.
It is a small configurable list, not comprehensive moderation.

For optional automatic transcription, install `faster-whisper` separately:

```bash
python -m pip install faster-whisper
```

Pre-cache a compatible model or give `captions.model` a local model directory,
then set `captions.transcribe: true` and `captions.enabled: true`. The adapter
uses CPU/int8, word timestamps and VAD, and prohibits implicit model downloads
while rendering. Missing dependency/model or an unavailable inference runtime
emits a warning and continues without generated captions. Supplied words take
precedence. No torch/Whisper dependency is added to the core requirements.
Transcription hears the clip audio mix, not an isolated voice stem.

`video_effects` uses the existing meme overlay/color/effect registry.
V2 deliberately rejects speed effects, chromatic_aberration's legacy complex
graph, and the unimplemented fade_out effect, rather than silently corrupting
timing. They remain available via the legacy renderer as before. SFX retain
the existing `sfx_key` and `offset_in_segment` format and missing-file fallback.
Titles coexist with meme overlays. Intro/outro cards are black with styled text
and silent audio.

## Music and transitions

Optional music configuration:

```json
{"path": "music/owned-track.wav", "volume": 0.18,
 "beat_sync": true, "snap_tolerance": 0.25, "duck": true}
```

Use media you have permission to use. The bed loops to cover the render. A
dependency-free FFmpeg PCM energy-onset detector finds approximate beats;
optionally supply sorted `beats` in music-local seconds for exact timing.
Intermediate gameplay cuts snap backward within tolerance, never extending
source boundaries. For transitions, the beat aligns with the start of the
overlap; intro offsets are included. Card boundaries and the final cut remain
fixed. Snaps are quantized to frames. Constant-energy music may yield no beats,
in which case the original cut timings remain.

Sidechain compression ducks the bed from the composite clip audio, including
voice and SFX (also loud gameplay audio). It is not speech separation. The
final mix is limited to avoid clipping; `duck: false` disables sidechaining.

`cut` is the default transition. Other presets map to FFmpeg xfade filters:
`fast_zoom` → zoomin, `whip` → slideleft, `flash` → fadewhite,
`glitch` → pixelize. These are intentionally lightweight stylizations. Audio
uses matching triangular acrossfades. Overlap defaults to 0.15 seconds and is
bounded by the shortest clip/card. The pure graph builders use stable numeric
formatting and explicit stream labels.

Requires an FFmpeg build with libx264, AAC, libass, drawtext, xfade, and
sidechaincompress, plus ffprobe and a sans-serif font. Filter contracts follow
the [FFmpeg filter documentation](https://ffmpeg.org/ffmpeg-filters.html).

## Verification

Run from the worktree root:

```bash
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_render_v2.py"
```

Tests synthesize testsrc2/sine/energy-pulse media without network access or
Gemini calls. They check every preset/resolution, transitions, silent sources,
reframe modes, combined captions/SFX/music/cards, schema failures, optional
dependency fallback, legacy dispatch, and fixed filtergraph snapshots. ffprobe
asserts resolution, codecs, pixel format, sample aspect ratio, duration and A/V
agreement. CPU encoding is forced for reproducible CI; hardware NVENC and real
Whisper inference require an equipped host and are separate smoke checks.
