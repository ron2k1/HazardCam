# EVENT-DAY MASTER ORCHESTRATOR PROMPT — v3

You are the event-day implementation lead for Ambient Urban Mirror.

The application, real-data scenarios, Qwen perception adapter, deterministic fusion/triangulation, Mistral reasoning adapter, tool libraries, API, frontend, evaluation harness, and tests were prepared beforehand. The event rule supplied by the team requires the **OpenClaw agent itself** to be built today.

Your job is to create that agent fresh and wire it into the required NemoClaw + OpenClaw + OpenShell stack without rewriting stable components.

## 0. Establish and verify the baseline

Read:

1. `CLAUDE.md`
2. `docs/PREBUILD_BOUNDARY.md`
3. `docs/FRESH_EVENT_DAY_BUILD.md`
4. `docs/ON_DAY_BUILD.md`
5. `TASK_GRAPH.json`
6. `artifacts/PREBUILD_SNAPSHOT.json` if present

Run:

```bash
./scripts/event_day_start.sh
./scripts/assert_prebuild_boundary.sh artifacts/event_day/BOUNDARY_AT_START.txt
```

Record machine/model/runtime probes in `artifacts/event_day/EVENT_DAY_PREFLIGHT.md`.

## 1. Execute D00-D04 in dependency order

Prefer the smallest possible implementation that satisfies the stable contracts and tests.

### D00 — create actual OpenClaw agent definition/playbook

Create it today under the documented event-day agent paths. Implement bounded planning, evidence requirements, alternatives, limitations, and abstention.

### D01 — register the tested tool surface

Wrap/register existing ordinary functions. Do not clone their implementation into agent code. Enforce least privilege and ground-truth exclusion.

### D02 — NemoClaw/OpenShell/runtime wiring

Run through the required stack and local inference routes. No cloud model route.

### D03 — GB10 calibration + judged-path E2E

Tune deployment settings only: sampling, concurrency, timeouts, context, serving profile. Preserve app/tool contracts.

### D04 — harden and rehearse

Run clean startup repeatedly, capture status/evidence/screenshots, and produce a backup recording after the first clean run.

## 2. Stable invariants

- Qwen only reports visual observations.
- Deterministic code handles timestamps and geometry.
- Ground-truth camera is inaccessible to the agent.
- Mistral output is bounded structured reasoning, not unrestricted prose.
- Final result includes evidence IDs, alternatives, confidence, and limitations.
- Agent may return unknown/insufficient evidence.
- Runtime inference is local.

## 3. Work in visible, testable increments

After each D-task:

```bash
./scripts/event_day_commit.sh D00   # substitute current task id
```

Write a task report in `artifacts/event_day/workers/` with commands actually run and their results.

## 4. Final proof

Before the judged demo:

```bash
make verify-event-delta
make demo-check
```

Capture:
- NemoClaw/OpenShell status
- local model health
- event-day git diff/commits
- ground-truth exclusion test
- Playwright judged-path screenshot
- E2E latency
- backup demo recording

Write `artifacts/FINAL_VERIFICATION.md`.
