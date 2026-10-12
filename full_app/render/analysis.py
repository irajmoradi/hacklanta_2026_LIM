"""Bounded, dependency-free FFmpeg analysis with deterministic output."""

from array import array
import math
import subprocess
import sys

from .plan import TrackPoint


def motion_track(source, start, duration):
    """Sample grayscale differences at 4Hz, ignoring tiny changes and HUD edges."""
    cmd = ["ffmpeg", "-v", "error", "-ss", str(start), "-i", str(source),
           "-t", str(duration), "-vf", "fps=4,scale=96:54", "-pix_fmt", "gray",
           "-f", "rawvideo", "-"]
    points, previous = [], None
    # Read one frame at a time: memory does not grow with source length.
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        while True:
            frame = proc.stdout.read(96 * 54)
            if len(frame) != 96 * 54:
                break
            xsum = ysum = weight = 0
            if previous:
                for y in range(5, 49):
                    for x in range(9, 87):
                        delta = max(0, abs(frame[y * 96 + x] - previous[y * 96 + x]) - 12)
                        xsum += delta * x
                        ysum += delta * y
                        weight += delta
            points.append(TrackPoint(time=(len(points) / 4),
                                     x=xsum / weight / 96 if weight else 0.5,
                                     y=ysum / weight / 54 if weight else 0.5))
            previous = frame
        if proc.wait() != 0:
            raise RuntimeError("Motion analysis failed")
    # Limit expression complexity even for very long clips.
    stride = max(1, math.ceil(len(points) / 120))
    return smooth_track(points[::stride])


def smooth_track(points):
    """Exponential smoothing followed by linear interpolation in the crop graph."""
    result = []
    x = y = 0.5
    for point in points:
        x += 0.3 * (point.x - x)
        y += 0.3 * (point.y - y)
        result.append(TrackPoint(time=point.time, x=x, y=y))
    return result


def detect_beats(path, duration):
    """Energy-onset peaks, not a musical tempo model. Decode only the used bed."""
    cmd = ["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", str(path),
           "-t", str(duration), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"]
    energies = []
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        while True:
            block = proc.stdout.read(800)  # 50 ms
            if not block:
                break
            samples = array("h", block[:len(block) // 2 * 2])
            if sys.byteorder != "little":
                samples.byteswap()
            energies.append(sum(v * v for v in samples) / max(1, len(samples)))
        if proc.wait() != 0:
            raise RuntimeError("Music analysis failed")
    beats = []
    for i in range(1, len(energies) - 1):
        baseline = sum(energies[max(0, i - 8):i]) / min(i, 8)
        if energies[i] > max(10000, baseline * 1.5) and energies[i] >= energies[i + 1]:
            time = i * 0.05
            if not beats or time - beats[-1] >= 0.2:
                beats.append(round(time, 3))
    return beats


def snap_durations(durations, beats, tolerance, overlap=0, initial=0, minimum=0.1):
    """Trim only: keep source boundaries safe. Snap transition starts, excluding last cut."""
    result = list(durations)
    cursor = initial
    for i, duration in enumerate(durations[:-1]):
        target = cursor + duration - overlap
        candidates = [b for b in beats if target - tolerance <= b <= target
                      and b - cursor + overlap >= minimum]
        if candidates:
            result[i] = max(candidates) - cursor + overlap
        cursor += result[i] - overlap
    return result
