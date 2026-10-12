"""FFmpeg-only PIP renderer; timestamps are local to the rendered clip."""
import json
import math
import subprocess
import tempfile
import uuid
from pathlib import Path

PRESETS = {'landscape': 'bottom-right', 'vertical': 'top-left'}


def probe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                             '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def layout(width, height, preset):
    corner = PRESETS[preset]
    size = max(16, int(min(width, height) * 0.30) // 2 * 2)
    margin = max(8, int(min(width, height) * 0.04))
    return (size, width - size - margin if corner.endswith('right') else margin,
            height - size - margin if corner.startswith('bottom') else margin)


def render_overlay(base_clip, reaction, preset='landscape', *, peak_time=None,
                   output_path=None, show_speaker=False, duck_gain=0.25):
    """Start a reaction at the peak, clamped to the available clip duration.

    Returns a new MP4 Path. Never modifies the source. Requires ffmpeg/ffprobe.
    """
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
    if not math.isfinite(length) or length <= 0:
        raise ValueError('Reaction duration must be positive and finite')
    peak = duration / 2 if peak_time is None else float(peak_time)
    if not math.isfinite(peak):
        raise ValueError('peak_time must be finite')
    start = min(max(0, peak), max(0, duration - length))
    end, fade = start + length, min(0.16, length / 3)
    size, x, y = layout(video['width'], video['height'], preset)
    audio = any(s['codec_type'] == 'audio' for s in info['streams'])
    voice = any(s['codec_type'] == 'audio' for s in head_info['streams'])
    key = 'colorkey=0xFFFFFF:0.22:0.08,' if reaction.background == 'light' else ''
    mask = f"if(lte(pow(X-{size}/2,2)+pow(Y-{size}/2,2),pow({size}/2-1,2)),alpha(X,Y),0)"
    graph = [
        '[0:v]setpts=PTS-STARTPTS[base]',
        f'[1:v]trim=duration={length},setpts=PTS-STARTPTS,scale={size}:{size}:force_original_aspect_ratio=increase,'
        f"crop={size}:{size},format=rgba,{key}geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{mask}',"
        f'fade=t=in:st=0:d={fade}:alpha=1,fade=t=out:st={length-fade}:d={fade}:alpha=1,'
        f'setpts=PTS+{start}/TB,split[head][shade]',
        '[shade]colorchannelmixer=rr=0:gg=0:bb=0:aa=0.5,gblur=sigma=3[shadow]',
    ]
    # Slide up a few pixels while fading in/out, giving a small pop motion.
    motion = f'{y}+{size*0.12}*(max(0,1-(t-{start})/{fade})+max(0,1-({end}-t)/{fade}))'
    graph += [f"[base][shadow]overlay=x={x+4}:y='{motion}+4':enable='between(t,{start},{end})':eof_action=pass:repeatlast=0[bg]",
              f"[bg][head]overlay=x={x}:y='{motion}':enable='between(t,{start},{end})':eof_action=pass:repeatlast=0[pip]"]
    with tempfile.TemporaryDirectory(prefix='reaction-') as temporary:
        cwd = Path(temporary)
        if show_speaker:
            (cwd / 'speaker.txt').write_text(reaction.speaker, encoding='utf-8')
            graph.append(f"[pip]drawtext=textfile=speaker.txt:expansion=none:fontsize={max(12,size//9)}:"
                         f"fontcolor=white:box=1:boxcolor=black@0.65:x={x}:y={y+size-18}:"
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
                   '-i', str(Path(reaction.file).resolve()), '-filter_complex_threads', '1',
                   '-filter_complex', ';'.join(graph), '-map', '[v]', '-map', '[a]',
                   '-t', str(duration), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
                   '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-movflags', '+faststart', str(output)]
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f'Reaction overlay failed: {result.stderr[-2000:]}')
    return output
