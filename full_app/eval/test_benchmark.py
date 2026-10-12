"""Regression coverage for split isolation, media evidence, deterministic mocks and accounting."""
import copy
import json
from unittest.mock import patch

import pytest

from demo import make_demo_gameplay as demo
from . import benchmark as bench
from .benchmark_data import GAMES, schedule


def test_schedule_coverage_and_disjoint_seeds():
    for game in GAMES:
        a, b = schedule(731, 120, game), schedule(831, 120, game)
        assert a != b
        assert a == schedule(731, 120, game)
        assert sum(e["kind"] == "highlight" for e in a) == 4
        assert {e["kind"] for e in a} == {"highlight", "death", "spectating", "distractor"}
        assert all(0 <= e["start"] < e["end"] <= 120 for e in a)
        assert all(x["end"] < y["start"] for x, y in zip(a, a[1:]))


def test_noise_control():
    assert bench.noise("v", 2, "score", 7, .3) == bench.noise("v", 2, "score", 7, .3)
    assert bench.noise("v", 2, "score", 7, 0) == 0
    assert bench.noise("v", 2, "score", 7, .3) != bench.noise("v", 2, "score", 8, .3)
    assert abs(bench.noise("v", 2, "score", 7, .3)) <= .3


def test_real_media_mock_and_audio_chat(tmp_path):
    events = [dict(id="a", start=3, end=7, text="ACE", kind="highlight", color="lime", score=0),
              dict(id="b", start=10, end=14, text="SPECTATING", kind="spectating", color="cyan", score=0)]
    with patch.object(demo, "events_for", return_value=events):
        video, _ = demo.generate(tmp_path, duration=20, width=320, height=180, fps=5)
    (tmp_path / "chat.json").write_text(json.dumps([dict(time_in_seconds=4, message="Pog clip it")]))
    observations = bench.mock_observations(video)
    assert [r["kind"] for r in observations] == ["highlight", "spectating"]
    assert observations[0]["start"] == pytest.approx(3, abs=.5)
    # Delete the renderer's truth: prediction must use media/chat only.
    (tmp_path / "ground_truth.json").unlink()
    features = bench.prepare(dict(id="sample", path=video, duration_seconds=20))
    assert features["rows"]
    assert max(r["chat"] for r in features["rows"]) > 0
    assert set(features["timings"]) == {"signals", "vlm", "audio", "chat"}
    assert all(t >= 0 for t in features["timings"].values())
    assert features["audio_backends"]["events"] == "heuristic"
    assert features["whole"] == bench.prepare(dict(id="sample", path=video, duration_seconds=20))["whole"]


def fixture_features():
    return dict(rows=[dict(start=2, end=6, signals=.7, vlm=.8, audio=.6, chat=.8, dead=0),
                      dict(start=10, end=14, signals=.9, vlm=.6, audio=.8, chat=.8, dead=1)],
                whole=[dict(start=2, end=6, score=.8)], timings=dict(signals=1, vlm=2, audio=3, chat=4))


def test_tune_training_only_and_veto():
    training = [dict(id="train", duration_seconds=20, path="unused", highlights=[dict(start=2, end=6)])]
    features = {"train": fixture_features(), "test": fixture_features()}
    result = bench.tune(training, features)
    features["test"] = {"malformed": "would fail if held-out features were accessed"}
    assert bench.tune(training, features) == result
    weights = result[0]["fusion-audio-chat"]
    assert len(bench.predict(features["train"], "fusion-audio-chat", weights)) == 1


def test_report_cost_death_and_frozen_weights(tmp_path, monkeypatch):
    records = []
    for i in range(6):
        path = tmp_path / f"{i}.mp4"
        path.touch()
        records.append(dict(id=str(i), path=path.name, duration_seconds=120,
                            split="train" if i < 3 else "test", highlights=[dict(start=2, end=6)],
                            forbidden=[dict(start=10, end=14, kind="spectating")]))
    manifest = tmp_path / "labels.json"
    manifest.write_text(json.dumps(dict(version=1, videos=records)))
    monkeypatch.setattr(bench, "prepare", lambda *args: copy.deepcopy(fixture_features()))
    report = bench.run(manifest, tmp_path / "out")
    assert set(report["train_ids"]).isdisjoint(report["test_ids"])
    signals = report["pipelines"]["signals-only"]["summary"]
    assert signals["forbidden_picks"] == signals["spectating_picks"] == 3
    assert signals["death_picks"] == 0
    assert signals["seconds_per_footage_minute"] >= .5
    assert signals["estimated_api_usd_per_minute"] == 0
    whole = report["pipelines"]["vlm-only"]["videos"][0]
    assert whole["estimated_api_usd"] == pytest.approx((12200 * .3 + 100 * 2.5) / 1e6)
    assert whole["cost_usd"] == 0
    weights = tmp_path / "out" / "tuned_weights.json"
    assert bench.load_weights(weights) == report["weights"]
    monkeypatch.setattr(bench, "tune", lambda *args: pytest.fail("Frozen run must not tune"))
    frozen = bench.run(manifest, tmp_path / "frozen", weights_path=weights)
    assert frozen["weights"] == report["weights"]
    assert frozen["pipelines"]["vlm-only"]["summary"]["mAP"] == 1


@pytest.mark.parametrize("value", [-1, float("nan"), True])
def test_bad_weights(tmp_path, value):
    w = dict(signals=.4, vlm=.6, audio=0, chat=0, death_penalty=.5, threshold=value)
    path = tmp_path / "weights.json"
    path.write_text(json.dumps({"signals-vlm": w, "fusion-audio-chat": w}))
    with pytest.raises(ValueError):
        bench.load_weights(path)
