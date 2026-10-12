#!/usr/bin/env python3
"""Matte light-background reaction packs offline, optionally watching an appended batch."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'full_app'))
from reactions.matte import matte_pack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pack', type=Path)
    parser.add_argument('--qa-dir', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--low', type=float, default=10)
    parser.add_argument('--high', type=float, default=65)
    parser.add_argument('--smoothing', type=float, default=.25)
    parser.add_argument('--force', action='store_true', help='Regenerate existing mattes on the first pass')
    parser.add_argument('--only', nargs='+', help='Restrict to these clip IDs')
    parser.add_argument('--sam-local', action='store_true', help='Optional local SAM2 refinement, never remote')
    parser.add_argument('--wait-for', type=int, default=0)
    parser.add_argument('--wait-minutes', type=float, default=45)
    parser.add_argument('--poll-seconds', type=float, default=300)
    args = parser.parse_args()
    if args.wait_minutes < 0 or args.poll_seconds <= 0:
        parser.error('Wait must be nonnegative and polling interval positive')
    deadline = time.monotonic()+args.wait_minutes*60
    report = {'runs': [], 'polls': []}
    while True:
        report['runs'].extend(matte_pack(args.pack, qa_dir=args.qa_dir, force=args.force, only=args.only, low=args.low,
                                        high=args.high, smoothing=args.smoothing, sam_local=args.sam_local))
        args.force = False
        clips = json.loads((args.pack/'pack.json').read_text())['clips']
        count = len(clips)
        report['polls'].append({'time': time.time(), 'clips': count})
        report['target_reached'] = count >= args.wait_for and all(
            c.get('background') != 'light' or c.get('alpha_file') or c.get('mask_file')
            for c in clips if not args.only or c['id'] in args.only)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2)+'\n')
        print(f'pack clips={count}, target={args.wait_for}', flush=True)
        if report['target_reached'] or time.monotonic() >= deadline:
            return 0 if report['target_reached'] else 2
        time.sleep(min(args.poll_seconds, max(0, deadline-time.monotonic())))


if __name__ == '__main__':
    raise SystemExit(main())
