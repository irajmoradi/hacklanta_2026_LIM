"""Copy deliverables locally, excluding gameplay, privacy cache and job sources."""
from pathlib import Path
import subprocess

FILES = ['extension_demo.mp4', 'montage_landscape.mp4', 'montage_vertical.mp4',
         'montage_mean_vertical.mp4', 'ui_walkthrough.mp4', 'contact_sheet.jpg',
         'frontend.png', 'evidence.json', 'clip_signals.csv', 'output_manifest.json',
         'analysis.json', 'landscape.json', 'vertical.json', 'mean_vertical.json',
         'profile_detection.json', 'live_calls.json', 'ui_scenes.json',
         'combined_result.json', 'local_candidates.json', 'mean_editorial_input.json',
         'share_landscape', 'share_vertical', 'share_mean_vertical']


if __name__ == '__main__':
    target = Path(__file__).parent / 'out'
    target.mkdir(exist_ok=True)
    for name in FILES:
        subprocess.run(['scp', '-r', '-i', str(Path.home() / '.ssh/village_vultr'),
                        'root@104.207.133.47:/srv/demo_out/demo01/' + name,
                        str(target)], check=True)
        print('Copied', name, flush=True)
