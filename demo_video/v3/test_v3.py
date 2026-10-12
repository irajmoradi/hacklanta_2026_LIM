"""Offline tests: synthetic media only; ElevenLabs is always mocked."""
import base64
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import narration as n
import render as r


def voices():
    return [{"name": f"Village - {name}", "voice_id": name, "category": "cloned"}
            for name in ("Iraj", "Stefanny", "Lance", "Mario")] + [
            {"name": "Chris", "voice_id": "stock", "category": "premade"}]


def alignment(words, length=6):
    return {"characters": list(words),
            "character_start_times_seconds": [i * length / len(words) for i in range(len(words))],
            "character_end_times_seconds": [(i+1) * length / len(words) for i in range(len(words))]}


def test_voice_allowlist_and_script():
    selected = n.choose(voices() + [{"name": "Other clone", "voice_id": "no"}])
    assert set(selected) == {"Iraj", "Stefanny", "Lance", "Mario", "Narrator"}
    assert selected["Narrator"]["category"] == "premade"
    assert 150 <= sum(len(n.SCRIPT[i][1].split()) for i in n.PLAYBACK) <= 200
    assert sum(len(s) for _, s in n.SCRIPT) < 2500
    with pytest.raises(ValueError):
        n.choose(voices() + [voices()[0]])
    with pytest.raises(ValueError):
        n.choose(voices()[:-1])
    with pytest.raises(ValueError):
        n.choose(voices()[1:])


def test_budget_cache_and_no_regeneration(tmp_path):
    calls = []
    def api(key, endpoint, body):
        calls.append(endpoint)
        return {"audio_base64": base64.b64encode(b"mock audio").decode(),
                "alignment": alignment(body["text"])}
    selected = n.choose(voices())
    n.synthesize("mock", selected, tmp_path, api)
    n.synthesize("mock", selected, tmp_path, api)
    assert len(calls) == 10
    ledger = r.read(tmp_path / "synthesis_ledger.json")
    assert len(ledger) == 10 and all(x["status"] == "completed" for x in ledger)
    (tmp_path / "voice_9.mp3").unlink()
    with pytest.raises(RuntimeError, match="refusing regeneration"):
        n.synthesize("mock", selected, tmp_path, api)
    assert len(calls) == 10


def test_failure_spends_attempt_and_releases_lock(tmp_path):
    def fail(*args):
        raise RuntimeError("mock provider failure")
    with pytest.raises(RuntimeError, match="mock provider"):
        n.synthesize("mock", n.choose(voices()), tmp_path, fail)
    assert r.read(tmp_path / "synthesis_ledger.json")[0]["status"] == "reserved"
    assert not (tmp_path / "synthesis.lock").exists()
    with pytest.raises(RuntimeError, match="refusing regeneration"):
        n.synthesize("mock", n.choose(voices()), tmp_path, fail)


def test_concurrent_synthesis_refused(tmp_path):
    (tmp_path / "synthesis.lock").touch()
    with pytest.raises(FileExistsError):
        n.synthesize("mock", n.choose(voices()), tmp_path, lambda *a: pytest.fail("network"))


def test_captions_preserve_every_word():
    words = "A long caption should wrap cleanly at a space and retain every word. Bruh!"
    subs = r.captions(alignment(words), "Mario", 2)
    assert " ".join(s["text"] for s in subs) == words
    assert all(s["speaker"] == "Mario" and 2 <= s["start"] < s["end"] <= 8 for s in subs)


def test_real_evidence_required(tmp_path):
    source = tmp_path / "demo02"
    source.mkdir()
    payload = {"candidates": [{}, {}], "window_scores": [{}],
               "timings": {"signals": 2, "window_scoring": 3}}
    (source / "analysis.json").write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="Missing measured"):
        r.evidence(source)
    (source / "landscape.json").write_text(json.dumps({"timings": {"edit_plan": .2, "render": 5, "social": .4}}))
    data = r.evidence(source)
    assert data["seconds"] == [2, 3, .2, 5, .4]
    assert data["candidates"] == 2 and data["scored"] == 1


def test_source_selection_waits_in_five_minute_checks(tmp_path, monkeypatch):
    now = [0]
    monkeypatch.setattr(r.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(r.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    assert r.select_source(tmp_path) == tmp_path / "demo01"
    assert now[0] == 2400
    (tmp_path / "demo02").mkdir()
    (tmp_path / "demo02/montage_landscape.mp4").touch()
    monkeypatch.setattr(r, "probe", lambda path: {})
    assert r.select_source(tmp_path) == tmp_path / "demo02"


def test_synthetic_media_timeline_frames_and_mix(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    r.run(["-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-c:a", "libmp3lame", cache / "tone.mp3"])
    for i, (speaker, words) in enumerate(n.SCRIPT):
        (cache / f"voice_{i}.mp3").write_bytes((cache / "tone.mp3").read_bytes())
        (cache / f"voice_{i}.json").write_text(json.dumps({"speaker": speaker, "text": words,
                                                          "alignment": alignment(words)}))
    blocks, subs, total = r.timeline(cache)
    assert 60 <= total <= 90
    assert {b["speaker"] for b in blocks} == {"Iraj", "Stefanny", "Lance", "Mario", "Narrator"}
    beats = r.beats_for(blocks, total)
    assert beats[0]["start"] == 0 and beats[-1]["end"] == total
    assert all(1 <= b["end"] - b["start"] <= 3.00001 for b in beats)
    assert all(a["end"] == b["start"] for a, b in zip(beats, beats[1:]))
    source = tmp_path / "demo01"
    source.mkdir()
    r.run(["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10:duration=2",
           "-f", "lavfi", "-i", "sine=frequency=120:duration=2", "-c:v", "libx264",
           "-threads", "1", "-c:a", "aac", source / "montage_landscape.mp4"])
    for name in ("montage_vertical.mp4", "montage_mean_vertical.mp4", "ui_raw.webm"):
        # OpenCV detects the container from its bytes, including this test UI alias.
        (source / name).write_bytes((source / "montage_landscape.mp4").read_bytes())
    (source / "ui_scenes.json").write_text(json.dumps([
        {"label": "evidence trim share kit", "start": 0, "end": 2}]))
    footage = r.Footage(source, source)
    data = {"source": "demo01", "seconds": [1, 2, 3, 4, 5], "candidates": 10, "scored": 8, "note": "Synthetic test"}
    try:
        for b in beats:
            assert r.frame(b["start"] + .1, b, subs, data, footage, total).size == (1920, 1080)
    finally:
        footage.close()
    r.make_audio(cache, tmp_path, blocks, total, source)
    assert abs(r.duration(tmp_path / "mix.wav") - total) < .1
    r.write_srt(subs, tmp_path / "captions.srt")
    assert "Mario:" in (tmp_path / "captions.srt").read_text()
