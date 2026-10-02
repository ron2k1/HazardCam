#!/usr/bin/env bash
set -euo pipefail
TASK_ID="${1:?usage: spawn_code_worker.sh TASK_ID [claude|codex|ultracode] [local|remote]}"
ENGINE="${2:-claude}"
WHERE="${3:-local}"
PROMPT="$(find tasks -type f -name "${TASK_ID}_*.md" | head -1)"
[ -n "$PROMPT" ] || { echo "Task prompt not found for $TASK_ID" >&2; exit 2; }
mkdir -p artifacts/workers

if [ "$WHERE" = "remote" ]; then
  exec "$(dirname "$0")/spawn_remote_code_worker.sh" "$TASK_ID" "$ENGINE"
fi

WT="$("$(dirname "$0")/create_worktree.sh" "$TASK_ID")"
cp "$PROMPT" "$WT/WORKER_PROMPT.md"
LOG="$(git rev-parse --show-toplevel)/artifacts/workers/${TASK_ID}_${ENGINE}.log"

case "$ENGINE" in
  claude)
    (cd "$WT" && claude -p "$(cat WORKER_PROMPT.md)" --output-format text --max-turns "${MAX_TURNS:-40}") | tee "$LOG"
    ;;
  ultracode)
    if command -v ultracode >/dev/null 2>&1; then
      (cd "$WT" && ultracode run "$(cat WORKER_PROMPT.md)") | tee "$LOG"
    else
      echo "Standalone ultracode binary not installed. Use Claude Code Ultracode for orchestration or set ENGINE=claude." >&2
      exit 3
    fi
    ;;
  codex)
    if command -v codex >/dev/null 2>&1; then
      # Codex CLI syntax varies by release; prefer a user-supplied template when set.
      if [ -n "${CODEX_WORKER_CMD:-}" ]; then
        (cd "$WT" && WORKER_PROMPT="$(cat WORKER_PROMPT.md)" bash -lc "$CODEX_WORKER_CMD") | tee "$LOG"
      else
        echo "codex found, but CODEX_WORKER_CMD is not set. Set it to the headless command for your installed version." >&2
        echo "Example concept: CODEX_WORKER_CMD='codex exec \"$WORKER_PROMPT\"' (verify your local CLI first)." >&2
        exit 4
      fi
    else
      echo "codex not installed" >&2; exit 3
    fi
    ;;
  *) echo "Unknown engine: $ENGINE" >&2; exit 2 ;;
esac

echo "Worker finished. Review branch worker/$TASK_ID and $LOG"
