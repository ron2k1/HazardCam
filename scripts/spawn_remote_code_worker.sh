#!/usr/bin/env bash
set -euo pipefail
TASK_ID="${1:?usage: spawn_remote_code_worker.sh TASK_ID [claude]}"
ENGINE="${2:-claude}"
CFG="config/remote.env"
[ -f "$CFG" ] || { echo "Missing $CFG" >&2; exit 2; }
# shellcheck disable=SC1090
source "$CFG"
PROMPT="$(find tasks -type f -name "${TASK_ID}_*.md" | head -1)"
[ -n "$PROMPT" ] || { echo "Task prompt not found" >&2; exit 2; }
ROOT="$(git rev-parse --show-toplevel)"
REMOTE_DIR="${REMOTE_ROOT%/}/${TASK_ID}"
mkdir -p artifacts/workers

# This copies working files, not credentials. .git and secrets are excluded.
ssh "$REMOTE_ALIAS" "mkdir -p '$REMOTE_DIR'"
rsync -az --delete \
  --exclude '.git' --exclude '.worktrees' --exclude 'node_modules' \
  --exclude '.env' --exclude 'config/remote.env' --exclude 'artifacts' \
  "$ROOT/" "$REMOTE_ALIAS:$REMOTE_DIR/"
cat "$PROMPT" | ssh "$REMOTE_ALIAS" "cat > '$REMOTE_DIR/WORKER_PROMPT.md'"

case "$ENGINE" in
  claude)
    ssh "$REMOTE_ALIAS" "cd '$REMOTE_DIR' && claude -p \"\$(cat WORKER_PROMPT.md)\" --output-format text --max-turns ${MAX_TURNS:-40}" \
      | tee "artifacts/workers/${TASK_ID}_remote_claude.log"
    ;;
  *)
    echo "Remote engine '$ENGINE' not automated. Authenticate/configure it remotely and extend this adapter deliberately." >&2
    exit 3
    ;;
esac

echo "Remote worker changed a remote copy only. Review its report/log; sync code back deliberately rather than blind rsync overwrite."
