#!/usr/bin/env bash
# Copy only published SAMFIX outputs, then check all four video hashes locally.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
command -v cygpath >/dev/null && ROOT="$(cygpath -u "$ROOT")"
IP="${RUNNER_IP:-$(cat "$ROOT/tools/runner_ip")}"
KEY="${RUNNER_KEY:-$HOME/.ssh/village_vultr}"
mkdir -p "$ROOT/demo_video/samfix/out"
rsync -az -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new" \
  --exclude landscape/ --exclude mean_vertical/ \
  "root@$IP:/srv/demo_out/samfix/" "$ROOT/demo_video/samfix/out/"
cd "$ROOT/demo_video/samfix/out"
sha256sum --check SHA256SUMS
