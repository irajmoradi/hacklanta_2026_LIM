#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$APP_ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec python -m demo.pipeline "$@"
