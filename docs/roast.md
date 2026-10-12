# Roast mode v2 (EXT-29)

`full_app/roast` is an opt-in planner and FFmpeg adapter for gameplay failures.
It does not change the Flask pipeline or UI defaults. Those files are outside
this task's allowed paths; the integrator can invoke this API from Mean mode.
No model, network request, subprocess, or credential lookup occurs on import.

## Try it

From `full_app`, with an existing extracted clip:

```python
import subprocess
from roast import FailMoment, plan_roasts, video_filter

plan = plan_roasts(
    [FailMoment(0.5, "whiff"), FailMoment(3.0, "death")],
    duration=5.0, fps=30, intensity=2,
)
subprocess.run([
    "ffmpeg", "-y", "-i", "clip.mp4", "-filter_threads", "1",
    "-vf", video_filter(plan), "-c:v", "libx264", "-c:a", "copy",
    "roasted.mp4",
], check=True)
print(plan.to_dict())
```

Use the actual clip duration and frame rate. Fail times are seconds on the
**extracted, speed-adjusted clip**, not the original upload. Allowed kinds are
`whiff`, `death`, `fall`, `reload`, and generic `fail`. Invalid/nonfinite times
raise `ValueError`. Events are sorted, quantized down to the frame boundary,
and deduplicated by frame (first event wins, kind breaks equal-time ties).
Each caption ends at the next fail, 2.4 seconds later, or clip end, whichever
comes first. Intervals are start-inclusive and end-exclusive.

Intensity is integer `0` (off), `1` (gentle, default), `2` (spicy), or `3`
(extra playful). Higher settings change the curated line, hold duration
(0.3/0.5/0.7 seconds), zoom (1.08/1.18/1.28), and enable SFX at 2–3. Off
and empty event lists never call a writer. Freezes replace motion in-place;
they do not insert time, shift later events, or alter source audio duration.
At very low FPS or very short intervals, the hold may be only one frame.

## Overlay and FX contract

`plan.to_dict()` is JSON serializable and contains:

- `duration`, `fps`, `intensity`: clip-local rendering context.
- `overlays`: `template`, `start`, `end`, `caption`, `source` (`gemini` or
  `fallback`), and fail `kind`.
- `beats`: `start`, `end`, and `zoom` for a freeze plus centered zoom punch.
- `sound_effects`: `sfx_key` and `offset_in_segment`, directly compatible with
  `FFmpegRunner.overlay_sfx(path, plan.to_dict()["sound_effects"], index)`.

The video adapter emits a standard unlabeled `-vf` chain. It uses EXT-18's
`zoom_punch` registry effect and duration-preserving frame selection. Apply it
after trims/speed changes and before concatenation. Source frames should start
at PTS zero; the adapter resets PTS. It preserves dimensions. FFmpeg needs
`drawtext`, `drawbox`, `perspective`, and font support.

Templates cycle deterministically, or set `template=` to one of:

- `top_bottom`: setup at the top and roast punchline at the bottom.
- `two_panel`: Drake-style reject/approve layout using red/green graphic panels
  and NO/YES labels, without likenesses or downloaded artwork.
- `wasted`: translucent center banner with red WASTED title.
- `stat_card`: explicitly labeled fake stats (Aim: 3%, Confidence: 100%).

Text scales to frame width and length. Fake stats are jokes, not measurements.
The SFX resolver prefers a registered `record_scratch` asset if it exists.
**This checkout has no record-scratch asset or registry entry**, so it uses the
existing `spongebob_fail` sound instead. Missing assets yield no sound spec.
No new audio files are downloaded or generated. Run the existing SFX mixer
from `full_app`, as its asset paths are relative to that working directory.
The video filter itself does not mix sound. The existing mixer expects a source
audio stream; for silent clips, add a silent audio track before mixing or omit SFX.

## Gemini and safety

Deterministic templates are the default. To opt into Gemini, inject an already
configured client and explicit model:

```python
from roast import GeminiLines
writer = GeminiLines(client, model="your-configured-model")
plan = plan_roasts(events, duration=duration, intensity=2, line_writer=writer)
```

Configure client timeouts and disable SDK retries when enforcing a strict call
budget. One plan invokes the writer at most once for all events; there are no
planner retries. Client creation and env-only credentials remain the caller's
responsibility (including Vertex express settings). Use only explicitly marked
live smoke tests for paid requests, at most three calls per task run.

Only fixed event kinds and intensity go into the request: no player names,
transcripts, chat, or freeform descriptions. Returned JSON must be a list with
exactly one item per event. Every line passes `safe_line`, including when a
caller constructs overlay specs directly for rendering. The filter requires
a gameplay noun subject, a narrow ASCII vocabulary, and at most 80 characters.
Unknown words, identity terms, personal insults, controls, Unicode obfuscation,
and FFmpeg syntax are rejected. Increasing intensity never weakens safety.
Malformed JSON, refusal, wrong counts, provider errors, and rejected lines
fall back to curated gameplay-only captions without exposing response text.

This is deliberately a constrained English caption language, not a general
moderation classifier. It rejects many harmless creative lines and all other
languages. The vocabulary should receive safety review before expansion.
The model can vary phrasing within this vocabulary; arbitrary freeform roasts
are not accepted. No heavy or additional dependencies are required.

## Verification

From the worktree root:

```sh
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_roast.py"
```

Tests mock Gemini and prohibit networking. FFmpeg generates `testsrc2` and
`sine` fixtures in pytest temporary directories. Tests cover all templates,
safety and injection rejection, provider fallback, event bounds/deduplication,
SFX selection, audio/geometry/duration preservation, held frames, resumed motion,
and multiple beats including a fail on the last frame. No media is committed.

Task-run results (Linux runner, 2026-10-12):

- `tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_roast.py"`
  initially exited 1: 57 passed, one curated-caption vocabulary mismatch. Added
  the missing word `every` and reran with regression coverage.
- `tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_roast.py tests/test_fx.py tests/test_pipeline.py tests/test_render_v2.py"`
  exited 0: **150 passed in 140.48 seconds**, including 60 roast tests.
- No live Gemini calls; no credentials read.
