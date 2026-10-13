---
id: POLISH-1
branch: ext/POLISH-1
allowed_paths: [full_app/pipeline/**, full_app/planner/**, full_app/render/**, full_app/cards/**, full_app/fx/**, full_app/tests/**, demo_video/polish1/**, docs/pipeline.md, docs/cards.md, docs/rendering.md]
---
# POLISH-1: Fix what the final renders show

Review FINAL-2's outputs (`demo_video/final2/out/*/contact_*.jpg`, `job.json`, `planned.json` on `Extension`; masters on runner 1
`/srv/demo_out/final2/`). Fix these, each with a regression test:
1. **Internal label leaks on screen:** `pipeline/ranking.py:28` uses `'Signal candidate'` as the clip description, and it is rendered as a caption
   ("Signal candidate" under the NO SHOT pop in the Valorant landscape). Internal/default descriptions must never become on-screen text.
2. **Captions are dry model descriptions** ("Phoenix ults and aggressively pushes through the smoke to secure multiple kills.") rendered as
   two-line subtitles on every clip. Without speech, on-screen text should be short punchy editorial lines (≤ 5 words, e.g. "SMOKE PUSH",
   "1v3 INCOMING", "he did NOT see that") or nothing; never full descriptions. Keep descriptions in the share kit/chapters only.
3. **Text overlap:** caption text overlaps FX banners/arrows (NEXT TIME >>> over the caption in the mean vertical). Give each preset safe
   zones (word pops top/centre, banners mid band, captions lower third, reactions corner) and resolve collisions by shifting/omitting the
   lower-priority text. Test: no two text boxes overlap in any frame of a planned timeline.
4. **Vertical AI cards:** in 9:16 the AI intro/outro card is a small letterboxed 16:9 image. Generate/compose cards per preset aspect
   (request the right aspect from the image model if supported, else smart-crop/zoom-fill the 16:9 card with a blurred background fill)
   so the card fills the frame. Same for 1:1.
5. **Deadlock outro fell back** to the local fish card: read the recorded failure in FINAL-2 job warnings/errors and fix the cause if it is
   ours (prompt, aspect, safety, timeout, budget accounting); keep the visible fallback otherwise.
Then re-render **Valorant nice landscape 60 s + mean vertical 30 s** from FINAL-2's saved job state on runner 1 (reuse analysis/plans;
**at most 6 Gemini calls**, image calls for cards only; `GOOGLE_API_KEY` env-only from /c/Users/mourn/Downloads/hacklanta/.env, Vertex express)
into `/srv/demo_out/polish1/` + local `demo_video/polish1/out/` (gitignored), Discord copies < 20 MB, contact sheets. Inspect every
contact sheet for leaked labels, overlaps and letterboxing before reporting. Full suite green on the runner.
