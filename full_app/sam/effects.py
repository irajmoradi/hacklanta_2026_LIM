"""Mask compositing with bounded ffmpeg encoding and audio-preserving freeze insertion."""
import json
import math
from pathlib import Path
import subprocess
import tempfile

import cv2
import numpy as np

from .tracking import clip_masks, track_from_masks


def composite(frame: np.ndarray, mask: np.ndarray, effect: str, phase: float = 0) -> np.ndarray:
    """Pure BGR compositor, also useful to an existing frame renderer."""
    base = frame.astype(np.float32)
    if effect in {"background_blur", "spotlight_freeze"}:
        alpha = mask.astype(np.float32)[..., None]
        blurred = cv2.GaussianBlur(frame, (0, 0), 7).astype(np.float32)
        background = blurred * (.3 if effect == "spotlight_freeze" else 1)
        base = base*alpha + background*(1-alpha)
    if effect in {"outline_pulse", "spotlight_freeze"}:
        edge = cv2.dilate(mask, np.ones((5, 5), np.uint8)) - mask
        glow = cv2.GaussianBlur(edge.astype(np.float32), (0, 0), 4)
        strength = .55 + .45 * math.cos(phase*math.tau*2)
        amount = np.clip((edge + glow*3)*strength, 0, 1)[..., None]
        base = base*(1-amount) + np.array([255, 220, 60])*amount
    return np.clip(base, 0, 255).astype(np.uint8)


