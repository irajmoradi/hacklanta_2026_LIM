"""python -m privacy input.mp4 private.mp4 --options options.json --track track.json"""
import argparse
import json
from pathlib import Path

from . import sanitize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--options", type=Path)
    parser.add_argument("--track", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.options.read_text(encoding="utf-8")) if args.options else {}
    _, track = sanitize(args.source, args.output, payload)
    if args.track:
        args.track.write_text(track.model_dump_json(indent=2), encoding="utf-8")
    for warning in track.warnings:
        print(f"Privacy warning: {warning}")


if __name__ == "__main__":
    main()
