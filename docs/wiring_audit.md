# WIRE-1 wiring audit

Audit scope: Extension additions versus `main`, using `git diff main...HEAD
--name-only`, module call sites, runner-1 DEMO-02 JSONs, and synthetic real renders.
No credentials were read and no paid calls were made. FX/SFX selection and the
effects registry belong to FX-2 and were not changed.

## Evidence before changes

`python -m pipeline.wire1_inspect` read the three actual files under
`/srv/demo_out/demo02/planned_{landscape,vertical,mean_vertical}.json`.
Landscape has seven segments; both vertical plans have four. All have music null,
cut joins, no cards, no SAM metadata, empty word lists and empty `fx` /
`video_effects`. Each has two reaction placements. Mean vertical has three legacy
SFX placements. These empty top-level effect lists do **not** mean there were no
effects: timed placements contain bruh text, flash and fade. Saved options have
captions false and privacy true. Most missing features were never requested;
transcription suppression, two-reaction selection, silent SAM fallback and
script-only narration were actual wiring gaps.

The stock path is `server.api.start -> JobQueue.run -> Pipeline.analyze/plan/render
-> pipeline.extensions / pipeline.rendering -> render.engine.Renderer`. A module
import alone is not proof of output. The matrix distinguishes automatic movie
stages from deliberately separate product operations.

## Feature matrix after WIRE-1

Defaults are ordinary API defaults; **Full** means enabled by the full-experience
button / API preset. Test paths below are relative to `full_app/tests/`.
“Plan” includes stored analysis evidence and the resolved `render_plan` where
the feature is resolved after planning. “Output” distinguishes movie pixels/audio
from non-video artifacts. Optional capabilities are not represented as real ML
when only a heuristic fallback ran.

