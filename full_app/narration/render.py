"""Post-montage FFmpeg hook: mix speech and duck the game audio."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import subprocess

from fx.media import probe

if TYPE_CHECKING:
    from . import NarrationTrack


def filter_graph(track: NarrationTrack, *, game_audio: bool = True, duck_gain: float = 0.25) -> str:
    if not 0 <= duck_gain <= 1:
        raise ValueError("duck_gain must be between zero and one")
    spoken = [s for s in track.segments if s.audio_file is not None]
    graph = []
    if game_audio:
        filters = [f"volume={duck_gain}:enable='between(t,{s.start:.6f},{s.end:.6f})'" for s in spoken]
        graph.append("[0:a]" + (",".join(filters) or "anull") + "[game]")
    else:
        graph.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={track.duration:.6f}[game]")
    for i, s in enumerate(spoken, 1):
        graph.append(f"[{i}:a]atrim=duration={s.end-s.start:.6f},asetpts=PTS-STARTPTS,"
                     f"adelay={round(s.start*1000)}:all=1[n{i}]")
    if spoken:
        inputs = "[game]" + "".join(f"[n{i}]" for i in range(1, len(spoken)+1))
        graph.append(inputs + f"amix=inputs={len(spoken)+1}:duration=first:normalize=0,"
                     "alimiter=limit=0.95:level=0:latency=1[outa]")
    else:
        graph.append("[game]anull[outa]")
    return ";".join(graph)


def render(video: str | Path, track: NarrationTrack, output: str | Path, *, duck_gain: float = 0.25) -> Path:
    """Apply a track to the matching final montage; no-op for script-only tracks."""
    video, output = Path(video).resolve(), Path(output).resolve()
    spoken = [s for s in track.segments if s.audio_file is not None]
    if not spoken:
        return video
    if output in [video] + [Path(s.audio_file).resolve() for s in spoken]:
        raise ValueError("Output must not overwrite an input")
    info = probe(video, timeout=30)
    if abs(float(info["format"]["duration"]) - track.duration) > 0.15:
        raise ValueError("Narration timeline does not match montage duration")
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    command = ["ffmpeg", "-nostdin", "-v", "error", "-n", "-i", str(video)]
    for segment in spoken:
        command += ["-i", str(segment.audio_file)]
    command += ["-filter_complex", filter_graph(track, game_audio=has_audio, duck_gain=duck_gain),
                "-map", "0:v:0", "-map", "[outa]", "-c:v", "copy", "-c:a", "aac", str(output)]
    subprocess.run(command, capture_output=True, check=True, timeout=600)
    return output
