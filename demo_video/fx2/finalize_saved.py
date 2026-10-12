"""Apply the final mastering fix to completed pre-fix renders, without re-encoding video."""
import hashlib
import json
from pathlib import Path
import subprocess

from render_saved import discord_copy
from render.audio import master_audio

out = Path('/srv/demo_out/fx2')
manifest = json.loads((out/'manifest.json').read_text())
for name in ('landscape','vertical','mean_vertical'):
    record = manifest[name]
    if record.get('final_master'):
        continue
    output = out/f'montage_{name}.mp4'
    mastered = out/f'mastered_{name}.mp4'
    master_audio(output, mastered)
    mastered.replace(output)
    discord = out/f'montage_{name}_discord.mp4'
    duration = float(record['metadata']['format']['duration'])
    discord_copy(output, discord, duration)
    assert discord.stat().st_size < 20_000_000
    record.update(final_master=True, bytes=output.stat().st_size, discord_bytes=discord.stat().st_size,
                  sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                  metadata=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams',
                                      '-show_format','-of','json',str(output)])))
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print(name,'mastered',flush=True)
