# Prebuild Boundary and Integrity Plan

The goal is to maximize engineering preparedness while respecting the event rule supplied by the team: **the agent itself is built on the day**.

## Fully build and test before the event

- final UI and animation system
- FastAPI backend and SSE
- scenario loading and ground-truth access control
- real-data preparation pipeline
- video/frame sampling
- Qwen perception adapter and finalized observation prompt
- deterministic time correlation
- deterministic coarse triangulation
- Mistral reasoning adapter and finalized hypothesis prompt
- direct-call development harness that exercises the exact future tool functions
- evidence timeline and video seeking
- model profile loader
- fixture/lite/full model integration tests
- evaluation harness and metrics
- offline package checks
- local serving scripts/containers where licensing permits
- ordinary tool implementations and tool argument/result schemas

## Create fresh on event day

- OpenClaw agent definition
- OpenClaw tool registration code/config
- actual OpenClaw system prompt/playbook
- OpenClaw decision loop/policy
- final NemoClaw/OpenShell wiring around that agent

## Important distinction

The prebuild harness may call the same tested functions in a fixed deterministic sequence so the full product can be validated before the event. It must remain clearly identified as a non-agent harness and must not contain a hidden finished OpenClaw implementation.

The event-day workflow is intentionally optimized so creating the real agent is mostly adapter/registration work against already-proven interfaces and acceptance tests.

## Audit trail

Before the event:

```bash
make boundary-check
make snapshot-prebuild
```

On event day:

```bash
make event-day-start
make boundary-check
./scripts/event_day_task_runner.sh D00 claude
...
make verify-event-delta
```

This records the exact prebuild state and the actual event-day delta.
