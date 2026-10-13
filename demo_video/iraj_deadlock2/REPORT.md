# IRAJ-DL2 owner revision

Branch: `ext/IRAJ-DL2`. No pushes or merges. Implementation milestones:
`b17de11` (controls/filter/defaults), `a9ef215` (clear stale narration metadata).
Offline render/verification milestone: `7b28524`.

Full experience now defaults to `narration=false` in the API and production UI.
Narration remains an explicit toggle with the existing persona choices. The new
`reaction_speakers` option accepts exact configured-pack names; `[]` or omission
means everyone. The API rejects unknown names and removes duplicates. The UI
discovers names from capabilities and supports multiple selections or clearing
the selection. Speaker coverage and label/take rotation only consider selected
speakers; there is no fallback to someone else's face.

Changed implementation files: `full_app/pipeline/{experience,extensions}.py`,
`full_app/reactions/pack.py`, `full_app/server/{validation,capabilities}.py`,
`full_app/production_frontend/src/{api,features}.ts`,
`full_app/production_frontend/src/components/EditSettings.tsx`. Tests changed:
`full_app/tests/{test_iraj_dl2,test_wire1}.py` and
`full_app/production_frontend/src/features.test.tsx`. Documentation:
`docs/{pipeline,reactions}.md`. Replay/verification/fetch tools and this report
are in `demo_video/iraj_deadlock2/`.

## Try it

Configure `REACTION_PACK` to the team pack, open Edit settings, choose **Full
experience**, then select **Iraj** under **Reaction speakers**. AI narration is
unchecked. API example: `{"full_experience":true,"reaction_speakers":["Iraj"],
"narration":false}`. Narration can still be enabled with `narration=true` and
`narration_persona="hype_caster"`, `"deadpan_roast"`, or `"nature_documentary"`.

Replay on runner 1, with no credentials and zero network/provider calls:

```sh
bash tools/remote_run.sh 'python -u demo_video/iraj_deadlock2/render_saved.py'
bash tools/remote_run.sh 'python -u demo_video/iraj_deadlock2/verify.py'
bash demo_video/iraj_deadlock2/fetch.sh
```

The replay reuses each original saved `edit_plan`, reviewed clips, source video,
cached cards, speech words and share thumbnails. It never runs analysis or
planning. Python network connections and provider construction are blocked.
It renders to `/srv/demo_out/iraj_deadlock2/`; fetching copies that tree to the
gitignored `demo_video/iraj_deadlock2/out/`. Existing original outputs stay intact.
Replay skips completed `job.json` entries for safe continuation.

## Choices and limits

- Cinematic's saved plan removes sustained `dark_mood` and `vignette` effects;
  its color tint, grain, timing and fades remain. This is an owner-specific replay
  change; the global cinematic planner is outside this task's allowed paths.
- The existing rendering module is outside scope. The allowed extension hook
  supplies speaker names through a context-local, single-use selector binding,
  tied to the renderer's disposable directory. Tests cover concurrent jobs,
  explicit overrides, consumption, and failure cleanup.
- Original optional SAM model availability is preserved as the reported motion
  fallback. No model downloads or paid calls are made. Existing meme SFX, music,
  gameplay audio and Iraj reaction lines remain; the generic narration stage is
  absent. An audio stream count alone cannot establish this: verification also
  checks options, executed stage timings, absence of narration track/graph, and
  the clean-source replay path.
- Share covers are reused exactly. Existing posting copy/chapters are retained
  as provenance from the old edit; the copied share video's media is replaced
  with the new un-narrated master.

## Validation

- `bash tools/remote_run.sh 'cd full_app && python -m pytest -q tests/test_iraj_dl2.py tests/test_wire1.py'`
  — exit **0**, **27 passed**. Includes mocked HTTP upload/analyze/plan/render
  with synthetic video, owner-only selection and no narration, plus explicit
  narration opt-in, validation and concurrent selection tests.
- `bash tools/remote_run.sh 'cd full_app/production_frontend && npm ci --silent && npm test && npm run build'`
  — exit **0**, **45 tests passed**; TypeScript and Vite production build passed.
- Repeated the targeted backend command after clearing stale narration evidence:
  exit **0**, **28 passed**.
- `bash tools/remote_run.sh 'python -u demo_video/iraj_deadlock2/render_saved.py'`
  — exit **0**, all three saved cuts rendered, zero new Gemini calls.
- `bash tools/remote_run.sh 'python -u demo_video/iraj_deadlock2/verify.py hype'`
  and the same command with `meme` and `cinematic` — each exit **0**.
  All six MP4s decode without error, contain one H.264 video stream and one AAC
  audio stream, and remain within their duration budgets. Source ranges and
  cached card/cover bytes match the original; all executed reaction IDs resolve
  to Iraj in the real pack. No narrator track, mix graph or execution stage exists.
- `bash demo_video/iraj_deadlock2/fetch.sh` — exit **0**. Local master SHA-256
  values match runner verification for all three cuts.
- An initial full-suite run was intentionally interrupted for the final metadata
  fix: remote exit **2** (local wrapper exit **1**), 583 passed / 9 skipped at
  interruption. It was restarted against the final implementation.

## Deliverables and inspection

| Cut | Actual duration | Master | Discord bytes | Iraj placements |
| --- | ---: | --- | ---: | ---: |
| Hype (60 s cap) | 58.854 s | 1920×1080 | 16,744,460 | 7 |
| Meme (30 s cap) | 28.988 s | 1080×1920 | 8,230,030 | 4 |
| Cinematic (45 s cap) | 43.654 s | 1920×1080 | 12,340,583 | 6 |

Open `out/{hype,meme,cinematic}/discord.mp4` for sharing or `master.mp4` for
the full-resolution version. Each folder includes `job.json`, `planned.json`,
`provenance.json`, ffprobe stream lists, event contact sheets, and reaction-only
contact sheets. [verification.json](verification.json) records hashes and checks.

Visual review inspected all **17 reaction placements** in the three
`reaction-contacts/contact-01.jpg` sheets: the same glasses-wearing Iraj head and
Iraj label appear throughout; no other pack speaker appears. Cinematic's first
general contact page also shows the reused intro and readable gameplay across
the color grade and transitions. Center-frame luma increased at all six sampled
gameplay timestamps: 66.89→124.98, 19.57→67.92, 33.66→82.03, 38.37→88.87,
26.82→61.29, and 65.77→122.06 (8-bit grayscale). Fade-in frames remain
intentionally darker. Narrator absence was verified from the fresh-source render
path, options, stage/evidence JSON and stream inventory, not a listening test.

Final full-suite command:

```sh
bash tools/remote_run.sh 'set -o pipefail && cd full_app && python -m pytest -q | tee /srv/demo_out/iraj_deadlock2/pytest.log'
```

Exit **0**: **1,480 passed, 20 skipped in 661.59 seconds**. This run used the
final backend implementation, including stale-narration cleanup. The full log
is in `/srv/demo_out/iraj_deadlock2/pytest.log` and `out/pytest.log`.
No requested work remains. No live calls were made and no credential file was read.
