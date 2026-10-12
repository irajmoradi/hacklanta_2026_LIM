"""Original eight-video benchmark. Media and annotations are generated, never committed."""
import argparse
import json
import random
from pathlib import Path
from unittest.mock import patch

from demo import make_demo_gameplay as demo

GAMES = {
    "valorant": ["ACE", "Player ELIMINATED Enemy", "CLUTCH", "ROUND WON"],
    "ow2": ["TEAM KILL", "Player ELIMINATED Enemy", "ULTIMATE READY", "POINT CAPTURED"],
    "deadlock": ["DOUBLE KILL", "GUARDIAN DESTROYED", "SOULS SECURED", "PATRON DEFEATED"],
    "league": ["PENTAKILL", "DOUBLE KILL", "BARON SECURED", "VICTORY"],
}
# A visible synthetic HUD code is consumed only by the mocked VLM, not the detector.
COLORS = {"highlight": "lime", "death": "red", "spectating": "cyan", "distractor": "yellow"}


def schedule(seed, duration, game):
    rng = random.Random(seed)
    kinds = ["highlight"] * 4 + ["death"] * 2 + ["spectating"] * 2 + ["distractor"] * 2
    rng.shuffle(kinds)
    events = []
    for i, kind in enumerate(kinds):
        start = round(8 + i * (duration - 20) / 10 + rng.uniform(-2, 2), 2)
        text = (rng.choice(GAMES[game]) if kind == "highlight" else
                "KILLED BY Rival - RESPAWN" if kind == "death" else
                "SPECTATING Teammate ELIMINATED Enemy" if kind == "spectating" else "AMMO LOW - OBJECTIVE CONTESTED")
        events.append(dict(id=f"event_{i}", start=start, end=round(start + rng.uniform(4, 7), 2),
                           kind=kind, text=text, color=COLORS[kind], score=0))
    return events


def generate(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for split in ("train", "test"):
        for index, game in enumerate(GAMES):
            seed = 731 + index + (100 if split == "test" else 0)
            duration = 120 + index * 15
            identity = f"{split}-{game}"
            events = schedule(seed, duration, game)
            directory = output / identity
            # Reuse the demo renderer with a benchmark-specific authored event schedule.
            with patch.object(demo, "events_for", return_value=events):
                video, _ = demo.generate(directory, duration=duration, width=640, height=360, fps=15)
            # Real synthesized voice-band bursts, including one deliberately misleading spectator burst.
            voiced = [e for i, e in enumerate(events) if e["kind"] == "highlight" or
                      (e["kind"] == "spectating" and i % 2 == 0)]
            gate = "+".join(f"between(t,{e['start']},{e['end']})" for e in voiced)
            mixed = directory / "benchmark.mp4"
            demo.ffmpeg(["-i", video, "-f", "lavfi", "-i",
                         f"aevalsrc='0.22*sin(2*PI*440*t)*({gate})':s=24000:d={duration}",
                         "-filter_complex", "[0:a][1:a]amix=inputs=2:normalize=0[a]",
                         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", mixed])
            rng = random.Random(seed + 4000)
            messages = [{"time_in_seconds": t, "message": "hello"} for t in range(0, duration, 11)]
            for event in events:
                # Missing reactions and spectator excitement make chat imperfect evidence.
                if rng.random() < (.8 if event["kind"] == "highlight" else .25):
                    messages.extend({"time_in_seconds": event["start"] + j * .4 + 1,
                                     "message": "Pog clip it"} for j in range(5))
            (directory / "chat.json").write_text(json.dumps(messages, indent=2) + "\n")
            records.append(dict(id=identity, path=str(mixed.relative_to(output)).replace("\\", "/"),
                                duration_seconds=duration, split=split, game=game, seed=seed,
                                highlights=[{k: e[k] for k in ("start", "end")} for e in events if e["kind"] == "highlight"],
                                forbidden=[{k: e[k] for k in ("start", "end", "kind")} for e in events if e["kind"] in ("death", "spectating")]))
            print(f"generated {identity}: {duration}s", flush=True)
    manifest = output / "labels.json"
    manifest.write_text(json.dumps(dict(version=1, videos=records), indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    print(generate(parser.parse_args().output))
