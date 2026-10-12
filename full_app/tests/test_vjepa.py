import builtins
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from vjepa import score, weak_labels
from vjepa.features import TinyEncoder, WindowConfig, decode, extract, windows
from vjepa.heads import Heads, match_split, metrics
from vjepa.inference import fusion_signals
from vjepa.labels import align_labels
from vjepa.train import train


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "synthetic.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=64x64:rate=8:duration=5.25", "-c:v", "mpeg4", str(path)], check=True)
    return path


def test_windowing_and_padding(video):
    cfg = WindowConfig(16, 8, 32, 1)
    assert windows(5.25, cfg) == [(0, 2), (1, 3), (2, 4), (3, 5), (4, 5.25)]
    assert windows(0.5, cfg) == [(0, 0.5)]
    frames = decode(video, 5, 5.25, cfg)
    assert frames.shape == (16, 32, 32, 3)
    np.testing.assert_array_equal(frames[-1], frames[-2])
    for bad in ({"frames": 15}, {"frames": 17}, {"fps": 0}, {"resolution": 31}, {"stride": 100}):
        with pytest.raises(ValueError):
            WindowConfig(**bad)
    with pytest.raises(ValueError):
        windows(float("nan"), cfg)


def test_cache_batching_and_invalidation(video, tmp_path):
    class Counting(TinyEncoder):
        calls = []
        def encode(self, videos):
            self.calls.append(len(videos))
            return super().encode(videos)
    encoder = Counting()
    cfg = WindowConfig(16, 8, 32, 1)
    cache = tmp_path / "cache"
    first = extract(video, encoder, cache, cfg, 2)
    assert encoder.calls == [2, 2, 1]
    second = extract(video, encoder, cache, cfg, 2)
    assert encoder.calls == [2, 2, 1]
    np.testing.assert_array_equal(first["features"], second["features"])
    next(cache.glob("*.npz")).write_bytes(b"broken")
    extract(video, encoder, cache, cfg, 2)
    assert encoder.calls[-1] == 1
    truncated = next(cache.glob("*.npz"))
    truncated.write_bytes(truncated.read_bytes()[:30])
    calls_before = len(encoder.calls)
    extract(video, encoder, cache, cfg, 2)
    assert len(encoder.calls) == calls_before + 1
    before = len(list(cache.glob("*.npz")))
    extract(video, TinyEncoder(seed=2), cache, cfg, 2)
    assert len(list(cache.glob("*.npz"))) == before * 2
    extract(video, encoder, cache, WindowConfig(16, 8, 48, 1), 2)
    assert len(list(cache.glob("*.npz"))) == before * 3
    # Same valid video with different bytes must not hit an old cache entry.
    with video.open("ab") as handle:
        handle.write(b"different-content")
    extract(video, encoder, cache, cfg, 2)
    assert len(list(cache.glob("*.npz"))) == before * 4


def test_labels_alignment_and_preferences():
    payload = {"candidates": [
        {"id": "a", "start": 0, "end": 4, "events": [{"type": "kill", "timestamp": 1}], "decision": "keep"},
        {"id": "b", "start": 4, "end": 6, "events": [{"kind": "death", "time": 4}], "decision": "drop"},
        {"id": "c", "start": 6, "end": 8, "events": []}],
        "preferences": [{"winner": "a", "loser": "b", "source": "gemini"}]}
    labels = weak_labels(json.dumps(payload))
    assert labels["preferences"] == [("a", "b")]
    assert [row["label"] for row in labels["windows"]] == ["kill", "death", "none"]
    assert align_labels([(0, 2), (2, 4), (4, 6), (6, 8), (8, 10), (7, 9)], labels) == [1, 0, 2, 0, -1, -1]
    payload["preferences"] = [{"winner": "missing", "loser": "b"}]
    with pytest.raises(ValueError):
        weak_labels(payload)
    assert weak_labels([{"start": 0, "end": 1, "events": ["kill", "death"]}])["windows"][0]["label"] == "death"


