# EXT-18 montage FX library

FX-2: `fx.catalog.catalog()` inventories every non-`none` entry of
`models.effects.VIDEO_EFFECTS` and `SOUND_EFFECTS` with event, mood, intensity,
recommended slice length and timing tags. The lengths are editorial slices,
not claims about asset file duration. The planner varies selections and stack
depth using chaos/seed; the renderer supports the complete timed VFX inventory.
New legacy-compatible IDs are `zoom_punch`, `freeze`, `deep_fry`, and `hitmarker`.
Freeze's dynamic hold is implemented in the v2 timed path; its legacy whole-clip
filter is neutral because a freeze requires a timestamp. No new media assets or
heavy dependencies are added. See `docs/planner.md` for option semantics and the
HTTP integration boundary, and `docs/rendering.md` for the unified mixer.

`full_app/fx` provides pure FFmpeg filter builders, a planner catalog, a composition
helper, and video-only previews. No API key, network, ML package, or model download
is needed. Importing `fx` does not probe hardware or launch FFmpeg.

## Renderer and planner API

Run Python from `full_app` (or add it to `PYTHONPATH`):

```python
import json
from fx import REGISTRY, Timing, Request, compose, metadata

print(json.dumps(metadata(), indent=2))  # safe to include in a planner prompt
hit = Timing(duration=2, start=0.5, end=1.0, fps=30)
snippet = REGISTRY["impact_frame"].filter(hit, brightness=0.6)
chain = compose([
    Request("impact_frame", hit, {"brightness": 0.6}),
    Request("zoom_punch", hit, {"zoom": 1.2}),
    Request("kill_counter", hit, {"count": 3}),
])
# Pass chain as ONE argv value following -vf; never invoke a shell.
REGISTRY["impact_frame"].preview("source.mp4", "/tmp/impact.mp4", hit)
```

All registered effects expose `.filter(timing, **params)`,
`.output_duration(timing, **params)`, `.preview(source, output, timing, **params)`,
parameter defaults/ranges, a description, and a qualitative CPU cost estimate.
Unknown parameters, nonfinite numbers, invalid timing and unsafe display text fail
before rendering. Use the registry's validated `.filter` API for planner output.
The module-level functions are the underlying pure builders.

Snippets are single-input, single-output, unlabeled video filter chains. Comma-join
them or use `compose`; they need no auxiliary source, graph label, asset or global
counter. Normalize timestamps to zero first (as `compose` does). Effects preserve
dimensions; convert the final chain to `format=yuv420p` for H.264 delivery.
Even input dimensions and constant-rate video are recommended.

`Timing` uses seconds on the current clip, with an inclusive start and exclusive
end. It requires `0 <= start < end <= duration`, and FPS from 1 to 240. Every effect
preserves duration except `speed_ramp`. When composing after a speed ramp, supply
the new output duration and express subsequent effect windows on that new timeline.
`compose` rejects mismatched consecutive durations. Do not supply absolute source
timestamps after trimming a source segment.

Consumers can append `compose(requests)` to a renderer's video chain and expose
`metadata()` to the planner. Speed ramps require retiming audio, captions, SFX,
and subsequent edit points; this package renders silent previews.

Raw FFprobe metadata is shared through `fx.media.probe`. The existing
`services.probe.probe_video` requires video codec and frame-rate fields and returns
a summary, which cannot represent audio-only inputs or still-image previews.
Callers retain their existing timeouts and error contracts. Encoding stays in
each renderer because their stream maps, output ownership, and deadlines differ.

## Effects

Costs compare CPU work qualitatively at the same resolution; they are not measured
latency guarantees. Defaults and validation bounds are authoritative in `metadata()`.

