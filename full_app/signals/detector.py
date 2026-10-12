"""Streaming, downscaled video signals and FFmpeg audio statistics."""

from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
import warnings

import cv2
import numpy as np

from .fusion import fuse
from .models import Config
from .ocr import HUDReader, regions_for


def _probe(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    if video is None:
        raise ValueError("input has no video stream")
    duration = float(video.get("duration", data.get("format", {}).get("duration", 0)))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("input needs a finite positive duration")
    return duration, video, any(s["codec_type"] == "audio" for s in data["streams"])


def _scene_detector(cfg):
    if cfg.scene_backend == "ffmpeg":
        return None
    try:
        from scenedetect.detectors import AdaptiveDetector, ContentDetector
    except ImportError:
        if cfg.scene_backend != "auto":
            warnings.warn("PySceneDetect is unavailable; using FFmpeg scene scores", RuntimeWarning)
        return None
    if cfg.scene_backend == "content":
        return ContentDetector(threshold=27, min_scene_len=1)
    return AdaptiveDetector(min_scene_len=1)


def _video(path, duration, stream, cfg, regions):
    count = math.ceil(duration)
    motion, scene = np.zeros(count), np.zeros(count)
    samples = np.zeros(count)
    events = []
    reader = HUDReader(regions, cfg.ocr_cooldown) if cfg.ocr else None
    width = cfg.ocr_width if reader and reader.executable else cfg.width
    height = max(2, round(stream["height"] * width / stream["width"] / 2) * 2)
    detector = _scene_detector(cfg)
    # Computing FFmpeg's scene score on the same sampled frames avoids another
    # full decode; gte(scene,0) retains all frames for motion/OCR.
    filters = (f"setpts=PTS-STARTPTS,fps={cfg.sample_fps},scale={width}:{height},"
               "select='gte(scene,0)',metadata=print:key=lavfi.scene_score")
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-threads", str(cfg.threads),
               "-noautorotate", "-i", str(path), "-map", f"0:{stream['index']}", "-an",
               "-filter_threads", "1", "-vf", filters, "-pix_fmt", "bgr24",
               "-threads", "1", "-f", "rawvideo", "pipe:1"]
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
        previous = None
        index = 0
        try:
            while True:
                chunk = proc.stdout.read(width * height * 3)
                if not chunk:
                    break
                if len(chunk) != width * height * 3:
                    raise RuntimeError("FFmpeg returned an incomplete frame")
                frame = np.frombuffer(chunk, np.uint8).reshape(height, width, 3)
                timestamp = index / cfg.sample_fps
                second = min(count - 1, int(timestamp))
                gray = cv2.cvtColor(cv2.resize(frame, (cfg.width, max(2, round(height * cfg.width / width)))),
                                    cv2.COLOR_BGR2GRAY)
                if previous is not None:
                    motion[second] += float(cv2.absdiff(previous, gray).mean()) / 255
                    samples[second] += 1
                previous = gray
                if detector:
                    for cut in detector.process_frame(index, frame):
                        t = float(cut) / cfg.sample_fps
                        scene[min(count - 1, int(t))] += 1
                        events.append({"time": round(t, 3), "type": "scene_cut"})
                if reader:
                    events.extend(reader.read(frame, timestamp))
                index += 1
            proc.wait()
        finally:
            proc.stdout.close()
            if proc.poll() is None:
                proc.terminate()
            proc.wait()
        errors.seek(0)
        log = errors.read().decode("utf-8", errors="replace")
        if proc.returncode:
            raise RuntimeError(f"FFmpeg video extraction failed: {log[-2000:]}")
    if not index:
        raise ValueError("input contains no decoded video frames")
    if detector is None:
        timestamp = 0.
        for line in log.splitlines():
            match = re.search(r"pts_time:([\d.eE+-]+)", line)
            if match:
                timestamp = float(match[1])
            match = re.search(r"lavfi.scene_score=([\d.eE+-]+)", line)
            if match and float(match[1]) > cfg.scene_threshold:
                scene[min(count - 1, int(timestamp))] += 1
                events.append({"time": round(timestamp, 3), "type": "scene_cut"})
    return motion / np.maximum(samples, 1), scene, events


def _audio(path, duration, present, cfg):
    count = math.ceil(duration)
    rms, onset, sustained = (np.zeros(count) for _ in range(3))
    if not present:
        return rms, onset, sustained, []
    # 100 ms RMS blocks preserve short shots/claps; metadata is much smaller
    # than a full PCM recording. Timestamp correction preserves delayed audio.
    command = ["ffmpeg", "-v", "error", "-nostdin", "-threads", str(cfg.threads),
               "-i", str(path), "-map", "0:a:0", "-vn", "-filter_threads", "1",
               "-af", "aresample=8000:async=1:first_pts=0,aformat=channel_layouts=mono,"
               "asetnsamples=n=800,astats=metadata=1:reset=1,"
               "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
               "-f", "null", "-"]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    times, levels = [], []
    timestamp = 0.
    for line in result.stdout.splitlines():
        match = re.search(r"pts_time:([\d.eE+-]+)", line)
        if match:
            timestamp = float(match[1])
        if line.startswith("lavfi.astats.Overall.RMS_level="):
            db = float(line.split("=", 1)[1])
            times.append(timestamp)
            levels.append(10 ** (db / 20) if math.isfinite(db) else 0.)
    levels = np.asarray(levels)
    if not len(levels):
        return rms, onset, sustained, []
    baseline = np.median(levels)
    loud = levels > max(.025, baseline * 2.5)
    changes = np.maximum(0, np.diff(levels, prepend=levels[0]))
    sums, samples = np.zeros(count), np.zeros(count)
    for t, level, change in zip(times, levels, changes):
        if 0 <= t < duration:
            i = int(t)
            sums[i] += level * level
            samples[i] += 1
            onset[i] = max(onset[i], change)
    rms = np.sqrt(sums / np.maximum(samples, 1))
    events = []
    start = None
    for j in range(len(loud) + 1):
        if j < len(loud) and loud[j]:
            if start is None:
                start = j
        elif start is not None:
            end = min(duration, times[j - 1] + .1)
            if end - times[start] >= .5:
                events.append({"time": round(times[start], 3), "end": round(end, 3),
                               "type": "sustained_audio"})
                for i in range(max(0, int(times[start])), min(count, math.ceil(end))):
                    sustained[i] = max(sustained[i], min(i + 1, end) - max(i, times[start]))
            start = None
    return rms, onset, sustained, events


def detect_candidates(video_path, profile="auto", **cfg):
    """Return score-ranked Candidate objects; timestamps are seconds from start.

    See Config and docs/signals.md for tunables. Missing optional OCR/scene
    libraries degrade gracefully; invalid input and decoder errors are raised.
    """
    config = Config(**cfg)
    regions = regions_for(profile, config.ocr_regions)
    path = Path(video_path).resolve(strict=True)
    duration, stream, has_audio = _probe(path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        audio = pool.submit(_audio, path, duration, has_audio, config)
        motion, scene, events = _video(path, duration, stream, config, regions)
        rms, onset, sustained, audio_events = audio.result()
    events.extend(audio_events)
    events.sort(key=lambda event: (event["time"], event["type"]))
    ocr = np.zeros(math.ceil(duration))
    for event in events:
        if event["type"] in {"kill", "death"}:
            ocr[min(len(ocr) - 1, int(event["time"]))] += 1
    return fuse({"scene": scene, "rms": rms, "onset": onset,
                 "sustained": sustained, "motion": motion, "ocr": ocr}, events, duration, config)
