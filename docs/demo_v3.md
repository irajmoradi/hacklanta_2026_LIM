# LIM Studio: Extension demo v3

An ffmpeg/Pillow/OpenCV motion-graphics trailer at 1920×1080, 30 fps. The
sequence uses voice-aligned kinetic type, masked reveals, whip cuts, zoom punches,
BRUH glitches, measured pipeline counters, monitor/phone frames, an earlier/new
edit wipe, UI evidence, and a repository end card. Beat lengths are 1–3 seconds.
Every spoken phrase has a burned-in speaker caption and an SRT entry.
The main script is 170 words, plus four short pack reactions.

## Script and voices

Playback order below preserves the existing synthesis cache. Four consented team
clones plus a stock narrator are used. All ten historical synthesis attempts are
already spent: 1,148 characters total. This continuation makes no paid calls.
The original cache blocks 3 and 6 were replaced by Lance and Mario (8 and 9).
Do not remove the ledger or regenerate audio to refresh a render.

1. **Narrator:** You remember the play. Finding it in a whole match? That's the slow
   part. LIM Studio turns gameplay into a cut you can actually share.
2. **Iraj:** Keep the clutch. Keep the chaos. And yes, keep the moment I absolutely
   should have hit that shot.
   **Iraj reaction:** That was so clutch!
3. **Narrator:** Start with signals: motion, sound, and scene changes. Gemini scores
   candidate windows. The planner builds a sequence, then the renderer puts it together.
4. **Lance:** These are measured stages from a real run. Check the picks. Trim the
   edges. Put the best moment first. Yep, that one.
   **Lance reaction:** Let's go!
5. **Stefanny:** That one stays. This one? Bruh. Give me the nice cut, then show me the roast.
   **Stefanny reaction:** Bruh.
6. **Narrator:** The same match, a different edit. Watch it wide, or take it vertical.
   The share kit brings covers and posting copy along with the export.
7. **Mario:** Less scrubbing. More watching. Keep the cover and posting copy with
   the export. Wait, run that back. That's the part I want to share.
   **Mario reaction:** I can't stop laughing!
8. **Narrator:** Your highlights. Your questionable decisions. One place to shape
   the story. LIM Studio. Make every play count.

Reaction wording is read from the delivered pack, which is authoritative. Each
reaction gets an isolated pause after narration, its original audio, a bouncing
corner picture-in-picture, a name tag and a caption. The feature label reads
“Gaussian-splat talking head from one selfie.” No additional synthesis is needed.
Both game audio and an original synthesized beat bed are sidechain-ducked by
narration **and** reactions, then peak-limited.

## Inputs and provenance

- Narration: `demo_video/v3/cache/voice_0..9.mp3`, matching alignment JSON and
  `synthesis_ledger.json`. These ignored files must be retained privately.
- Footage/evidence: `/srv/demo_out/demo02/`, with `/srv/demo_out/demo01/` as the
  earlier-cut comparison and fallback share-kit UI. Selection checks every five
  minutes for up to forty minutes. Available DEMO-02 landscape and portrait exports
  take priority. A missing DEMO-02 roast export falls back to the visibly labeled
  DEMO-01 roast; the manifest identifies every actual input.
- Team pack: `/srv/packs/team/pack.json` and its MP4s. Every render re-reads it and
  requires Iraj/clutch, Lance/hype, Stefanny/bruh and Mario/funny, with audio.
  Missing people stop the render rather than being impersonated or omitted.
- Stage values come from `analysis.json` and `landscape.json`: signals,
  window scoring, edit plan, render, social. Missing values fail loudly.
  Candidate and assessment counts are derived from the corresponding arrays.
  Render and share-kit measurements can overlap; they are not summed as latency.

The ignored `out/manifest.json` records timings, source paths, captions, beat
boundaries, reaction placement and synthesis accounting. `verification.json`
records final dimensions, sizes, duration and SHA-256 hashes.

## Re-render on runner 1

From this worktree root in Git Bash:

```bash
tools/remote_run.sh "pip install -q -r demo_video/v3/requirements.txt && python -m pytest -q demo_video/v3/test_v3.py"
tools/remote_run.sh "python demo_video/v3/render.py --preview"
tools/remote_run.sh "python -u demo_video/v3/render.py && python demo_video/v3/verify.py"
python demo_video/v3/runner.py collect
```

On Windows PowerShell, use `python demo_video/v3/runner.py sync "<command>"`;
this invokes the same required `tools/remote_run.sh`. The `ssh` mode runs a command
in the existing remote checkout without syncing. Use it after rendering to avoid
`remote_run.sh`'s `rsync --delete` removing remote ignored outputs that are not
present locally. Collect outputs before any later sync.

`--source /srv/demo_out/demo02` selects an explicit source; `--pack` selects an
alternate complete pack. `--preview` generates the contact sheet and four full-size
reaction stills without encoding. Rendering itself has no API access.
The CLI waits up to forty minutes for all four reaction clips, checking every
minute; `--wait-pack-minutes 0` makes missing inputs fail immediately.

For a genuinely new authorized task with a fresh synthesis budget, the separate
`narration.py --list` command lists only matching consented voices and the stock
narrator; `--live-synthesize` is an explicit paid opt-in. It reads the account key
from the environment or the supplied `.env` path into memory only, refuses ambiguous
names, caches results, reserves failed attempts and prevents concurrent spending.
Do not invoke synthesis again for DEMO-03.

## Deliverables and validation

Ignored outputs under `demo_video/v3/out/`:

- `extension_demo_v3.mp4`: H.264/AAC, 1080p.
- `extension_demo_v3_discord.mp4`: H.264/AAC, 720p, two-pass budget under 20 MB decimal.
- `contact_sheet.jpg`, `reaction_*.jpg`, `captions.srt`, manifest and verification JSON.

Tests generate synthetic `testsrc2` video and sine audio; network synthesis is
mocked. They cover consent selection, budget and cache safety, complete captions,
measured evidence, five-minute source checks, synthetic frame rendering, reaction
placement and audio mixing. Verification fully decodes both final MP4s and checks
runtime, dimensions, codecs, captions, all four speakers and reactions, beat
continuity and Discord size. Visual inspection of the actual contact sheet and
reaction stills is also required after rendering.

## Recorded run

DEMO-02 evidence read on 2026-10-12: 83 candidate windows, 40 Gemini
assessments. Measured seconds: signals **515.5394**, Gemini window scoring
**223.1471**, planner **0.019**, render **194.87**, share kit **4.1352**.
The counters display rounded values; the manifest preserves source precision.
The 0.019-second planner measurement describes this recorded run, not an AI API
latency claim. The older DEMO-01 cut and share-kit UI remain explicitly identified
as source media in the manifest.
