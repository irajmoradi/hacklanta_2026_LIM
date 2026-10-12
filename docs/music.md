# Offline music beds (EXT-22)

`full_app/music/` provides original procedural music and a local, user-supplied
library. It makes no network/API calls, downloads no assets, and requires no
soundfonts or model weights. NumPy is already a core dependency. ffmpeg is needed
only to decode user audio and analyze saved tracks. librosa is optional; no new
mandatory dependency is introduced.

From `full_app/`:

```python
from music import pick_or_generate, analyze_track

bed = pick_or_generate("energetic", length=30, climax_at=12.3,
                       bpm=140, output_dir="workspace/music")
print(bed.path, bed.bpm, bed.beats, bed.sections)
print(analyze_track(bed.path, use_librosa=False))
```

The three positional arguments are style (`energetic` or `chill`), target length
in seconds, and climax time in seconds. Length is between one audio sample and
600 seconds; climax is in `[0, length)`. Inputs must be finite. Optional `bpm`
is 40–240 and defaults to 140 for energetic and 85 for chill. `seed=0` produces
repeatable audio; every invocation uses a unique output filename.

`MusicBed` contains a `Path`, native BPM, a list of beat times, and `Section`
objects with `name`, `start`, `end` in seconds. Sections cover the bed in order:
intro, drop, outro. The beat grid is shifted so the climax is exactly a beat and
the drop starts there, even for a fractional climax. Audio timing is quantized
to the nearest 22.05 kHz sample. The intro is quieter; the drop introduces full
instrumentation and volume; the final section fades out. Edge cases can have a
zero-length intro or a very short drop/outro. Tiny beds are valid but cannot
contain a musically complete phrase. Synthesis uses repeating four-bar harmony,
bass, arpeggios, synthesized kick, and noise percussion. Finished beds have fades
and are not intended to be seamlessly repeated in their entirety.

Outputs are mono 16-bit PCM WAV, peak limited to 0.9. The caller owns cleanup;
without `output_dir` files go to the system temp directory under `lim-music/`.
This is a standalone API: the Flask endpoints and renderer defaults are unchanged.
An integrator can supply `str(bed.path)` as the renderer's music input, mix/duck it
against gameplay, and use the timing metadata for cuts. No renderer wiring is
included because it is outside this task's allowed paths.

## User library manifest

Use a UTF-8 JSON file. Paths resolve relative to the manifest (absolute local paths
also work). Keep tracks and private license documents out of git.

```json
{
  "version": 1,
  "tracks": [
    {
      "path": "tracks/my-original-hype.wav",
      "energy": 0.9,
      "mood": ["hype", "intense"],
      "bpm": 140,
      "license": "My own original composition and recording",
      "attribution": "Music by the montage creator",
      "styles": ["energetic"],
      "modes": ["highlight", "competitive"],
      "drop_at": 8.5714285714
    }
  ]
}
```

`path`, `energy` (0–1), `mood` (list of tags), and nonempty `license` are required.
`bpm` can be omitted/null to estimate it. Optional `styles` and `modes` lists
restrict eligibility; empty lists match any request. Tags are case-insensitive.
`mode` is an arbitrary application tag, such as highlight/lowlight. Omitting it
does not filter on mode. Compatible tracks are ranked by distance from the style's
target energy (0.85 energetic, 0.30 chill), with a 0.25 penalty for no matching mood
(energetic/hype/intense or chill/calm/relaxed). Ties use the resolved path.

```python
bed = pick_or_generate("energetic", 30, 12.3,
                       manifest="/path/to/library.json", mode="highlight",
                       output_dir="workspace/music")
```

No compatible track (including an empty library) falls back to procedural music.
Malformed manifests, missing files, undecodable selected audio, or an unmeasurable
tempo without an explicit BPM raise errors rather than silently hiding bad data.
All manifest entries are validated, even those not selected.

Library beds retain native BPM; `bpm=` only controls procedural synthesis.
`drop_at` is a source beat/drop timestamp (default 0); it must lie within the
decoded whole-beat loop region. The source is trimmed to a whole number of beats,
cyclically offset so that `drop_at` lands at `climax_at`, and repeated/trimmed to
length. Brief seam fades reduce clicks; section dynamics and outer fades are then
applied. This assumes a steady-tempo, beat-aligned source starting on a beat.
For musical continuity, supply a clean whole-bar loop and accurate drop metadata.
The algorithm does not discover a recording's true musical drop or time-stretch it.
`source`, `license`, and `attribution` preserve provenance on the returned bed.

## Analysis and dependencies

`analyze_track(path, use_librosa=True)` decodes up to ten minutes to mono at
22.05 kHz and returns `TrackAnalysis(bpm, energy, duration, method)`. `duration`
describes the analyzed prefix. Energy is normalized amplitude RMS in [0, 1],
not perceived loudness or a semantic mood prediction. Silence, very short audio,
and signals without detectable rhythm return `bpm=None`.

If installed separately in your environment (`python -m pip install librosa`),
librosa is imported lazily for tempo detection. Missing or incompatible librosa
falls back to NumPy onset-envelope FFT autocorrelation. `use_librosa=False`
forces that fallback. Estimates are constrained to 40–240 BPM; half/double-tempo
ambiguity, syncopation and variable tempo remain limitations. Manually curated
manifest BPM takes precedence. Optional librosa is tested via mocks; it is not
required for the Linux test suite.

## Licensing and provenance

No third-party music, samples, melodies, or soundfonts are bundled. Procedural
audio uses code-generated oscillators/noise and a generic chord progression;
`license=None` indicates no separate third-party asset license. It is not a legal
clearance certificate or a claim of exclusive ownership over generated output.

Users supply and verify library permissions, including synchronization in video,
distribution, monetization, and any attribution requirements. “Royalty-free”
does not itself describe those permissions. Record the actual license identifier,
license URL, or owned-work description in `license`, and required credit text in
`attribution`; keep supporting documentation with the original assets. The package
checks that license metadata exists, not that the rights claim is true. Attribution
is returned to the caller; it is not automatically added to a video or credits.

## Verification

From the worktree root in Bash:

```sh
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_music.py"
tools/remote_run.sh "cd full_app && python -m pytest -q"
```

Tests synthesize all their audio, check actual waveform tempo and duration,
climax alignment, section dynamics, deterministic output, library selection and
provenance, input validation, ffmpeg decoding, and optional dependency fallbacks.
They use no Gemini calls or external media.
