"""Offline FFmpeg integration tests; no downloaded media or paid API calls."""
import json
import subprocess

import numpy as np
import pytest

from multipov import Alignment, Angle, SyncError, TeamCandidate, Video, render_montage, sync, team_candidates


def ffmpeg(*args):
    result = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *map(str, args)],
                            capture_output=True, timeout=90)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


@pytest.fixture(scope="module")
def recordings(tmp_path_factory):
    folder = tmp_path_factory.mktemp("multipov")
    shared = folder / "shared.wav"
    ffmpeg("-f", "lavfi", "-i", "anoisesrc=r=16000:d=40:seed=73",
           "-af", "aeval=val(0)*(0.15+abs(sin(2.1*t+0.07*t*t))*abs(sin(5.7*t)))",
           "-c:a", "pcm_s16le", shared)
    result = []
    # First POV starts four seconds into the synthetic match.
    for index, (origin, rate) in enumerate(((4, 1), (6.375, 1.0015), (1.65, .9985), (5.125, 1))):
        path = folder / f"player{index}.mp4"
        color = ("red", "blue", "green", "yellow")[index]
        ffmpeg("-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=30:d=26",
               "-ss", origin, "-i", shared,
               "-f", "lavfi", "-i", f"anoisesrc=r=16000:d=28:seed={100 + index}:amplitude=0.6",
               "-filter_complex",
               f"[1:a]asetrate={16000 * rate},aresample=16000[game];"
               "[2:a]lowpass=f=700,aeval=val(0)*(0.5+0.5*sin(3*t))[voice];"
               "[game][voice]amix=inputs=2:normalize=0[a]",
               "-map", "0:v", "-map", "[a]", "-t", "26", "-c:v", "libx264",
               "-threads", "2", "-preset", "ultrafast", "-c:a", "aac", "-ac", "1", path)
        result.append(Video(path, ("Alice", "Bob: 100% [x]; 'hi'", "Chris", "Dana")[index]))
    return result


def test_sync_offsets_drift_and_voice_chat_within_one_frame(recordings):
    alignments = sync(recordings)
    assert alignments[0] == Alignment(0)
    for actual, offset, rate in zip(alignments[1:], (2.375, -2.35, 1.125), (1.0015, .9985, 1)):
        for local in (0, 13, 26):
            assert abs(actual.to_match(local) - (offset + rate * local)) < 1 / 30
        assert actual.confidence > .3
        assert actual.to_local(actual.to_match(7)) == pytest.approx(7)


def test_candidates_use_shared_clock_and_signals_score(recordings):
    offsets = [Alignment(0), Alignment(2.375, 1.0015)]
    local = offsets[1]
    candidates = team_candidates(recordings[:2], [
        [dict(start=8, end=12, score=.4), dict(start=20, end=22, score=.9)],
        [dict(start=local.to_local(8.1), end=local.to_local(12.1), score=.95)],
    ], offsets=offsets)
    assert len(candidates) == 2
    assert candidates[0].start == pytest.approx(8.1)
    assert candidates[0].end == pytest.approx(12)
    assert candidates[0].best.video_index == 1
    assert candidates[0].best.player == recordings[1].player
    assert len(candidates[1].angles) == 1


def test_distinct_events_and_same_pov_do_not_merge(recordings):
    result = team_candidates(recordings[:2], [
        [dict(start=5, end=9, score=1, event_id="kill"), dict(start=6, end=10, score=2)],
        [dict(start=5, end=9, score=1, event_id="death")],
    ], offsets=[Alignment(0), Alignment(0)])
    assert len(result) == 2
    assert all(len({a.video_index for a in c.angles}) == len(c.angles) for c in result)
    assert len(result[0].angles) == 1


@pytest.mark.parametrize("mode", ["best", "split", "pip"])
def test_render_valid_pixels_audio_names_and_duration(recordings, tmp_path, mode):
    offsets = [Alignment(0), Alignment(2.375, 1.0015)]
    candidate = TeamCandidate(8, 10, (Angle(0, 8, 10, .9, "Alice"), Angle(1, 8, 10, .8, "Bob")))
    # Include a second segment to exercise actual montage concatenation.
    single = TeamCandidate(13, 14, (Angle(1, 13, 14, .9, "Bob"),))
    output = render_montage(recordings[:2], [single, candidate], tmp_path / f"{mode}.mp4",
                            offsets=offsets, mode=mode, width=640, height=360)
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                                     "-of", "json", str(output)], check=True, capture_output=True).stdout)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (640, 360)
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    assert float(info["format"]["duration"]) == pytest.approx(3, abs=.12)
    ffmpeg("-i", output, "-f", "null", "-")  # Decode the complete output.
    pixels = np.frombuffer(ffmpeg("-ss", "0.5", "-i", output, "-frames:v", "1", "-f", "rawvideo",
                                 "-pix_fmt", "rgb24", "pipe:1"), dtype=np.uint8).reshape(360, 640, 3)
    assert pixels[180, 100, 0] > 150  # primary red POV
    if mode == "split":
        assert pixels[180, 500, 2] > 150  # blue replay panel
    if mode == "pip":
        assert pixels[250, 500, 2] > 150  # blue inset
    assert np.any(np.all(pixels[8:35, 8:130] > 180, axis=2))  # visible name tag
    assert np.any(np.all(pixels[332:352, 8:500] > 180, axis=2))  # team credit


@pytest.mark.parametrize("audio", [None, "anullsrc=r=8000", "sine=f=440:r=8000"])
def test_unusable_audio_rejected(tmp_path, audio):
    path = tmp_path / "unusable.mp4"
    inputs = ["-f", "lavfi", "-i", "testsrc2=s=160x120:r=30:d=5"]
    if audio:
        inputs += ["-f", "lavfi", "-i", audio]
    ffmpeg(*inputs, "-t", "5", "-c:v", "libx264", "-threads", "2", path)
    # A single reference is not evidence of a successful pairwise alignment.
    second = tmp_path / "second.mp4"
    second.write_bytes(path.read_bytes())
    with pytest.raises(SyncError):
        sync([path, second])


def test_invalid_inputs_and_source_protection(recordings, tmp_path):
    with pytest.raises(ValueError):
        sync([])
    with pytest.raises(ValueError):
        sync([recordings[0], recordings[0]])
    with pytest.raises(ValueError):
        Alignment(0, float("nan"))
    with pytest.raises(ValueError):
        team_candidates(recordings[:1], [[dict(start=0, end=99)]], offsets=[Alignment(0)])
    candidate = TeamCandidate(2, 3, (Angle(0, 2, 3, 1, "Alice"),))
    with pytest.raises(ValueError, match="overwrite"):
        render_montage(recordings[:1], [candidate], recordings[0].path, offsets=[Alignment(0)])
    with pytest.raises(ValueError, match="outside"):
        render_montage(recordings[:1], [candidate], tmp_path / "invalid.mp4", offsets=[Alignment(5)])


def test_render_without_audio_with_manual_alignment(tmp_path):
    path = tmp_path / "silent.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=3", "-c:v", "libx264", "-threads", "2", path)
    result = render_montage([path], [TeamCandidate(0, 1, (Angle(0, 0, 1, 1, "Silent"),))],
                            tmp_path / "result.mp4", offsets=[Alignment(0)], width=320, height=180)
    ffmpeg("-i", result, "-f", "null", "-")
