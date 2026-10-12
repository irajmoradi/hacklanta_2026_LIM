"""Integration tests use only tiny, generated video/audio; never network inputs."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from ingest import IngestError, Limits, chunk_ranges, prepare
from ingest import media


@pytest.fixture(scope="module")
def vfr_video(tmp_path_factory):
    path = tmp_path_factory.mktemp("synthetic") / "vfr.mp4"
    media.run([
        "ffmpeg", "-nostdin", "-v", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=640x512:rate=30:duration=4",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=4",
        "-vf", "select='if(lt(t,2),not(mod(n,3)),1)'", "-fps_mode", "vfr",
        "-c:v", "libx264", "-threads", "2", "-c:a", "aac", str(path),
    ])
    return path


def frames(path):
    data = json.loads(media.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time,key_frame", "-of", "json", str(path),
    ]))
    return data["frames"]


def test_vfr_to_cfr_proxy_audio_and_chunks(vfr_video, tmp_path):
    original = frames(vfr_video)
    times = [float(f["best_effort_timestamp_time"]) for f in original]
    assert len({round(b - a, 3) for a, b in zip(times, times[1:])}) > 1
    events = []
    result = prepare(vfr_video, cache_dir=tmp_path, chunk_seconds=2, overlap_seconds=0.5,
                     progress=events.append)
    normalized = frames(result.path)
    times = [float(f["best_effort_timestamp_time"]) for f in normalized]
    assert times[0] == pytest.approx(0, abs=0.001)
    assert all(b - a == pytest.approx(1 / 30, abs=2e-6) for a, b in zip(times, times[1:]))
    keyframes = [i for i, frame in enumerate(normalized) if frame["key_frame"]]
    assert keyframes == [0, 60]
    assert media.probe(result.proxy)["height"] == 480
    assert media.probe(result.proxy)["fps"] == 30
    streams = json.loads(media.run([
        "ffprobe", "-v", "error", "-show_streams", "-of", "json", str(result.path),
    ]))["streams"]
    audio = next(s for s in streams if s["codec_type"] == "audio")
    assert audio["sample_rate"] == "48000"
    assert audio["channels"] == 2
    assert result.duration == pytest.approx(4)
    assert [(c.start, c.end) for c in result.chunks] == [(0, 2), (1.5, 3.5), (3, 4)]
    for chunk in result.chunks:
        assert media.probe(chunk.path)["duration"] == pytest.approx(chunk.duration, abs=1 / 30)
        assert float(frames(chunk.path)[0]["best_effort_timestamp_time"]) == pytest.approx(0, abs=0.001)
        assert chunk.global_timestamp(0.25) == chunk.start + 0.25
    with pytest.raises(IngestError):
        result.chunks[0].global_timestamp(9)
    assert events[-1]["stage"] == "complete"
    assert json.loads(json.dumps(result.to_dict()))["fps"] == 30


def test_content_cache_and_chunk_profile_reuse(vfr_video, tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    first = prepare(vfr_video, cache_dir=cache, chunk_seconds=2, overlap_seconds=0.5)
    copy = tmp_path / "different-name.mp4"
    shutil.copyfile(vfr_video, copy)
    encode = media.encode
    calls = []

    def record(*args, **kwargs):
        calls.append((args, kwargs))
        return encode(*args, **kwargs)

    monkeypatch.setattr(media, "encode", record)
    events = []
    again = prepare(copy, cache_dir=cache, chunk_seconds=2, overlap_seconds=0.5,
                    progress=events.append)
    assert calls == []
    assert again == first
    assert all(e["cache_hit"] for e in events if "cache_hit" in e)
    prepare(copy, cache_dir=cache, chunk_seconds=3, overlap_seconds=0.5)
    assert len(calls) == 2
    assert all(kwargs["start"] >= 0 for _, kwargs in calls)
    calls.clear()
    first.proxy.write_bytes(b"truncated")
    prepare(copy, cache_dir=cache, chunk_seconds=2, overlap_seconds=0.5)
    assert len(calls) == 1
    assert media.probe(first.proxy)["fps"] == 30


def test_cache_recovers_failed_encode(vfr_video, tmp_path, monkeypatch):
    encode = media.encode

    def fail(source, target, **kwargs):
        target.write_bytes(b"partial")
        raise IngestError("simulated failed encode")

    monkeypatch.setattr(media, "encode", fail)
    with pytest.raises(IngestError, match="simulated"):
        prepare(vfr_video, cache_dir=tmp_path)
    assert not list(tmp_path.rglob("manifest.json"))
    assert not list(tmp_path.rglob("*.mp4"))
    monkeypatch.setattr(media, "encode", encode)
    assert prepare(vfr_video, cache_dir=tmp_path).proxy.is_file()


def test_concurrent_same_content_is_encoded_once(vfr_video, tmp_path, monkeypatch):
    encode = media.encode
    calls = []

    def record(*args, **kwargs):
        calls.append(args)
        return encode(*args, **kwargs)

    monkeypatch.setattr(media, "encode", record)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(prepare, vfr_video, cache_dir=tmp_path) for _ in range(2)]
        first, second = [future.result() for future in futures]
    assert first == second
    assert len(calls) == 2  # one normalization and one proxy, across both callers


def test_silent_video_and_cli(tmp_path):
    video = tmp_path / "silent.mp4"
    media.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
               "testsrc2=size=160x90:rate=24:duration=1", "-c:v", "libx264", str(video)])
    import sys
    result = subprocess.run([sys.executable, "-m", "ingest", str(video), "--cache-dir",
                             str(tmp_path / "cache")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["chat_signal"] is None
    assert data["chunks"][0]["path"] == data["proxy"]
    assert media.probe(Path(data["proxy"]))["height"] == 90  # no upscale


@pytest.mark.parametrize("kwargs, message", [
    ({"limits": Limits(max_bytes=10)}, "max_bytes"),
    ({"limits": Limits(max_duration=1)}, "max_duration"),
    ({"proxy_height": 1080}, "proxy_height"),
    ({"chunk_seconds": 10, "overlap_seconds": 10}, "overlap"),
    ({"chunk_seconds": float("nan")}, "finite"),
])
def test_limits_before_encoding(vfr_video, tmp_path, monkeypatch, kwargs, message):
    monkeypatch.setattr(media, "encode", lambda *a, **k: pytest.fail("must not encode"))
    with pytest.raises(IngestError, match=message):
        prepare(vfr_video, cache_dir=tmp_path, **kwargs)


def test_multi_hour_ranges_and_exact_tail():
    ranges = list(chunk_ranges(3 * 3600 + 0.5, 900, 15))
    assert ranges[0] == (0, 900)
    assert ranges[-1][1] == 10800.5
    assert all(a[1] - b[0] == 15 for a, b in zip(ranges, ranges[1:]))
    assert list(chunk_ranges(10, 5, 0)) == [(0, 5), (5, 10)]
    assert list(chunk_ranges(9, 5, 1)) == [(0, 5), (4, 9)]
