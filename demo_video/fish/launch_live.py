"""Explicit live launcher: runtime key travels over SSH stdin, never in a file."""
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[2]
    value = None
    for line in Path('C:/Users/mourn/Downloads/hacklanta/.env').read_text(encoding='utf-8-sig').splitlines():
        name, sep, candidate = line.partition('=')
        if sep and name.strip() == 'GOOGLE_API_KEY':
            value = candidate.strip().strip('"').strip("'")
    if not value:
        raise SystemExit('Runtime GOOGLE_API_KEY missing')
    script = 'diagnose_live.py' if '--diagnose' in sys.argv else 'live_smoke.py'
    command = f'cd /srv/lim/{root.name} && .venv/bin/python demo_video/fish/{script}'
    result = subprocess.run(['ssh', '-i', str(Path.home() / '.ssh/village_vultr'),
                             '-o', 'StrictHostKeyChecking=accept-new', 'root@104.207.133.47', command],
                            input=value+'\n', text=True)
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
