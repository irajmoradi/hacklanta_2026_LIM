"""Run with python -m audio_ai input.mp4 (JSON on stdout)."""

import argparse

from . import analyze


def main():
    parser = argparse.ArgumentParser(description="Extract per-second audio evidence offline")
    parser.add_argument("video")
    parser.add_argument("--audio-track", type=int, default=0)
    parser.add_argument("--speech", choices=["auto", "off", "whisper"], default="auto")
    parser.add_argument("--whisper-model", default="tiny")
    parser.add_argument("--allow-model-downloads", action="store_true")
    parser.add_argument("--vad", choices=["auto", "energy", "webrtc"], default="auto")
    parser.add_argument("--yamnet-model", help="Local YAMNet SavedModel directory")
    args = parser.parse_args()
    result = analyze(args.video, audio_track=args.audio_track, speech=args.speech,
                     whisper_model=args.whisper_model, allow_model_downloads=args.allow_model_downloads,
                     vad=args.vad, events="yamnet" if args.yamnet_model else "heuristic",
                     yamnet_model=args.yamnet_model)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
