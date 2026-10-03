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

## Operator addendum (added on event day, 2026-10-03)

The team wants a Telegram alert when the agent detects an abnormality. Design it into the agent definition, playbook and policy:

- After a successful `submit_hypothesis` whose result is not an abstention (a known event type at or above the policy's abstention threshold), the agent sends one short alert through OpenClaw's Telegram channel (the channel itself is registered by the operator with `nemoclaw ambient-mirror channels add telegram` and wired in D02): event type, confidence, coarse region, the supporting camera ids and timestamps, and the run id. Abstentions send no alert.
- At most one alert per run. The alert never contains ground truth or judge data (the agent has none), raw frames, tokens, or token-bearing URLs.
- The alert is best effort: a Telegram failure (no network, token rejected, channel absent) must not fail or delay the run, the SSE stream or the UI. The judged path stays fully local.
- Allow only the messaging capability needed for this one send; keep every other tool group denied.
- The bot token never appears in repo files, logs or artifacts; it lives only in the OpenShell gateway credential store.
