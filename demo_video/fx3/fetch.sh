#!/usr/bin/env bash
# Copy only top-level deliverables, not intermediate rendering directories.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
command -v cygpath >/dev/null && ROOT="$(cygpath -u "$ROOT")"
RUNNER_IP="${RUNNER_IP:-$(cat "$ROOT/tools/runner_ip")}"
KEY="${RUNNER_KEY:-$HOME/.ssh/village_vultr}"
mkdir -p "$ROOT/demo_video/fx3/out"
rsync -az --exclude '*/' -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new" \
  "root@$RUNNER_IP:/srv/demo_out/fx3/" "$ROOT/demo_video/fx3/out/"
