"""Bounded frame sampling, saliency composition, and measured thumbnail type."""

import importlib
import io
import logging
from pathlib import Path
import subprocess

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

SIZES = {"youtube": (1280, 720), "vertical": (1080, 1920), "square": (1080, 1080)}
logger = logging.getLogger(__name__)


def select_frame(video: str | Path, start: float, end: float,
                 samples: int = 8) -> tuple[Image.Image, dict]:
    if end <= start or not 1 <= samples <= 24:
        raise ValueError("Invalid frame sampling interval or count")
    candidates = []
    previous = None
    for index in range(samples):
        time = start + (end - start) * (index + 0.5) / samples
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{time:.6f}", "-i", str(video),
             "-frames:v", "1", "-vf", "scale=960:-2", "-f", "image2pipe", "-vcodec", "png", "-threads", "1", "-"],
            capture_output=True, check=True, timeout=60,
        )
        if not result.stdout:
            continue
        frame = Image.open(io.BytesIO(result.stdout)).convert("RGB")
        gray = frame.resize((160, 90)).convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES).crop((1, 1, 159, 89))
        sharpness = ImageStat.Stat(edges).var[0]
        action = ImageStat.Stat(ImageChops.difference(gray, previous)).mean[0] if previous else 0
        candidates.append((frame, time, sharpness, action))
        previous = gray
    if not candidates:
        raise ValueError("No decodable frames in selected clip")
    max_sharp = max(c[2] for c in candidates) or 1
    max_action = max(c[3] for c in candidates) or 1
    best = max(candidates, key=lambda c: 0.65 * c[2] / max_sharp + 0.35 * c[3] / max_action)
    return best[0], {"timestamp": best[1], "sharpness": best[2], "action": best[3]}


def saliency_center(image: Image.Image) -> tuple[float, float]:
    small = image.resize((64, 64)).convert("L").filter(ImageFilter.FIND_EDGES)
    # Ignore edge borders and downweight HUD edges with a center prior.
    cells = []
    for y in range(8, 56, 8):
        for x in range(8, 56, 8):
            energy = ImageStat.Stat(small.crop((x, y, x + 8, y + 8))).mean[0]
            prior = 1 - (abs(x + 4 - 32) + abs(y + 4 - 32)) / 80
            cells.append((energy * prior, (x + 4) / 64, (y + 4) / 64))
    score, x, y = max(cells, key=lambda c: c[0])
    return (x, y) if score > 0 else (0.5, 0.5)


def _font(size):
    for name in ("DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def fit_text(draw, text, area):
    """Return text, font, and actual stroked ink bounds wholly inside area."""
    text = " ".join(str(text).split())[:160] or "GAMEPLAY HIGHLIGHTS"
    left, top, right, bottom = area
    width, height = right - left, bottom - top
    for size in range(104, 17, -2):
        font = _font(size)
        lines = [""]
        # Prefer word boundaries; split only oversized tokens (including CJK).
        for word in text.split():
            trial = (lines[-1] + " " + word).strip()
            box = draw.textbbox((0, 0), trial, font=font, stroke_width=4)
            if box[2] - box[0] <= width:
                lines[-1] = trial
                continue
            if lines[-1]:
                lines.append("")
            for char in word:
                trial = lines[-1] + char
                box = draw.textbbox((0, 0), trial, font=font, stroke_width=4)
                if box[2] - box[0] > width and lines[-1]:
                    lines.append(char)
                else:
                    lines[-1] = trial
        wrapped = "\n".join(line.rstrip() for line in lines)
        box = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=10, stroke_width=4)
        if box[2] - box[0] <= width and box[3] - box[1] <= height:
            position = (left - box[0], top - box[1])
            return wrapped, font, position, (left, top, left + box[2] - box[0], top + box[3] - box[1])
    raise ValueError("Thumbnail text cannot fit safe area")


def render_thumbnail(frame: Image.Image, text: str, size: tuple[int, int],
                     subject_cutout: bool = False) -> tuple[Image.Image, dict]:
    center = saliency_center(frame)
    # Center the saliency point in the crop, clamped to image boundaries.
    w, h = frame.size
    crop_w, crop_h = min(w, h * size[0] / size[1]), min(h, w * size[1] / size[0])
    x = max(0, min(w - crop_w, center[0] * w - crop_w / 2))
    y = max(0, min(h - crop_h, center[1] * h - crop_h / 2))
    canvas = frame.crop((x, y, x + crop_w, y + crop_h)).resize(size, Image.Resampling.LANCZOS).convert("RGBA")
    mode = "saliency"
    if subject_cutout:
        try:
            # Optional adapter contract; no model download or heavy dependency here.
            cutout = importlib.import_module("sam").cutout(frame.copy())
            if not isinstance(cutout, Image.Image) or cutout.mode != "RGBA" or cutout.getchannel("A").getbbox() is None:
                raise ValueError("sam.cutout must return a nonempty RGBA Pillow image")
            cutout = ImageOps.contain(cutout.crop(cutout.getbbox()), (int(size[0] * 0.8), int(size[1] * 0.62)))
            position = ((size[0] - cutout.width) // 2, int(size[1] * 0.3))
            glow = Image.new("RGBA", size)
            glow.paste((0, 230, 255, 220), (*position, position[0] + cutout.width, position[1] + cutout.height), cutout.getchannel("A"))
            canvas = Image.alpha_composite(canvas, glow.filter(ImageFilter.GaussianBlur(18)))
            canvas.alpha_composite(cutout, position)
            mode = "sam"
        except Exception:
            logger.warning("Subject cutout unavailable; using saliency composition")
    width, height = size
    area = (int(width * .08), int(height * .12), int(width * .88), int(height * .38))
    overlay = Image.new("RGBA", size)
    draw = ImageDraw.Draw(overlay)
    wrapped, font, position, box = fit_text(draw, text, area)
    draw.rounded_rectangle((box[0] - 15, box[1] - 15, box[2] + 15, box[3] + 15), radius=20, fill=(0, 0, 0, 145))
    draw.multiline_text(position, wrapped, font=font, fill="white", stroke_width=4, stroke_fill="black", spacing=10)
    # Bright outlined arrow directs attention to the retained action area.
    arrow = [(int(width * .2), int(height * .65)), (int(width * .44), int(height * .54))]
    draw.line(arrow, fill="black", width=24)
    draw.line(arrow, fill="#ffdc35", width=14)
    tip = arrow[-1]
    draw.polygon([tip, (tip[0] - 45, tip[1] - 3), (tip[0] - 18, tip[1] + 38)], fill="#ffdc35", outline="black", width=3)
    canvas = Image.alpha_composite(canvas, overlay)
    return canvas.convert("RGB"), {"size": list(size), "safe_area": list(area), "text_bounds": list(box), "composition": mode, "text": wrapped}
