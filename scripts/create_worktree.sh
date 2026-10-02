#!/usr/bin/env bash
set -euo pipefail
TASK_ID="${1:?usage: create_worktree.sh TASK_ID}"
ROOT="$(git rev-parse --show-toplevel)"
WT="$ROOT/.worktrees/$TASK_ID"
BRANCH="worker/$TASK_ID"
mkdir -p "$ROOT/.worktrees"
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  git worktree add "$WT" "$BRANCH"
else
  git worktree add -b "$BRANCH" "$WT" HEAD
fi
printf '%s\n' "$WT"