| Feature | Default / enable control and API | Stock call path | Plan / output trace | Proof | Verdict |
|---|---|---|---|---|---|
| Motion/scenes/audio-energy signals | On; Gameplay signals / `use_signals` | `analyze -> signals.detect_candidates -> rank_merge` | candidates + interest curve affect selected cuts | `test_pipeline.py`, `test_signals.py` | Works |
| HUD OCR | With profiles; Game / `profiles`, `game` | detector receives `ocr=True` and profile | OCR events/scores influence candidates; detector degradation now warns | `test_game_profiles.py`, `test_signals.py` | Opt-in only; requires Tesseract |
| Audio AI / words/events | Off, Full; Audio AI / `audio_ai` | `extra_signals -> audio_ai.analyze` | audio_signals, merged events and warnings; selected cuts | `test_int02.py`, `test_audio_ai.py` | Works with explicit fallback warnings |
| V-JEPA | Off; API `vjepa`, env `VJEPA_HEAD` | `extra_signals -> vjepa.score` | vjepa_signals / candidates; missing head warns | `test_int02.py`, `test_vjepa.py` | Opt-in only; no installed trained head claimed |
| Twitch replay counts | Off; API `ingest=true, chat=[numeric bins]` | `extra_signals -> ingest.chat.chat_signal` | merged count evidence influences clips | `test_ingest_chat.py`, `test_int02.py` | Opt-in only; UI replay upload intentionally not advertised |
| Game profiles | Off, Full; Game / `profiles`, `game` | `analysis_inputs -> detect_game/get_profile` | game/profile prompt, OCR areas, planning input | `test_game_profiles.py`, `test_int02.py` | Works |
| Ingest proxies/chunks | Off; API `ingest` | `analysis_inputs -> ingest.prepare -> whole_video` | proxy/chunks with source-time offsets | `test_ingest_media.py`, `test_pipeline.py` | Opt-in only; remote URL import is a separate library entrypoint |
| Window VLM scoring | API on, UI off; window scoring / `window_scoring` | `score_windows -> rank_merge` | window_scores, alive veto, candidate scores affect cuts | `test_pipeline.py`, `test_video_understanding.py` | Works; paid budgets remain provider-owned |
| Planner v2 | Off, Full; Story planner / `planner` (`planner_v2`) | `planner_plan -> plan_edit -> to_render_plan` | source cuts, speeds, timed placements | `test_planner_adapter.py`, `test_wire1.py` | Works |
| Render v2 aspect/reframe | On; Canvas / `preset`; plan `reframe` | `_render_job -> Renderer` | crop/scale filter graph, probed dimensions | `test_render_v2.py`, `test_wire1.py` | Works |
| Captions and word captions | Off, Full; Captions / `captions` | Renderer transcribes even with editorial texts | words, ASS graphs, subtitle_events; editorial fallback warning | `test_wire1.py`, `test_pipeline.py` | Fixed wired no-op |
| Transitions | Cut, Full varied; Varied transitions / `transitions` or plan `transition` | `enrich -> join_graph` | mixed xfade types, audio acrossfade, timeline overlap | `test_wire1.py`, `test_render_v2.py` | Fixed missing automatic selection |
| Intro/outro | Off, Full; Intro and outro / `cards` | planner budget reservation, `Renderer.card` | cards in plan, ASS on black frames | `test_wire1.py` | Fixed missing automatic selection |
| Reactions | On only when pack configured; UI off, Full on; `reactions`, `REACTION_PACK` | enrichment + selector + render_overlay per clip | planned events and actual IDs/speakers in evidence; picture/audio overlays | `test_wire1.py`, `test_reactions.py` | Fixed montage-wide two-event bottleneck |
| SAM subject crop | Off, Full; Subject-aware crop / `sam_reframe` | subject_track -> crop graph | normalized tracks and actual crop expressions; fallback warns | `test_wire1.py`, `test_sam.py` | Works; fallback is not SAM inference |
| SAM spotlight/cutout-style mask | Off, Full; SAM spotlight / `sam` | real masks checked before duration-preserving spotlight | keyed spotlight event in evidence, mask pixels; no-model skip warns | `test_wire1.py`, `test_sam.py` | Fixed silent fake-model appearance; no separate cutout compositor claimed |
| Privacy | **Off in API/UI/every preset**; explicit Privacy blur / `privacy=true` | selected_source/private_range/sanitize before crop | privacy_track, blur video only when explicitly enabled | `test_int02.py` explicit opt-in; `test_wire1.py` default-off | Works; owner-requested default changed |
| Music / beat sync | Off, Full; Music bed + beat toggle / `music`, `music_mood`, `beat_sync` | offline generation -> snap_durations -> music_graph | beat grid, shortened clip timing, ducked AAC mix | `test_wire1.py`, `test_music.py`, `test_render_v2.py` | Fixed beat_sync false and lost UI mood |
| Narration/caster | Off, Full; AI narration/persona / `narration`, `narration_persona` | finish_output -> build -> cached/local voice -> render | narration_track, voice flags and mix graph; no voice/gap warns | `test_wire1.py`, `test_narration.py` | Fixed script-only silence and card/transition timing |
| Multi-POV | Off; repeated video uploads enable `multipov`; team layout / `team_mode` | team_source -> sync -> render_montage | team alignments/candidates, composite source used by renderer | `test_int02.py`, `test_multipov.py` | Works; sync failure warns |
| Share kit / social metadata | Off, Full; Share kit / `social` (`share_kit`) | finish_output -> build_share_kit | share_kit, video, covers, chapters, posting copy | `test_wire1.py`, `test_social.py` | Works; not external publication |
| External publishing | Off; Python publisher `upload(dry_run=False, confirm=True)` | Deliberately separate from movie job | upload receipts, not movie changes | `test_publish.py` (mocked) | Opt-in only; credentials/confirmation required by module |
| Player stats/votes | Read-only on request; `/api/stats/*`, no UI | owner-filtered jobs adapter mounts existing blueprint | JSON aggregation/votes, no movie mutation | `test_wire1.py`, `test_stats.py` | Fixed dead stock registration; owner-scoped, not cross-owner friends board |
| Library search | On request; `/api/search`, no UI | owner-filtered snapshot -> SearchIndex -> blueprint | searchable captions/events and source seek URLs | `test_wire1.py`, `test_search.py` | Fixed dead stock registration; BM25, optional embeddings not auto-loaded |
| Mean/roast mode | Nice default; Mode / `mode=mean` | deterministic planner's mean path | lowlight selection, bruh texts and reaction labels | `test_planner.py`, `test_wire1.py`, DEMO replay | Works; standalone `roast` template/FX library is separate (FX-2 ownership) |
| Editor agent | Off; Director / `editor_agent`, `/agent/*` | server.editor -> editor_agent loop -> validated plan | versioned plans/previews reach subsequent render | `test_editor_agent_api.py`, `test_editor_agent.py` | Opt-in only; not added to Full paid budget |
| Local VLM | Gemini default; Provider / `provider=local` | Pipeline.client -> LocalClient -> localvlm provider | same clips/scoring/plan contract as Gemini | `test_localvlm.py`, `test_provider_config.py` | Opt-in only; requires configured local runtime |
| Capture / OBS | Off; capture CLI/hotkey | capture client uploads to jobs API | input recording becomes ordinary analyzed source | `test_capture.py` | Opt-in only; input client, not a montage stage |
| Desktop | Separate desktop shell (outside full_app) | invokes capture/API | same job outputs | capture/client tests; no desktop GUI session run | Opt-in only; no desktop runtime claim |
| Discord bot | Off; bot commands + bot token | bot API client uploads/analyzes/renders | job/output link returned by separate client | `test_discord_bot.py` | Opt-in only; never auto-posted by a movie job |
| Public share page | Off; explicit POST `/api/jobs/<id>/share-page` | owner-authorized create, existing `/s/<id>` blueprint | expiring public player link to output and cover | `test_wire1.py`, `test_sharepage.py` | Fixed dead stock registration; never auto-published |
| Perf, eval and demos | Perf renderer default; eval/demo CLI | perf runner/cache/parallel; test tools separately | same movie contract; benchmark/demo artifacts | `test_perf.py`, `eval/`, `tests/e2e/` | Works / separate development tools |
| FX/SFX modules | Existing opt-in `fx` and planner placements | Existing compose/legacy mixers | timed effects and audio placements | existing `test_fx.py`, `test_planner_adapter.py` | Unchanged, FX-2 owns selection and registry |

