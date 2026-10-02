#!/usr/bin/env bash
set -euo pipefail
PROMPT_FILE="${1:-PREBUILD_ORCHESTRATOR_PROMPT.md}"
if ! command -v claude >/dev/null 2>&1; then
  echo "claude CLI not found. Install/authenticate Claude Code first." >&2
  exit 1
fi

echo "Claude version: $(claude --version 2>/dev/null || true)"
echo "Starting Claude session with $PROMPT_FILE"

if claude --help 2>&1 | grep -q -- '--effort'; then
  exec claude --effort ultracode "$(cat "$PROMPT_FILE")"
else
  echo "This CLI does not advertise --effort; starting normally." >&2
  echo "Enable the highest available workflow/agent effort inside the session if supported." >&2
  exec claude "$(cat "$PROMPT_FILE")"
fi
