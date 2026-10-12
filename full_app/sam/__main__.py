"""Offline by default: python -m sam input.mp4 output.mp4 --end 5."""
import argparse

from .effects import render_effect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("output")
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--effect", choices=["spotlight_freeze", "outline_pulse", "background_blur"], default="outline_pulse")
    parser.add_argument("--kill-time", type=float)
    parser.add_argument("--freeze-seconds", type=float, default=.6)
    parser.add_argument("--prompt", default="player character")
    parser.add_argument("--vertical", action="store_true")
    args = vars(parser.parse_args())
    print(render_effect(**args))


if __name__ == "__main__":
    main()
