## Measured exports and visual review

**Two stock API exports succeeded; landscape did not.** The API's landscape
failure is retained in `out/landscape.json`. Its 44.053s MP4 and share kit are a
separate no-key diagnostic rendering of the saved API plan, explicitly labelled
in `summary.json`; they are not represented as a successful API download.
`landscape_bounded_diagnosis.json` reproduces `Cannot allocate memory` at
`render/engine.py`'s FFmpeg join under the same 8 GiB address-space limit.
The unrestricted diagnostic passes the worker's duration guard, ruling out the
initial duration/share-kit suspicion for this particular failure.

| Variant | API result | Media | Segments | Timed VFX / SFX / editorial words | Actual heads | Sampled frames |
|---|---|---|---:|---|---:|---:|
| Nice landscape, 45s target | **Error**; separate diagnostic below | 1920×1080, 44.053s | 6 | 17 / 17 / 50 | 6 | 124 |
| Nice vertical, 30s target | **Done** | 1080×1920, 29.312s | 4 | 11 / 9 / 41 | 4 | 91 |
| Mean vertical, 30s target | **Done** | 1080×1920, 29.013s | 5 | 21 / 21 / 69 | 5 | 154 |

All three files decode completely and contain H.264 video plus AAC audio. There
are **369 event samples across 20 montage contact sheets**, plus 24 source
samples. Every contact-sheet page was visually inspected; individual labelled
JPEGs and exact sample times remain alongside `events.json`. Counts demonstrate
coverage, not that every planned effect is perceptually successful.

| Frames inspected | What is actually visible / remaining issue |
|---|---|
| `landscape_frames/contact_00–01.jpg`, segment 0 | Flash and increased saturation; Lance's matted head appears at 2.517s without a white rectangular background. Word captions incorrectly say “Yoru” over Phoenix footage. |
| `landscape_frames/contact_01.jpg`, segment 1 | At 7.7–9.8s, combat report, spectator HUD and scoreboard appear in the **nice** montage; Stefanny's hype head overlays it. Brightness change is visible; grain is subtle. Unscored signal filler bypasses the intended POV/alive quality gate. |
| `landscape_frames/contact_02.jpg`, segment 2 | GG text and vignette are visible; contrast enhancement is less distinguishable. Iraj's head is small. A large blue shape is the game's kill animation, not a newly implemented SAM effect. |
| `landscape_frames/contact_02–03.jpg`, segment 3 | Flash and zoom appear during a one-second reload slice; Mario gets only 0.35s. “Two quick kills” text describes broader context rather than an event visible in this cut. |
| `landscape_frames/contact_03–04.jpg`, segment 4 | Hit-marker is small; dark-mood effect visibly darkens the frame; Stefanny's head appears. Caption's “Omen” attribution is inconsistent with the visible Phoenix hands/abilities. |
| `landscape_frames/contact_04–06.jpg`, segment 5 | Flash, head and fade are apparent; shake/grain/sharpen/blur are much less obvious in sampled frames. Overlapping source material repeats the opening kill context. No big procedural meme effect or SAM silhouette appears. |
| `vertical_frames/contact_00–01.jpg`, segments 0–1 | Flash, Lance and Stefanny appear. Central crop keeps much combat visible but removes peripheral HUD/feed context. “Signal candidate” appears as viewer-facing caption text. |
| `vertical_frames/contact_02.jpg`, segment 2 | NICE, cold tint, small hit-marker and Iraj are visible. Wrong “Omen” words remain. |
| `vertical_frames/contact_03–04.jpg`, segment 3 | Transition pixelation, flash, Mario and ending fade are visible. Grain is weak. The Phoenix sequence repeats the opening context. |
| `mean_vertical_frames/contact_00–01.jpg`, segment 0 | Black-and-white freeze and Lance are visible, but planned **text_rip is absent at 2.517s**. The subsequent freeze captures the image before the slightly later RIP text begins. Fast editorial words remain visible because captions are a later pass. |
| `mean_vertical_frames/contact_02.jpg`, segment 1 | Zoom/saturation/warm changes and Stefanny are visible; sharpening is hard to distinguish. A successful kill is paired with a fail-labelled reaction, showing weak event/reaction semantics. |
| `mean_vertical_frames/contact_03.jpg`, segment 2 | Flash, GG and Iraj are apparent; heavy grain/glitch subtle. Mean mode still includes successful plays, which is allowed, but this is not evidence of a sophisticated roast narrative. |
| `mean_vertical_frames/contact_04–05.jpg`, segment 3 | HIGHLIGHT and darkening are clear, Mario appears; shake and sharpening are subtle. The same incorrect “Yoru” narration/caption is reused. |
| `mean_vertical_frames/contact_05–07.jpg`, segment 4 | BRUH/deep-fry color change, Stefanny, fade and outro are clear. Long spectator/round-loss passage and repeated opening context; captions include the generic “Confidence: 100. Accuracy: 0.” |
| All cards, joins and heads | Plain black/yellow title cards; wipe/flash/pixelated joins visibly occur. All four pack speakers appear. Heads have transparent backgrounds, small lower-right placement and 0.35–1.0s slots. No true SAM spotlight, Nano Banana image card, original car/fish outro, or readable streamer-sized reaction appears. |

Share kits contain `video.mp4`, SRT, chapters, metadata and two covers. Metadata
says **provider `template`, thumbnail provider `local`**. Mean cover's long
death/spectator caption overlays a smoke-ball frame with an arrow: neither an AI
image nor a semantically matched death frame. No generated head cutout appears
in these covers. Nice vertical chapters are `[0, 2, 12, 18]` seconds while actual
segment starts are `[0.8667, 2.7, 12.5667, 18.4333]`; `intro_duration` is wrongly
zero. Subtitles do use executed caption events. All four checked mean HTTP
download/share routes return 200, and the downloaded MP4 hash matches the saved
mean output (`http_downloads.json`). Earlier variants were copied immediately
after their stages, before the shared workspace was reused.

Audio evidence combines actual reaction selection, SFX placements, recorded
mix/filter graphs, generated music metadata, narration tracks and decoded PCM.
Music has beat-sync/duck enabled and volume 0.18. Narration is local computer
speech, with 4 voiced nice-vertical lines and 3 mean lines; the mean job warns
that another line did not fit its safe gap. Nice narration includes the fragment
“What a” and filler “Signal candidate”. This is not a cloned-caster demo.
Decoded mono RMS is 0.1334/0.1479/0.1536 and peak is
1.1529/1.0384/1.1557 (landscape diagnostic/nice/mean). Narration has a 0.95 sample
limiter, but AAC encoding can overshoot; these figures do **not** alone establish
audible clipping or a verified true-peak ceiling. No listening-based claim about
voice identity, intelligibility or mix balance is made.

UI screenshots retain every settings control, review, Director and export;
`ui_controls.json` records values and disabled states, and `ui_result.json`
contains the full visible text with zero browser page errors. Director is
present. Reroll and Chaos counts are zero. The upload-response attachment shim
uses the same real trim for source playback; its settings remain local Full
defaults rather than a restored copy of API job options. Therefore the pictured
Nice/landscape selectors are not used as evidence of a failed mean-mode request.
The 155.7s candidate-versus-edit timeline mismatch is independently confirmed in
`normalizeJob` and the executed plans (F60).

**Actual paid-request total: 14/25** (13 reserved generation attempts, including
six failed default-model requests, plus one failed model-list request). Both
diagnostic renders, frame extraction, browser checks and HTTP downloads make no
inference calls. No additional paid provider was used.
