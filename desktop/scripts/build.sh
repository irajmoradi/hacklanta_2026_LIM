#!/usr/bin/env bash
# Native macOS/Linux build. Pass --dry-run for an unpacked application.
set -euo pipefail
cd "$(dirname "$0")/.."
npm ci
npm run build -- "$@"
