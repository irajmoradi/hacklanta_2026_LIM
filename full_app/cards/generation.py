"""Two image attempts per job, including failed attempts; no provider retries."""
import json
import random
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont
from services.call_budget import CallBudget

FONT = Path(__file__).parent / 'fonts' / 'NotoEmoji.ttf'
VARIANTS = ('electric neon lightning and speed lines',
            'retro arcade stickers and ridiculous explosions',
            'comic-book halftones, starbursts and confetti')
CARS = ('tiny pink hatchback', 'golden sports car', 'rusty station wagon', 'flying taxi')


def prompt_for(name, title, mode, rng):
    style = rng.choice(VARIANTS)
    if name == 'intro':
        return (f'Edit this gameplay frame into a flashy TikTok montage thumbnail. '
                f'Keep the gameplay recognizable and visible. Huge bold corny hype title: "{title}". '
                f'Use {style}. Keep all lettering within the middle 75% of the image.')
    roast = ('Playfully roast the gameplay: "EVEN THE FISH AIMED BETTER". ' if mode == 'mean'
             else 'Celebrate the ridiculous gaming adventure. ')
    return (f'Make an absurd shitpost meme-style outro from this gameplay frame, with {style}. '
            f'Big readable "THANKS FOR WATCHING". A {rng.choice(CARS)} and a clearly visible '
            f'fish are MANDATORY; make the fish hilariously oversized. {roast}'
            'Keep the text, fish and car within the middle 75% of the image.')


def local_card(frame, output, title, name, mode):
    """Self-contained fallback: bundled OFL monochrome fish/car glyphs."""
    if frame.is_file():
        with Image.open(frame) as reference:
            image = reference.convert('RGB').resize((1280, 720))
        image = ImageEnhance.Brightness(image).enhance(.3)
    else:
        image = Image.new('RGB', (1280, 720), '#10152d')
    draw = ImageDraw.Draw(image)
    text = title if name == 'intro' else 'THANKS FOR WATCHING'
    font = ImageFont.load_default(size=62)
    # Wrap by measured width, including long single words.
    lines, line = [], ''
    for char in text[:200]:
        if draw.textlength(line + char, font=font) > 1100 or char == '\n':
            lines.append(line)
            line = ''
        if char != '\n':
            line += char
    lines.append(line)
    for i, line in enumerate(lines[:4]):
        draw.text((640, 110+i*72), line, font=font, anchor='mm', fill='#fff36a')
    emoji = ImageFont.truetype(str(FONT), 150)
    draw.text((470, 490), '\U0001f41f', font=emoji, anchor='mm', fill='#58efff')
    draw.text((810, 490), '\U0001f697', font=emoji, anchor='mm', fill='#ff84ba')
    if name == 'outro' and mode == 'mean':
        draw.text((640, 650), 'EVEN THE FISH AIMED BETTER',
                  font=ImageFont.load_default(size=32), anchor='mm', fill='white')
    image.save(output)


def generate_cards(job, source, segments, client_factory, warn, *, top_index=0):
    """Cache successes AND fallbacks across renders/restarts of the same job.

    An exclusive attempt marker prevents retrying a role after interruption; the
    durable client ledger additionally caps transport attempts at two per job.
    A new edit of the same job deliberately reuses its original cards.
    """
    directory = Path(job['dir']) / 'cards'
    directory.mkdir(parents=True, exist_ok=True)
    budget = CallBudget(directory / 'image-budget.sqlite3', limit=2)
    options = job['options']
    title = str(options.get('title') or job.get('title') or job.get('edit_plan', {}).get('title')
                or ('BRUH MOMENTS: AIM NOT FOUND' if options.get('mode') == 'mean'
                    else 'ABSOLUTE CINEMA: ONE MORE ROUND'))[:200]
    assets = {}
    for name, segment in [('intro', segments[top_index]), ('outro', segments[-1])]:
        output, frame = directory / f'{name}.png', directory / f'{name}_frame.png'
        manifest = directory / f'{name}.json'
        if output.is_file() and manifest.is_file():
            record = json.loads(manifest.read_text())
            if record['fallback']:
                warn(f'AI {name} card unavailable; using cached local fish/car card')
            assets[name] = output
            continue
        fallback, reason = False, None
        prompt = prompt_for(name, title, options.get('mode', 'nice'), random.Random(f'{job.get("id", directory)}:{name}'))
        try:
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss',
                            str((segment['source_start']+segment['source_end'])/2),
                            '-i', str(source), '-frames:v', '1', '-vf', 'scale=1280:-2', str(frame)],
                           check=True, capture_output=True, timeout=60)
            # Mark before opening the client; never retry a failed role on rerender.
            with (directory / f'{name}.attempt').open('x'):
                pass
            with client_factory() as client:
                client.generate_thumbnail(frame, prompt, output, image_budget=budget)
            with Image.open(output) as image:
                image.verify()
        except Exception as error:
            # Provider exceptions may contain credentials; only a safe warning escapes.
            from services.provider_errors import classify
            reason = classify(error).code
            fallback = True
            local_card(frame, output, title, name, options.get('mode', 'nice'))
            warn(f'AI {name} card unavailable ({reason}); using local fish/car card')
        manifest.write_text(json.dumps(dict(fallback=fallback, reason=reason, prompt=prompt, title=title)), encoding='utf-8')
        assets[name] = output
    job['ai_cards'] = {name: str(path) for name, path in assets.items()}
    return assets
