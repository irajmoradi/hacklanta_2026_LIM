# Shared game profiles

The package supplies game-specific regions, vocabulary, detection and scoring prompt fragments.
Profiles are JSON data loaded into standard-library dataclasses; no Python ML,
OCR, image or model dependency is required to import the package.

```python
# When running from full_app (or with full_app on PYTHONPATH):
from profiles import get_profile, detect_game, match_events

name, confidence = detect_game("gameplay.mp4")
profile = get_profile(name)
crop = profile.regions["kill_feed"].pixels(1920, 1080)
events = match_events("PENTAKILL", "league_of_legends")  # {'teamwipe'}
fragment = profile.prompt_fragment()
# Append fragment to the window-scoring prompt.
# Apply profile.signal_weights as multipliers to the fusion baseline weights.
```

Imports also work as `from full_app.profiles import ...` from the repository root.
Supported canonical names are `generic`, `valorant`, `overwatch2`, `deadlock`, and
`league_of_legends`. Unknown explicit names raise `ValueError`; auto-detection
returns `('generic', 0.0)` for insufficient or ambiguous evidence.

## Per-game summary

| Profile | HUD / death evidence | Highlights | Lowlights |
| --- | --- | --- | --- |
| Valorant | Upper-right feed; right combat report / killed-by panel; bottom-left spectator label; bottom-center health | Aces, clutches, multikills, spike plays | Whiffs, failed utility, exposed positioning, failed defuse |
| Overwatch 2 | Upper-right feed; upper-left eliminated-by banner; respawn timer at upper right; bottom kill cam; lower-left health | Team kills, ult combos, environmental kills, payload/point contests | Wasted ult, stagger, missed save, abandoning objective |
| Deadlock | Upper-left cream/red feed; right incoming-damage report; lower-center respawn banner; health left of centre, souls bottom left, four-lane minimap bottom right | Picks/team fights, multikills, soul denial, urn steals, Guardian/Walker/Patron fights | Lost urn, whiffed ultimate, getting ganked, costly deaths |
| League of Legends | Right feed; upper-center announcements; bottom-center champion HUD; gray screen + respawn timer | Multikills/pentakills, shutdowns, low-HP outplays, Baron/Dragon steals, towers | Failed smite, bad dive, consequential missed skillshot |
| Generic | Broad approximate regions; explicit death or spectator evidence | Confirmed player multikills, outplays, objectives | Observable mistakes with consequences |

League is a top-down MOBA: **never require a crosshair or ammo**. Death is supported
by gray screen plus respawn timer or a personal slain banner. Following an ally
after death is spectating; free camera movement by itself is not. FPS first-person
HUDs can also be visible while spectating or watching a kill cam.

The existing clip-finder rules informed the Valorant, OW2, and Deadlock state
descriptions. Regions are conservative search areas, not verified pixel-perfect
contracts for every game patch. FIX-5 calibrates the Valorant layout against the
owner-provided demo VOD; DEADLOCK-1 calibrates Deadlock against the supplied CC BY
No Copyright Gameplay recording. OW2 and League retain synthetic-only calibration.

## Region and OCR contracts

`Box(x1, y1, x2, y2, anchor)` uses normalized 16:9 coordinates and exclusive right
and bottom crop edges. `pixels(width, height)` returns clamped integer crop bounds.
`left`, `right`, and `center` anchors preserve height-relative HUD size and move
horizontally with that screen anchor on native 16:10 or ultrawide footage.
`stretch` scales with the whole frame. Vertical coordinates remain normalized.
`pixels(..., letterboxed=True)` instead maps into a centered 16:9 content rectangle.
Crop recordings with baked-in borders before detection: the detector assumes
native, full-frame gameplay. User HUD scale, minimap placement and accessibility
settings can require custom region calibration.

All profiles define kill feed, death banner, spectator indicator, round/score,
announcement and health regions. `keywords` contains candidate events: `kill`,
`death`, `assist`, `multikill`, `teamwipe`, `round_won`, `round_lost`, and
`objective_taken`. `teamwipe` includes ace/pentakill phrases; it is a shared fusion
category, not proof that all opponents were simultaneously dead. Kill/assist feed
text and objective banners require separate player attribution and timing checks.
OCR mentions of Baron/Dragon/urn identify objective candidates, not completed
captures. Keywords include selected English, Portuguese and Spanish variants;
coverage is intentionally partial. Matching ignores case, accents and punctuation,
but uses whole phrases so `ace` does not match `placement`.

`alive_rules`, `dead_rules`, and `spectating_rules` are guidance for consumers, not
an implemented state classifier. Verify player control before accepting highlights.
For a death lowlight, keep the lead-in action and stop at death; never score the
subsequent spectator interval as the recorder's play. Prompt fragments include
these rules and semantic reaction hints, without imposing a new output schema.

