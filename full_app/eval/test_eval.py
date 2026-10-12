import json
import subprocess
import sys
import types
from unittest.mock import Mock

import pytest

from .dataset import load_dataset
from .metrics import detection_metrics, interval, summarize, temporal_iou
from .pipelines import GeminiOnly, Unavailable, signals_only, signals_vlm
from .runner import evaluate, main
from .synthetic import generate


def clip(start=1, end=2, score=1):
    return {"start": start, "end": end, "score": score}


def video():
    return {"id": "v", "path": "unused.mp4", "duration_seconds": 6, "highlights": [clip()]}


def test_iou_and_threshold_boundary():
    assert temporal_iou(clip(0, 2), clip(1, 3)) == pytest.approx(1 / 3)
    assert temporal_iou(clip(0, 1), clip(1, 2)) == 0
    assert detection_metrics([clip(0, 2)], [clip(1, 3)], .3)["tp"] == 1
    assert detection_metrics([clip(0, 2)], [clip(1, 3)], .5)["tp"] == 0
    assert detection_metrics([clip(0, 2)], [clip(1, 2)], .5)["tp"] == 1


def test_duplicates_and_ranked_ap():
    predictions = [clip(4, 5, .9), clip(1, 2, .8), clip(1, 2, .7)]
    result = detection_metrics(predictions, [clip()], .5)
    assert result == {"tp": 1, "fp": 2, "fn": 0, "precision": 1 / 3,
                      "recall": 1, "f1": .5, "ap": .5}
    assert detection_metrics(list(reversed(predictions)), [clip()], .5) == result


def test_match_best_unmatched_and_interpolated_ap():
    result = detection_metrics([clip(0, 2, 3), clip(0, 3, 2)], [clip(0, 2), clip(2, 3)], .3)
    assert result["tp"] == 2
    result = detection_metrics([clip(4, 5, 3), clip(0, 1, 2), clip(2, 3, 1)],
                               [clip(0, 1), clip(2, 3)], .5)
    assert result["ap"] == pytest.approx(2 / 3)


@pytest.mark.parametrize("predictions,truth", [([], []), ([], [clip()]), ([clip()], [])])
def test_empty_cases(predictions, truth):
    result = detection_metrics(predictions, truth, .5)
    assert result["f1"] == result["ap"] == 0


@pytest.mark.parametrize("bad", [clip(-1, 2), clip(2, 2), clip(3, 2),
                                  clip(0, float("inf")), clip(score=float("nan"))])
def test_invalid_intervals(bad):
    with pytest.raises(ValueError):
        interval(bad)


def test_accounting_and_no_label_leakage():
    def predict(inputs):
        assert "highlights" not in inputs
        return {"clips": [clip()], "cost_usd": .02}
    ticks = iter([10, 12])
    report = evaluate([video()], {"p": predict}, clock=lambda: next(ticks))["pipelines"]["p"]
    assert report["summary"]["mAP"] == 1
    assert report["summary"]["cost_usd_per_minute"] == pytest.approx(.2)
    assert report["summary"]["mean_time_to_first_clip_seconds"] == 2
    row = report["videos"][0]
    row["cost_usd"] = None
    assert summarize([row])["cost_usd_per_minute"] is None


def test_negative_videos_affect_precision_but_not_map():
    negative = {**video(), "id": "negative", "highlights": []}
    summary = evaluate([video(), negative], {"p": lambda v: [clip()]})["pipelines"]["p"]["summary"]
    assert summary["mAP"] == 1
    assert summary["thresholds"]["0.5"]["precision"] == .5


def test_skip_error_and_no_clip_timing():
    def unavailable(v):
        raise Unavailable("not installed")
    def broken(v):
        raise RuntimeError("secret must not appear")
    result = evaluate([video()], {"skip": unavailable, "broken": broken, "empty": lambda v: []})
    assert result["pipelines"]["skip"]["status"] == "skipped"
    assert result["pipelines"]["broken"]["status"] == "error"
    assert "secret" not in json.dumps(result)
    assert result["pipelines"]["empty"]["summary"]["mean_time_to_first_clip_seconds"] is None


def test_gemini_mock_and_budget():
    client = Mock()
    client.find_clips.return_value = [clip()]
    adapter = GeminiOnly(client=client)
    for _ in range(3):
        assert adapter(video())["clips"] == [clip()]
    with pytest.raises(Unavailable, match="budget"):
        adapter(video())
    assert client.find_clips.call_count == 3
    with pytest.raises(Unavailable, match="disabled"):
        GeminiOnly()(video())


def test_optional_signal_and_vlm_hooks(monkeypatch):
    detector = Mock(return_value=[clip()])
    monkeypatch.setitem(sys.modules, "signals", types.SimpleNamespace(detect_candidates=detector))
    assert signals_only(video())["cost_usd"] == 0
    scorer = Mock(return_value={"clips": [clip()], "cost_usd": 0})
    assert signals_vlm(video(), scorer)["clips"] == [clip()]
    scorer.assert_called_once_with("unused.mp4", [clip()])
    monkeypatch.setitem(sys.modules, "signals", None)
    with pytest.raises(Unavailable):
        signals_only(video())


def test_synthetic_manifest_and_cli(tmp_path):
    manifest = generate(tmp_path)
    dataset = load_dataset(manifest)
    assert len(dataset) == 2
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "json", str(dataset[0]["path"])],
                           capture_output=True, text=True, check=True)
    assert float(json.loads(probe.stdout)["format"]["duration"]) == pytest.approx(6, abs=.2)
    output = tmp_path / "report.json"
    assert main([str(manifest), "--mock", "--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["mode"] == "mock"
    assert report["pipelines"]["gemini-only"]["summary"]["mAP"] == 1
    assert report["pipelines"]["signals-only"]["summary"]["thresholds"]["0.5"]["recall"] == .5
    data = json.loads(manifest.read_text())
    data["videos"].append(data["videos"][0])
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="unique"):
        load_dataset(manifest)


def test_replay_cli_errors_are_nonzero(tmp_path):
    manifest = generate(tmp_path)
    replay = tmp_path / "replay.json"
    replay.write_text(json.dumps({"gemini-only": {"bursts": {"clips": [clip(0, 10)]}}}))
    assert main([str(manifest), "--replay", str(replay), "--output", str(tmp_path / "report.json")]) == 1
