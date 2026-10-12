"""Override only card rendering; native joins, music and timeline remain intact."""
from pathlib import Path


def install_cards(renderer, assets):
    class CardRenderer(renderer):
        def card(self, card, name, plan, directory):
            if name not in assets:
                return super().card(card, name, plan, directory)
            from models.effects import SOUND_EFFECTS
            duration = round(card.duration * plan.fps) / plan.fps
            width, height = plan.size
            root = Path(__file__).resolve().parents[1]
            sound = root / SOUND_EFFECTS['cinematic_boom']['file']
            args = ['-loop', '1', '-i', str(assets[name])]
            if sound.is_file():
                args += ['-i', str(sound)]
            else:
                import warnings
                warnings.warn('Card boom SFX unavailable; using silence', RuntimeWarning)
                args += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
            # Pad rather than crop: generated lettering survives every aspect preset.
            graph = (f'[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,'
                     f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,'
                     f"zoompan=z='1+0.045*on/{max(1, duration*plan.fps)}':"
                     f"x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={width}x{height}:fps={plan.fps},"
                     'format=yuv420p[outv];[1:a]aresample=48000,volume=0.5,apad[outa]')
            args += ['-filter_complex', graph, '-map', '[outv]', '-map', '[outa]', '-t', str(duration)]
            return self.encode(args, directory / f'{name}.mp4', directory), duration
    return CardRenderer
