#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT="${1:-artifacts/PREBUILD_BOUNDARY_CHECK.txt}"
mkdir -p "$(dirname "$OUT")"

fail=0
{
  echo "Ambient Urban Mirror prebuild boundary check"
  echo "UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo "Allowed prebuild agent files: templates/readmes only."
  echo
  echo "Executable-looking files under agent/:"
  mapfile -t BAD < <(find agent -type f \
    ! -name '*.template.md' \
    ! -name '*.template.txt' \
    ! -name '*.template.json' \
    ! -name 'README.md' \
    ! -name '.gitkeep' \
    \( -name '*.py' -o -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.mjs' -o -name '*.cjs' -o -name '*.yaml' -o -name '*.yml' -o -name '*.toml' -o -name '*.json' -o -name '*.md' \) -print)
  if ((${#BAD[@]})); then
    printf 'FORBIDDEN_PREBUILD_AGENT_FILE %s\n' "${BAD[@]}"
    fail=1
  else
    echo "PASS: no finished agent implementation detected."
  fi
  echo
  echo "Event-day directory contents:"
  find agent/event_day -maxdepth 1 -type f -printf '%f\n' 2>/dev/null | sort || true
} | tee "$OUT"

exit "$fail"
