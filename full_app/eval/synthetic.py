"""Generate tiny, copyright-free fixtures. Labels represent visible bright bursts."""

import argparse
import json
import subprocess
from pathlib import Path


def generate(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    videos = []
    for name, bursts in (("bursts", [(1, 2), (4, 5)]), ("quiet", [])):
        enabled = "+".join(f"between(t,{a},{b})" for a, b in bursts) or "0"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10:duration=6",
            "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=16000:duration=6",
            "-vf", f"drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='{enabled}'",
            "-af", f"volume='if({enabled},1,0.02)':eval=frame",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(destination / f"{name}.mp4")
        ], check=True, capture_output=True, text=True, timeout=60)
        videos.append({"id": name, "path": f"{name}.mp4", "duration_seconds": 6,
                       "highlights": [{"start": a, "end": b} for a, b in bursts]})
    manifest = destination / "labels.json"
    manifest.write_text(json.dumps({"version": 1, "videos": videos}, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    print(generate(parser.parse_args().destination))
