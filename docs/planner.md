# Edit planner v2

`full_app/planner` produces a deterministic, validated Pydantic `RenderPlan`.
It needs no network, media files, model weights, or new dependencies. The optional
Gemini pass rewrites caption wording only. The pipeline still uses its separate
Gemini planning path; this package is an opt-in library.

## Try it

Run Python from `full_app` (the same import root as the existing backend):

```python
from planner import plan_edit

plan = plan_edit([
    {"id": "duel", "start": 0, "end": 12, "score": 70,
     "label": "highlight", "caption": "Clean opener",
     "signals": {"kill_time": 8}},
    {"id": "clutch", "start": 20, "end": 34, "score": 98,
     "label": "highlight", "caption": "Last player standing",
     "reaction_label": "clutch", "game_profile": "fps",
     "signals": {"action_time": 29, "kill_time": 29, "clutch": True}},
], mode="nice", style="hype montage", target_length=14, aspect="9:16")
print(plan.model_dump_json(indent=2))
```

`plan_edit(clips, *, mode="nice", style="hype montage", target_length=30,
aspect="16:9", min_clip_length=1, max_clip_length=6, refiner=None)` accepts
an iterable of `RankedClip` objects or dictionaries. Styles are `hype montage`,
`clean edit`, `meme edit`, and `cinematic`; aspects are `16:9`, `9:16`, and `1:1`.
Input must have unique IDs, finite numbers, and positive source durations.
Invalid input raises `ValueError`/Pydantic `ValidationError` before any provider call.

## Input and selection semantics

- Required fields: `id`, `start`, `end`, `score`, `label` (`highlight` or `lowlight`).
  Scores need not be normalized: larger means a stronger highlight or a worse fail.
  Ties break by ID, independently of input order.
- Optional fields: `caption` (up to 240 characters), `reaction_label`,
  `game_profile` (an opaque profile ID, default `generic`), and `signals`.
  The profile is passed through for renderer reframing policy; it is not a game detector.
- Signals: `action_time`, `kill_time`, `fail_time` are **absolute source seconds**
  in `[start, end)`. `clutch` and `multikill` are booleans. `kind` is an optional
  similarity category. Adapt richer scoring/profile objects to this typed boundary;
  unknown fields are rejected rather than silently changing planning behavior.
- Primary peak: explicit `action_time`, then label-appropriate kill/fail timestamp,
  then source midpoint. A kill effect uses `kill_time` independently, if it survives
  the trim. Without grounded event timing, the midpoint is only a heuristic.
- Nice mode selects highlights. Mean mode selects lowlights, optionally preceded
  by a highlight setup. If the requested label is absent, use available clips and
  include a note; do not invent failures. Mean mode does not roast highlight clips.

The first clip is a teaser (normally two seconds, always at most three) of the
highest-scored eligible clip of the requested label. Reserve the climax's full
available output duration before filling the middle. Select high scores first,
then order middle clips by increasing score. Mean mode puts the setup before fails.
The best source is deliberately repeated as the final clip; other sources appear
only once. A text outro and fade occupy its existing aftermath, so there is no
extra source clip or hidden duration after the climax.

Similarity uses normalized `signals.kind`, otherwise clutch/multikill/kill/fail/play.
Never put three equal categories consecutively, including the hook and climax.
Rejected candidates are reconsidered when another category makes room; variety
takes priority over filling the budget. All-identical inputs may yield only two
clips. The greedy selection is deterministic, not a global optimization solver.

Durations are output seconds: `(source_end - source_start) / speed`. Clutches run
at 0.5x in hype/cinematic styles, including that extra playback time in the budget;
the usual teaser stays at 1x. Trims retain approximately 65% lead-in around the
peak, clamped inside source bounds. The default output limits are 1ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“6 seconds per
clip. Minimum length must fit the maximum, budget, and three-second hook limit.
Short budgets combine hook and climax into one clip; insufficient footage or
variety yields a shorter plan with notes. No qualifying footage yields a valid
empty plan. Callers should skip rendering that plan.

## RenderPlan contract

`planner.models.RenderPlan` differs from `render.plan.RenderPlan`; callers need
an adapter between them. Export its JSON Schema with
`RenderPlan.model_json_schema()` and JSON with `model_dump_json()`.

Every placement uses **absolute output-timeline** `start` and `duration` plus the
owning timeline `clip_id`. Source timestamps appear only on `clips`. There are no
overlapping clips, xfade overlaps, or unbudgeted cards. A renderer translating
placements into per-clip time must subtract `clip.start`.

| Field | Meaning |
| --- | --- |
| `clips[]` | Timeline ID, source ID/trims, output start/duration, speed, story phase, score, label, similarity key, game profile and absolute output peak |
| `effects[]` | Timed `name` from `models.effects.VIDEO_EFFECTS` |
| `sfx[]` | Timed `name` from `SOUND_EFFECTS`, plus normalized gain |
| `text[]` | Literal content, caption/meme/outro role, center/lower-safe position |
| `transitions[]` | Cut/fade-in/flash-white on entry, fade-out on the final tail |
| `reactions[]` | Label, peak-aligned slot, corner position and game-audio ducking intent |
| `music` | Mood, normalized energy keyframes and duck-under categories; no asset path |

