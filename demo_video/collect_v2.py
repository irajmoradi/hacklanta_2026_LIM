"""Collect only DEMO-02 deliverables; never source footage, jobs or credentials."""
from pathlib import Path
import subprocess

FILES=['extension_demo_v2.mp4','extension_demo_v2_discord.mp4','montage_landscape.mp4',
       'montage_vertical.mp4','montage_mean_vertical.mp4','ui_walkthrough.mp4','comparison.mp4',
       'contact_sheet.jpg','frontend.png','evidence.json','clip_signals.csv','output_manifest.json',
       'analysis.json','landscape.json','vertical.json','mean_vertical.json','live_calls.json',
       'review','attempt_audit.json','ui_scenes.json','verification.json','SHA256SUMS','share_landscape','share_vertical','share_mean_vertical']


def main():
    root=Path(__file__).resolve().parents[1]
    out=root/'demo_video/out';out.mkdir(exist_ok=True)
    host=(root/'tools/runner_ip').read_text().strip()
    for name in FILES:
        subprocess.run(['scp','-r','-i',str(Path.home()/'.ssh/village_vultr'),
                        'root@'+host+':/srv/demo_out/demo02/'+name,str(out)],check=True)
        print('Copied',name,flush=True)
    import hashlib,json
    verified=json.loads((out/'verification.json').read_text())
    for name,result in verified.items():
        with (out/name).open('rb') as f:
            assert hashlib.file_digest(f,'sha256').hexdigest()==result['sha256'],name
    print('All local video hashes match decoded runner originals.')


if __name__=='__main__':main()
