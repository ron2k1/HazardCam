# D00 — Create OpenClaw agent definition and playbook

**Phase:** event_day  
**Wave:** 10  
**Owner:** agent  
**Remote OK:** false  
**Dependencies:** P16

## Goal

EVENT DAY: create the actual OpenClaw agent definition, system prompt/playbook, bounded policy, and abstention behavior.

## Allowed paths

- `agent/**`
- `artifacts/event_day/**`

## Acceptance criteria

- [ ] Files created/changed after event-day start
- [ ] Agent policy documented
- [ ] No ground-truth access
- [ ] Alternatives/limitations/abstention

## Worker report

Before marking complete, write `artifacts/workers/D00.md` with changed files, commands/tests run, results, assumptions, and blockers.

## Event-day integrity

This task must be performed on event day. Do not copy a prebuilt finished agent/runtime implementation into place and represent it as newly authored. Use the prepared libraries/interfaces, then create the agent integration now.

## Fresh-build requirement

Implement the OpenClaw-specific portion for this task from the current repository state during the event-day session. Reuse already-tested ordinary libraries/interfaces, but do not source or copy a prewritten hidden OpenClaw implementation from outside the event-day working tree. Record commands/tests in `artifacts/event_day/workers/`.
