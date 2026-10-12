# Local talking-head reactions

The opt-in `full_app/reactions` module needs only Python, FFmpeg and ffprobe (FFmpeg
with libx264, AAC and drawtext/font support for optional names). No API calls or ML
dependencies are used. Existing montage behavior is unchanged until the backend
calls the hook. Backend routes are outside EXT-06's allowed paths.

## Pack format

Put packs in `full_app/reaction_packs/<name>/` (already gitignored). Never commit
real faces, voices or generated media. `pack.json` is UTF-8:

```json
{"version": 1, "clips": [
  {"id": "alex-kill-01", "speaker": "Alex", "label": "sick_kill",
   "text": "Sick kill!", "file": "alex-kill-01.mp4", "duration": 1.2,
   "background": "light"}
]}
```

IDs must be unique; files must resolve within the pack (including symlinks).
Duration is positive seconds. Labels: `sick_kill`, `clutch`, `bruh`, `fail`,
`funny`, `wholesome`, `hype`, `roast`. Background is `light` (white/light key),
`transparent` (preserve source alpha), or `opaque` (circle crop only). Square,
centered portraits work best; other aspect ratios are center-cropped. The light
key also removes near-white foreground details; use alpha video for those avatars.

From Village, export each authorized avatar/voice reaction as a short, synchronized
video with audible voice, preferably a clean light background or alpha. Trim idle
lead/trail time, normalize voice levels, give every variation a unique ID and label,
and measure duration with `ffprobe -v error -show_entries format=duration clip.mp4`.
Copy exports into the ignored pack folder and create its manifest. Export multiple
speakers and takes per label for rotation. The integrator builds the real pack locally.

## Try the synthetic pack

From `full_app`:

```sh
python -m reactions.demo
python -m pytest -q tests/test_reactions.py
```

The generator creates four tiny colored-circle avatars with moving mouths and beep
audio. Only generator code is shipped; tests generate everything in temporary folders.

## Backend integration

```python
from reactions import load_pack, ReactionSelector, apply_reaction

selector = ReactionSelector(load_pack('reaction_packs/synthetic'), seed=42)
# One selector per montage, reused sequentially for each rendered segment:
path = apply_reaction(segment_path,
    {'label': 'sick_kill', 'score': 0.9, 'peak_time': 1.4,
     'suggested_reaction_label': 'sick_kill'},
    selector, preset='landscape', enabled=True, mode='nice', show_speaker=True)
# Pass path to the existing segment concatenation step.
```

Call after segment timing/speed/effects are final and before concatenation. The
peak is local seconds in that final segment: convert source timestamps by subtracting
the trim start and dividing by playback speed. Without a peak, use the midpoint.
The reaction starts at the peak, shifted earlier when needed to fit before the end;
long reactions are trimmed to the base duration. Scores are expected on [0, 1].
Nice mode excludes roast; mean mode allows all labels and defaults to roast.
Valid VLM suggestions outrank clip labels, then fallback uses score/mode. Never
repeat an ID consecutively; when no alternative exists, skip the overlay. Rotate
speakers within the preferred label when possible, then favor less-used takes.
The same speaker may recur if only that speaker covers the preferred label.

`render_overlay(base_clip, reaction, preset) -> Path` also works directly; keyword
options are `peak_time`, `show_speaker`, `duck_gain` (default 0.25) and `output_path`.
Unique output filenames prevent collisions. Existing outputs are never overwritten.
Errors propagate so the backend can report them; disabled/empty hooks return the base.

Landscape uses bottom-right; vertical uses top-left to leave lower caption space.
The renderer preserves base dimensions, uses a circle of 30% of the smaller dimension,
4% margin, soft offset shadow and short fade/slide pop transitions. It does not convert
landscape to portrait: supply a segment already rendered at the desired aspect ratio.
Game audio is ducked during the voice clip; voice is mixed at original gain with a
limiter. Silent bases get an audio track; silent reactions do not duck game audio.
Speaker text is read literally from a temporary file, never interpolated as a filter.

Tests probe output duration/dimensions/audio streams, inspect decoded frames before,
during and after the reaction and at mask corners, and measure game/voice frequency
amplitudes to check ducking and recovery. Local packs are trusted media; untrusted
uploads still need the backend's normal resource limits. Rendering re-encodes video
and audio and requires enough disk space for a new segment.
