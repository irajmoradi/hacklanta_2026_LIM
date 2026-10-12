"""Usage: python -m signals gameplay.mp4 [--profile valorant] [--ocr]."""

import argparse
import json
import subprocess
import sys

from . import detect_candidates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("--profile", default="auto")
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--config", default="{}", help="JSON object of Config overrides")
    args = parser.parse_args()
    try:
        config = json.loads(args.config)
        if not isinstance(config, dict):
            raise ValueError("--config must be a JSON object")
        if args.ocr:
            config["ocr"] = True
        results = detect_candidates(args.video, profile=args.profile, **config)
    except (ValueError, TypeError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"signals: {exc}", file=sys.stderr)
        return 2
    print(json.dumps([candidate.to_dict() for candidate in results], allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
