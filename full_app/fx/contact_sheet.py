"""python -m fx.contact_sheet --output /tmp/fx-gallery [--source clip.mp4]"""

import argparse
from pathlib import Path

from . import REGISTRY, Timing
from .preview import probe, run


def generate(output: Path, source: Path | None = None) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    if source is None:
        source = output / "synthetic.mp4"
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
             "testsrc2=s=320x180:r=30:d=2", "-c:v", "libx264", "-threads", "2", source])
    if float(probe(source)["format"]["duration"]) < 2:
        raise ValueError("Contact sheet source must contain at least two seconds")
    for index, (name, effect) in enumerate(REGISTRY.items()):
        timing = Timing(2, 0.5, 1.1)
        preview = effect.preview(source, output / f"{name}.mp4", timing)
        tile = output / f"tile-{index:02d}.png"
        # Sample the flash itself and the interior of every other effect's window.
        position = 0.53 if name == "impact_frame" else 0.8
        run(["ffmpeg", "-v", "error", "-y", "-ss", position, "-i", preview,
             "-vf", f"scale=320:180,pad=320:210:0:0:black,drawtext=text='{name}':fontsize=17:fontcolor=white:x=8:y=186",
             "-frames:v", "1", "-threads", "1", tile])
    sheet = output / "contact-sheet.png"
    run(["ffmpeg", "-v", "error", "-y", "-framerate", "1", "-i", output / "tile-%02d.png",
         "-vf", f"tile=4x3:nb_frames={len(REGISTRY)}", "-frames:v", "1", "-threads", "1", sheet])
    return sheet


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    print(generate(args.output, args.source))
