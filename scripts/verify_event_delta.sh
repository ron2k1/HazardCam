#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/_python.sh
. scripts/_python.sh
# shellcheck source=scripts/_boundary.sh
. scripts/_boundary.sh
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
mapfile -t EVAL_HITS < <(eval_import_hits)
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
  echo
  echo "== imports of the judge-side eval package from ${EVENT_DAY_CODE_DIRS[*]} =="
  if ((${#EVAL_HITS[@]})); then
    printf 'FORBIDDEN_EVAL_IMPORT %s\n' "${EVAL_HITS[@]}"
  else
    echo "none"
  fi
} | tee artifacts/event_day/DELTA_REPORT.txt

# Decided out here: the report block above runs in a subshell.
if ((${#EVAL_HITS[@]})); then
  echo "event-day code imports eval/ (see artifacts/event_day/DELTA_REPORT.txt)" >&2
  exit 1
fi
