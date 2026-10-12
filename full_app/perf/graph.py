"""Single-encode clip commands using the existing effect registry."""
import math
from dataclasses import dataclass
from pathlib import Path
from models.effects import VIDEO_EFFECTS, CATEGORY_ORDER, FONT_PATH
from .encoders import best
from .media import probe, run


@dataclass
class Clip:
    source: Path
    output: Path
    start: float
    end: float
    width: int = 1920
    height: int = 1080
    fps: float = 60
    speed: float = 1
    transition: str = "cut"
    cheap_blur: bool = False
    timing: str = "legacy"


def tempo(speed):
    parts = []
    while speed > 2:
        parts.append("atempo=2")
        speed /= 2
    while speed < .5:
        parts.append("atempo=0.5")
        speed *= 2
    return parts + [f"atempo={speed}"]


def single_pass(clip, effects=(), sfx=(), preset="preview", *, encoder=None, cache=None):
    """Return argv; SFX dictionaries contain file, offset (output seconds), volume.

    Call media.run(argv) or render(). Text registry effects and complex RGB splits
    are composed in the same graph. Unknown effect/transition names fail explicitly.
    """
    if isinstance(clip, dict):
        clip = Clip(**clip)
    if not all(math.isfinite(x) for x in (clip.start, clip.end, clip.speed, clip.fps)) or not (
            0 <= clip.start < clip.end and clip.speed > 0 and clip.fps > 0):
        raise ValueError("invalid clip timing")
    if clip.width < 2 or clip.height < 2 or clip.width % 2 or clip.height % 2:
        raise ValueError("output dimensions must be positive and even")
    effects = [effects] if isinstance(effects, str) else list(effects)
    for name in effects:
        if name not in VIDEO_EFFECTS:
            raise ValueError(f"unknown effect: {name}")
    effects.sort(key=lambda name: CATEGORY_ORDER[VIDEO_EFFECTS[name]["category"]])
    encoder = encoder or best()
    if clip.timing not in ("legacy", "source"):
        raise ValueError("timing must be legacy or source")
    cmd = ["ffmpeg", "-v", "error", "-y", *encoder.input_args(), "-filter_threads", str(encoder.threads),
           "-filter_complex_threads", str(encoder.threads)]
    if clip.timing == "source":
        cmd += ["-ss", str(clip.start), "-t", str(clip.end-clip.start)]
    cmd += ["-i", str(clip.source)]
    has_audio = any(s["codec_type"] == "audio" for s in probe(clip.source)["streams"])
    # Explicit trim before setpts ensures source interval is unchanged by speed effects.
    vf = [f"setpts=(PTS-STARTPTS)/{clip.speed}"]
    af = ["asetpts=PTS-STARTPTS", *tempo(clip.speed)]
    duration = (clip.end-clip.start) / clip.speed
    for name in effects:
        if name == "slow_motion":
            duration *= 2
        elif name == "speed_2x":
            duration /= 2
    if clip.timing == "legacy":
        duration = clip.end - clip.start
    for name in effects:
        eff = VIDEO_EFFECTS[name]
        if name == "fade_out":
            # Matches the current registry's no-op; do not silently change semantics.
            continue
        filt = eff["filter"]
        if filt:
            if clip.cheap_blur and name in ("moderate_blur", "heavy_blur"):
                radius = 2 if name == "moderate_blur" else 3
                filt = f"scale={max(2, clip.width//4//2*2)}:{max(2, clip.height//4//2*2)},boxblur={radius}:1,scale={clip.width}:{clip.height}"
            vf.append(filt.format(width=clip.width, height=clip.height, fps=clip.fps, fontpath=FONT_PATH))
        if eff.get("audio_filter"):
            af.append(eff["audio_filter"])
    if clip.timing == "legacy":
        vf += [f"trim=start={clip.start}:duration={duration}", "setpts=PTS-STARTPTS"]
        af += [f"atrim=start={clip.start}:duration={duration}", "asetpts=PTS-STARTPTS"]
    vf += [f"scale={clip.width}:{clip.height}:force_original_aspect_ratio=decrease",
           f"pad={clip.width}:{clip.height}:(ow-iw)/2:(oh-ih)/2", f"fps={clip.fps}", "setsar=1", "format=yuv420p"]
    if clip.transition not in ("cut", "none", "fade_in", "flash_white"):
        raise ValueError("unknown transition")
    transition = []
    if clip.transition in ("fade_in", "flash_white"):
        fade = .5 if clip.transition == "fade_in" else .2
        color = "black" if clip.transition == "fade_in" else "white"
        vf.append(f"fade=t=in:st=0:d={fade}:color={color}")
        transition.append(f"afade=t=in:st=0:d={fade}")
    graph = ["[0:v]" + ",".join(vf) + encoder.upload_filter() + "[v]"]
    if has_audio:
        graph.append("[0:a]" + ",".join(af) + ",aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration=" + str(duration) + "[base]")
    else:
        graph.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={duration}[base]")
    labels = ["[base]"]
    for i, entry in enumerate(sfx, 1):
        offset, volume = float(entry.get("offset", 0)), float(entry.get("volume", .7))
        if not math.isfinite(offset) or not math.isfinite(volume) or offset < 0 or volume < 0:
            raise ValueError("invalid SFX offset/volume")
        source = cache.audio(entry["file"]) if cache else entry["file"]
        cmd += ["-i", str(source)]
        graph.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={int(offset*1000)}:all=1,volume={volume}[s{i}]")
        labels.append(f"[s{i}]")
    mix = f"amix=inputs={len(labels)}:duration=first" if len(labels) > 1 else "anull"
    graph.append("".join(labels) + mix + ("," + ",".join(transition) if transition else "") + "[a]")
    return cmd + ["-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]", *encoder.args(preset),
                  "-r", str(clip.fps), "-video_track_timescale", "15360", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                  "-t", str(duration), "-movflags", "+faststart", str(clip.output)]


def render(clip, effects=(), sfx=(), preset="preview", **kwargs):
    run(single_pass(clip, effects, sfx, preset, **kwargs))
    return Path(clip["output"] if isinstance(clip, dict) else clip.output)
