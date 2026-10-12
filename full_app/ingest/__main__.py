"""CLI: python -m ingest VIDEO [--cache-dir PATH]."""

import argparse
import json
import sys

from . import IngestError, Limits, prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("--cache-dir")
    parser.add_argument("--proxy-height", type=int, choices=[480, 720], default=480)
    parser.add_argument("--chunk-seconds", type=float, default=900)
    parser.add_argument("--overlap-seconds", type=float, default=15)
    parser.add_argument("--max-bytes", type=int, default=Limits().max_bytes)
    parser.add_argument("--max-duration", type=float, default=Limits().max_duration)
    parser.add_argument("--owns-content", action="store_true", help="I own or have rights to the URL content")
    parser.add_argument("--chat-log")
    parser.add_argument("--twitch-vod-id")
    parser.add_argument("--chat-offset", type=float, default=0)
    args = vars(parser.parse_args())
    try:
        limits = Limits(args.pop("max_bytes"), args.pop("max_duration"))
        result = prepare(**args, limits=limits,
                         progress=lambda event: print(json.dumps(event), file=sys.stderr))
    except (IngestError, OSError) as exc:
        parser.exit(1, f"ingest: {exc}\n")
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
