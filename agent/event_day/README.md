# Event-day agent output directory

The prebuild package left this directory with no agent implementation. Everything here was
written on event day (2026-10-03), after `make event-day-start`, from the tested interfaces
in `tools/`, `contracts/` and `apps/api/schemas`.

- `POLICY.md`: the agent's policy, abstention and alert rules, the D01 registration and the hand-off to D02 (start here)
- `openclaw/agent.json`: the OpenClaw `agents.list[]` entry for `urban-mirror`
- `openclaw/workspace/`: playbook and identity files, injected into the agent's system prompt
- `policy.py`: the bounded tool policy the D01 registration puts between the agent and the tools
- `registration.py`: D01. Tool specs from the contract, agent-facing replies, the OpenClaw config
- `mcp_server.py`: D01. The `mirror` MCP server (Streamable HTTP, one path, bearer token)
- `executor.py`: D01. `OpenClawAgentExecutor`, the API's run executor for the agent
- `app.py`: D01. The API with the agent executor (`uvicorn --factory agent.event_day.app:create_agent_app`)
- `register.py`: D01. Merges the registration into an `openclaw.json`
- `hazard_tools.py`: hazard agent task. `HazardJobSession`, the three `mirror__hazard_*` tools
  for one leased clip (contract: `contracts/hazard_tools.schema.json`)
- `hazard_runner.py`: hazard agent task. `AgentHazardRunner`, the `/hazards` review seam
  (`app.state.hazard_review_runner`, name `openclaw-agent`): one OpenClaw turn per clip review
- `tests/`: D00 tests (`.venv/bin/python -m pytest agent/event_day/tests`); D01's are in
  `tests/integration/agent/`
