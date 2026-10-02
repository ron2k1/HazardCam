#!/usr/bin/env bash
set -euo pipefail
TASK_ID="${1:?usage: event_day_task_runner.sh D00 [claude|print]}"
ENGINE="${2:-claude}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

[ -f artifacts/event_day/START.txt ] || {
  echo "Run ./scripts/event_day_start.sh first." >&2
  exit 2
}

PROMPT="$(find tasks/event_day -type f -name "${TASK_ID}_*.md" | head -1)"
[ -n "$PROMPT" ] || { echo "No event-day task prompt for $TASK_ID" >&2; exit 2; }

mkdir -p artifacts/event_day/workers
BUNDLE="artifacts/event_day/workers/${TASK_ID}_PROMPT.md"
cat CLAUDE.md > "$BUNDLE"
printf '\n\n--- EVENT-DAY BUILD PROTOCOL ---\n\n' >> "$BUNDLE"
cat docs/FRESH_EVENT_DAY_BUILD.md >> "$BUNDLE"
printf '\n\n--- TASK ---\n\n' >> "$BUNDLE"
cat "$PROMPT" >> "$BUNDLE"
printf '\n\n--- EXECUTION RULES ---\n\n' >> "$BUNDLE"
cat >> "$BUNDLE" <<'RULES'
Implement this task against the current repository state. Inspect existing interfaces before editing. Reuse tested ordinary libraries; do not reimplement them inside the agent. Run the task's acceptance tests/commands. Record a short report under artifacts/event_day/workers/. Do not claim success for commands you did not execute.
RULES

case "$ENGINE" in
  claude)
    command -v claude >/dev/null 2>&1 || { echo "claude CLI not found" >&2; exit 3; }
    claude -p "$(cat "$BUNDLE")" --output-format text --max-turns "${MAX_TURNS:-45}" | tee "artifacts/event_day/workers/${TASK_ID}_claude.log"
    ;;
  print)
    cat "$BUNDLE"
    ;;
  *)
    echo "Unsupported engine: $ENGINE (use claude or print)" >&2
    exit 2
    ;;
esac
