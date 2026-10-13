"""Leave AAC headroom in published demos without re-encoding their video."""
import array
import hashlib
import json
from pathlib import Path
import subprocess


def peak(path):
    values = array.array('f')
    values.frombytes(subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path),
                                             '-vn', '-f', 'f32le', '-']))
    return max(abs(v) for v in values)


def finalize_outputs(out, names=('landscape', 'mean_vertical')):
    manifest_path = out/'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    report_path = out/'mastering.json'
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    for name in names:
        for suffix in ('', '_discord'):
            path = out/f'montage_{name}{suffix}.mp4'
            if not path.exists():
                continue
            before = peak(path)
            gain = .93/before if before >= .98 else 1
            if gain < 1:
                temporary = path.with_suffix('.headroom.mp4')
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(path), '-map', '0:v:0',
                                '-map', '0:a:0', '-c:v', 'copy', '-af', f'volume={gain}',
                                '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart',
                                str(temporary)], check=True)
                after = peak(temporary)
                assert after < .99, (path, after)
                temporary.replace(path)
            else:
                after = before
            report[path.name] = dict(before=before, gain=gain, after=after)
            if name in manifest:
                manifest[name]['discord_bytes' if suffix else 'bytes'] = path.stat().st_size
                manifest[name]['discord_sha256' if suffix else 'sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    report_path.write_text(json.dumps(report, indent=2))
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print('Audio mastering', json.dumps(report), flush=True)


if __name__ == '__main__':
    finalize_outputs(Path('/srv/demo_out/samfix'))
