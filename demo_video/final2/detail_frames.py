"""Larger card, damage and reaction stills for portrait readability review."""
import json
from pathlib import Path
import subprocess

root = Path('/srv/demo_out/final2')
for directory in sorted(root.iterdir()):
    samples = directory/'review_samples.json'
    if not samples.is_file():
        continue
    roles = set()
    for timestamp, label in json.loads(samples.read_text()):
        role = next((p for p in ('intro', 'outro', 'damage_', 'reaction ') if label.startswith(p)), None)
        if role is None or role in roles:
            continue
        roles.add(role)
        target = directory/f"detail_{role.strip().strip('_')}.png"
        if target.exists():
            continue
        subprocess.run(['ffmpeg', '-v', 'error', '-threads', '2', '-ss', str(timestamp),
            '-i', str(directory/'master.mp4'), '-frames:v', '1', '-vf', 'scale=720:-2',
            str(target)], check=True)
        print(target, flush=True)
    discord_still = directory/'detail_discord.png'
    if not discord_still.exists():
        timestamp = next((t for t, label in json.loads(samples.read_text())
                          if label.startswith('reaction ')), 1.)
        subprocess.run(['ffmpeg', '-v', 'error', '-threads', '2', '-ss', str(timestamp),
            '-i', str(directory/'discord.mp4'), '-frames:v', '1', '-vf', 'scale=720:-2',
            str(discord_still)], check=True)
        print(discord_still, flush=True)
