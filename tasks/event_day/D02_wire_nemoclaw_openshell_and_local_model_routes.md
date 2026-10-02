# D02 — Wire NemoClaw/OpenShell and local model routes

**Phase:** event_day  
**Wave:** 12  
**Owner:** runtime  
**Remote OK:** false  
**Dependencies:** D01

## Goal

EVENT DAY: run the OpenClaw agent through the required NemoClaw/OpenShell stack and connect local inference routes.

## Allowed paths

- `runtime/**`
- `scripts/runtime/**`
- `config/models/gb10.yaml`
- `artifacts/event_day/**`
- `tests/integration/runtime/**`

## Acceptance criteria

- [ ] Required stack status captured
- [ ] No cloud model route
- [ ] Failure surfaced to UI
- [ ] Runtime command documented

## Worker report

Before marking complete, write `artifacts/workers/D02.md` with changed files, commands/tests run, results, assumptions, and blockers.

## Event-day integrity

This task must be performed on event day. Do not copy a prebuilt finished agent/runtime implementation into place and represent it as newly authored. Use the prepared libraries/interfaces, then create the agent integration now.

## Fresh-build requirement

Implement the OpenClaw-specific portion for this task from the current repository state during the event-day session. Reuse already-tested ordinary libraries/interfaces, but do not source or copy a prewritten hidden OpenClaw implementation from outside the event-day working tree. Record commands/tests in `artifacts/event_day/workers/`.
