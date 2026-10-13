"""Offline artifact checks after the live smoke has finished; no provider calls."""
import json
from pathlib import Path
import subprocess
import sys

from services.probe import probe_video


def main():
    root = Path(sys.argv[1])
    result = json.loads((root/'results.json').read_text())
    assert result['success'] and 0 < result['calls'] <= 50
    assert result['game'] == 'deadlock' and result['confidence'] >= .7
    assert result['assessed'] > 0 and abs(result['duration']-1113.683) < .1
    checked = []
    for mode, preset, target, aspect in [('nice', 'landscape', 45, 16/9), ('mean', 'vertical', 30, 9/16)]:
        status = json.loads((root/f'{mode}-status.json').read_text())
        assert status['status'] == 'done'
        assert status['options']['privacy'] is False and status['options']['reactions'] is True
        assert all(s['source_end'] <= 923 or s['source_start'] >= 936
                   for s in status['edit_plan']['segments']), 'Reviewed shop interval returned to the plan'
        assert any(k.startswith('reactions_') for k in status['timings']), 'No reaction render recorded'
        if mode == 'mean':
            assert any(r['label'] == 'roast' for s in status['edit_plan']['segments']
                       for r in s.get('reactions', [])), 'Mean reaction tone was not applied'
        for filename in (f'{mode}-stock.mp4', f'{mode}-{preset}.mp4', f'{mode}-{preset}-discord.mp4'):
            path = root/filename
            meta = probe_video(path)
            assert abs(meta['duration']-target) <= .25, (filename, meta)
            assert abs(meta['width']/meta['height']-aspect) < .01, (filename, meta)
            if 'discord' in filename:
                assert path.stat().st_size < 20_000_000
            subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'], check=True)
            checked.append(dict(file=filename, duration=meta['duration'], width=meta['width'],
                                height=meta['height'], bytes=path.stat().st_size))
        assert (root/f'{mode}-contact.jpg').stat().st_size > 0
    assert (root/'credit.txt').read_text() == 'Gameplay: No Copyright Gameplay (CC BY)'
    print(json.dumps(dict(success=True, calls=result['calls'], files=checked), indent=2))


if __name__ == '__main__':
    main()