| Registry key | Parameters and defaults | Cost | Behavior |
| --- | --- | --- | --- |
| `impact_frame` | `brightness=0.65` (0–1) | low | Hold hit frame; brighten first two frames |
| `speed_ramp` | `fast=2` (1–8), `slow=0.5` (0.125–1), `interpolation="none"` | low / high with optical flow | Fast → slow during kill window → fast |
| `zoom_punch` | `zoom=1.18` (1–2) | medium | Centered perspective crop, original dimensions |
| `screen_shake` | `pixels=8` (0–64), `frequency=25` (1–100 rad/s) | low | Oscillating horizontal and vertical displacement |
| `chromatic_aberration` | `pixels=3` (0–32) | low | Opposing Cb/Cr offsets |
| `rgb_split` | `pixels=6` (0–32) | medium | Opposing red/blue offsets |
| `vhs_crt` | `noise=12` (0–100) | medium | Temporal noise, desaturation, scan lines |
| `motion_blur_trail` | `frames=4` (2–16) | medium | Blend recent frames |
| `letterbox` | `fraction=0.12` (0–0.4) | low | Black bars, each a fraction of image height |
| `color_grade` | `preset="teal-orange"` | low | Also `high-contrast` and `neon` |
| `kill_counter` | `count=1` (0–9999) | low | Timed `KILLS N`; use nonoverlapping requests for increasing counts |
| `freeze_name_tag` | `name="PLAYER"` | low | Hold hit frame and show centered name |

Freeze effects replace motion during the selected interval, rather than extending
the clip or shifting later gameplay. Their CFR conversion rounds up and duplicates
the preceding retained frame. Timing is quantized to frames; choose aligned hit
times for exact holds. A hold through the final frame is padded and trimmed back
to the original duration. Shake exposes a black padded border at peak displacement.
Names accept 1–48 Unicode word characters, spaces, or `. ! ? # @ + ( ) / -`;
quotes, colons, backslashes and expression expansion characters are rejected.

The speed ramp uses three **stepped** speed regions, not continuous acceleration.
For duration `D`, start `a`, end `b`, output duration is:

```text
a / fast + (b - a) / slow + (D - b) / fast
```

For the example two-second clip, `[0.5, 1.0)` at 0.5x and the rest at 2x
produces 1.75 seconds, rounded to the output frame grid. `interpolation="minterpolate"`
enables FFmpeg motion-compensated interpolation after retiming. Otherwise frames
are duplicated/dropped. Tail padding compensates for interpolation latency and
trimming bounds the output. Optical flow is expensive and may warp HUD text or
produce artifacts at cuts. Reference: [official FFmpeg filter documentation](https://ffmpeg.org/ffmpeg-filters.html).

### Optional RIFE hook

No RIFE implementation or dependency is bundled. A caller can pass a trusted
`rife_hook(source_preview: Path, candidate: Path, fps: float)` keyword to `.preview`.
The hook should write an interpolated video to `candidate`, preserving dimensions
and duration; the preview renderer checks these before replacing its output.
The callback executes after the FFmpeg preview, so for production optical-flow
pipelines that need original frame timestamps, integrate your model before CFR
conversion instead. The callback must manage its own resources and timeout.
If the optional hook raises (including `ImportError`) or produces an invalid video,
the renderer emits a warning and retains the working FFmpeg preview. Without a
hook the FFmpeg path is used directly. No automatic model download occurs.

## Previews and contact sheet generator

FFmpeg/ffprobe must be on PATH, with libx264 and the listed filters. Text effects
and the gallery labels need `drawtext` and an available default font. Use a normal
FFmpeg build with FreeType/fontconfig. Missing core filters raise an actionable
FFmpeg error instead of silently dropping an effect. Previews invoke subprocesses
with argument lists and a 180-second timeout per invocation.

The executable generator lives in `full_app/fx/contact_sheet.py`:

```bash
cd full_app
python -m fx.contact_sheet --output /tmp/fx-gallery
# Optional own media (at least two seconds):
python -m fx.contact_sheet --source /path/to/clip.mp4 --output /tmp/fx-gallery
```

It creates a two-second synthetic test source when no input is supplied, renders
one MP4 for every registry entry, extracts 320×180 stills with separate label bands,
and tiles a 1280×630 `contact-sheet.png`. Inspect the MP4s to assess temporal effects; a still
cannot demonstrate speed, shake, or motion trails. Outputs stay in the requested
directory and are not meant to be committed. Re-running replaces gallery outputs.

## Offline verification

From the worktree root:

```bash
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_fx.py"
```

Tests generate synthetic `testsrc2` video, render and decode every effect, verify
geometry and duration (including multiple speed settings and minterpolate), check
freeze hold/resume behavior, exercise composition and both other grade presets,
reject invalid parameters, verify pure builders and JSON metadata, test optional
RIFE success/fallback, and render the complete contact sheet. No paid calls occur.
