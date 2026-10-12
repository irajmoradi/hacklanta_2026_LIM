# Player stats and friends' clip of the week (EXT-26)

`full_app/stats/` provides pure aggregation, a persistent SQLite vote store, and
an opt-in Flask blueprint. It does not call Gemini, load ML models, change the
pipeline, or register itself in the server. Registration and identity enrichment
are the integrator's responsibility because those files are outside EXT-26 scope.

## Register and try

Run from `full_app`, using a writable persistent database path whose parent exists:

```python
from pathlib import Path
from flask import g
from stats import VoteStore, create_blueprint

# app is the existing Flask app. These two application-specific functions must
# come from the authentication/group layer:
# authenticated_member(group_id): trusted member ID, or None
# jobs_for_group(group_id): iterable of authorized, player-enriched job snapshots
group_id = "my-friends"
votes = VoteStore(Path(app.config["WORKSPACE"]) / "stats.sqlite3")
app.register_blueprint(create_blueprint(
    votes,
    get_jobs=lambda: jobs_for_group(group_id),
    get_user=lambda: authenticated_member(group_id),
    group_id=group_id,
))
```

Both callbacks run inside the Flask request context. All routes require a
nonempty authenticated member ID. `get_jobs` must return only jobs visible to
that group; use the same full group-visible set for all members so rankings agree.
Do not use request JSON or an unverified header as user identity. The host must
apply its normal CSRF protection if authentication uses cookies. The default
blueprint name and prefix support one board per app; a separate app instance or
Flask registration name/prefix override is needed for additional boards.

For a local, synthetic-only demonstration (no server or auth setup):

```python
from stats import aggregate_players

print(aggregate_players([{
    "id": "demo", "player_id": "alice", "created_at": "2026-10-12T12:00:00Z",
    "meta": {"duration": 1800}, "game_profile": "valorant", "agent": "Jett",
    "clips": [{"start_seconds": 10, "end_seconds": 20, "type": "good"}],
    "ocr_events": [
        {"time": 11, "type": "kill", "player_id": "alice", "region": "kill_feed"},
        {"time": 14, "type": "kill", "player_id": "alice", "region": "kill_feed"},
    ],
    "window_scores": [{"start": 10, "end": 20, "hype": 9,
                       "kind": "highlight", "caption": "Double kill"}],
}]))
# Two kills, four kills/hour, one double-kill chain, one ranked play.
```

## Input contract and deliberate choices

Pass decoded job dictionaries (for example, adapted `JobStore.all()` records).
The adapter must supply a stable `player_id` for the recording's POV owner.
Unattributed jobs are skipped, rather than combined under an invented player.

| Field | Meaning |
| --- | --- |
| `id`, `player_id` | Nonempty strings. Duplicate job IDs use the last supplied snapshot. |
| `clips` or `completed` | A clips list (including empty), or `"analyze"` in completed, marks an analyzed snapshot. |
| `meta.duration` | Positive finite recording seconds; `duration` is an alternate field. |
| `recorded_at` / `created_at` | Recording time, falling back to job creation. Epoch seconds or ISO timestamp; naive ISO means UTC. Invalid/missing dates are skipped. |
| `game_profile` | Profile name string or object with `name`; also accepted from `options.game_profile`. Defaults to `unknown`. |
| `character`, `agent`, `hero`, `champion` | Explicit detected POV character, first nonempty field wins. Missing values stay unknown. No roster/text guessing. |
| `ocr_events` | Optional structured OCR events for the whole recording. |
| `candidates[].events`, `window_scores[].events` | Existing detector/scorer events, combined with top-level OCR events. |
| `candidates`, `clips`, `window_scores` | Potential plays. Invalid ranges are skipped. |

Events use the existing `time`/`type` schema (`kill` or `death`) and must lie in
`[0, duration)`. Only `region: "kill_feed"` is counted; omitted region means
kill feed for enriched events. Attribution follows these rules:

1. Explicit `player_id` identifies the subject of the event's `type`.
2. Otherwise, structured `killer`/`victim` IDs determine the POV player's role:
   a feed entry with the POV as victim is a death, even if its type is `kill`.
   A self-kill counts as a death.
3. Otherwise, `pov: true` explicitly asserts that the event belongs to the owner.
   Other players and unattributed text-only events are excluded.

The current detector emits unassigned OCR text. The integrator must add trusted
actor attribution or `pov` after confirming an event's subject; simply displaying
a feed entry on the owner's screen does not establish ownership. Text descriptions
and VLM highlight labels never manufacture kills or deaths.

