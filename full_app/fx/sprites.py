"""Reproducible original emoji-like artwork (Pillow only at asset-build time)."""
from pathlib import Path


def generate(destination):
    from PIL import Image, ImageDraw
    destination.mkdir(parents=True, exist_ok=True)
    for name in ('skull_rain', 'fire_rain', 'laugh_rain', 'confetti_ace'):
        canvas = Image.new('RGBA', (640, 900))
        for i in range(18):
            tile = Image.new('RGBA', (88, 88))
            d = ImageDraw.Draw(tile)
            if name == 'skull_rain':
                d.ellipse((9, 4, 79, 70), fill='white', outline='black', width=4)
                d.rectangle((23, 50, 65, 81), fill='white', outline='black', width=4)
                for x in (23, 51):
                    d.ellipse((x, 27, x+17, 47), fill='black')
                d.polygon([(44,43),(38,55),(50,55)], fill='black')
                for x in (33,44,55):
                    d.line((x,66,x,79), fill='black', width=3)
            elif name == 'fire_rain':
                d.polygon([(44,2),(53,28),(66,15),(79,53),(72,75),(44,86),
                           (17,75),(9,53),(28,20),(25,47)], fill='orangered', outline='black', width=3)
                d.polygon([(43,29),(57,54),(60,69),(43,79),(29,65)], fill='gold')
            elif name == 'laugh_rain':
                d.ellipse((4,4,84,84), fill='gold', outline='black', width=4)
                d.line([(17,34),(29,25),(36,36)], fill='black', width=5)
                d.line([(52,36),(60,25),(73,34)], fill='black', width=5)
                d.pieslice((20,32,68,76), 0, 180, fill='black')
                d.arc((24,37,64,64), 0, 180, fill='white', width=5)
                d.ellipse((5,37,19,59), fill='deepskyblue')
                d.ellipse((70,37,84,59), fill='deepskyblue')
            else:
                colors = ('cyan','gold','magenta','lime','orangered')
                for j in range(8):
                    x, y = (j*29+i*7)%70, (j*17+i*13)%70
                    d.rectangle((x,y,x+9,y+17), fill=colors[(i+j)%5])
            # Reserve the central aiming area; distribute across both margins.
            x = (i%2)*510 + ((i*17)%35)
            y = (i//2)*98
            canvas.alpha_composite(tile, (x,y))
        canvas.save(destination/(name+'.png'), optimize=True)


def filter_for(name, width, height):
    path = Path(__file__).resolve().parents[1]/'assets'/'vfx'/(name+'.png')
    escaped = path.as_posix().replace(':', r'\:').replace("'", r"\'")
    # A static cached PNG is read once, held by framesync, and moved at frame rate.
    return (f"null[bg_{name}];movie=filename='{escaped}',scale={width}:{int(height*1.4)}[sprite_{name}];"
            f"[bg_{name}][sprite_{name}]overlay=x=0:y='mod(t*{height}*.45,{height}*.35)-{height}*.35':"
            "eof_action=repeat")


if __name__ == '__main__':
    generate(Path(__file__).resolve().parents[1]/'assets'/'vfx')
