#!/usr/bin/env bash
# Keep runner-only consented media during remote_run.sh's --delete sync.
# This does not change the test command or application environment.
set -euo pipefail
rsync() {
  command rsync --filter='P full_app/reaction_packs/***' "$@"
}
export -f rsync
bash tools/remote_run.sh "$@"
