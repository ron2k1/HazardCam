#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/_boundary.sh
. scripts/_boundary.sh
OUT="${1:-artifacts/PREBUILD_BOUNDARY_CHECK.txt}"
mkdir -p "$(dirname "$OUT")"

mapfile -t BAD < <(find agent -type f \
  ! -name '*.template.md' \
  ! -name '*.template.txt' \
  ! -name '*.template.json' \
  ! -name 'README.md' \
  ! -name '.gitkeep' \
  \( -name '*.py' -o -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.mjs' -o -name '*.cjs' -o -name '*.yaml' -o -name '*.yml' -o -name '*.toml' -o -name '*.json' -o -name '*.md' \) -print)
mapfile -t EVAL_HITS < <(eval_import_hits)

# The report block feeds tee, so it runs in a subshell: the verdict is decided below from
# the arrays, never from a variable assigned inside the block.
{
  echo "Ambient Urban Mirror prebuild boundary check"
  echo "UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo "Allowed prebuild agent files: templates/readmes only."
  echo
  echo "Executable-looking files under agent/:"
  if ((${#BAD[@]})); then
    printf 'FORBIDDEN_PREBUILD_AGENT_FILE %s\n' "${BAD[@]}"
  else
    echo "PASS: no finished agent implementation detected."
  fi
  echo
  echo "Imports of the judge-side eval package from ${EVENT_DAY_CODE_DIRS[*]}:"
  if ((${#EVAL_HITS[@]})); then
    printf 'FORBIDDEN_EVAL_IMPORT %s\n' "${EVAL_HITS[@]}"
  else
    echo "PASS: none."
  fi
  echo
  echo "Event-day directory contents:"
  find agent/event_day -maxdepth 1 -type f -printf '%f\n' 2>/dev/null | sort || true
} | tee "$OUT"

if ((${#BAD[@]} + ${#EVAL_HITS[@]})); then
  echo "boundary check FAILED (see $OUT)" >&2
  exit 1
fi
