"""Runner preflight for optional local models. Zero Gemini calls."""
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'full_app'))


if __name__ == '__main__':
    from sam import Config, clip_masks
    from faster_whisper import WhisperModel
    started = time.monotonic()
    masks = clip_masks('/srv/demo_in/valorant_phoenix_44k.mp4', 960, 961,
        config=Config(backend='local', checkpoint='/srv/models/sam2.1_hiera_small.pt',
                      timeout=120, budget=300, max_samples=2))
    record = dict(sam_degraded=masks.degraded, sam_seconds=time.monotonic()-started,
                  samples=len(masks.times))
    WhisperModel('tiny', device='cpu', compute_type='int8')
    record['whisper_cached'] = True
    Path('/srv/demo_out/final2/runtime.json').write_text(json.dumps(record, indent=2))
    print(record, flush=True)
    assert not masks.degraded
