#!/usr/bin/env bash
# Event day (2026-10-03, D02): start the API with the OpenClaw agent as its run executor.
#
#   scripts/runtime/start_api.sh            # agent: urban-mirror in the NemoClaw sandbox
#   AUM_EXECUTOR=dev scripts/runtime/start_api.sh   # fallback: the dev-sequence harness
#
# Agent mode runs agent.event_day.app:create_agent_app. Each run calls
#   openshell sandbox exec -n $AUM_SANDBOX -- openclaw agent --agent urban-mirror ...
# so the turn runs on the sandbox's OpenClaw gateway with Qwen via inference.local, and
# the agent's mirror__* tools call back to the host MCP server on 172.18.0.1:8090
# (host.openshell.internal inside the sandbox; egress preset mirror-tools). Deploy the
# agent first: .venv/bin/python scripts/runtime/deploy_agent.py
#
# Env: API_PORT (8088; the OpenShell gateway owns 8080), AUM_SANDBOX (ambient-mirror),
# AUM_EXECUTOR (agent|dev), MODEL_PROFILE (gb10). Runs in the foreground.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"
export PATH="$HOME/.local/bin:$PATH"

API_PORT="${API_PORT:-8088}"
AUM_EXECUTOR="${AUM_EXECUTOR:-agent}"
AUM_SANDBOX="${AUM_SANDBOX:-ambient-mirror}"
export MODEL_PROFILE="${MODEL_PROFILE:-gb10}"
TOKEN_FILE="${AUM_PRIVATE_DIR:-$HOME/.config/ambient-mirror}/tools.token"
BRIDGE_IP="${AUM_BRIDGE_IP:-172.18.0.1}"

if [[ "$AUM_EXECUTOR" == "dev" ]]; then
  echo "executor: dev-sequence (fallback) on 127.0.0.1:$API_PORT"
  exec .venv/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port "$API_PORT" \
    --log-level info
fi

if [[ ! -s "$TOKEN_FILE" ]]; then
  echo "no tool token at $TOKEN_FILE; run scripts/runtime/deploy_agent.py first" >&2
  exit 1
fi
AUM_TOOLS_TOKEN="$(cat "$TOKEN_FILE")"
export AUM_TOOLS_TOKEN
export AUM_TOOLS_BIND="127.0.0.1:8090,$BRIDGE_IP:8090"
export AUM_OPENCLAW_CMD="$(command -v openshell) sandbox exec -n $AUM_SANDBOX -- openclaw"

echo "executor: openclaw agent urban-mirror in sandbox $AUM_SANDBOX on 127.0.0.1:$API_PORT"
echo "tools: mirror MCP on $AUM_TOOLS_BIND (bearer token from $TOKEN_FILE)"
exec .venv/bin/python -m uvicorn --factory agent.event_day.app:create_agent_app \
  --host 127.0.0.1 --port "$API_PORT" --log-level info
