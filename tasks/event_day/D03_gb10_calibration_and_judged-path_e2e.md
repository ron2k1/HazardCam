# D03 — GB10 calibration and judged-path E2E

**Phase:** event_day  
**Wave:** 13  
**Owner:** verifier  
**Remote OK:** false  
**Dependencies:** D02

## Goal

EVENT DAY: calibrate deployment-only parameters, run real judged scenario, measure latency, verify ground-truth exclusion.

## Allowed paths

- `config/models/gb10.yaml`
- `tests/e2e/**`
- `artifacts/**`
- `scripts/**`

## Acceptance criteria

- [ ] Real Qwen+Mistral+OpenClaw path completes
- [ ] Latency recorded
- [ ] Ground-truth exclusion proof
- [ ] Playwright screenshot

## Worker report

Before marking complete, write `artifacts/workers/D03.md` with changed files, commands/tests run, results, assumptions, and blockers.

## Event-day integrity

This task must be performed on event day. Do not copy a prebuilt finished agent/runtime implementation into place and represent it as newly authored. Use the prepared libraries/interfaces, then create the agent integration now.

## Fresh-build requirement

Implement the OpenClaw-specific portion for this task from the current repository state during the event-day session. Reuse already-tested ordinary libraries/interfaces, but do not source or copy a prewritten hidden OpenClaw implementation from outside the event-day working tree. Record commands/tests in `artifacts/event_day/workers/`.
