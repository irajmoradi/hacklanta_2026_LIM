# EXT-15: VOD ingestion

`full_app/ingest/` is an opt-in Python library and CLI for preparing gameplay
before analysis. It does not change the existing Flask upload/analyze/plan/render
flow. Integration into routes is outside EXT-15's allowed paths. No Gemini calls,
credentials, or ML models are involved.

## Local files

Requires Python 3.10+ and `ffmpeg`/`ffprobe` on PATH, with H.264 (`libx264`) and AAC
encoding support. No additional Python dependency is needed for local video or
offline chat.

From `full_app/`:

```python
from ingest import prepare, Limits

video = prepare(
    "/path/to/gameplay.mp4",
    proxy_height=480,                 # 480 or 720, no upscaling
    chunk_seconds=900,                # 15-minute windows
    overlap_seconds=15,
    limits=Limits(max_bytes=20 * 1024**3, max_duration=12 * 3600),
    progress=lambda event: print(event),
)
print(video.to_dict())
```

```bash
python -m ingest /path/to/gameplay.mp4 --proxy-height 720 \
  --chunk-seconds 900 --overlap-seconds 15
```

The CLI prints result JSON on stdout and progress events on stderr. All paths in
the result are absolute. `PreparedVideo` contains:

| Field | Meaning |
| --- | --- |
| `path` | Normalized full-resolution MP4, H.264, even dimensions, 30 fps CFR, two-second GOP |
| `proxy` | H.264 MP4 analysis proxy, at most the requested height, 30 fps |
| `duration` | Prepared video stream duration in seconds (audio padding is excluded) |
| `fps` | `30.0` for prepared video and analysis chunks |
| `chunks` | `Chunk(path, start, end)` records, using global, half-open time ranges |
| `chat_signal` | Dense per-second signal records, or `None` when chat was not requested |

Audio, when present, becomes stereo AAC at 48 kHz with asynchronous resampling.
Silent videos remain silent. Only the primary non-cover-art video and first audio
track are retained. Subtitles and metadata are omitted. The input is never
modified. ffmpeg encoding uses two threads per job to limit CPU contention.

Size and duration limits apply to local inputs too, including cache hits. Container
duration is also checked, so a short video track cannot conceal overlong audio.
Invalid, empty, audio-only, or unprobeable inputs fail with `IngestError`.
An upload must finish writing before calling `prepare`; size/mtime checks detect
ordinary writes during hashing/normalization.

## Cache and chunks

Default cache: `full_app/workspace/ingest/` (already ignored by git). Override it
with `cache_dir=` or `--cache-dir`. A streaming SHA-256 hash identifies input
contents, independent of filename. A versioned directory holds normalization,
resolution-specific proxies, and chunk sets keyed by frame-aligned window/overlap.
Changing chunk settings reuses normalization and the proxy; changing proxy height
reuses normalization. Every call still reads the input to hash it and probes it.

Only completed staging directories are published. Per-content OS locks serialize
concurrent preparation and release on process exit; competing callers wait up to
one hour. Manifests check expected files and sizes; missing/truncated entries are
rebuilt. Same-size bit corruption is not detected. Do not edit cache files. Hard
process termination may leave unused staging directories; normal failures clean
them up. There is no automatic eviction: remove unused cache directories when
no readers or preparations are active. Allow disk space for the normalized video,
proxy, chunks, and transient download/encoding output.

Chunk boundaries are rounded to the nearest 30 fps frame. Overlap must be
nonnegative and smaller than a chunk after rounding. Windows cover the whole
video, with a shorter final window and no redundant overlap-only tail. A short
video uses the proxy directly as its only chunk. Longer chunks are independently
encoded from the proxy for accurate seeks (stream-copy cuts would drift to
keyframes). Each chunk starts at local timestamp zero:

```python
from concurrent.futures import ThreadPoolExecutor

# analyze_chunk is supplied by the caller/provider integration.
def analyze(chunk):
    findings = analyze_chunk(chunk.path)
    return [
        {**finding,
         "start": chunk.global_timestamp(finding["start"]),
         "end": chunk.global_timestamp(finding["end"])}
        for finding in findings
    ]

with ThreadPoolExecutor(max_workers=4) as pool:
    findings_by_chunk = list(pool.map(analyze, video.chunks))
```

`global_timestamp` validates that the local timestamp is within the chunk.
Merge/deduplicate findings in overlapping windows downstream. Preparation builds
chunks sequentially; analysis can run in parallel. Bounds are relative to the
prepared video, not wall-clock time or the original stream's absolute timestamps.

Progress callbacks receive dicts with `stage` (`probe`, `hash`, `normalize`,
`proxy`, `chunk`, `download`, `chat`, `complete`). Cacheable stages include
`cache_hit`; chunk work includes a zero-based `index` and `total`. Encoding events
are stage-level, not frame-level percentages. Download events include status and
byte counts. Callbacks run synchronously; exceptions abort preparation.

