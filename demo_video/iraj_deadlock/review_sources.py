"""Offline source-cut review for the current stock plan and labeled lowlights."""
import json
from pathlib import Path
import sys
from verify_outputs import contacts


def main():
    root = Path('/srv/demo_out/iraj_deadlock')
    if '--deaths' in sys.argv:
        events = [dict(time=t, label='death boundary review') for t in
                  [884, 887, 890, 893, 896, 899, 1549, 1553, 1556, 1559, 2310, 2313, 2316, 2319]]
        contacts('/srv/demo_in/deadlock_iraj_gfn_20261012.mp4', events, root/'death-review')
        return
    analysis = json.loads((root/'analysis-status.json').read_text())
    events = []
    for clip in analysis['clips']:
        if clip['type'] != 'bad':
            continue
        start, end = clip['start_seconds'], clip['end_seconds']
        for fraction in (.1, .5, .9):
            events.append(dict(time=start+(end-start)*fraction,
                               label=f'lowlight {clip["id"]}: {start}-{end}'))
    contacts('/srv/demo_in/deadlock_iraj_gfn_20261012.mp4', events, root/'lowlight-review')
    ranges = [(440, 455), (550, 565), (785, 800), (900, 916), (1370, 1385),
              (1548, 1563), (1878, 1895), (2015, 2030), (2170, 2185),
              (2305, 2321), (2450, 2475), (2545, 2575)]
    events = [dict(time=start+(end-start)*fraction, label=f'candidate {start}-{end}')
              for start, end in ranges for fraction in (.1, .5, .9)]
    contacts('/srv/demo_in/deadlock_iraj_gfn_20261012.mp4', events, root/'candidate-review')


if __name__ == '__main__':
    main()
