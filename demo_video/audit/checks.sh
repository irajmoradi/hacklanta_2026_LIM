#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/../.."
mkdir -p demo_video/audit/out
cd full_app
python -m pytest -q --disable-warnings --ignore=tests/test_video_live.py > ../demo_video/audit/out/pytest.log 2>&1
rc=$?
echo "pytest exit=$rc"
tail -40 ../demo_video/audit/out/pytest.log
exit "$rc"
