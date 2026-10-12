"""One mixer for all v2 paths: timed ducking, explicit gains and peak protection."""
from pathlib import Path
import subprocess
from models.effects import SOUND_EFFECTS


def master_audio(source, output):
    """Final AAC headroom after segment encoding/concatenation; copy video unchanged."""
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(source),
                    '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy',
                    '-af', 'alimiter=limit=0.85:level=0:latency=1',
                    '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
                    '-movflags', '+faststart', str(output)], check=True, capture_output=True)
    return output


def sfx_graph(sounds, first_input, duration, cache=None):
    args, chains, labels, windows = [], [], ['[ducked]'], []
    root = Path(__file__).resolve().parents[1]
    for index, sound in enumerate(sounds, first_input):
        entry = SOUND_EFFECTS.get(sound.sfx_key)
        if not entry or not entry['file']:
            raise ValueError(f'Unknown SFX: {sound.sfx_key}')
        path = root / entry['file']
        if not path.is_file():
            raise ValueError(f'Missing registered SFX: {sound.sfx_key}')
        path = cache.audio(path) if cache else path
        args += ['-i', str(path)]
        length = min(sound.duration or duration, duration-sound.offset_in_segment)
        end = sound.offset_in_segment+length
        windows.append(f'between(t,{sound.offset_in_segment},{end})')
        chains.append(f'[{index}:a]atrim=duration={length},asetpts=PTS-STARTPTS,'
                      f'aresample=48000,volume={sound.gain},afade=t=out:st={max(0,length-.04)}:d=0.04,'
                      f'adelay={round(sound.offset_in_segment*1000)}:all=1[sfx{index}]')
        labels.append(f'[sfx{index}]')
    duck = '+'.join(windows) or '0'
    chains.insert(0, f"[baseaudio]volume='if(gt({duck},0),0.72,1)':eval=frame[ducked]")
    chains.append(''.join(labels)+f'amix=inputs={len(labels)}:duration=first:normalize=0,'
                  'alimiter=limit=0.95:level=0:latency=1[outa]')
    return args, ';'+';'.join(chains)