## Optional URL imports: only content you own or have rights to

Install the optional adapter explicitly:

```bash
python -m pip install yt-dlp
python -m ingest 'https://www.twitch.tv/videos/YOUR_VOD_ID' --owns-content
```

Python: `prepare(url, owns_content=True, limits=Limits(...), progress=callback)`.
Only HTTPS URLs on the supported Twitch/YouTube hosts are accepted. The flag
asserts ownership or permission; it does not establish those rights for you.
The adapter uses [yt-dlp's Python API](https://github.com/yt-dlp/yt-dlp#embedding-yt-dlp).
Single VODs/clips only: playlists, live/upcoming streams, and unknown durations
are rejected. Metadata limits are checked before media download, actual cumulative
download bytes are checked in progress hooks, and the completed file is probed
and size-checked before normalization. Hook enforcement can overshoot by a network
block/fragment; these limits are not an OS disk quota. Input limits do not cap
transcoded output size. Temporary downloads are removed after success or failure.

Imports use public access only; no credentials/cookies are read from disk. Site
restrictions, unavailable VODs, or missing optional dependencies produce errors.
Authenticated imports are not implemented. Repeated URLs are downloaded again
before content hashing; their resulting video/proxy caches are reused if bytes
match. This avoids treating mutable URLs as permanent content identities.

## Chat replay as an extra EXT-01 signal

```python
video = prepare("vod.mp4", chat_log="chat.json")
# For a source trimmed to start 120 seconds into a replay:
video = prepare("trimmed.mp4", chat_log="chat.json", chat_offset=-120)
```

Supported offline inputs: TwitchDownloader `{"comments": [...]}` exports with
`content_offset_seconds` and `message.body`/`message.fragments`, chat-downloader
arrays (or `{"messages": [...]}`) with `time_in_seconds` and string `message`,
or records with `offset` and `text`. Paths, parsed objects, and message iterables
are accepted. `.jsonl` paths stream one message object per line; conventional
JSON exports are loaded into memory. Prefer JSONL/iterables for very large logs.
Malformed JSON raises an error; invalid records and out-of-range offsets are
ignored. Gaps are filled with zeros. Offsets are relative seconds, not Unix time.
No user identifiers or message text are included in the result.

Each record has the EXT-01-compatible numeric `signals{...}` mapping:

```json
{
  "start": 12.0,
  "end": 13.0,
  "signals": {
    "chat_activity": 8,
    "chat_emotes": 5,
    "chat_emote_spike": 2.4,
    "chat_clip_it": 2
  }
}
```

`chat_activity` counts messages; `chat_emotes` counts case-insensitive whole-word
occurrences of PogChamp/Pog/PogU/Poggers, LUL/LULW, KEKW, OMEGALUL, PepeLaugh,
Kappa, and monkaS. `chat_emote_spike` is the positive population z-score of emote
counts across this video's second bins (zero for constant counts).
`chat_clip_it` counts messages mentioning "clip it", "clip that", "clip this",
or their no-space forms. Multiple emotes count independently; a clip request
counts at most once per message. Custom emote IDs without text are not resolved.
The final bin can be shorter than a second. These are counts, not calibrated
highlight probabilities.

EXT-01's implementation is not present on this task branch. Consumers should
align these global one-second bins with their interest curve, z-score/weight raw
counts during fusion, and aggregate relevant bins into `Candidate.signals`.
This library does not directly modify `signals/` or rank candidate moments.

For an optional network replay lookup:

```bash
python -m pip install chat-downloader
python -m ingest vod.mp4 --twitch-vod-id 123456789
```

The adapter streams messages with
[ChatDownloader](https://chat-downloader.readthedocs.io/en/latest/source/chat_downloader.html)
and closes its session after aggregation. `chat_log` takes precedence if both
inputs are provided, allowing offline replay even when a VOD ID is known. Replay
availability depends on Twitch and the installed adapter; archived chat may be
unavailable. Missing `chat-downloader` gives an actionable error; callers can
provide JSON instead. Chat is optional and never fetched implicitly from a video
URL. A chat failure leaves prepared video cached for a retry without chat.

## Validation

From the worktree root:

```bash
tools/remote_run.sh "cd full_app && python -m pytest -q"
```

Tests generate tiny VFR/CFR, audible, and silent videos with ffmpeg. They check
frame intervals, GOPs, audio resampling, proxy dimensions, chunk offsets/coverage,
content cache reuse, concurrent writers, recovery, CLI JSON, chat bins/spikes,
mocked URL downloads, progress, and import limits. URL and replay adapters are
mocked; no paid API calls, remote media downloads, or copyrighted fixtures occur.
Multi-hour coverage is tested arithmetically, not with a multi-hour encode.
