#!/usr/bin/env bash
# Run a command on the Linux test runner (has ffmpeg, python3, node, uv, tesseract).
# Usage (from a worktree root): tools/remote_run.sh "cd full_app && python -m pytest -q"
# Syncs this worktree (minus .git, node_modules, venvs, workspace outputs) and runs inside a per-worktree
# Python venv whose deps install from full_app/requirements*.txt (cached by their hash).
set -euo pipefail
RUNNER_IP="${RUNNER_IP:-$(cat "$(dirname "$0")/runner_ip" 2>/dev/null || true)}"
[ -n "$RUNNER_IP" ] || { echo "RUNNER_IP not set (tools/runner_ip)"; exit 2; }
KEY="${RUNNER_KEY:-$HOME/.ssh/village_vultr}"
ROOT="$(git rev-parse --show-toplevel)"; command -v cygpath >/dev/null && ROOT="$(cygpath -u "$ROOT")"
NAME="$(basename "$ROOT")"
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=20 "root@$RUNNER_IP")
rsync -az --delete -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new" \
  --exclude .git --exclude node_modules --exclude .venv --exclude 'full_app/workspace' --exclude '__pycache__' \
  "$ROOT/" "root@$RUNNER_IP:/srv/lim/$NAME/"
"${SSH[@]}" bash -s -- "$NAME" "$*" <<'REMOTE'
set -e
NAME="$1"; CMD="$2"; cd "/srv/lim/$NAME"
REQ=$(cat full_app/requirements*.txt 2>/dev/null | sha256sum | cut -c1-16)
if [ "$(cat .venv/.req 2>/dev/null)" != "$REQ" ]; then
  python3 -m venv .venv >/dev/null && . .venv/bin/activate
  pip install -q --upgrade pip >/dev/null
  for f in full_app/requirements*.txt; do pip install -q -r "$f"; done
  pip install -q pytest >/dev/null; echo "$REQ" > .venv/.req
fi
. .venv/bin/activate
set +e; bash -lc "$CMD"; RC=$?; echo "remote exit=$RC"; exit $RC
REMOTE