def test_heads_learn_save_load_and_metrics(tmp_path):
    rng = np.random.default_rng(4)
    x = np.concatenate([rng.normal(center, 0.1, (20, 2)) for center in (-2, 0, 2)])
    y = np.repeat([0, 1, 2], 20)
    head = Heads().fit(x, y, [(59, 0), (58, 1)], epochs=500)
    probabilities, ranking = head.predict(x)
    assert (probabilities.argmax(axis=1) == y).mean() > 0.95
    assert ranking[59] > ranking[0]
    report = metrics(y, probabilities)
    assert report["macro_f1"] > 0.95
    assert report["classes"]["kill"]["auroc"] > 0.95
    assert metrics([0, 0], np.ones((2, 3)) / 3)["classes"]["kill"]["auroc"] is None
    assert metrics([0, 1], np.ones((2, 3)) / 3)["classes"]["kill"]["auroc"] == 0.5
    path = tmp_path / "head.npz"
    head.save(path, {"game": "valorant"})
    restored, metadata = Heads.load(path)
    assert metadata["game"] == "valorant"
    np.testing.assert_allclose(restored.predict(x)[0], probabilities)
    np.testing.assert_allclose(restored.predict(x)[1], ranking)
    plain = Heads().fit(x, y)
    assert not plain.ranking_trained
    assert not plain.predict(x)[1].any()
    with pytest.raises(ValueError):
        head.predict(np.zeros((2, 3)))


def test_split_no_match_leakage():
    matches = ["a", "a", "b", "b", "c", "d"]
    training, validation = match_split(matches)
    assert not {matches[i] for i in training} & {matches[i] for i in validation}
    np.testing.assert_array_equal(match_split(matches)[0], training)
    with pytest.raises(ValueError):
        match_split(["a", "a"])


def test_training_and_signal_integration(video, tmp_path, monkeypatch):
    candidates = [
        {"id": "kill", "start": 0, "end": 2, "events": [{"type": "kill", "time": 0.5}], "decision": "keep"},
        {"id": "none", "start": 2, "end": 4, "events": [], "decision": "drop"},
        {"id": "death", "start": 4, "end": 5.25, "events": [{"type": "death", "time": 4.5}]}]
    # Reused fixture represents separate matches only for this wiring test.
    manifest = [{"game": "valorant", "match_id": f"match-{i}", "video": str(video), "candidates": candidates} for i in range(3)]
    encoder, cfg = TinyEncoder(), WindowConfig(16, 8, 32, 2)
    output, cache = tmp_path / "head.npz", tmp_path / "cache"
    report = train(manifest, output, encoder, cache, cfg, epochs=20)
    assert set(report["train_matches"]).isdisjoint(report["validation_matches"])
    assert report["train_pairs"] == 2 and report["validation_pairs"] == 1
    kwargs = dict(enabled=True, head_path=output, encoder=encoder, cache_dir=cache, game="valorant")
    rows = score(video, **kwargs)
    assert len(rows) == 6
    assert [row["second"] for row in rows] == list(range(6))
    assert all(set(row) == {"second", "kill_prob", "sick_score"} for row in rows)
    assert all(0 <= row[field] <= 1 for row in rows for field in ("kill_prob", "sick_score"))
    curves = fusion_signals(video, **kwargs)
    assert len(curves["vjepa_kill"]) == 6
    assert score(video, enabled=False, head_path=output) == []
    assert score(video, enabled=True, head_path=tmp_path / "missing") == []
    with pytest.raises(ValueError, match="game"):
        score(video, **{**kwargs, "game": "overwatch2"})
    with pytest.raises(ValueError, match="fingerprints"):
        score(video, **{**kwargs, "encoder": TinyEncoder(seed=100)})
    monkeypatch.setenv("VJEPA_ENABLED", "1")
    monkeypatch.setenv("VJEPA_HEAD", str(output))
    assert len(score(video, encoder=encoder, cache_dir=cache)) == 6
    original_import = builtins.__import__
    def no_numpy(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("simulated missing optional extra")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_numpy)
    assert score(video, **kwargs) == []


