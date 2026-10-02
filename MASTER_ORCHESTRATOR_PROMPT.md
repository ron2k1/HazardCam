# Ambient Urban Mirror — Master Orchestrator Pointer v3

## Before the event

Use `PREBUILD_ORCHESTRATOR_PROMPT.md` and complete every PREBUILD task. The target is a fully working product through the non-agent development harness, including real model evaluation where hardware permits.

Before freezing the repo run:

```bash
make boundary-check
make snapshot-prebuild
```

## At the event

Start a fresh session with `EVENT_DAY_ORCHESTRATOR_PROMPT.md`. Create the actual OpenClaw agent and required NemoClaw/OpenShell wiring against the already-tested interfaces.

For maximum speed, drive D00-D04 sequentially with `scripts/event_day_task_runner.sh` and commit each completed step.

Do not pre-create a hidden finished agent and later copy it into place while claiming it was authored at the venue.
