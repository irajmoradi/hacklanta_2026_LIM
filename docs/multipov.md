# Multi-POV team montages (EXT-21)

`full_app/multipov` is an opt-in, offline Python API for recordings of the same
match. It uses the existing NumPy dependency and FFmpeg/ffprobe (with libx264,
AAC and drawtext support). It needs no Gemini calls, credentials, ML models or
new packages. The existing upload/analyze/plan/render defaults are unchanged.
Call this API after gathering each recording's scored candidates.

## Try it

Run Python from `full_app`:

```python
from multipov import Video, sync, team_candidates, render_montage

videos = [Video("alice.mp4", "Alice"), Video("bob.mp4", "Bob")]
offsets = sync(videos)
for video, clock in zip(videos, offsets):
    print(video.player, clock.offset, clock.rate, clock.confidence)

# Replace with local timestamps and fused scores from your signal detector.
# Dictionaries, signals.Candidate and models.schemas.ScoringCandidate work.
per_video = [
    [{"start": 12, "end": 18, "score": .8}],
    [{"start": 10, "end": 16, "score": .9}],
]
highlights = team_candidates(videos, per_video, offsets=offsets)
render_montage(videos, highlights, "team.mp4", offsets=offsets, mode="split")
```

The example timestamps must fall within each actual recording and overlap in
match time to become alternate angles. `team_candidates(videos, per_video)`
also works: it computes synchronization automatically. Retain the explicit
`offsets` when planning to render, to avoid running synchronization twice.

## Clock contract

`sync(videos) -> list[Alignment]` returns one record per input, in input order.
Inputs may be `Video(path, player)` objects or filesystem paths. Paths must be
unique. Names default to the file stem.

The first recording defines the shared match clock:

```
match_seconds = alignment.offset + alignment.rate * local_seconds
local_seconds = (match_seconds - alignment.offset) / alignment.rate
```

The first alignment is `(offset=0, rate=1, confidence=1)`. An offset of +2 means
that POV starts two seconds after the reference. Negative match times are valid
and preserved. A rate of 1.001 means one local second spans 1.001 match seconds.
Use `to_match()` and `to_local()` rather than adding offsets alone. `confidence`
is mean accepted normalized correlation, not a probability or a promise of
frame accuracy. Manual `Alignment` values support recordings without audio.

Synchronization decodes mono 8 kHz audio, measures four spectral energy bands
at 5 ms hops, and cross-correlates 19 distributed two-second windows against the
reference. Per-band normalization reduces the effect of independent voice chat,
gain differences and waveform polarity. A deterministic affine fit rejects
outlier matches and corrects linear drift up to 2%. It requires at least three
unambiguous windows, a three-second fit span and four seconds of input audio.
Periodicity, silence, missing audio, inconsistent clocks and insufficient overlap
raise `SyncError`; they do not silently produce zero offsets. Invalid media and
FFmpeg failures raise exceptions with bounded diagnostics. Subprocesses have
timeouts. There are no network calls.

## Shared highlights and rendering

`team_candidates` accepts one candidate iterable per recording. Each candidate
has finite `start`, `end`, and optional `score` (default zero). Times must be inside
the recording. The score is the upstream fused signals score; callers should use
the same scoring scale for all POVs. Candidate objects are never modified.

Highlights from different recordings group when every pair shares at least 50%
of its shorter interval (`overlap` is configurable). Explicit `event_id` values
must agree when both candidates provide one. Complete pairwise comparison avoids
merging a long chain of separate events. Candidates from the same recording do
not merge. Without event IDs, temporal overlap is a heuristic for the same event.

The result is chronological `TeamCandidate` records with `start`, `end`, and
`angles`. Each `Angle` retains its match interval, player, source `video_index`
and score. Angles sort by descending score, with input order breaking ties;
`candidate.best` gives the first. Group intervals use the intersection of their
angles so every panel has media available throughout the replay. This can shorten
the original highlight's lead-in or tail. Separate groups can still overlap.

`render_montage(..., offsets=..., mode=...)` writes an H.264/AAC MP4:

- `best`: the highest-scoring POV fills the canvas.
- `split`: the two highest-scoring POVs play side by side.
- `pip`: the second POV appears in an inset over the highest-scoring POV.

Single-angle highlights fill the canvas in every mode. Two-angle layouts show
the event simultaneously; the replay panel reads `From <player>'s POV...`.
Video timestamps and audio tempo both follow the fitted clock. Only the primary
angle's audio is used, avoiding duplicated sound; absent audio becomes silence.
Every panel has a player tag and every segment includes a full team credit, even
for players whose angles were not selected. Names are literal UTF-8 text files
with FFmpeg text expansion disabled; punctuation cannot inject filters.

The default canvas is 1280x720 at 30 fps. Width/height must be divisible by four
and at least 320x180. Sources are letterboxed, never stretched. Temporary media
is cleaned up; the destination is replaced only after successful rendering.
The output cannot be any input path. The function returns the resolved output
`Path`. Each segment is rendered with identical settings and concatenated;
AAC/container padding may add a small fraction of a second to total duration.

## Tests and limits

From the worktree root:

```bash
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_multipov.py"
tools/remote_run.sh "cd full_app && python -m pytest -q -m 'not live'"
```

Tests synthesize shared audio and videos with FFmpeg, add different voice-like
noise, introduce offsets of +2.375, -2.35 and +1.125 seconds and rates of 1.0015,
0.9985 and 1.0. They require alignment error below one 30 fps frame at the start,
middle and end. Rendering tests decode the complete MP4 and inspect panel colors,
visible text, duration, dimensions and audio. No copyrighted media is downloaded.
Additional fixtures reject unrelated recordings and verify that a visual flash
appears simultaneously in drift-corrected split-screen panels.

The one-frame assertion is for the tested synthetic fixtures, not all gameplay.
Strong voice/music interference, unrelated in-game sound mixes, very short overlap,
repeated sounds, nonlinear drift or edits in a recording can fail synchronization.
Every POV must overlap the first; chaining through another POV is not implemented.
Full audio is decoded in memory and each sampled window searches the reference;
long recordings consume memory and CPU. This is intended for trusted local media,
not an unbounded public upload endpoint. No GPU is required. Long player names
or large team rosters can exceed the canvas width, and non-Latin glyph availability
depends on the installed FFmpeg font configuration. More than two POVs are ranked
and credited, but only two panels are displayed per highlight.
