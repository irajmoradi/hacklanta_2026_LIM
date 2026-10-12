"""FFmpeg-only PIP renderer; timestamps are local to the rendered clip."""
import math
import subprocess
import tempfile
import uuid
from functools import lru_cache
from pathlib import Path

from fx.media import probe
from .pack import Reaction

PRESETS = {'landscape': 'bottom-right', 'vertical': 'bottom-left', 'square': 'bottom-right'}


def layout(width: int, height: int, preset: str, reaction_size: str = 'large') -> tuple[int, int, int]:
    if preset not in PRESETS:
        raise ValueError(f'Unknown reaction preset: {preset}')
    corner = PRESETS[preset]
    if reaction_size not in ('small', 'medium', 'large'):
        raise ValueError('Unknown reaction size')
    fraction = {'landscape': .33, 'vertical': .27, 'square': .30}[preset]
    size = max(16, int(min(width, height) * fraction * {'small': .55, 'medium': .78, 'large': 1}[reaction_size]) // 2 * 2)
    margin = max(2, int(size * .025))
    return (size, width - size + margin if corner.endswith('right') else -margin,
            height - size + margin)


@lru_cache(maxsize=128)
def matte_bounds(path: str, modified: int, alpha: bool):
    """Union of sampled visible matte pixels; fixed crop avoids animated resizing."""
    import numpy as np
    command = ['ffmpeg', '-v', 'error']
    if alpha:
        command += ['-c:v', 'libvpx-vp9']
    command += ['-i', path, '-vf', ('alphaextract,' if alpha else '') + 'fps=4,scale=256:256',
                '-t', '30', '-f', 'rawvideo', '-pix_fmt', 'gray', '-']
    raw = subprocess.run(command, capture_output=True, check=True).stdout
    if not raw:
        raise ValueError('Empty reaction matte')
    visible = np.frombuffer(raw, np.uint8).reshape(-1, 256, 256).max(axis=0) > 24
    ys, xs = np.nonzero(visible)
    if not len(xs):
        raise ValueError('Empty reaction silhouette')
    # Small padding retains feathered hair edges.
    return (max(0, int(xs.min())-2)/256, max(0, int(ys.min())-2)/256,
            min(256, int(xs.max())+3)/256, min(256, int(ys.max())+3)/256)


def render_overlay(base_clip: str | Path, reaction: Reaction, preset: str = 'landscape', *, peak_time: float | None = None,
                   output_path: str | Path | None = None, show_speaker: bool | None = None, duck_gain: float = 0.25,
                   max_duration: float | None = None, position: str | None = None,
                   reaction_size: str = 'large') -> Path:
    """Start a reaction at the peak, clamped to the available clip duration.

    Returns a new MP4 Path. Never modifies the source. Requires ffmpeg/ffprobe.
    """
    if preset not in PRESETS:
        raise ValueError(f'Unknown reaction preset: {preset}')
    base_clip = Path(base_clip).resolve()
    output = Path(output_path).resolve() if output_path else base_clip.with_name(
        f'{base_clip.stem}_reaction_{uuid.uuid4().hex[:10]}.mp4')
    if output in (base_clip, Path(reaction.file).resolve()):
        raise ValueError('Output must differ from both inputs')
    if output.exists():
        raise FileExistsError(f'Reaction output already exists: {output}')
    if not math.isfinite(duck_gain) or not 0 <= duck_gain <= 1:
        raise ValueError('duck_gain must be between 0 and 1')
    info, head_info = probe(base_clip), probe(reaction.file)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    duration = float(info['format']['duration'])
    length = min(float(reaction.duration), float(head_info['format']['duration']), duration)
    if max_duration is not None:
        if not math.isfinite(max_duration) or max_duration <= 0:
            raise ValueError('max_duration must be positive and finite')
        length = min(length, max_duration)
    if not math.isfinite(length) or length <= 0:
        raise ValueError('Reaction duration must be positive and finite')
    peak = duration / 2 if peak_time is None else float(peak_time)
    if not math.isfinite(peak):
        raise ValueError('peak_time must be finite')
    start = min(max(0, peak), max(0, duration - length))
    end, fade = start + length, min(0.16, length / 3)
    size, x, y = layout(video['width'], video['height'], preset, reaction_size)
    if position is not None:
        if position not in ('top_right', 'bottom_right'):
            raise ValueError('Unknown reaction position')
        margin = max(2, int(size * .025))
        x = video['width'] - size + margin
        y = margin if position == 'top_right' else video['height'] - size + margin
    audio = any(s['codec_type'] == 'audio' for s in info['streams'])
    voice = any(s['codec_type'] == 'audio' for s in head_info['streams'])
    alpha_file = reaction.alpha_file
    mask_file = reaction.mask_file if not alpha_file else None
    if show_speaker is None:
        show_speaker = bool(alpha_file or mask_file)
    key = 'colorkey=0xFFFFFF:0.22:0.08,' if reaction.background == 'light' else ''
    mask = f"if(lte(pow(X-{size}/2,2)+pow(Y-{size}/2,2),pow({size}/2-1,2)),alpha(X,Y),0)"
    graph = ['[0:v]setpts=PTS-STARTPTS[base]']
    if alpha_file:
        graph.append('[2:v]setpts=PTS-STARTPTS,format=rgba[portrait]')
    elif mask_file:
        graph += ['[1:v]setpts=PTS-STARTPTS,format=rgb24[color]',
                  '[2:v]setpts=PTS-STARTPTS,format=gray[matte]',
                  '[color][matte]alphamerge[portrait]']
    else:
        graph.append(f"[1:v]setpts=PTS-STARTPTS,format=rgba,{key}null[portrait]")
    # Keep the complete silhouette for matted assets, including hair outside the old circle.
    crop_mask = '' if alpha_file or mask_file else f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{mask}',"
    geometry = (f'scale={size}:{size}:force_original_aspect_ratio=decrease,'
                f'pad={size}:{size}:(ow-iw)/2:(oh-ih)/2:color=black@0' if alpha_file or mask_file else
                f'scale={size}:{size}:force_original_aspect_ratio=increase,crop={size}:{size}')
    if alpha_file or mask_file:
        matte_path = Path(alpha_file or mask_file)
        left, top, right, bottom = matte_bounds(str(matte_path), matte_path.stat().st_mtime_ns, bool(alpha_file))
        geometry = (f'crop=iw*{right-left}:ih*{bottom-top}:iw*{left}:ih*{top},' + geometry)
    graph += [
        f'[portrait]trim=duration={length},{geometry},format=rgba,{crop_mask}'
        f'fade=t=in:st=0:d={fade}:alpha=1,fade=t=out:st={length-fade}:d={fade}:alpha=1,'
        f'setpts=PTS+{start}/TB,split[head][shade]',
        '[shade]colorchannelmixer=rr=0:gg=0:bb=0:aa=0.5,gblur=sigma=3[shadow]',
    ]
    # Slide up a few pixels while fading in/out, giving a small pop motion.
    motion = (f'{y}+{size*0.12}*(max(0,1-(t-{start})/{fade})+max(0,1-({end}-t)/{fade}))'
              f'-{size*.045}*sin(min(1,max(0,(t-{start})/{fade}))*PI)'
              f'+{size*.018}*sin(2*PI*(t-{start})/2.4)')
    graph += [f"[base][shadow]overlay=x={x+4}:y='{motion}+4':enable='between(t,{start},{end})':eof_action=pass:repeatlast=0[bg]",
              f"[bg][head]overlay=x={x}:y='{motion}':enable='between(t,{start},{end})':eof_action=pass:repeatlast=0[pip]"]
    with tempfile.TemporaryDirectory(prefix='reaction-') as temporary:
        cwd = Path(temporary)
        if show_speaker:
            (cwd / 'speaker.txt').write_text(reaction.speaker, encoding='utf-8')
            graph.append(f"[pip]drawtext=textfile=speaker.txt:expansion=none:fontsize={max(12,size//9)}:"
                         f"fontcolor=white:box=1:boxcolor=black@0.65:x={max(4,x)}:y='{motion}+{size*.75}':"
                         f"enable='between(t,{start},{end})'[v]")
        else:
            graph.append('[pip]null[v]')
        if audio:
            gain = duck_gain if voice else 1
            graph.append(f"[0:a]asetpts=PTS-STARTPTS,volume='{gain}':enable='between(t,{start},{end})'[game]")
        else:
            graph.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={duration}[game]')
        if voice:
            graph += [f'[1:a]atrim=duration={length},asetpts=PTS-STARTPTS,afade=t=in:d=0.02,'
                      f'afade=t=out:st={max(0,length-0.03)}:d=0.03,adelay={round(start*1000)}:all=1[line]',
                      '[game][line]amix=inputs=2:duration=first:normalize=0:dropout_transition=0,alimiter=limit=0.95:level=0[a]']
        else:
            graph.append('[game]anull[a]')
        command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-n', '-i', str(base_clip),
                   '-i', str(Path(reaction.file).resolve())]
        if alpha_file:
            # Native VP9 decoding can silently discard alpha; libvpx preserves it.
            command += ['-c:v', 'libvpx-vp9', '-i', str(Path(alpha_file).resolve())]
        elif mask_file:
            command += ['-i', str(Path(mask_file).resolve())]
        command += ['-filter_complex_threads', '1',
                   '-filter_complex', ';'.join(graph), '-map', '[v]', '-map', '[a]',
                   '-t', str(duration), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
                   '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-movflags', '+faststart', str(output)]
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f'Reaction overlay failed: {result.stderr[-2000:]}')
    return output
