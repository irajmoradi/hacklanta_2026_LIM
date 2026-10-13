# FINAL-2 delivery report

Branch: `ext/FINAL-2`; no push or merge.

Implementation, exact test commands/results, runtime setup and reproduction: [docs/final_render.md](../../docs/final_render.md).

Five stock-API cuts; measurements below include both cards. Each linked folder contains master.mp4, discord.mp4, share kit, cards, job.json (all warnings), timings.json, verification.json and event contact sheets.

| Cut | Seconds / cap | Discord MB | SAM applied / rejected | API wall seconds |
|---|---:|---:|---:|---:|
| [valorant_nice_landscape](out/valorant_nice_landscape/) | 58.721 / 60 | 17.03 | 1 / 2 | 432.21 |
| [valorant_mean_vertical](out/valorant_mean_vertical/) | 29.054 / 30 | 8.47 | 0 / 3 | 468.49 |
| [valorant_mean_vertical_reroll](out/valorant_mean_vertical_reroll/) | 29.054 / 30 | 8.47 | 0 / 3 | 257.58 |
| [deadlock_nice_landscape](out/deadlock_nice_landscape/) | 43.421 / 45 | 12.69 | 0 / 3 | 384.15 |
| [deadlock_mean_vertical](out/deadlock_mean_vertical/) | 29.121 / 30 | 8.42 | 1 / 2 | 338.07 |

API wall times cover the final attempt (plan/analyze, render and download), not earlier cancelled/failed audit attempts or offline packaging. Both nice cuts resume analysis; Reroll and mean Deadlock reuse their job analysis. Raw stage times retain the latest recorded value per stage key, including earlier analysis/render stages not rerun in a variant, and include nested timers; do not sum them.

Live Gemini attempts: **59 / 60**, including cancelled audit work, Director and image attempts. Durable per-job totals: `{"deadlock": 15, "valorant": 19, "valorant_mean": 11, "valorant_nice": 14}`.

Full runner validation: **1438 pytest passed, 20 skipped; 44 frontend tests passed; production build passed; exit 0**. All ten delivered video files were decoded completely with ffmpeg -xerror. Reroll verification confirms identical analysis/job, changed seed and changed effects.

## Feature and visual audit

Review method: every scheduled effect, reaction and card sampled in contact sheets; every thumbnail variant reviewed; selected larger master and compressed stills inspected. This is sampled visual QA plus complete decode validation, not frame-by-frame human playback. Manual notes: [visual_review.json](visual_review.json).

### valorant_nice_landscape

AI cards: 2; Gemini thumbnail candidates: 2; speakers: Iraj, Lance, Mario, Stefanny. SFX events: 26; music beat sync: True; transitions: varied. Explicit reactions selected: 0 (clean=false permits them but does not force selection).

Warnings recorded by the stock job (cumulative across rerenders):

- WebRTC VAD unavailable (ModuleNotFoundError); using fallback.
- SAM spotlight skipped: unstable IoU
- Word captions: no speech words available; keeping editorial text lines

Visual findings:

- Readable AI intro and fish/car outro; large head-only reactions from all four speakers.
- Stacked hitmarkers, rain, camera movement, glitch effects and varied joins are visible.
- Complete editorial phrases replace the prior 67 ms GG footer.
- Stock selection still includes death/spectator material and a generic Signal candidate caption.
- One spotlight is recorded as applied; two unstable-mask targets are rejected. The accepted target does not establish reliable enemy recognition.
- The large bottom-right head partly covers the end of a long lower caption in the compressed preview.

### valorant_mean_vertical

AI cards: 2; Gemini thumbnail candidates: 2; speakers: Iraj, Lance, Mario, Stefanny. SFX events: 15; music beat sync: True; transitions: varied. Explicit reactions selected: 0 (clean=false permits them but does not force selection).

Warnings recorded by the stock job (cumulative across rerenders):

- WebRTC VAD unavailable (ModuleNotFoundError); using fallback.
- SAM spotlight skipped: fragmented
- SAM spotlight skipped: unstable IoU
- Word captions: no speech words available; keeping editorial text lines

Visual findings:

- The two 0.4-second damage flashes are confined to the edges; centre gameplay remains gray and untinted.
- All four head-only speakers appear; cards preserve their landscape lettering with portrait letterboxing.
- The outro visibly contains a large fish, pink car, thanks text and EVEN THE FISH AIMED BETTER.
- NEXT TIME VFX overlaps the editorial caption around 4.5 seconds; this existing lower-area text collision remains.
- All three strict spotlight targets are rejected; no SAM spotlight is claimed for this cut.

### valorant_mean_vertical_reroll

AI cards: 2; Gemini thumbnail candidates: 2; speakers: Iraj, Lance, Mario, Stefanny. SFX events: 18; music beat sync: True; transitions: varied. Explicit reactions selected: 0 (clean=false permits them but does not force selection).

Warnings recorded by the stock job (cumulative across rerenders):

- WebRTC VAD unavailable (ModuleNotFoundError); using fallback.
- SAM spotlight skipped: fragmented
- SAM spotlight skipped: unstable IoU
- Word captions: no speech words available; keeping editorial text lines
- SAM spotlight skipped: viewmodel