def _slam(frame: np.ndarray, progress: float, text: str) -> np.ndarray:
    frame = frame.copy()
    h, w = frame.shape[:2]
    scale = min(w/max(1, len(text)*21), h/80) * (1 + .4*max(0, 1-progress*5))
    thickness = max(1, round(scale*2))
    size, _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, scale, thickness)
    position = (max(0, (w-size[0])//2), max(size[1], int(h*.82)))
    cv2.putText(frame, text, position, cv2.FONT_HERSHEY_DUPLEX, scale, (0, 0, 0), thickness+3, cv2.LINE_AA)
    cv2.putText(frame, text, position, cv2.FONT_HERSHEY_DUPLEX, scale, (255, 255, 255), thickness, cv2.LINE_AA)
    return frame


def _vertical(frame: np.ndarray, center: tuple[float, float], size: tuple[int, int]) -> np.ndarray:
    h, w = frame.shape[:2]
    target_w, target_h = size
    crop_w = min(w, round(h*target_w/target_h))
    crop_h = min(h, round(w*target_h/target_w))
    x = int(np.clip(center[0]*w-crop_w/2, 0, w-crop_w))
    y = int(np.clip(center[1]*h-crop_h/2, 0, h-crop_h))
    return cv2.resize(frame[y:y+crop_h, x:x+crop_w], size)


def _run(command: list[str], timeout: float) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(command, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Media command failed: " + result.stderr.decode(errors="replace")[-500:])
    return result


def render_effect(video, output, start, end, *, effect="outline_pulse", kill_time=None,
                  freeze_seconds=.6, text="SICK KILL", vertical=False, size=(720, 1280),
                  prompt="player character", config=None, encode_timeout=120) -> Path:
    """Render [start,end) to H.264/AAC. Freeze adds rounded freeze_seconds to duration.

    kill_time is absolute source time. Other effects preserve clip duration. Model
    errors use fallback masks; invalid media/parameters and encoding errors raise.
    Output is replaced atomically only after a successful encode.
    """
    if effect not in {"outline_pulse", "background_blur", "spotlight_freeze", "spotlight"}:
        raise ValueError("Unknown mask effect")
    if not math.isfinite(freeze_seconds) or not 0 <= freeze_seconds <= 10:
        raise ValueError("freeze_seconds must be in [0,10]")
    if not math.isfinite(encode_timeout) or encode_timeout <= 0:
        raise ValueError("encode_timeout must be positive")
    if any(not isinstance(v, int) or v < 2 or v % 2 for v in size):
        raise ValueError("Output dimensions must be positive even integers")
    source = Path(video).resolve(strict=True)
    target = Path(output).resolve()
    if source == target:
        raise ValueError("Source and output must differ")
    clip = clip_masks(source, start, end, prompt=prompt, config=config)
    track = track_from_masks(clip)
    count = clip.stop-clip.first
    duration = count/clip.fps
    if kill_time is None:
        kill_time = (clip.first+clip.stop-1)/(2*clip.fps)
    if not math.isfinite(kill_time) or not clip.first/clip.fps <= kill_time < clip.stop/clip.fps:
        raise ValueError("kill_time must lie inside the decoded clip")
    kill_index = min(count-1, max(0, round(kill_time*clip.fps)-clip.first))
    freeze_frames = round(freeze_seconds*clip.fps) if effect == "spotlight_freeze" else 0
    freeze_duration = freeze_frames/clip.fps
    dimensions = size if vertical else (clip.width//2*2, clip.height//2*2)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sam-", dir=target.parent) as temporary:
        raw = Path(temporary)/"frames.mp4"
        cap = cv2.VideoCapture(str(source))
        writer = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"mp4v"), clip.fps, dimensions)
        try:
            if not writer.isOpened():
                raise RuntimeError("Could not open intermediate video encoder")
            cap.set(cv2.CAP_PROP_POS_FRAMES, clip.first)
            for index in range(count):
                ok, frame = cap.read()
                if not ok:
                    raise ValueError("Video ended during rendering")
                mask = clip.mask_at((clip.first+index)/clip.fps)
                if effect == 'spotlight':
                    normal = composite(frame, mask, 'spotlight_freeze', index/clip.fps) if abs(index-kill_index) <= clip.fps*.3 else frame
                else:
                    normal = frame if effect == "spotlight_freeze" else composite(frame, mask, effect, index/clip.fps)
                def fit(image):
                    return _vertical(image, track[index][1:3], dimensions) if vertical else cv2.resize(image, dimensions)
                writer.write(fit(normal))
                if index == kill_index and freeze_frames:
                    frozen = fit(composite(frame, mask, "spotlight_freeze"))
                    for hold in range(freeze_frames):
                        writer.write(_slam(frozen, hold/max(1, freeze_frames-1), text))
        finally:
            cap.release()
            writer.release()
        probe = _run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                      "stream=index", "-of", "json", str(source)], min(encode_timeout, 10))
        has_audio = bool(json.loads(probe.stdout)["streams"])
        encoded = Path(temporary)/"result.mp4"
        command = ["ffmpeg", "-v", "error", "-y", "-i", str(raw)]
        if has_audio:
            command += ["-ss", str(clip.first/clip.fps), "-t", str(duration), "-i", str(source)]
            audio = f"[1:a:0]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration={duration},asetpts=PTS-STARTPTS"
            if freeze_frames:
                split = (kill_index+1)/clip.fps
                # For a freeze on the last frame there is no trailing source audio.
                if kill_index == count-1:
                    filters = audio + f"[pre];anullsrc=r=48000:cl=stereo,atrim=duration={freeze_duration}[hold];[pre][hold]concat=n=2:v=0:a=1[a]"
                else:
                    filters = audio + f"[base];[base]asplit=2[x][y];[x]atrim=end={split},asetpts=PTS-STARTPTS[pre];[y]atrim=start={split},asetpts=PTS-STARTPTS[post];anullsrc=r=48000:cl=stereo,atrim=duration={freeze_duration}[hold];[pre][hold][post]concat=n=3:v=0:a=1[a]"
            else:
                filters = audio + "[a]"
            command += ["-filter_complex", filters, "-map", "0:v:0", "-map", "[a]", "-c:a", "aac"]
        else:
            command += ["-map", "0:v:0", "-an"]
        command += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-t", str(duration+freeze_duration), "-movflags", "+faststart", str(encoded)]
        _run(command, encode_timeout)
        encoded.replace(target)
    return target
