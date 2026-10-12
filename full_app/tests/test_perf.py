import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from perf import encoders
from perf.cache import Cache
from perf.graph import Clip, render, single_pass
from perf.media import concatenate, copy_cut, probe, run
from perf.parallel import render_all, worker_count


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "source.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-threads", "2",
         "-g", "30", "-bf", "0", "-sc_threshold", "0", "-c:a", "aac", "-ar", "48000", "-ac", "2", path])
    return path


def test_encoder_fallback(monkeypatch):
    encoders.best.cache_clear()
    calls = []
    def unavailable(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1)
    monkeypatch.setattr(encoders.subprocess, "run", unavailable)
    assert encoders.best().name == "libx264"
    assert len(calls) == 4
    assert "fastdecode" in encoders.best().args()
    assert "faster" in encoders.best().args("final")
    encoders.best.cache_clear()


@pytest.mark.parametrize("name", ["h264_nvenc", "h264_qsv", "h264_vaapi", "h264_videotoolbox"])
def test_encoder_probe(monkeypatch, name):
    encoders.best.cache_clear()
    monkeypatch.setattr(encoders.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0 if name in cmd else 1))
    assert encoders.best().name == name
    encoders.best.cache_clear()


def test_cache_atomic_invalidation(tmp_path):
    cache = Cache(tmp_path / "cache")
    source = tmp_path / "asset"
    source.write_text("first")
    calls = []
    def build(out):
        calls.append(out)
        out.write_bytes(b"png")
    first = cache.overlay([source], {"text": "hello"}, build)
    assert cache.overlay([source], {"text": "hello"}, build) == first
    assert len(calls) == 1
    source.write_text("changed size")
    assert cache.overlay([source], {"text": "hello"}, build) != first
    def fail(out):
        out.write_bytes(b"partial")
        raise RuntimeError("failed")
    with pytest.raises(RuntimeError):
        cache.overlay([], {}, fail)
    assert len(list(cache.root.iterdir())) == 2


def test_parallel_order_limits_and_errors():
    enc = encoders.Encoder(threads=2)
    assert worker_count(enc, cores=8) == 4
    assert worker_count(encoders.Encoder("h264_nvenc"), gpu_sessions=1, cores=16) == 1
    assert render_all([lambda: 3, lambda: 1], enc) == [3, 1]
    with pytest.raises(ZeroDivisionError):
        render_all([lambda: 1/0], enc)


@pytest.mark.parametrize("effects,speed", [([], 1), (["heavy_blur", "text_gg"], 1),
    (["chromatic_aberration", "contrast_pop"], 1), (["slow_motion"], 1), ([], 2), ([], .25)])
def test_single_pass_streams_duration(source, tmp_path, effects, speed):
    from services.ffmpeg_runner import FFmpegRunner
    slow = FFmpegRunner(tmp_path, source, 320, 180, 30)
    slow._encoder_args = lambda: encoders.Encoder().args()
    baseline = slow.extract_segment(0, 0, 1, effects if "chromatic_aberration" not in effects else [], speed)
    clip = Clip(source, tmp_path / "fast.mp4", 0, 1, 320, 180, 30, speed, "fade_in")
    render(clip, effects, [{"file": source, "offset": .1}], encoder=encoders.Encoder())
    a, b = probe(baseline), probe(clip.output)
    assert abs(float(a["format"]["duration"]) - float(b["format"]["duration"])) < .15
    assert [(s["codec_type"], s.get("width"), s.get("height")) for s in a["streams"]] == [
        (s["codec_type"], s.get("width"), s.get("height")) for s in b["streams"]]
    run(["ffmpeg", "-v", "error", "-i", clip.output, "-f", "null", "-"])


def test_copy_and_concat(source, tmp_path):
    assert not copy_cut(source, tmp_path / "bad.mp4", .1, 1)
    assert copy_cut(source, tmp_path / "cut.mp4", 0, 1)
    assert abs(float(probe(tmp_path / "cut.mp4")["format"]["duration"]) - 1) < .1
    out = concatenate([source, source], tmp_path / "joined.mp4")
    assert abs(float(probe(out)["format"]["duration"]) - 4) < .15
    other = render(Clip(source, tmp_path / "small.mp4", 0, 1, 160, 90, 30), encoder=encoders.Encoder())
    with pytest.raises(ValueError, match="identical"):
        concatenate([source, other], tmp_path / "badconcat.mp4")


def test_media_cache(source, tmp_path):
    cache = Cache(tmp_path)
    for get in (cache.audio, cache.proxy):
        path = get(source)
        stamp = path.stat().st_mtime_ns
        assert get(source).stat().st_mtime_ns == stamp
    assert probe(cache.audio(source))["streams"][0]["sample_rate"] == "48000"


def test_silent_source_and_validation(source, tmp_path):
    silent = tmp_path / "silent.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-i", source, "-an", "-c:v", "copy", silent])
    clip = Clip(silent, tmp_path / "out.mp4", 0, 1, 320, 180, 30)
    render(clip, encoder=encoders.Encoder())
    assert len(probe(clip.output)["streams"]) == 2
    clip.speed = 0
    with pytest.raises(ValueError):
        single_pass(clip)


@pytest.mark.parametrize("speed,expected", [(2, .5), (.5, 2)])
def test_source_timing(source, tmp_path, speed, expected):
    clip = Clip(source, tmp_path / "retimed.mp4", .5, 1.5, 320, 180, 30, speed, timing="source")
    render(clip, encoder=encoders.Encoder())
    assert abs(float(probe(clip.output)["format"]["duration"]) - expected) < .08


def test_multiple_complex_effects(source, tmp_path):
    clip = Clip(source, tmp_path / "complex.mp4", 0, .5, 320, 180, 30)
    render(clip, ["chromatic_aberration", "chromatic_aberration", "text_gg"], encoder=encoders.Encoder())
    assert probe(clip.output)["streams"][0]["width"] == 320


def test_nonzero_legacy_cut(source, tmp_path):
    from services.ffmpeg_runner import FFmpegRunner
    slow = FFmpegRunner(tmp_path, source, 320, 180, 30)
    slow._encoder_args = lambda: encoders.Encoder().args()
    old = slow.extract_segment(0, .5, 1.5, ["contrast_pop"])
    new = render(Clip(source, tmp_path / "new.mp4", .5, 1.5, 320, 180, 30), ["contrast_pop"], encoder=encoders.Encoder())
    assert abs(float(probe(old)["format"]["duration"]) - float(probe(new)["format"]["duration"])) < .08


def test_shared_cache_concurrency(tmp_path):
    cache = Cache(tmp_path)
    calls = []
    def build(out):
        calls.append(out)
        out.write_bytes(b"complete")
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(lambda _: cache.overlay([], {"text": "GG"}, build), range(8)))
    assert len(set(paths)) == 1
    assert len(calls) == 1


def test_encoder_timeout(monkeypatch):
    encoders.best.cache_clear()
    def timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 10)
    monkeypatch.setattr(encoders.subprocess, "run", timeout)
    assert encoders.best().name == "libx264"
    encoders.best.cache_clear()
