# Event-day agent output directory

The prebuild package left this directory with no agent implementation. Everything here was
written on event day (2026-10-03), after `make event-day-start`, from the tested interfaces
in `tools/`, `contracts/` and `apps/api/schemas`.

- `POLICY.md`: the agent's policy, abstention and alert rules, and the hand-off to D01/D02 (start here)
- `openclaw/agent.json`: the OpenClaw `agents.list[]` entry for `urban-mirror`
- `openclaw/workspace/`: playbook and identity files, injected into the agent's system prompt
- `policy.py`: the bounded tool policy the D01 registration puts between the agent and the tools
- `tests/`: D00 tests (`.venv/bin/python -m pytest agent/event_day/tests`)
