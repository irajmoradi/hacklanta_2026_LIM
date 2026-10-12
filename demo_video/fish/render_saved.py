"""Offline preview of diagnostic stills; never constructs a provider."""
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'full_app'))


def main():
    from cards import install_cards
    from render.engine import Renderer
    from render.plan import RenderPlan
    from services.ffmpeg_runner import FFmpegRunner
    from music import pick_or_generate
    output = Path(__file__).parent / 'out'
    source = Path('/srv/demo_out/demo02/automatic_montage_landscape.mp4')
    with tempfile.TemporaryDirectory(dir=output) as temporary:
        work = Path(temporary)
        bed = pick_or_generate('energetic', 11, 8, output_dir=work)
        renderer = install_cards(Renderer, {role: output / f'diagnostic_{role}.png' for role in ('intro', 'outro')})
        engine = renderer(FFmpegRunner(work, source, 1280, 720, 24))
        plan = RenderPlan(resolution=720, fps=24, segments=[dict(source_start=2, source_end=4),
                          dict(source_start=8, source_end=10)], intro=dict(text='INTRO', duration=3.5),
                          outro=dict(text='OUTRO', duration=3.5),
                          music=dict(path=str(bed.path), beat_sync=False))
        result = engine.render(plan)
        shutil.copyfile(result, output / 'valorant_ai_preview.mp4')
    print('Offline AI preview rendered; paid calls: 0')


if __name__ == '__main__':
    main()
