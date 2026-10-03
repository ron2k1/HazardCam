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

## Operator addendum (event day, 2026-10-03)

- The reasoning slot is `nvidia/Cosmos-Reason2-8B` on `:8001`, a user-approved deviation from Mistral because the offline bundle has no Mistral weights. Record it as such; "Qwen+Mistral" in the criteria means Qwen + this reasoning slot. Qwen is `nvidia/Qwen3.6-35B-A3B-NVFP4` on `:8000`. The API runs on `127.0.0.1:8088`, because OpenShell owns `:8080`.
- Time budget: about 35 minutes. One real judged run through the D02 agent path is enough. Record the latency per stage and the ground-truth exclusion proof in `artifacts/event_day/`. Take the Playwright screenshot against the running app (web `:3000`, API `:8088`); do not run `next build` if another build is in progress.
- Do not edit `hazards/`, `apps/**` or the Safety hazard files. If the D02 agent path is not working, run the judged scenario on the dev-sequence path, and say plainly in the worker report what is missing from the agent path.
