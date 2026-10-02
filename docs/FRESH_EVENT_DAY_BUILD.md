# Fresh Event-Day Agent Build Protocol

The event instructions provided by the team require the agent to be built on the day. The fastest compliant strategy is to prebuild and test every ordinary component, then construct the OpenClaw-specific agent layer fresh from the stable interfaces and tests.

## What is already proven before the event

- real-data scenarios and provenance
- video/frame sampling
- Qwen perception adapter and observation prompt
- deterministic correlation and triangulation
- Mistral reasoning adapter and hypothesis prompt
- FastAPI/SSE backend
- final Next.js/21st.dev interface
- tool implementations and JSON schemas
- direct-call non-agent harness
- fixture/lite/full evaluation paths
- offline dependency bundle

## What is created fresh on event day

The following must not exist as a finished implementation in the prebuild snapshot:

- OpenClaw agent definition
- OpenClaw tool registration code/config
- OpenClaw system prompt/playbook
- OpenClaw decision loop/policy
- event-day NemoClaw/OpenShell wiring for that agent

## Fast step-by-step construction

1. Run `make event-day-start`.
2. Run `make boundary-check` and keep the output in `artifacts/event_day/`.
3. Create the agent definition from the tested requirements in `tasks/event_day/D00_*`.
4. Register the tested tool surface in D01.
5. Wire NemoClaw/OpenShell and local routes in D02.
6. Run the real GB10 path and calibrate only deployment parameters in D03.
7. Harden/rehearse in D04.
8. Run `make verify-event-delta`.

Each D-task can be driven by a fresh CLI coding session with:

```bash
./scripts/event_day_task_runner.sh D00 claude
./scripts/event_day_task_runner.sh D01 claude
./scripts/event_day_task_runner.sh D02 claude
./scripts/event_day_task_runner.sh D03 claude
./scripts/event_day_task_runner.sh D04 claude
```

The runner gives the coding CLI the task prompt plus the stable repo rules. It does not copy a hidden prewritten agent into place.

## Why this is almost as fast as copying files

All difficult implementation surfaces are already fixed and tested. Event-day code only adapts those stable functions to OpenClaw and the required runtime. Tests tell the coding CLI exactly when each step is correct.

That makes the event-day work small, reproducible, and auditable without pretending prebuilt agent code was authored at the venue.