## Design limits and scope decisions

No paid calls, model downloads, automatic external posts or unrequested public
links were introduced. Missing SAM means no spotlight, not a motion-mask effect
presented as a working model. Editorial word timing is explicitly labelled as a
fallback, not speech recognition. Reaction speaker coverage is bounded by clip
count and allowed labels (nice mode excludes roast). Narration protects actual
reaction intervals, including beat-trimmed output clocks; short clips may have no
safe speech gap and warn. The original mean plan's FX/SFX are preserved.

Stats/search/share-page were dead on the stock server because their blueprints
were never registered; WIRE-1 supplies server adapters. Capture, desktop, bot,
OAuth publishing, optional embedding models and standalone roast templates are
separate entrypoints, not silent movie-stage drops. Stock UI controls for
unimplemented URL/music/chat upload remain disabled rather than being falsely
advertised. Search/stats have HTTP endpoints but no new frontend page.

## DEMO-02 replay result

Command: `tools/remote_run.sh "cd full_app && python -u -m pipeline.wire1_demo"`
(exit **0**). Output: `/srv/demo_out/wire1/output.mp4`, copied to
`demo_video/wire1/out/output.mp4`. The requested local artifact directory contains
its own generated `demo_video/wire1/.gitignore` (`*`); `git check-ignore` confirms
the movie is excluded. This task-required artifact destination is outside source
allowed_paths; no artifact or ignore file there is committed.

* 21.269 seconds, 1080 x 1920, 30 fps, H.264 / AAC.
* Same four saved mean-vertical cuts; no new inference or clip hallucination.
* `BRUH MOMENTS` intro and `GG - NEXT ROUND` outro. Intro frame at 0.3 seconds
  and the 12-cell contact sheet were visually inspected.
* Four reaction overlays: Stefanny roast, Iraj clutch, Stefanny fail, Iraj roast.
  The configured team pack has exactly these two speakers, so both appear.
* 47 animated editorial words, with explicit no-transcriber/fallback warnings.
  These are **not** a transcript. Contact-sheet frames show words and both speakers.
* Original generated music, ducking and beat sync are present in the executed
  graph. The first and third gameplay durations trim from 2/5 to 1.9667/4.9667 s;
  the intro and crossfade offsets are included in the beat calculation.
* Two offline espeak-ng narration clips are mixed at 5.9203-8.7167 and
  11.9913-16.8 seconds. Other speech is omitted with a safe-gap warning.
  espeak-ng was installed only on the runner; it is an optional system dependency.
* Four fallback crop tracks contain 120, 90, 300 and 300 points. No SAM model was
  installed; spotlight is skipped with an explicit warning, not faked.
* `privacy=false`, no privacy stage/cache/blur graph in this replay. Vertical
  framing still crops the source normally. No claim that an arbitrary crop is a
  privacy guarantee.