Events duplicated across overlapping windows are counted once per job, using
an explicit event `id`, or an exact tuple of type, timestamp, normalized text,
killer and victim. Upstream OCR is responsible for cooldown/deduplication of
persistent feed entries at different timestamps when IDs are absent. Each event
counts as one kill/death; a text banner saying “triple kill” is not three events.

## Stats semantics

`aggregate_players(jobs, week=None)` returns players sorted by ID. Each has
all-time totals (or totals for the selected week), plus ascending `weeks` buckets.
Weeks begin Monday at 00:00 UTC, including across calendar-year boundaries.
The entire recording belongs to its recording-start week; recordings are not
split at midnight. Reuploaded footage under different job IDs is distinct.

Results include `jobs`, `duration_seconds`, `kills`, `deaths`, `kills_per_hour`,
`deaths_per_hour`, `multikills`, `multikill_counts`, `character_usage`,
`most_common_character`, `best_plays`, and `roast_worthy_fails`. Rates divide
observed attributed feed events by total included recording hours, not by clip
duration. They are OCR-derived estimates, not authoritative game telemetry:
missing/unattributed OCR yields zero observed events, not proof of zero actual
kills. Partial candidate-only coverage can undercount. No K/D ratio is inferred.

Multikills are maximal chains of at least two attributed kills separated by
at most five seconds. Deaths break a chain; chains never cross jobs. Counts are
keyed by chain size (`{"2": 3, "4": 1}`); a four-kill chain contributes once,
not additional doubles/triples. This fixed heuristic is game-independent.

Character frequency counts one observation per analyzed job, grouped by game and
character. Ties use alphabetical game/character order; unknowns do not compete.

Plays with identical start/end ranges are merged, preferring scored windows over
clips over candidates. `start_seconds`/`end_seconds` clip aliases are supported.
Each gets a stable SHA-256 ID from job ID and numeric range. Distinct overlapping
ranges remain distinct nominations. Hype must be finite and between 0 and 10;
otherwise it is `null`. Raw detector z-scores are not treated as hype.
Ranked lists order by descending hype (unknown last), then clip ID.

Lowlight kind, bad clip type, or reactions `fail`, `roast`, `bruh` mark a fail.
Best plays exclude fails; each stats list returns at most ten items. Weekly
nominations include all valid plays, including fails, so friends can vote for
a funny fail. Descriptions are existing captions/descriptions (up to 500 chars),
not generated insults. Responses whitelist clip metadata and never return source
paths, job secrets, raw OCR text, or voter identities.

## JSON endpoints

Prefix: `/api/stats`. `week`, when accepted, must be a Monday date `YYYY-MM-DD`.

| Method/path | Result |
| --- | --- |
| `GET /players[?week=2026-10-12]` | `{"players": [...]}`; omitted week means all time. |
| `GET /players/<player_id>[?week=2026-10-12]` | One stats object; 404 if absent from visible analyzed jobs. |
| `GET /clip-of-the-week[?week=2026-10-12]` | `{week, clips, winner}`; omitted week means current UTC week. |
| `POST /clip-of-the-week/vote` | JSON `{"clip_id": "<ID from nominations>"}` only. Server selects the current week and trusted user. |

Votes return `{week, clip_id, created}`: 201 for a new vote, 200 for the same
vote retried, 409 if the member already voted for another clip. Malformed JSON,
extra fields, invalid weeks, and any vote query parameters return JSON 400.
Unknown, inaccessible, or non-current-week clip IDs return 404. Missing identity
returns JSON 401. There is no endpoint for changing, deleting, or backdating votes.

The SQLite primary key `(group_id, week, user_id)` guarantees one vote per member
per week **within a friend group**, including simultaneous requests and processes.
Use a persistent file, not `:memory:`; connections close after every transaction.
Retries are atomic and idempotent. Each group uses a server-configured namespace.
The same user may vote in different groups. No client-supplied group ID is used.

Weekly clips sort by vote count, then hype, then lexical clip ID for a final
deterministic tie. A board with no votes has `winner: null`, even if it has
nominations. Current-week winners are provisional. Historical boards use the
currently available job snapshots: votes persist, but deleted/invisible clips
are omitted, and editing scores can change tie-breaks. This task deliberately
does not create an immutable weekly archive or copy video files. A deleted clip's
vote still consumes that user's vote for the week.

## Verification

From the worktree root:

```bash
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_stats.py tests/test_jobs.py"
```

Stats tests use synthetic job data and temporary SQLite files, covering rates,
deduplication, attribution, rankings, character detection, UTC rollover, malformed
inputs, identity/visibility, idempotency, persistence, group isolation, concurrent
vote contention, and ties. Existing job tests exercise the upload/analyze/plan/render
lifecycle with mocked inference and ffmpeg-generated footage. No live Gemini calls
are needed. Runtime dependencies: existing Flask plus Python standard library.
