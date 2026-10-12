---
id: DEMO-03
branch: ext/DEMO-03
allowed_paths: [demo_video/v3/**, docs/demo_v3.md]
---
# DEMO-03: Snappy, animated, narrated demo video

Owner: "make the demo video more snappy and cool, add animation and narration."
Build `demo_video/v3/`, a motion-graphics demo (Remotion with React/TS is preferred; the Village repo at `/c/Users/mourn/Downloads/hacklanta/apps/trailer`
has a working Remotion trailer setup you can copy patterns from; or ffmpeg + generated animated title cards if faster).
**Style:** 60-90 s total, fast cuts (1-3 s beats), kinetic typography (words slamming in, masked reveals, counters ticking up for real numbers),
animated pipeline diagram (signals → Gemini window scoring → planner → render → share kit) with the actual stage numbers, punchy transitions
(whip pans, zoom punches, glitch on the "BRUH"), the montage footage playing inside device frames (16:9 monitor, 9:16 phone), a quick old-vs-new
split wipe, captions on every line, a strong end card ("LIM Studio · Make every play count" + repo URL github.com/irajmoradi/hacklanta_2026_LIM).
**Narration (updated by owner: use all 4 of our ElevenLabs voices):** write a tight, energetic script (about 150-200 words, plain language, no
hype clichés) as a **multi-voice** piece using the team's four cloned voices: **Iraj, Stefanny, Lance and Mario** (all four have voice consent and
allow_voice_by_friends = true in the prod DB, verified 2026-10-12). Split the explainer lines between them (each gets a few lines plus a short
reaction), optionally a stock narrator for connective tissue. Find their voice IDs by listing the account's voices (GET /v1/voices) and matching
names; do not use any other cloned voice. Use `ELEVENLABS_API_KEY` from /c/Users/mourn/Downloads/hacklanta/.env at runtime only, never written to
disk or logs. At most 10 synth calls, total under 2,500 characters; cache the mp3s (gitignored) and never regenerate in a loop. Never commit voice
audio. Duck music and game audio under narration; time cuts to the narration beats; caption every line with the speaker's name.
If `demo_video/v3/` already has work from an earlier attempt of this task, review it and continue from it.
**Gaussian-splat reaction overlays (owner request):** use the team reaction pack (LAM Gaussian-splat talking heads, voiced clips) as pop-in
reaction overlays on key montage moments in the demo (corner picture-in-picture with a quick scale/bounce-in, name tag, and the reaction's own audio),
featuring all 4 people. Runner 1 `/srv/packs/team/` has Iraj + Stefanny (8 clips each); Lance + Mario (same 8 labels) are being rendered now and
will be added to that folder and `pack.json` within ~20 minutes (re-read pack.json before the final render). Include at least one reaction per
person and one beat that shows the reaction feature itself (label + "Gaussian-splat talking head from one selfie").
**Footage:** on runner 1 (`tools/runner_ip`), `/srv/demo_out/demo01/` has montages, UI walkthrough and stats from the first demo; `/srv/demo_out/demo02/` will get
better montages and numbers from DEMO-02 (running now). Build with demo01 assets first; if `/srv/demo_out/demo02/montage_landscape.mp4` exists when
you are ready to render (check, wait up to 40 minutes in 5-minute checks), use demo02's montages and numbers instead. Real numbers only.
Render on the runner; outputs to `demo_video/v3/out/` (gitignored): `extension_demo_v3.mp4` (1080p) + `extension_demo_v3_discord.mp4` (under 20 MB) +
a contact sheet. Never commit footage, voices or renders. Write docs/demo_v3.md (script, how to re-render).
