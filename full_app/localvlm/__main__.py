"""Run from full_app: python -m localvlm --help."""

import argparse
import json
import os
from pathlib import Path
import shlex

from . import LocalVLMProvider, RuntimeConfig, health_check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["launch", "health", "score"])
    parser.add_argument("--backend", choices=["vllm", "ollama"], default="vllm")
    parser.add_argument("--model")
    parser.add_argument("--url")
    parser.add_argument("--decoding", choices=["schema", "vllm", "json", "prompt"], default="schema")
    parser.add_argument("--video", type=Path)
    parser.add_argument("--candidates", type=Path, help="JSON array using the ScoringCandidate schema")
    args = parser.parse_args()
    runtime = RuntimeConfig(backend=args.backend, decoding=args.decoding,
        model=args.model or ("qwen2.5vl:7b" if args.backend == "ollama" else "Qwen/Qwen2.5-VL-7B-Instruct"),
        base_url=args.url or ("http://127.0.0.1:11434/v1" if args.backend == "ollama" else "http://127.0.0.1:8000/v1"))
    if args.command == "launch":
        for command in runtime.launch_commands():
            print(shlex.join(command))
        return 0
    key = os.getenv("LOCAL_VLM_API_KEY")
    if args.command == "health":
        result = health_check(runtime, api_key=key)
        print(json.dumps(result))
        return 0 if result["ok"] else 1
    if not args.video or not args.candidates:
        parser.error("score requires --video and --candidates")
    provider = LocalVLMProvider(runtime, api_key=key)
    results = provider.score_windows(args.video, json.loads(args.candidates.read_text(encoding="utf-8")))
    print(json.dumps([r.model_dump() for r in results], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