`signal_weights` are positive multipliers for `ocr`, `announcements`, `motion`,
`audio`, and `objective`; they are not probabilities and do not sum to one. Generic
uses all ones. League emphasizes OCR/announcements and reduces motion; the consumer
must map these keys to its own fusion signals and normalize weights as appropriate.

## Offline detection and optional hooks

`detect_game(path, sample_count=16, ocr=None, vlm_fallback=None, language='eng')`
uses ffprobe duration and samples midpoint positions of equal timeline bins, up to
32 frames. ffmpeg emits PNGs downscaled to at most 1280 pixels wide. Each process
has a timeout (20 seconds for probe/OCR, 30 for decoding each frame). Sampling is
bounded; this does not guarantee a distinctive banner is present.

Tesseract is an **optional system executable**, invoked in sparse-text mode with
TSV output; install language packs to use `language='eng+por+spa'`. Missing OCR,
missing language packs, or unreadable media gracefully produce no local evidence.
Missing ffmpeg/ffprobe also returns generic. Missing input paths and invalid sample
counts raise errors. Nothing installs dependencies or downloads weights at runtime.

The detector matches profile-specific phrases in expected regions, gives weak
support to numeric health/score text, and adds bounded support for repeat evidence
across frames. This is a simple OCR-derived HUD-layout heuristic, not a trained
visual detector. Generic words alone cannot identify a game. Confidence
is a heuristic ranking score, **not a calibrated probability**. Multiple games in
one recording, edited overlays, menus, unknown languages, resized HUDs and very
small text can produce generic or wrong results. Explicit user game selection
should take precedence.

FIX-5 adds an optional `detection_layout` profile field. Valorant's fallback
requires a readable round timer and health number plus bright ability slots and
minimap edges together in at least three frames (and at least 18% of decoded
samples). Tight crops, upscaling and a low-chroma white-glyph mask recover HUD
numbers lost by full-frame sparse OCR. Paired red/teal rows corroborate the
upper-right kill-feed position; an empty feed is normal between eliminations.
The fallback only resolves otherwise generic results. A single matching frame,
blank screen, or partial HUD cannot activate it. Other profiles keep keyword
detection, except Deadlock's fallback described below. Injected OCR readers retain their original full-frame-only contract.
The visual helper lazily uses the app's existing OpenCV/NumPy dependencies;
Tesseract remains optional, and no weights or model downloads are introduced.

DEADLOCK-1 adds timer OCR, mint souls-counter text, four colored minimap lanes and
top portrait-bar corroboration, required together with the same repeated-frame
threshold. It resolves only otherwise generic results. Its calibrated feed is
upper-left `(0.025, 0.18, 0.36, 0.45)`; cream/red rows support candidate events
without claiming player attribution. Objective outcomes require explicit text,
and souls gains are weak economy evidence. See [Deadlock validation and demo](deadlock.md)
for full-source measurements, stock API reproduction, attribution and limitations.

Custom OCR adapters accept PNG `bytes` and return `Sequence[OCRToken]`, each with
text, a normalized `Box`, and confidence in `[0,1]`. Preserve reading order for
multiword phrases. Tokens below 0.45 are ignored. To avoid media decoding entirely,
use `detect_frames([(width, height, tokens), ...])` with precomputed OCR.

The optional `vlm_fallback(images)` receives a tuple of sampled PNG bytes only when
local detection is generic and decoding yielded frames. It returns a canonical
`(name, confidence)` with confidence in `[0,1]`. Unknown names and nonfinite scores
raise `ValueError`; hook exceptions propagate. There is no built-in network client
or automatic paid call. Callers must enforce live-smoke authorization and budgets
before installing any network-backed hook. The built-in detector uses no API keys or live calls.

## Adding a game

1. Add `full_app/profiles/data/<name>.json` following the existing schema, with all
   six core regions, event sets, state rules, highlight/lowlight definitions,
   detection phrases, aspect notes and positive signal multipliers.
2. Register the canonical name in `list_profiles()` and increase the loader cache
   size if needed. Keep names explicit; no file path is accepted as a profile name.
3. Add `full_app/prompts/games/<name>.txt` with alive/dead/spectating rules,
   attribution, highlights/lowlights and reaction hints.
4. Add synthetic region and OCR tests, including competing-game and blank-screen
   cases. Calibrate actual recordings separately with permission before claiming
   production accuracy. Keep real recordings and generated test videos out of git.

## Validation

From the worktree root:

```bash
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_game_profiles.py"
```

The tests generate temporary synthetic footage with ffmpeg drawtext and use the
Linux runner's Tesseract and DejaVu font. They test real OCR for ACE, KILLED BY,
ELIMINATED BY, KILLING BLOW and PENTAKILL, multilingual matching, aspect transforms,
ambiguous layouts, fallback validation and missing-tool behavior. No network/API
calls occur inside the tests (SSH/rsync is used only to run them on the Linux runner).
