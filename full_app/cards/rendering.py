"""Override only card rendering; native joins, music and timeline remain intact."""
from pathlib import Path


def compose_card(source, output, size):
    """Fill the preset with artwork, preserving lettering in cached 16:9 art.

    The thumbnail provider currently fixes image requests to 16:9. A blurred
    cover layer fills the frame while a contain layer keeps titles/fish intact.
    This also works offline and when a cached job changes aspect.
    """
    from PIL import Image, ImageFilter, ImageOps
    with Image.open(source) as image:
        image = image.convert('RGB')
        canvas = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)
        canvas = canvas.filter(ImageFilter.GaussianBlur(max(size)*.025))
        foreground = ImageOps.contain(image, size, method=Image.Resampling.LANCZOS)
        canvas.paste(foreground, ((size[0]-foreground.width)//2, (size[1]-foreground.height)//2))
        canvas.save(output)
    return output


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
            artwork = compose_card(assets[name], directory / f'{name}_{plan.preset}.png', plan.size)
            args = ['-loop', '1', '-i', str(artwork)]
            if sound.is_file():
                args += ['-i', str(sound)]
            else:
                import warnings
                warnings.warn('Card boom SFX unavailable; using silence', RuntimeWarning)
                args += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
            graph = (f'[0:v]scale={width}:{height},setsar=1,'
                     f"zoompan=z='1+0.045*on/{max(1, duration*plan.fps)}':"
                     f"x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={width}x{height}:fps={plan.fps},"
                     'format=yuv420p[outv];[1:a]aresample=48000,volume=0.5,apad[outa]')
            args += ['-filter_complex', graph, '-map', '[outv]', '-map', '[outa]', '-t', str(duration)]
            return self.encode(args, directory / f'{name}.mp4', directory), duration
    return CardRenderer
