"""Synthetic jobs only: no paid inference, media, or optional ML dependencies."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone

from flask import Flask, request
import pytest

from stats import VoteConflict, VoteStore, aggregate_players, create_blueprint, normalize_jobs, week_start


def job(job_id="j1", player="alice", when="2026-10-12T12:00:00Z"):
    return {"id": job_id, "player_id": player, "created_at": when,
            "meta": {"duration": 1800}, "game_profile": {"name": "valorant"},
            "agent": "Jett", "clips": [{"start_seconds": 10, "end_seconds": 20,
                                         "type": "good", "description": "play"}],
            "candidates": [{"start": 10, "end": 20, "score": 80, "events": [
                {"time": 11, "type": "kill", "killer": "alice", "victim": "bob", "text": "A > B"},
                {"time": 15, "type": "kill", "player_id": "alice"},
                {"time": 19, "type": "kill", "pov": True},
                {"time": 21, "type": "kill", "killer": "bob", "victim": "alice"},
                {"time": 30, "type": "kill", "player_id": "bob"},
                {"time": 40, "type": "kill", "text": "unattributed"}]}],
            "window_scores": [{"start": 10, "end": 20, "hype": 9, "kind": "highlight", "caption": "clutch"},
                              {"start": 100, "end": 110, "hype": 7, "kind": "lowlight", "reaction": "roast"}]}


def test_stats_deduplication_rates_and_rankings():
    first = job()
    first["ocr_events"] = deepcopy(first["candidates"][0]["events"])
    first["window_scores"][0]["events"] = deepcopy(first["ocr_events"])
    original = deepcopy(first)
    result = aggregate_players([first, first])[0]
    assert first == original
    assert result["jobs"] == 1
    assert (result["kills"], result["deaths"]) == (3, 1)
    assert (result["kills_per_hour"], result["deaths_per_hour"]) == (6, 2)
    assert result["multikill_counts"] == {"3": 1}
    assert result["most_common_character"] == {"game": "valorant", "character": "Jett", "jobs": 1}
    assert len(result["best_plays"]) == len(result["roast_worthy_fails"]) == 1
    assert result["best_plays"][0]["hype"] == 9
    assert result["best_plays"][0]["description"] == "clutch"


def test_time_buckets_players_and_character_frequency():
    older = job("old", when="2026-10-11T23:59:59Z")
    older["hero"] = "Sage"
    del older["agent"]
    second = job("second")
    second["champion"] = "Sage"
    del second["agent"]
    other = job("other", "bob")
    result = aggregate_players([job(), older, second, other])
    assert [p["player_id"] for p in result] == ["alice", "bob"]
    assert result[0]["jobs"] == 3
    assert [w["week"] for w in result[0]["weeks"]] == ["2026-10-05", "2026-10-12"]
    assert result[0]["most_common_character"]["character"] == "Sage"
    assert aggregate_players([job(), older], "2026-10-05")[0]["jobs"] == 1
    assert week_start("2026-10-12T00:30:00+02:00") == "2026-10-05"
    assert week_start("2027-01-01") == "2026-12-28"
    assert week_start(0) == "1969-12-29"


@pytest.mark.parametrize("update", [
    {"player_id": None}, {"clips": None}, {"created_at": "bad"},
    {"meta": {"duration": 0}}, {"meta": {"duration": float("nan")}},
    {"meta": {"duration": float("inf")}}, {"id": ""},
])
def test_invalid_jobs_are_skipped(update):
    record = job()
    record.update(update)
    assert aggregate_players([None, record]) == []


def test_missing_signals_and_unknown_characters():
    record = {"id": "j", "player_id": "p", "created_at": 0, "duration": 10,
              "clips": [], "candidates": None, "window_scores": None}
    result = aggregate_players([record])[0]
    assert result["kills"] == result["deaths"] == result["multikills"] == 0
    assert result["most_common_character"] is None
    assert result["best_plays"] == result["roast_worthy_fails"] == []


def test_event_bounds_attribution_and_multikill_chain_breaks():
    record = job()
    record["candidates"] = []
    record["ocr_events"] = [
        {"type": "kill", "time": t, "pov": True} for t in (0, 5, 11, 12, 14, 25, 30, -1, 1800, float("nan"))]
    record["ocr_events"] += [
        {"type": "death", "time": 13, "pov": True},
        {"type": "kill", "time": 31, "pov": True, "player_id": "bob"},
        {"type": "kill", "time": 32, "pov": True, "region": "banner"},
        {"type": "kill", "time": 33},
    ]
    result = aggregate_players([record])[0]
    assert result["kills"] == 7
    assert result["deaths"] == 1
    assert result["multikill_counts"] == {"2": 3}


def test_event_ids_and_clip_ids_are_stable():
    record = job()
    record["ocr_events"] = [{"id": "e", "type": "kill", "time": t, "pov": True} for t in (50, 51)]
    record["candidates"] = []
    initial = normalize_jobs([record])[0]
    record["clips"].reverse()
    record["window_scores"].reverse()
    assert normalize_jobs([record])[0] == initial
    assert len(initial["events"]) == 1


def test_invalid_clips_and_uncalibrated_scores():
    record = job()
    record["window_scores"] = []
    record["clips"] += [{"start": -1, "end": 2}, {"start": 2, "end": 1900},
                        {"start": 3, "end": 3}, {"start": float("nan"), "end": 6}]
    result = aggregate_players([record])[0]
    assert len(result["best_plays"]) == 1
    assert result["best_plays"][0]["hype"] is None


@pytest.fixture
def api(tmp_path):
    store = VoteStore(tmp_path / "votes.sqlite3")
    jobs = [job(), job("other", "bob")]
    jobs[1]["window_scores"][0]["hype"] = 10
    instant = [datetime(2026, 10, 12, 12, tzinfo=timezone.utc)]
    app = Flask(__name__)
    app.config["TESTING"] = True
    # Header identity is a TEST fixture only, not production authentication.
    app.register_blueprint(create_blueprint(store, lambda: jobs, lambda: request.headers.get("Test-User"),
                                           clock=lambda: instant[0]))
    client = app.test_client()
    client.environ_base["HTTP_TEST_USER"] = "friend"
    return client, jobs, instant, store


def test_endpoints_and_vote_tie_breaks(api):
    client, jobs, _, _ = api
    assert len(client.get("/api/stats/players").json["players"]) == 2
    assert client.get("/api/stats/players/alice").json["kills"] == 3
    assert client.get("/api/stats/players/nobody").status_code == 404
    board = client.get("/api/stats/clip-of-the-week").json
    assert board["winner"] is None
    high, low = board["clips"][:2]
    assert high["hype"] == 10
    url = "/api/stats/clip-of-the-week/vote"
    assert client.post(url, json={"clip_id": low["clip_id"]}).status_code == 201
    assert client.post(url, json={"clip_id": low["clip_id"]}).status_code == 200
    assert client.post(url, json={"clip_id": high["clip_id"]}).status_code == 409
    assert client.get("/api/stats/clip-of-the-week").json["winner"]["clip_id"] == low["clip_id"]
    assert client.post(url, json={"clip_id": high["clip_id"]}, headers={"Test-User": "other"}).status_code == 201
    assert client.get("/api/stats/clip-of-the-week").json["winner"]["clip_id"] == high["clip_id"]


def test_auth_validation_and_visibility(api):
    client, _, _, _ = api
    assert client.get("/api/stats/players", headers={"Test-User": ""}).status_code == 401
    assert client.post("/api/stats/clip-of-the-week/vote", json={}, headers={"Test-User": ""}).status_code == 401
    for week in ("2026-10-13", "nope", "2026-10-12T00:00:00", "2026-02-30"):
        response = client.get("/api/stats/players", query_string={"week": week})
        assert response.status_code == 400
        assert response.is_json
    assert client.get("/api/stats/players?week=2026-10-05").json == {"players": []}
    url = "/api/stats/clip-of-the-week/vote"
    for payload in ([], None, {}, {"clip_id": 1}, {"clip_id": "x", "user_id": "spoof"}):
        assert client.post(url, json=payload).status_code == 400
    assert client.post(url, data="{", content_type="application/json").status_code == 400
    assert client.post(url, json={"clip_id": "not-visible"}).status_code == 404
    assert client.post(url + "?week=2026-10-05", json={"clip_id": "x"}).status_code == 400


def test_week_rollover_and_historical_votes(api):
    client, jobs, instant, _ = api
    clip = client.get("/api/stats/clip-of-the-week").json["clips"][0]["clip_id"]
    url = "/api/stats/clip-of-the-week/vote"
    assert client.post(url, json={"clip_id": clip}).status_code == 201
    instant[0] = datetime(2026, 10, 19, tzinfo=timezone.utc)
    assert client.post(url, json={"clip_id": clip}).status_code == 404
    assert client.get("/api/stats/clip-of-the-week").json["winner"] is None
    assert client.get("/api/stats/clip-of-the-week?week=2026-10-12").json["winner"]["votes"] == 1
    jobs.append(job("next", when="2026-10-19T00:00:00Z"))
    next_clip = client.get("/api/stats/clip-of-the-week").json["clips"][0]["clip_id"]
    assert client.post(url, json={"clip_id": next_clip}).status_code == 201


def test_sqlite_concurrent_votes_persistence_and_groups(tmp_path):
    path = tmp_path / "votes.sqlite3"
    store = VoteStore(path)

    def cast(i):
        try:
            return store.vote("friends", "2026-10-12", "user", str(i), "now")
        except VoteConflict:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(cast, range(16)))
    assert sum(outcomes) == 1
    reopened = VoteStore(path)
    assert sum(reopened.counts("friends", "2026-10-12").values()) == 1
    assert reopened.vote("other-group", "2026-10-12", "user", "clip", "now")
    assert reopened.vote("friends", "2026-10-19", "user", "clip", "now")


def test_final_tie_is_deterministic(api):
    client, jobs, _, _ = api
    jobs[1]["window_scores"][0]["hype"] = 9
    clips = client.get("/api/stats/clip-of-the-week").json["clips"][:2]
    for user, clip in enumerate(clips):
        assert client.post("/api/stats/clip-of-the-week/vote", json={"clip_id": clip["clip_id"]},
                           headers={"Test-User": str(user)}).status_code == 201
    winner = client.get("/api/stats/clip-of-the-week").json["winner"]
    assert winner["clip_id"] == min(c["clip_id"] for c in clips)
