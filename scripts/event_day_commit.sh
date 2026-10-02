#!/usr/bin/env bash
set -euo pipefail
TASK_ID="${1:?usage: event_day_commit.sh D00}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not a git repo; skipping commit." >&2
  exit 0
fi
git add agent runtime tests artifacts/event_day config/models/gb10.yaml scripts 2>/dev/null || true
if git diff --cached --quiet; then
  echo "No staged changes for $TASK_ID"
  exit 0
fi
git commit -m "event-day: $TASK_ID"
