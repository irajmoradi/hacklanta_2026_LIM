"""Validate rendered deliverables; no network or paid API access."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from render import HERE, probe, read


def verify(out):
    manifest = read(out / "manifest.json")
    assert 60 <= manifest["duration"] <= 90
    assert {"Iraj", "Stefanny", "Lance", "Mario"} <= {b["speaker"] for b in manifest["blocks"]}
    assert len(manifest["synthesis"]) <= 10
    assert sum(x["characters"] for x in manifest["synthesis"]) < 2500
    assert all(x["status"] == "completed" for x in manifest["synthesis"])
    assert {r["speaker"] for r in manifest["reactions"]} == {"Iraj", "Stefanny", "Lance", "Mario"}
    for reaction in manifest["reactions"]:
        assert any(s["speaker"] == reaction["speaker"] and s["text"] == reaction["text"]
                   and s["start"] == reaction["start"] for s in manifest["captions"])
        assert all(reaction["end"] <= b["start"] or reaction["start"] >= b["end"]
                   for b in manifest["blocks"])
    assert 150 <= sum(len(b["text"].split()) for b in manifest["blocks"]) <= 200
    beats = manifest["beats"]
    assert beats[0]["start"] == 0 and beats[-1]["end"] == manifest["duration"]
    assert all(.99999 <= b["end"]-b["start"] <= 3.00001 for b in beats)
    assert all(abs(a["end"]-b["start"]) < .00001 for a,b in zip(beats, beats[1:]))
    for block in manifest["blocks"]:
        subs = [s for s in manifest["captions"] if block["start"] <= s["start"] < block["end"]]
        assert " ".join(s["text"] for s in subs).split() == block["text"].split()
        assert all(s["speaker"] == block["speaker"] for s in subs)
    result = {"duration": manifest["duration"], "source": manifest["source"],
              "evidence": manifest["evidence"], "files": {}}
    for name, dimensions in (("extension_demo_v3.mp4", (1920,1080)),
                             ("extension_demo_v3_discord.mp4", (1280,720))):
        path = out / name
        metadata = probe(path)
        video = next(s for s in metadata["streams"] if s["codec_type"] == "video")
        audio = next(s for s in metadata["streams"] if s["codec_type"] == "audio")
        assert (video["width"],video["height"]) == dimensions
        assert video["codec_name"] == "h264" and audio["codec_name"] == "aac"
        assert abs(float(metadata["format"]["duration"])-manifest["duration"]) < .15
        assert abs(float(audio["duration"])-manifest["duration"]) < .15
        if "discord" in name:
            assert path.stat().st_size < 20_000_000
        subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"], check=True)
        result["files"][name] = {"bytes": path.stat().st_size,
            "sha256": hashlib.file_digest(path.open("rb"), "sha256").hexdigest(),
            "video": f"{video['width']}x{video['height']}", "audio_seconds": audio["duration"]}
    assert (out / "contact_sheet.jpg").stat().st_size > 0
    (out / "verification.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=HERE / "out")
    verify(parser.parse_args().out)
