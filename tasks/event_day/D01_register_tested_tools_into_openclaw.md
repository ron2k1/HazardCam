# D01 — Register tested tools into OpenClaw

**Phase:** event_day  
**Wave:** 11  
**Owner:** agent  
**Remote OK:** false  
**Dependencies:** D00

## Goal

EVENT DAY: register the existing tested tool implementations into the newly created agent with least privilege.

## Allowed paths

- `agent/**`
- `runtime/**`
- `tests/integration/agent/**`
- `artifacts/event_day/**`

## Acceptance criteria

- [ ] Only allowed cameras accessible
- [ ] Tool schemas match prebuild contracts
- [ ] Agent integration test passes
- [ ] Generic ground-truth filesystem path inaccessible

## Worker report

Before marking complete, write `artifacts/workers/D01.md` with changed files, commands/tests run, results, assumptions, and blockers.

## Event-day integrity

This task must be performed on event day. Do not copy a prebuilt finished agent/runtime implementation into place and represent it as newly authored. Use the prepared libraries/interfaces, then create the agent integration now.

## Fresh-build requirement

Implement the OpenClaw-specific portion for this task from the current repository state during the event-day session. Reuse already-tested ordinary libraries/interfaces, but do not source or copy a prewritten hidden OpenClaw implementation from outside the event-day working tree. Record commands/tests in `artifacts/event_day/workers/`.

## Operator addendum (event day, 2026-10-03)

- **Telegram deferred (see D02's superseding bullet).** While registering the tools, remove the `message` grant that D00 put in `agent/event_day/openclaw/agent.json` (the `message` entry in `tools.alsoAllow` and the `message` actions block). Keep D00's one-alert guard in `policy.py`, but disarmed by default behind one explicit setting, so the alert can be re-enabled later without code changes. Update the D00 tests that assert the grant. No Telegram channel, egress or token anywhere.
- **Separate feature, out of scope here.** A "Safety hazard" single-camera review and its UI are being built in parallel under `hazards/`, `apps/api/**` and `apps/web/**`. Do not edit those paths.