* Five joins cycle zoom, whip, flash, pixelize, zoom. Existing timed bruh/flash/
  fade and three SFX placements remain owned by the saved plan / FX-2.
* `job.json`, `contact_sheet.jpg`, `intro.jpg`, `manifest.json` and
  `live_calls.json` are beside the local movie; the full share kit remains on
  runner 1. Paid calls: **0 Gemini, 0 other providers**. No key was read.

Movie SHA-256 (remote manifest and local `Get-FileHash` agree):
`38c66afb533c2bc3232ebee0fe4756023898016f91589f27d5008703158192ce`.

## Verification

All test commands below ran through `tools/remote_run.sh` from this worktree.
The helper prints the command's remote exit code; no paid/live tests were enabled.

| Command inside runner | Result / exit |
|---|---|
| `cd full_app && python -m pytest -q tests/test_wire1.py tests/test_pipeline.py::test_explicit_caption_options_survive_toggle tests/test_int02.py::test_new_planner_render_music_privacy_social_and_narration` | 5 passed, exit 0 |
| `cd full_app && python -m pytest -q tests/test_wire1.py tests/test_planner_adapter.py tests/test_sam.py` | 32 passed, exit 0; existing unknown `slow` marker warnings |
| `cd full_app/production_frontend && npm test && npm run build` | 35 tests passed; TypeScript/Vite build passed; exit 0 |
| `cd full_app && python -m pytest -q tests/test_wire1.py tests/test_pipeline.py::test_full_optional_matrix tests/test_fix4.py::test_selected_privacy_cache_and_source_clocks` | 26 passed, exit 0 |
| `cd full_app && python -u -m pipeline.wire1_demo` | Replay and FFmpeg contact sheet succeeded, exit 0 |

Development failures were real and corrected: initial test media used FFmpeg's
unsupported `.35` duration syntax; a fake SAM adapter supplied config twice;
cards initially exceeded planning budgets; narration initially omitted the outro
from its duration check; a privacy-cache test still assumed privacy-on defaults.
Explicit caption options and custom reaction placements are preserved. The first
replay failed the narration duration check (exit 1); the final replay above passed.
Final full-suite command: `tools/remote_run.sh 'cd full_app && python -m pytest -q > /tmp/wire1-final-suite.log 2>&1; rc=$?; tail -90 /tmp/wire1-final-suite.log; exit $rc'`.
Result: **1050 passed, 20 skipped in 622.10 seconds; remote exit 0**.
The preceding full run had one failure in the old privacy-default fixture; the
final run includes the explicit opt-in correction. The final targeted run passed
26 tests (exit 0), and the final UI run passed 35 tests plus build (exit 0).
The frontend also covers applying Full experience after analysis: changed cards
or transitions request a fresh plan instead of reusing the old automatic draft;
authoritative Director plans remain untouched.

## Changed source files

All committed changes are within WIRE-1's allowed paths. Work branch:
`ext/WIRE-1`. Implementation milestones: `13b3556`, `4c474b1`; no push or merge.

| Directory | Files |
|---|---|
| `full_app/pipeline/` | `experience.py`, `extensions.py`, `orchestrator.py`, `rendering.py`, `wire1_demo.py`, `wire1_inspect.py` |
| `full_app/server/` | `api.py`, `capabilities.py`, `library.py`, `queue.py`, `validation.py` |
| `full_app/render/` | `engine.py`, `graph.py`, `plan.py` |
| `full_app/sam/` | `effects.py`, `tracking.py` |
| `full_app/narration/` | `__init__.py`, `providers.py` |
| `full_app/reactions/` | `pack.py` |
| `full_app/production_frontend/src/` | `api.ts`, `api.test.ts`, `features.ts`, `features.test.tsx`, `components/EditSettings.tsx` |
| `full_app/tests/` | `test_wire1.py`, `test_pipeline.py`, `test_int02.py`, `test_fix4.py`, `live_fix4_smoke.py` |
| `docs/` | `pipeline.md`, `wiring_audit.md` |

Try it by selecting **Full experience** in production UI Edit settings, or send
`{"full_experience":true,"privacy":false}` to a job's analyze endpoint and then
render. Review `warnings`, `render_plan`, `render_evidence` and `narration_track`
in the job response. Install/cache optional models and configure `REACTION_PACK`
to replace the documented fallbacks; those resources are not bundled in git.
