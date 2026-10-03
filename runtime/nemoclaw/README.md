# NemoClaw/OpenShell runtime (event day, D02)

Written on event day (2026-10-03). It runs the OpenClaw agent `urban-mirror` (D00/D01, in
`agent/event_day/`) inside the NemoClaw sandbox `ambient-mirror`, with only local models.

```
browser :3000 ──SSE── API :8088 (agent.event_day.app, executor = OpenClawAgentExecutor)
                         │  per run: openshell sandbox exec -n ambient-mirror -- openclaw agent
                         │           --agent urban-mirror --session-key <run_id> --json
                         ▼
          sandbox ambient-mirror (OpenShell 0.0.116, OpenClaw 2026.7.1 gateway)
             agent brain: inference/nvidia/Qwen3.6-35B-A3B-NVFP4 via https://inference.local
                          (NemoClaw provider vllm-local -> host vLLM :8000)
             tools: mirror__* MCP -> http://host.openshell.internal:8090/mcp (preset mirror-tools)
                         │
                         ▼
          host tool server 172.18.0.1:8090 + 127.0.0.1:8090 (bearer token)
             -> tools.session -> Qwen :8000 (perception), Cosmos-Reason2-8B :8001 (reasoning slot)
```

## Commands

```bash
export PATH="$HOME/.local/bin:$PATH"

# 1. deploy the agent, the MCP registration and the egress preset into the sandbox
.venv/bin/python scripts/runtime/deploy_agent.py            # --dry-run to preview

# 2. start the API with the agent executor on 127.0.0.1:8088 (the gateway owns :8080)
scripts/runtime/start_api.sh
#    fallback: the dev-sequence harness, same API and UI
AUM_EXECUTOR=dev scripts/runtime/start_api.sh

# 3. capture stack status and local model health into artifacts/event_day/runtime/
scripts/runtime/capture_status.sh

# tests (hermetic; the live check needs the GB10)
.venv/bin/python -m pytest tests/integration/runtime
AUM_LIVE_RUNTIME=1 .venv/bin/python -m pytest tests/integration/runtime
```

The web app reads the API at `NEXT_PUBLIC_API_BASE_URL` (`http://127.0.0.1:8088` here). Pick
the `gb10` profile in `/ops` (or open `/ops?profile=gb10`) for real perception and reasoning.

## Files

- `mirror-tools.policy.yaml`: the only egress D02 adds. `openclaw`/`node` may reach
  `host.openshell.internal:8090` (pinned to `172.18.0.1/32`), `POST`/`DELETE /mcp` only. The
  OpenClaw MCP client's optional `GET /mcp` stream is denied at L7; the server would answer 405.
- `../../scripts/runtime/deploy_agent.py`: merges D01's registration into the sandbox
  `openclaw.json` (as the sandbox user, via `openshell sandbox exec`), refreshes `.config-hash`
  so the gateway hot-reloads, and copies the D00 workspace to
  `/sandbox/.openclaw/workspace-urban-mirror`. The previous config is kept in the sandbox as
  `openclaw.json.pre-d02`.
- `../../scripts/runtime/start_api.sh`, `../../scripts/runtime/capture_status.sh`.

## Security notes

- Tool token: `~/.config/ambient-mirror/tools.token` (0600, outside the repo). The NemoClaw
  gateway process has no `AUM_TOOLS_TOKEN` in its environment, so the sandbox `openclaw.json`
  (0600, sandbox user) holds the literal bearer header. The agent's tool policy denies
  `group:fs` and `group:runtime`, so it cannot read the file. `nemoclaw mcp add` was not used:
  it requires HTTPS and rejects `host.openshell.internal`.
- No cloud model route: the sandbox's only model provider is `inference` ->
  `https://inference.local/v1` (vllm-local), the agent has no fallbacks, the `gb10` profile
  points at loopback only, and the baseline `nvidia` egress entry
  (`integrate.api.nvidia.com`) was excluded with `nemoclaw ambient-mirror policy exclude nvidia`
  (undo: `policy restore nvidia`).
- Telegram is deferred: no channel, no Telegram egress, no `message` tool. D00's alert stays off
  unless `AUM_AGENT_TELEGRAM_ALERT` is set.

## Failure path

If the sandbox, gateway or agent cannot run a turn, `OpenClawAgentExecutor` raises
`AgentRunError` and the API emits `run.failed` with `stage: "agent"` and a one-line error
(for example `sandbox not found`). `/ops` shows it in the failure banner and the run phase
turns `failed`. A turn that runs but never submits abstains instead.
