# Optional AI caster narration

EXT-19 exposes a backend hook; existing uploads and renders remain unchanged. From
`full_app`, import `narration` and call:

```python
from narration import build, render

clips = [{"start": 10, "end": 22, "peak_time": 16,
          "caption": "A clutch win", "score": 9}]
plan = {"segments": [{"source_start": 10, "source_end": 22, "speed": 2}],
        "reaction_overlays": [{"start": 2, "end": 4}]}
track = build(clips, plan, "hype_caster", character_cap=1000)
# After the existing renderer has produced the matching six-second montage:
# result = render("montage.mp4", track, "narrated.mp4")
```

Personas: `hype_caster`, `deadpan_roast`, `nature_documentary` (spaces also accepted).
The return value is a `NarrationTrack` with `duration`, `characters`, `warnings`, and
`segments`; each segment has montage `start`, `end`, `text`, and `audio_file` (Path
or None). No keys means deterministic script-only output. Rendering such a track
returns the original video path and does not create an output file.

## Timing contract

Inputs accept dictionaries or existing Pydantic Clip/EditPlan models. Clips are
ranked in input order; the first intersecting clip supplies the caption and peak.
Clip `start`, `end`, and optional `peak_time` are absolute **source seconds**;
missing peaks use the edit segment midpoint. `description` substitutes for caption.
Segments follow edit-plan order. Their `speed` and legacy `slow_motion`/`speed_2x`
effects determine final durations. Reaction overlay `start`/`end` are **final
montage seconds**, supplied explicitly by the integration caller, including any
reaction audio tails. The scheduler reserves an additional 100 ms on either side.
It cannot infer overlays from media or reaction labels. This source peak contract
differs from `reactions.apply_reaction`, which takes a segment-local peak.

One short line per edit segment is placed in the safe gap nearest its peak. Words
are budgeted at two per second, capped at 18. Actual synthesized WAV duration is
measured before placement; speech too long for its gap is omitted, never clipped
into a reaction. The renderer validates montage duration. Intros, outros, overlaps,
crossfades or other timeline changes must be accounted for by the caller before
building the narration plan. This hook assumes simple sequential concatenation.

## Providers, consent and cost

Network is off by default, even if keys exist. Set `allow_network=True` explicitly
to enable one Gemini script request per build and one ElevenLabs request per
uncached line. No retries are performed. Gemini uses `GEMINI_API_KEY`, or
`GOOGLE_API_KEY` with `GOOGLE_GENAI_USE_VERTEXAI=true` for Vertex express;
`GEMINI_MODEL` overrides the existing repo default. Missing SDK/key, malformed
scripts or provider failures fall back to templates. ElevenLabs reads
`ELEVENLABS_API_KEY` at request time; missing credentials or request failures keep
script-only segments. Errors are summarized without provider bodies or secrets.

The default is ElevenLabs stock George (`JBFqnCBsd6RMkjVDRZzb`). A custom/cloned
voice is used **only** through `NARRATION_CONSENTED_VOICE_ID`: setting this variable
is the operator's explicit attestation that the voice owner consented. Generic
voice-ID environment variables are ignored. No cloning endpoint is called.
All personas use the stock voice by default; their distinction is script style.

`character_cap` (default 1000) limits all selected text per job, including cache
hits, failed synthesis attempts and speech later omitted for duration. Exhausted
budgets skip lines; shortened lines end at word boundaries. Repeated builds are
separate jobs. Cache keys include voice, exact text, fixed model and PCM format.
Validated WAVs are published atomically in the system temp directory under
`lim-narration-cache`, or explicit `cache_dir`. Offline builds can reuse cache.
Concurrent jobs may both pay for the same cold miss; there is no cross-process
request lock. Cache eviction is the caller's responsibility; it contains speech.

The TTS implementation uses the official [ElevenLabs speech endpoint](https://elevenlabs.io/docs/api-reference/text-to-speech/convert)
with `eleven_multilingual_v2` and `pcm_24000`, wrapped locally as WAV without heavy
dependencies. FFmpeg/ffprobe are required for rendering. `render` mixes speech,
reduces game audio to 25% during spoken intervals, and limits the mix. It handles
silent video inputs and refuses to overwrite existing outputs. It operates on
the final montage audio, so music/SFX in that mix are also ducked.

## Verification

From the worktree root:

```bash
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_narration.py"
```

Tests mock both paid providers and use FFmpeg-generated synthetic video/audio;
they verify timing, caching, consent gating, budgets, fallback and audible ducking.
No live calls are needed. Any future paid smoke test must be explicitly marked
`pytest.mark.live`, opt-in, and restricted to at most two ElevenLabs and three
Gemini calls per task run. No live test was run for EXT-19.

Integration remains opt-in: an integrator can call this hook after montage
rendering and supply the actual reaction intervals. The task's allowed paths do
not include app routes, UI controls or the existing renderer.
