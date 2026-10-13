#!/usr/bin/env bash
# Fetch the ignored deliverables after render_saved.py finishes on runner 1.
set -euo pipefail
cd "$(dirname "$0")/../.."
runner="${RUNNER_IP:-$(cat tools/runner_ip)}"
key="${RUNNER_KEY:-$HOME/.ssh/village_vultr}"
mkdir -p demo_video/polish1/out
for cut in valorant_nice_landscape valorant_mean_vertical; do
  scp -i "$key" -r "root@$runner:/srv/demo_out/polish1/$cut" demo_video/polish1/out/
done
scp -i "$key" "root@$runner:/srv/demo_out/polish1/live_calls.json" \
  "root@$runner:/srv/demo_out/polish1/pytest.log" demo_video/polish1/out/
scp -i "$key" "root@$runner:/srv/demo_out/polish1-render.log" demo_video/polish1/out/render.log
