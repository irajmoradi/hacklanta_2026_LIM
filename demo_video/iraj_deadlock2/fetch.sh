#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
runner="${RUNNER_IP:-$(cat tools/runner_ip)}"
key="${RUNNER_KEY:-$HOME/.ssh/village_vultr}"
mkdir -p demo_video/iraj_deadlock2/out
filters=(--exclude render_tmp/ --exclude extensions_tmp/)
if [ "${1:-}" = "--contacts" ]; then
  filters+=(--include '*/' --include '*.jpg' --include '*.json' --exclude '*')
fi
rsync -az "${filters[@]}" -e "ssh -i $key" "root@$runner:/srv/demo_out/iraj_deadlock2/" demo_video/iraj_deadlock2/out/
