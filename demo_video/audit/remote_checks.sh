#!/usr/bin/env bash
# Preserve this audit's active evidence and runner-only consented reaction pack.
# All synchronization and execution still use the required tools/remote_run.sh.
set -euo pipefail
rsync() {
  command rsync --exclude 'demo_video/audit/out' --exclude 'full_app/reaction_packs' "$@"
}
export -f rsync
bash tools/remote_run.sh "$@"
