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

# D04 — Final hardening, rehearsal, and backup recording

**Phase:** event_day  
**Wave:** 14  
**Owner:** integrator  
**Remote OK:** true  
**Dependencies:** D03

## Goal

EVENT DAY: eliminate fragile dependencies, warm models, rehearse 3-minute story, and record fallback demo.

## Allowed paths

- `apps/**`
- `scripts/**`
- `docs/**`
- `artifacts/**`

## Acceptance criteria

- [ ] demo-check passes 3x
- [ ] Backup recording exists
- [ ] 3-minute script rehearsed
- [ ] verify_event_delta.sh succeeds
- [ ] FINAL_VERIFICATION.md exists

## Worker report

Before marking complete, write `artifacts/workers/D04.md` with changed files, commands/tests run, results, assumptions, and blockers.

## Event-day integrity

This task must be performed on event day. Do not copy a prebuilt finished agent/runtime implementation into place and represent it as newly authored. Use the prepared libraries/interfaces, then create the agent integration now.

## Fresh-build requirement

Implement the OpenClaw-specific portion for this task from the current repository state during the event-day session. Reuse already-tested ordinary libraries/interfaces, but do not source or copy a prewritten hidden OpenClaw implementation from outside the event-day working tree. Record commands/tests in `artifacts/event_day/workers/`.

## Operator addendum (event day, 2026-10-03)

- **The story centres on Safety hazards** (`/hazards`, single-camera factory hazard review with the computer-vision evidence video). The operator called it the strongest part. The bus-station `/ops` multi-camera run is a secondary beat, about 30 s at most, to show the OpenClaw agent through NemoClaw/OpenShell. Write the 3-minute script in `docs/DEMO_SCRIPT.md`, in plain words for a non-technical audience.
- The demo can run in the hazards replay mode (`HAZARDS_DEMO_REPLAY=1`), which replays real GB10 runs recorded today and says so in Technical details. A backup recording is at `artifacts/hazards/demo/hazards_demo.mp4` if it exists; reuse it rather than re-recording, and add one short `/ops` clip if time allows.
- Some parts can start before D03 finishes: the script, `make demo-check` three times, and removing fragile dependencies. `FINAL_VERIFICATION.md` comes last, after D03's artifacts exist.
- Time budget: about 40 minutes. Keep the worker views leak-free: no ids, coordinates, scores or schema words. Never push.
- **No live demo (operator, later on 2026-10-03).** The demo is a staged screen recording, so the recording is the main deliverable and `demo-check` is a supporting check. Staging is fine, but nothing on screen may be hardcoded. Every value comes from real runs through the app's API: the hazard replay reads stored real GB10 runs, and the `/ops` beat is a real run. Never use `?mock=1` in the recording.
- **State at D04 start (operator, 13:25 CDT).** D02 (`fc49486`) and D03 (`86cb7e0`) are committed. Qwen fills both model slots on :8000, and Cosmos (:8001) is stopped, so run demo-check with `API_BASE_URL=http://127.0.0.1:8088 MISTRAL_BASE_URL=http://127.0.0.1:8000/v1`. Add a `/hazards` check to `scripts/demo_check.sh` if it is missing. `/` now redirects to `/hazards`.
- **The hazard screen is being rebuilt right now** by another workflow. The new flow: a CCTV-style feed plays on load; the check starts by itself; the structured result, the AI-marked video and the pictures appear only after the check; reasoning and process open in a second tab at `/hazards/process`. That workflow also builds an API runtime-status endpoint, and a separate worker is routing hazard checks through the OpenClaw agent (`agent/**`). Until both finish, do NOT edit `apps/web/src/{app,components}/hazards/**`, `apps/web/src/lib/hazards.ts`, `apps/api/{routes,services}/hazards.py`, `apps/api/main.py`, `hazards/**` or `agent/**`, and do not restart :8088.
- **Recording order.** Do the script (`docs/DEMO_SCRIPT.md`, written for the new flow), the demo-check runs and the dependency hardening first. The hazard workflow writes `artifacts/hazards/demo/hazards_demo.mp4` when it finishes, around 14:15 CDT. Wait for that file before judging the recording. Watch it with ffprobe and its key frames, and re-record only if it shows mock data, a stuck step, leaked ids or the old layout. Record the ~30 s `/ops` beat as a real gb10 run (`/ops?profile=gb10`), with no other model jobs running. Pause hazard reviews while recording: the shared GPU turned a 37 s run into 155 s in D03.
- `make verify-event-delta` and `FINAL_VERIFICATION.md` come last, after the hazard work is committed. If time runs short, write `FINAL_VERIFICATION.md` with what is verified and list plainly what is not.


--- EXECUTION RULES ---

Implement this task against the current repository state. Inspect existing interfaces before editing. Reuse tested ordinary libraries; do not reimplement them inside the agent. Run the task's acceptance tests/commands. Record a short report under artifacts/event_day/workers/. Do not claim success for commands you did not execute.
