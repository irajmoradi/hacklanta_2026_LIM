"""Repair lower-bitrate AAC overshoot in already encoded Discord copies."""
import json
from pathlib import Path
from render_saved import protect_discord

out = Path('/srv/demo_out/fx2')
manifest = json.loads((out/'manifest.json').read_text())
for name in ('landscape','vertical','mean_vertical'):
    path = out/f'montage_{name}_discord.mp4'
    protect_discord(path)
    assert path.stat().st_size < 20_000_000
    manifest[name]['discord_bytes'] = path.stat().st_size
(out/'manifest.json').write_text(json.dumps(manifest,indent=2))