Metadata includes `version=2`, mode/style/aspect, target and actual duration,
clip limits, and diagnostic notes. Validation checks continuous timing, speed
arithmetic, placement containment, registry names, hook/climax framing, variety,
and music bounds. Input/source provenance and score selection are planner rules,
not independently verifiable from a serialized RenderPlan alone.

Effect choices:

- Hype/meme: `flash_white` plus `impact_hit` at a known kill; `zoom_in_center`
  around multikill peaks. Mean-mode failures get `text_bruh`, `spongebob_fail`,
  and a short gameplay roast. All SFX durations are bounded to the owning clip.
- Hype/cinematic clutches: `slow_motion`. **Apply speed exactly once**:
  `clip.speed` controls timing; the `slow_motion` effect expresses the same intent,
  not an additional speed multiplier. Do not blindly apply both existing filters.
- Cinematic: `vignette` and fade-in. Clean: no video effects or SFX; source captions,
  reaction intent and a minimal outro remain. Meme text is specific to mean mode.
- Reaction slots occur at clutch/multikill/climax peaks, excluding separate
  teasers. Preferred labels are respected except roast/bruh/fail become wholesome
  in nice mode. Corners are top-right for vertical and bottom-right otherwise.
  The reaction selector resolves actual assets, speaker rotation, and repeats;
  it may truncate/omit a reaction when the remaining slot is too short.
- Music starts energetic for the teaser, drops for build-up, rises to the climax,
  and releases at the outro. The renderer selects licensed music and ducks under
  speech, SFX and reaction audio. Style sets mood, not a music asset.

The renderer must implement timed effect windows and escape literal caption text.
The existing registry's static FFmpeg filter strings are not a complete timed
renderer; callers must translate these declarative placements.
No legacy `EditPlan` conversion is supplied because it would discard text,
reaction, music and placement timing information.

## Optional Gemini refinement

Default planning makes **zero API calls**. A supplied refiner is called once, with
no retries, using `prompts/editor_v2.txt` plus the plan as data. The accepted response
is `{"captions": [{"text_index": 0, "content": "Clean finish!"}]}`. Only wording
changes; timing, effects, story, and budget cannot be changed. Invalid indices,
duplicate patches, excess fields, overlong captions, invalid JSON, and provider
failures retain the whole deterministic plan with a generic diagnostic note.
Provider exceptions are not echoed because they may contain credentials.

For an **explicitly marked live smoke test only** (at most three paid calls per
task run), the caller can construct the client at runtime:

```python
import os
from google import genai
from planner import GeminiRefiner, plan_edit

client = genai.Client(vertexai=True, api_key=os.environ["GOOGLE_API_KEY"])
refiner = GeminiRefiner(client, model=os.environ["GEMINI_MODEL"])
# One live call, using the same clips from the first example:
# plan = plan_edit(clips, refiner=refiner)
```

Keys stay in runtime environment variables. The planner does not read `.env` or
choose a provider/model implicitly. Unit tests inject a mocked client. Refinement is opt-in creative text generation,
not a content moderation guarantee.

## Verification

From the worktree root, use the Linux runner:

```bash
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_planner.py"
tools/remote_run.sh "cd full_app && python -m pytest -q"
```

Tests cover nice/mean arcs, budget and speed accounting, source/action bounds,
variety including fallback cases, four styles, reaction timing, registry names,
strict input and timeline validation, mocked Gemini success/failure and 200 seeded
randomized inputs. These are planner-only tests: no synthetic video is needed,
and they do not exercise a planner-to-renderer adapter.


## DEMO-02 fill policy

The stock pipeline now enables `fill_target=True` and a ten-second per-clip
ceiling. The library default remains the strict variety policy for compatibility.
Fill mode first tries varied candidates, then relaxes category repetition using
the remaining ranked evidence. It never fabricates source footage or repeats
extra IDs beyond the existing hook/climax pair. Insufficient eligible source
material still produces an explicit under-budget note. Source event times anchor
pre-roll (approximately 65%) and aftermath inside each candidate's bounds.

Pipeline defaults, when `max_duration` is absent, are 60 seconds landscape and
30 seconds vertical; explicit duration limits are respected. Unscored local
candidates remain available as fallbacks. Up to 500 local candidates survive
fusion input; `GEMINI_TOP_N` controls paid scoring separately (default 30).
Candidate detection retains at least three times that scoring count, capped at
500, so vetoes do not exhaust the local pool.

Nice plans exclude dead-player vetoes. Mean plans prefer lowlights, including
vetoed windows whose captions explicitly describe a death without spectator,
killcam or death-screen language. This is a conservative caption heuristic,
not proof that every veto is a death: uncertain POV and plain spectator footage
remain excluded. The existing provider neutralizes dead-player hype scores,
so recovered deaths retain their local signal score and explicit provenance.

Reviewed (`validated=True`) inputs precede unreviewed candidates during selection;
original scores remain unchanged in the plan. The pipeline marks VLM-scored and
whole-video observations reviewed. This means model-reviewed, not human-verified.
When lowlights cannot fill mean mode, remaining highlights supply honest context
without failure captions or roast decoration.

Grounded kill/death timestamps take precedence over heuristic acoustic anchors.
Otherwise, the pipeline centers the trim on the longest sustained-audio burst
inside the candidate, breaking ties by proximity to the candidate midpoint.
Scene cuts alone do not define an action peak. This avoids treating an early
ability sound or camera transition as the climax while cutting out later action.
Without usable event/audio timing the library uses the candidate midpoint.
