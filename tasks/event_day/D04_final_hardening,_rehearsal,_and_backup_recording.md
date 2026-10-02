# D04 — Final hardening, rehearsal, and backup recording

**Phase:** event_day  
**Wave:** 14  
**Owner:** integrator  
**Remote OK:** true  
**Dependencies:** D03

## Goal

EVENT DAY: eliminate fragile dependencies, warm models, rehearse 3-minute story, and record fallback demo.

## Allowed paths

- `apps/**`
- `scripts/**`
- `docs/**`
- `artifacts/**`

## Acceptance criteria

- [ ] demo-check passes 3x
- [ ] Backup recording exists
- [ ] 3-minute script rehearsed
- [ ] verify_event_delta.sh succeeds
- [ ] FINAL_VERIFICATION.md exists

## Worker report

Before marking complete, write `artifacts/workers/D04.md` with changed files, commands/tests run, results, assumptions, and blockers.

## Event-day integrity

This task must be performed on event day. Do not copy a prebuilt finished agent/runtime implementation into place and represent it as newly authored. Use the prepared libraries/interfaces, then create the agent integration now.

## Fresh-build requirement

Implement the OpenClaw-specific portion for this task from the current repository state during the event-day session. Reuse already-tested ordinary libraries/interfaces, but do not source or copy a prewritten hidden OpenClaw implementation from outside the event-day working tree. Record commands/tests in `artifacts/event_day/workers/`.
