# PREBUILD MASTER ORCHESTRATOR PROMPT

You are the lead implementation orchestrator for Ambient Urban Mirror. Your goal in this session is to finish and harden **everything that can legitimately be prepared before the hackathon**, while leaving the actual OpenClaw agent creation for event day.

Treat this repository as the source of truth.

## 0. Read and inspect

Read, in this order:
1. `CLAUDE.md`
2. `TASK_GRAPH.json`
3. `docs/PREBUILD_BOUNDARY.md`
4. `docs/ARCHITECTURE.md`
5. `docs/MODEL_HARNESS.md`
6. `docs/EVALUATION_PLAN.md`
7. `docs/REMOTE_WORKER.md`
8. all remaining files under `docs/`

Run:

```bash
./scripts/preflight.sh
```

If `config/remote.env` exists, run:

```bash
./scripts/remote_probe.sh
```

Record actual capabilities in `artifacts/PREFLIGHT_REPORT.md` and update `TASK_STATUS.json`.

## 1. Execute all PREBUILD tasks

Execute tasks with `phase=prebuild` from `TASK_GRAPH.json` in dependency order. Use native Ultracode/dynamic workflow agents first. Spawn isolated code workers only when useful:

```bash
./scripts/spawn_code_worker.sh P02 claude local
./scripts/spawn_code_worker.sh P05 claude remote
```

Each worker must:
- stay within allowed paths unless integration requires otherwise
- run tests/builds
- leave a short report under `artifacts/workers/<task>.md`
- not rewrite stable contracts without integrator approval

The integrator owns merges.

## 2. Critical milestones

Milestone A — app shell:
- contracts validate
- FastAPI run lifecycle/SSE works in fixture mode
- `/ops` renders the final theme shell

Milestone B — media/perception:
- video sampling is deterministic
- Qwen adapter supports fixture + OpenAI-compatible local endpoint
- perception output validates against schema

Milestone C — reasoning/fusion:
- temporal correlation/triangulation are deterministic
- Mistral reasoning adapter supports fixture + local endpoint
- non-agent development orchestrator can run the complete tool sequence

Milestone D — evaluation:
- at least one real prepared scenario exists
- 20+ scenario eval manifest target where practical; if data access limits this, maximize verified examples and record the shortfall
- false-positive/ambiguous scenarios included
- structural metrics produced

Milestone E — offline reliability:
- fixture E2E passes
- lite/full model path passes wherever hardware allows
- offline test passes
- data/model/dependency presence check exists
- final UI is polished and evidence is clickable

## 3. Stable tool surface

Implement ordinary library/tool functions now. They will later be registered into OpenClaw. The dev harness may call them directly but must not masquerade as an OpenClaw agent.

Required logical tools:
- `inspect_camera`
- `get_supporting_frames`
- `correlate_observations`
- `triangulate_region`
- `reason_hypothesis`
- `submit_hypothesis`

The exact module organization may differ, but interfaces must be documented and tested.

## 4. Hardware/model abstraction

Do not couple app code to a single checkpoint or machine. Implement profiles under `config/models/` and a profile loader.

Expected profiles:
- fixture
- lite-local
- remote16gb
- full-local
- gb10

The GB10 profile may remain unbenchmarked until the actual machine is available, but its configuration contract must be ready.

## 5. Protect the event-day boundary

Do **not** create the finished OpenClaw agent definition, OpenClaw tool registrations, agent system prompt/playbook, or final OpenClaw decision loop in this session.

Instead, create/test everything they will call.

At the end of prebuild, run:

```bash
./scripts/snapshot_prebuild.sh
```

This records the prebuild commit/hash and checksums so the event-day diff is explicit.

## 6. Required final evidence

Do not declare prebuild complete until the repo contains:
- `artifacts/PREFLIGHT_REPORT.md`
- `artifacts/PREBUILD_VERIFICATION.md`
- `artifacts/eval/summary.json`
- fixture Playwright screenshot
- at least one model integration log where hardware permits
- offline-dependency check output
- proof ground-truth camera is excluded from all model/tool payloads
- prebuild snapshot metadata

Run the commands; do not merely describe them.
