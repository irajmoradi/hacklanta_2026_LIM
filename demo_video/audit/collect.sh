#!/usr/bin/env bash
set -euo pipefail
# Evidence only; deliberately omit source footage, private job state and caches.
rsync -a --exclude workspace/ --exclude input_4min.mp4 --exclude 'diagnostic_*/' \
  -e 'ssh -i /c/Users/mourn/.ssh/village_vultr' \
  root@104.207.133.47:/srv/lim/lim-audit2/demo_video/audit/out/ demo_video/audit/out/