Visual findings:

- The seed changes build/hit/after effects visibly while retaining source analysis and the cached cards.
- All four head-only speakers appear; complete editorial text and new AI thumbnail candidates are visible.
- The freeze box/arrow is procedural VFX, not successful SAM evidence.
- All three strict spotlight targets are rejected, including a viewmodel mask.

### deadlock_nice_landscape

AI cards: 1; Gemini thumbnail candidates: 2; speakers: Iraj, Lance, Mario, Stefanny. SFX events: 20; music beat sync: True; transitions: varied. Explicit reactions selected: 0 (clean=false permits them but does not force selection).

Warnings recorded by the stock job (cumulative across rerenders):

- WebRTC VAD unavailable (ModuleNotFoundError); using fallback.
- AI outro card unavailable (provider); using local fish/car card
- AI outro card unavailable; using cached local fish/car card
- SAM spotlight skipped: unstable IoU
- SAM spotlight skipped: fragmented
- Word captions: no speech words available; keeping editorial text lines

Visual findings:

- AI intro and two AI thumbnail candidates are present; the outro is the local fallback with visible cyan fish, pink car and THANKS FOR WATCHING, not an AI outro.
- All four speakers appear as large head-only overlays; stacked hitmarkers, glitch, bars, freeze/arrow and camera effects are visible.
- The large bottom-right head overlaps the end of a long lower caption in the compressed preview.
- Editorial phrases remain complete; isolated transcribed words such as Thanks and Reduce remain. Their speech accuracy was not independently established.
- All three spotlight targets are rejected (two unstable IoU, one fragmented); no SAM spotlight is claimed.

### deadlock_mean_vertical

AI cards: 1; Gemini thumbnail candidates: 2; speakers: Iraj, Lance, Mario, Stefanny. SFX events: 18; music beat sync: True; transitions: varied. Explicit reactions selected: 1 (clean=false permits them but does not force selection).

Warnings recorded by the stock job (cumulative across rerenders):

- WebRTC VAD unavailable (ModuleNotFoundError); using fallback.
- AI outro card unavailable (provider); using local fish/car card
- AI outro card unavailable; using cached local fish/car card
- SAM spotlight skipped: unstable IoU
- SAM spotlight skipped: fragmented
- Word captions: no speech words available; keeping editorial text lines
- SAM spotlight skipped: viewmodel
- Speech exceeds its safe gap; omitted to protect reactions.

Visual findings:

- The AI intro and local fish/car outro are cached from the nice cut and letterboxed; this cut does not have a new AI outro or mean-specific card art.
- All four large head-only speakers appear, including one explicit Lance reaction; the compressed preview keeps the full editorial phrase above the head.
- The mean preset retains highlight footage and positive hype wording from stock selection, so it is not a convincing lowlight/roast montage despite SKILL ISSUE thumbnails.
- One spotlight was accepted; two were rejected as fragmented and viewmodel. Acceptance does not establish correct enemy identity in these heavily distorted frames.
- Bold hitmarkers, glitch, speed lines and edge fire appear; isolated transcribed words remain, with speech accuracy not independently established.
- One narration line was omitted by the stock safe-gap rule to protect reactions.

## Earlier audit attempts

`304b524e6a514d8a992a9b14147e7c5b`: cancelled; full snapshot: [out/304b524e6a514d8a992a9b14147e7c5b-error.json](out/304b524e6a514d8a992a9b14147e7c5b-error.json).

- WebRTC VAD unavailable (ModuleNotFoundError); using fallback.
- Word captions: no speech words available; keeping editorial text lines
- SAM spotlight skipped: fragmented
- SAM spotlight skipped: unstable IoU

`6339fcefee5e4ab59e47aefc102e20d8`: cancelled; full snapshot: [out/6339fcefee5e4ab59e47aefc102e20d8-error.json](out/6339fcefee5e4ab59e47aefc102e20d8-error.json).

- WebRTC VAD unavailable (ModuleNotFoundError); using fallback.

`84d768268e6d4dc3a365ae0cb8cd2988`: error; full snapshot: [out/84d768268e6d4dc3a365ae0cb8cd2988-error.json](out/84d768268e6d4dc3a365ae0cb8cd2988-error.json).

- WebRTC VAD unavailable (ModuleNotFoundError); using fallback.
- AI outro card unavailable (provider); using local fish/car card


## Limits and attribution

Strict SAM rejection means no spotlight was composited for that target; procedural boxes/arrows are not SAM evidence. Editorial phrases are present where speech transcription yields no words. Missing WebRTC VAD uses the stock fallback. The generated music bed and synthesized narration remain stock behavior.

Deadlock Gameplay - Free To Use
https://www.youtube.com/watch?v=aXZYyd4SoWM
Channel: No Copyright Gameplay
License: Creative Commons Attribution (CC BY). Credit the channel when published.

Retain the Deadlock credit when publishing. Each Deadlock share folder includes posting_with_credit.txt and ATTRIBUTION.txt; its Discord copy carries the credit in container metadata. No media, weights or secrets are committed.
