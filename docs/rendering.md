# Render engine v2 (EXT-04)

The job pipeline uses v2 composition by default and adapts legacy plans as needed.
Submit `render_version: 2` through the render endpoint's `edit_plan`, or call
`FFmpegRunner.render(RenderPlan(...))` directly. No Gemini call is needed for an
explicit plan. The optional local planner uses `planner.adapter.to_render_plan`;
do not pass a planner `model_dump()` straight to the renderer.

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
the previous final output is replaced only after successful rendering. Complex
graphs are passed through temporary scripts to avoid Windows command-line
length limits. Music is mixed separately and muxed with copied video to avoid
early audio termination from multi-input scheduling on older FFmpeg releases.

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
python -m pip install -r render/requirements-captions.txt
```

Pre-cache a compatible model or give `captions.model` a local model directory,
then set `captions.transcribe: true` and `captions.enabled: true`. The adapter
uses CPU/int8, word timestamps and VAD, and prohibits implicit model downloads
while rendering. Missing dependency/model or an unavailable inference runtime
emits a warning and continues without generated captions. Supplied words take
precedence. No torch/Whisper dependency is added to the core requirements.
Transcription hears the clip audio mix, not an isolated voice stem.

`video_effects` uses the existing meme overlay/color/effect registry.
Use segment `speed` for playback rate. `timed_effects` supports localized
chromatic aberration and fade-out; these remain excluded from the older
whole-segment `video_effects` list. The legacy renderer also supports them. SFX retain
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
agreement. Additional tests verify dense external tracks, mocked local Whisper,
NVENC retry behavior, and measurable music attenuation under a synthetic voice
signal. CPU encoding is forced for reproducible CI; hardware NVENC and real
Whisper inference require an equipped host and are separate smoke checks.

## Planner adapter and placement clocks

Adapter version 1 consumes planner `version: 2` and emits `render_version: 2`.
Empty/unknown planner versions are rejected. Source cuts remain source seconds;
`speed` changes their output duration. `texts`, `timed_effects`, `reactions`, SFX
and words are clip-local **output** seconds. The adapter subtracts the owning
clip start from absolute placements and preserves duration, SFX gain, reaction
position/ducking and text position. `slow_motion` annotations accompanying
speed=.5 are applied once. Intro/outro cards and music on explicit renderer
plans survive the pipeline adapter. Planner music intent does not identify an
asset and is not silently converted to a filesystem path.

Reactions are applied by the pipeline after the segment render. Landscape uses
bottom-right, vertical top-left, and square top-right; all default layouts leave
caption space. Unknown presets raise ValueError at the overlay boundary. Native
planner placements override corner/timing and empty reaction slots stay empty.
Direct Renderer callers must supply a segment processor to apply reaction slots.

Review text maps to `title`; supplied transcript words remain separate. Explicit
`captions:false` at the job boundary disables review titles and transcript/text
placements. Missing local transcription remains a warning, never a download.
Legacy preparation retimes words/tracks/FX using measured output duration and
preserves titles. Legacy fade-out now uses actual speed-adjusted duration;
chromatic aberration retains audio effects and normalized output geometry.

# FX-2 stacked effects

Every timed registry effect is rendered in list order, so overlapping windows
compose rather than replace one another. Timed text gates use their placement
clock even after two seconds. Zoom punch, deterministic shake, chromatic shift,
freeze and deep fry use CPU FFmpeg filters; slow motion uses segment speed and
`atempo`, preserving output-local placement clocks. Freeze holds the event frame
without extending the segment. Time-changing `speed_ramp` remains a prepared
source operation in the separate `fx` library.

Both performance modes now use the same SFX graph: one input per assigned sound,
trim/reset timestamps, explicit gain, 40 ms fade-out and millisecond delay.
Game audio drops to 72% during the union of SFX windows. `amix` has N+1 inputs
for N sounds and disables automatic normalization. A non-auto-leveling 0.95
limiter protects the sum; latency compensation preserves sync. After concatenation
and optional music, a final 0.85 limiter leaves AAC encoding headroom while
copying video unchanged. Missing registered
files and unknown names fail visibly instead of silently dropping sounds. Asset
paths resolve relative to `full_app`, independent of the working directory.

Run `python ../demo_video/fx2/render_saved.py` from `full_app` on runner 1 to
rebuild the three saved DEMO-02 plans. It preserves reviewed cuts and privacy
masks, disables optional reactions to isolate VFX/SFX, makes no analysis/API
calls, and writes MP4s, sub-20-MB Discord versions, JSON plans, metadata and a
per-clip effects table under `/srv/demo_out/fx2/`. The Discord encoder also checks
decoded float samples and, if AAC overshoots full scale, lowers audio gain and
remuxes the existing video until the headroom check passes.
