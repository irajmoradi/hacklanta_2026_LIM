"""Generate original, deterministic gameplay-like footage; no downloads or APIs."""

import argparse
import json
import math
from pathlib import Path
import subprocess


def ffmpeg(args, timeout=180):
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-filter_threads", "1", "-filter_complex_threads", "1", *map(str, args)],
        capture_output=True, timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-4000:])
    return result.stdout


def probe(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True, timeout=20,
    )
    return json.loads(result.stdout)


def events_for(duration):
    labels = ["Player ELIMINATED Enemy", "KILLED BY Rival", "ACE",
              "Player ELIMINATED Enemy", "PENTAKILL", "KILLED BY Rival"]
    colors = ["yellow", "red", "lime", "cyan", "magenta", "orange"]
    scores = [6, 2, 10, 7, 9, 3]
    return [dict(id=f"event_{i}", start=round(duration * (i + 1) / 7, 3),
                 end=round(duration * (i + 1) / 7 + min(1.5, duration / 28), 3),
                 text=label, kind="death" if "KILLED" in label else "highlight",
                 score=scores[i], color=colors[i]) for i, label in enumerate(labels)]


def generate(output, duration=150, width=640, height=360, fps=15):
    if not math.isfinite(duration) or duration < 14 or duration > 180:
        raise ValueError("duration must be between 14 and 180 seconds")
    if width < 320 or height < 180 or width % 2 or height % 2 or fps < 1:
        raise ValueError("use even dimensions >= 320x180 and positive fps")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    events = events_for(duration)
    # An abstract training arena: moving perspective grid, enemy targets, weapon,
    # crosshair, minimap, health, ammo, and transient announcements.
    vf = ["drawgrid=w=80:h=60:t=1:c=0x34506a@0.5",
          "drawbox=x=0:y=ih*0.62:w=iw:h=ih*0.38:c=0x192a33:t=fill",
          "drawbox=x=iw*0.1:y=ih*0.22:w=iw*0.16:h=ih*0.4:c=0x36506b:t=fill",
          "drawbox=x=iw*0.7:y=ih*0.15:w=iw*0.18:h=ih*0.47:c=0x456079:t=fill",
          "drawtext=text='[]':fontsize=42:fontcolor=0xff7657:x='w/2+sin(t*1.7)*w/4':y='h/2+cos(t)*20'",
          "drawbox=x=iw*0.56:y=ih*0.77:w=iw*0.14:h=ih*0.23:c=0x687b82:t=fill",
          "drawtext=text='+':fontsize=30:fontcolor=white:x='w/2-10+sin(t*2)*18':y='h/2-15+cos(t*1.3)*9'",
          "drawbox=x=12:y=12:w=80:h=65:c=0x08141f@0.9:t=fill",
          "drawbox=x=18:y=18:w=68:h=53:c=0x70a6af:t=2",
          "drawtext=text='TRAINING ARENA':fontsize=14:fontcolor=white:x=(w-tw)/2:y=12",
          "drawtext=text='HP 100   SHIELD 50':fontsize=14:fontcolor=0x55ffaa:x=16:y=h-30",
          "drawtext=text='AMMO 24 / 120':fontsize=14:fontcolor=white:x=w-tw-16:y=h-30"]
    for event in events:
        enable = f"between(t,{event['start']},{event['end']})"
        death = event["kind"] == "death"
        vf.extend([
            f"drawbox=x=iw*0.35:y=ih*0.3:w=iw*0.6:h=36:c=black@0.8:t=fill:enable='{enable}'",
            f"drawtext=text='{event['text']}':fontsize=18:fontcolor={event['color']}:x=w-tw-20:y=h*0.3+7:enable='{enable}'",
            # Full-width event barcode for deterministic pixel checks after encoding.
            f"drawbox=x=0:y=ih-8:w=iw:h=8:c={event['color']}:t=fill:enable='{enable}'",
        ])
        if death:
            vf.append(f"drawbox=x=0:y=0:w=iw:h=ih:c=red@0.18:t=fill:enable='{enable}'")
    gate = "+".join(f"between(t,{e['start']},{e['end']})" for e in events)
    # Harmonic voiced syllables and sharp deterministic pseudo-noise gunfire.
    voice = "0.055*(sin(2*PI*145*t)+0.5*sin(2*PI*290*t)+0.2*sin(2*PI*870*t))*max(0,sin(2*PI*3*t))"
    gunfire = f"0.32*sin(2*PI*(1700*t+400*t*t))*lt(mod(t,0.16),0.035)*({gate})"
    audio = f"aevalsrc='{voice}+{gunfire}':s=24000:d={duration}"
    video = output / "gameplay.mp4"
    ffmpeg(["-f", "lavfi", "-i", f"color=c=0x152738:s={width}x{height}:r={fps}:d={duration}",
            "-f", "lavfi", "-i", audio, "-vf", ",".join(vf), "-t", duration,
            "-c:v", "libx264", "-preset", "ultrafast", "-threads", "2", "-crf", "23",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", video])
    truth = dict(schema_version=1, seed=0, duration=duration, width=width, height=height,
                 fps=fps, events=events, top_event_ids=["event_2", "event_4"],
                 provenance="Original procedural shapes, text and synthesized tones; no speech or external assets.")
    (output / "ground_truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
    return video, truth


def synthetic_pack(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    video = output / "beep.mp4"
    ffmpeg(["-f", "lavfi", "-i", "color=white:s=128x128:r=15:d=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-vf", "geq=r='if(lt(hypot(X-64,Y-64),48),50,255)':g='if(lt(hypot(X-64,Y-64),48),180,255)':b='if(lt(hypot(X-64,Y-64),48),230,255)',drawtext=text='O':fontsize=24:fontcolor=black:x=56:y='72+4*sin(t*20)'",
            "-c:v", "libx264", "-threads", "2", "-pix_fmt", "yuv420p", "-c:a", "aac", video])
    reaction = dict(id="synthetic_hype", speaker="Tone Bot", label="hype", text="Beep!",
                    file="beep.mp4", duration=1.0, background="white")
    (output / "pack.json").write_text(json.dumps({"clips": [reaction]}, indent=2), encoding="utf-8")
    return {**reaction, "file": str(video.resolve())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("demo_out"))
    parser.add_argument("--duration", type=float, default=150)
    args = parser.parse_args()
    video, _ = generate(args.output, args.duration)
    print(video)


if __name__ == "__main__":
    main()
