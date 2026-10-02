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
