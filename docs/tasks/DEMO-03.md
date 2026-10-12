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
**Narration:** write a tight, energetic script (about 150-200 words, plain language, no hype clichés) and synthesize it with ElevenLabs TTS using a
stock energetic narrator voice (env `ELEVENLABS_API_KEY` from /c/Users/mourn/Downloads/hacklanta/.env at runtime only, never written to disk; at most
3 synth calls, total under 2,500 characters; cache the mp3). Duck music and game audio under narration; time cuts to the narration beats.
**Footage:** on runner 1 (`tools/runner_ip`), `/srv/demo_out/demo01/` has montages, UI walkthrough and stats from the first demo; `/srv/demo_out/demo02/` will get
better montages and numbers from DEMO-02 (running now). Build with demo01 assets first; if `/srv/demo_out/demo02/montage_landscape.mp4` exists when
you are ready to render (check, wait up to 40 minutes in 5-minute checks), use demo02's montages and numbers instead. Real numbers only.
Render on the runner; outputs to `demo_video/v3/out/` (gitignored): `extension_demo_v3.mp4` (1080p) + `extension_demo_v3_discord.mp4` (under 20 MB) +
a contact sheet. Never commit footage, voices or renders. Write docs/demo_v3.md (script, how to re-render).
