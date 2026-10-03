# GB10 handoff (event day, 2026-10-03)

Start a Claude Code session in this repo on the GB10 and tell it: `read docs/GB10_HANDOFF.md and follow it`.

## Context for the session

You are on a Dell Pro Max with GB10 (DGX OS, linux/arm64) at the Dell x NVIDIA Frontline Safety Agent
hackathon. There are two inputs:

- `~/bundle`: the offline bundle copied from our USB drive. `~/bundle/README.md` is its runbook (sections
  1-7, plus 5b for Nemotron 3 Nano on llama.cpp and 5c for Nemotron Nano Omni on vLLM). Before anything
  else, run `python3 ~/bundle/verify_bundle.py ~/bundle`. It must print `ALL OK`.
- This repo, branch `feat/prebuild`. Before changing anything, read `CLAUDE.md`, `README_FIRST.md`,
  `docs/COMPLIANCE.md`, `docs/PREBUILD_BOUNDARY.md`, `docs/FRESH_EVENT_DAY_BUILD.md` and
  `docs/EVENT_DAY_RUNTIME.md`.

## Integrity rule

Everything on `feat/prebuild` was prepared before the event, which the event instructions allow. The
OpenClaw agent itself is built today, fresh, in tasks D00-D04: its definition, tool registration,
prompt/playbook, policy, and the NemoClaw/OpenShell wiring. Never copy in a prewritten agent, never rewrite
history, and never backdate a commit.

## Order of work

1. Report `nvidia-smi`, `docker info -f '{{.DriverStatus}}'` and `df -h ~`.
2. Verify the bundle (above).
3. `docker load` the images and serve Qwen3.6 on vLLM port 8000 per bundle README section 5. Run images by
   TAG, never by digest.
4. Serve Cosmos-Reason2-8B on port 8001.
5. Set up this repo's environment (`./scripts/preflight.sh`), then run `make boundary-check`. If `make` is
   missing, `./scripts/run.sh <target>` runs the same targets.
6. Run `make event-day-start`, then build D00 to D04 with `./scripts/event_day_task_runner.sh D0n claude`.
   Finish with `make verify-event-delta`.

## Working rules

- Show the real command output for every step. Never claim success without it.
- Commit small and push after each green step.
- Never put secrets, tokens or API keys in commits, logs or chat.
