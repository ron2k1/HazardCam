#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/_python.sh
. scripts/_python.sh
mkdir -p artifacts/event_day
BASE_COMMIT=""
if [ -f artifacts/PREBUILD_SNAPSHOT.json ]; then
  BASE_COMMIT="$(py - <<'PY'
import json
try:
 print(json.load(open('artifacts/PREBUILD_SNAPSHOT.json')).get('git_commit') or '')
except Exception:
 print('')
PY
)"
fi
{
  echo "verified_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "prebuild_commit=${BASE_COMMIT:-unknown}"
  echo "current_commit=$(git rev-parse HEAD 2>/dev/null || echo no-git)"
  echo
  echo "== current status =="
  git status --short 2>/dev/null || true
  echo
  echo "== event-agent relevant diff =="
  if [ -n "$BASE_COMMIT" ] && git cat-file -e "$BASE_COMMIT^{commit}" 2>/dev/null; then
    git diff --stat "$BASE_COMMIT" -- agent runtime config/models/gb10.yaml scripts/runtime tests/integration/agent tests/integration/runtime 2>/dev/null || true
    echo
    git diff --name-status "$BASE_COMMIT" -- agent runtime config/models/gb10.yaml scripts/runtime tests/integration/agent tests/integration/runtime 2>/dev/null || true
  else
    echo "No usable prebuild git commit in snapshot; compare timestamps/checksums manually."
  fi
} | tee artifacts/event_day/DELTA_REPORT.txt