def test_disabled_import_needs_no_ml_dependencies():
    script = """
import builtins
real_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'numpy', 'torch', 'transformers', 'modal'}:
        raise ImportError('forbidden optional import')
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded
import vjepa
assert vjepa.score('missing.mp4', enabled=False) == []
import vjepa.modal_app
"""
    subprocess.run([sys.executable, "-c", script], check=True)


def test_train_cli(video, tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([{"game": "deadlock", "match_id": str(i), "video": video.name,
                                    "candidates": [{"start": 0, "end": 5.25, "events": []}]} for i in range(2)]))
    output = tmp_path / "cli-head.npz"
    result = subprocess.run([sys.executable, "-m", "vjepa.train", str(manifest), str(output),
                             "--tiny", "--resolution", "32", "--frames", "16", "--epochs", "2",
                             "--cache", str(tmp_path / "cache")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert output.is_file()
    assert json.loads(result.stdout)["samples"] > 0


def test_precomputed_training_and_metadata_guard(tmp_path):
    from dataclasses import asdict
    from vjepa.features import atomic_npz
    cfg = WindowConfig()
    path = tmp_path / "features.npz"
    arrays = {"features": np.eye(3), "windows": np.array([[0, 4], [4, 8], [8, 12]])}
    metadata = {"encoder": "hf-mean-v1:facebook/vjepa2-test@abc", "config": asdict(cfg), "duration": 12}
    atomic_npz(path, **arrays, metadata=json.dumps(metadata))
    records = [{"game": "league", "match_id": str(i), "features": str(path),
                "candidates": [{"start": 0, "end": 12, "events": []}]} for i in range(3)]
    report = train(records, tmp_path / "head.npz", None, tmp_path / "unused", epochs=2)
    assert report["samples"] == 3
    with pytest.raises(ValueError, match="configuration"):
        train(records, tmp_path / "bad.npz", None, tmp_path / "unused", WindowConfig(fps=16))
    records[0]["game"] = "deadlock"
    with pytest.raises(ValueError, match="one game"):
        train(records, tmp_path / "bad.npz", None, tmp_path / "unused")


def test_hf_wrapper_without_downloads(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from vjepa.features import HFEncoder
    calls = {}
    class Tensor:
        def __init__(self, array):
            self.array = array
        def mean(self, dim):
            return Tensor(self.array.mean(axis=dim))
        def float(self):
            return self
        def cpu(self):
            return self
        def numpy(self):
            return self.array
    class Inputs(dict):
        def to(self, device):
            calls["device"] = device
            return self
    class Processor:
        @classmethod
        def from_pretrained(cls, model_id, revision):
            calls["processor_revision"] = revision
            return cls()
        def __call__(self, videos, **kwargs):
            calls["processor_kwargs"] = kwargs
            return Inputs(pixel_values_videos=videos)
    class Model:
        config = SimpleNamespace(_commit_hash="resolved-commit")
        @classmethod
        def from_pretrained(cls, model_id, revision):
            return cls()
        def to(self, device):
            return self
        def eval(self):
            calls["eval"] = True
            return self
        def get_vision_features(self, pixel_values_videos):
            return Tensor(np.ones((len(pixel_values_videos), 8, 4)))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=nullcontext))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(AutoModel=Model, AutoVideoProcessor=Processor))
    encoder = HFEncoder(revision="requested-revision")
    features = encoder.encode(np.zeros((2, 16, 32, 32, 3), dtype=np.uint8))
    assert features.shape == (2, 4)
    assert encoder.identity.endswith("@resolved-commit")
    assert calls["eval"] and calls["device"] == "cpu"
    assert calls["processor_kwargs"]["do_sample_frames"] is False
    assert calls["processor_kwargs"]["do_resize"] is False
