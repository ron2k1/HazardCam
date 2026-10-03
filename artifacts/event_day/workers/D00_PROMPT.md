# Project Rules — Ambient Urban Mirror v3

You are engineering a local-first multi-camera causal inference demo for an NVIDIA hackathon.

## Product goal

Deliver one repeatable end-to-end demo:

`real/prepared multi-camera video -> Qwen visual observations -> deterministic temporal/spatial fusion -> bounded Mistral hypothesis -> SSE -> polished dashboard -> withheld ground truth`

The production event-day version replaces the non-agent development orchestrator with a newly created OpenClaw agent running through NemoClaw/OpenShell.

## Non-negotiable technical constraints

1. Runtime inference for the judged path is local.
2. Required event-day stack: NemoClaw + OpenClaw + OpenShell.
3. Qwen is the perception layer; it must output observations rather than the final hidden-event conclusion.
4. Mistral/Ministral is the causal-reasoning layer behind a stable adapter.
5. Timestamp correlation, camera transforms, and coarse triangulation are deterministic code.
6. The withheld ground-truth camera is never available to model/agent tools.
7. The app must support fixture, lite-local, exact-model, and GB10 profiles through the same interfaces.
8. No judged-path dependency on venue internet, third-party APIs, CDN assets, Google Fonts, or live streams.
9. Prefer sampled frames / short clips before whole-video inference.
10. Do not add paid/cloud infrastructure unless the human explicitly approves it.

## Hackathon integrity constraint

The event instructions supplied by the human state that the agent must be built on the day. Therefore:

### Build now
- application shell
- frontend/backend
- real-data scenarios
- Qwen perception implementation and prompts
- Mistral reasoning implementation and prompts
- deterministic tool implementations
- tool interfaces/schemas
- model profiles
- dev harness/orchestrator
- evaluation harness
- tests
- containers/start scripts
- offline dependency/model/data bundle

### Build on event day
- actual OpenClaw agent definition
- OpenClaw tool registration
- actual agent system prompt/playbook
- agent decision loop/policy
- NemoClaw/OpenShell runtime wiring for that agent

Do not pre-create the finished OpenClaw agent and later pretend it was written at the event. Record the prebuild git commit and event-day diff with the provided scripts.

Do not stage compliance by copying a prewritten agent into place file-by-file at the venue. The event-day code must be generated/implemented fresh from the requirements and tested interfaces.

## Development philosophy

The app should not care what hardware/model backend is active. All inference adapters expose stable interfaces. Profiles determine endpoints/checkpoints/sampling only.

The same flow must run in these modes:

- `fixture`: no model calls; deterministic JSON fixtures
- `lite`: small/free local model(s) or remote 16 GB worker if supported
- `full`: intended Qwen/Mistral checkpoints on any available capable machine
- `gb10`: competition configuration

## Remote 16 GB desktop

Probe first. Treat it as optional acceleration, not a dependency.

Good jobs:
- dataset download/staging
- ffmpeg extraction/transcoding
- optical flow/candidate-window scoring
- frontend build/test
- pytest/Playwright
- small quantized model serving if the hardware probe proves it is practical

Bad default job:
- large 35B-class model inference on 16 GB system RAM

Never transfer secrets, SSH private keys, API tokens, or auth databases into the repo.

## UI rules

Match `reference/theme-reference.jpeg`:
- nearly black background
- white/off-white type
- thin square borders
- micro telemetry labels, timestamps, coordinates, frame IDs
- subtle dotted/grid/noise field
- architectural / targeting geometry
- use copied 21st.dev component source, normalized to project tokens
- animation respects `prefers-reduced-motion`
- no generic rounded SaaS dashboard look

## Definition of prebuild done

A fresh machine with the prepared offline bundle can:
1. open `/ops`
2. select a prepared real-data scenario
3. run fixture mode end to end
4. run at least one real-model profile end to end when compatible hardware is available
5. stream camera observations and correlation steps
6. show final hypothesis + alternatives + limitations
7. click evidence and seek the supporting timestamp
8. show withheld ground truth for judge comparison
9. pass evaluation and Playwright checks
10. run without internet access

## Definition of event-day done

All prebuild checks still pass after the development harness is swapped for a newly created OpenClaw agent, and NemoClaw/OpenShell status plus local-model health are visible and captured in artifacts.


--- EVENT-DAY BUILD PROTOCOL ---

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


--- TASK ---

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


--- EXECUTION RULES ---

Implement this task against the current repository state. Inspect existing interfaces before editing. Reuse tested ordinary libraries; do not reimplement them inside the agent. Run the task's acceptance tests/commands. Record a short report under artifacts/event_day/workers/. Do not claim success for commands you did not execute.
