# Backend Spec

## FastAPI responsibilities

- scenario listing/loading
- strict filtering so inference/orchestrator cannot see ground truth
- run lifecycle
- model/runtime health aggregation
- dev-harness or event-agent invocation behind one stable interface
- SSE event bus
- run artifacts

## Minimal API

```text
GET  /healthz
GET  /api/scenarios
GET  /api/scenarios/{id}
POST /api/runs
GET  /api/runs/{id}
GET  /api/runs/{id}/events
GET  /api/models/health
```

## SSE event vocabulary

```text
run.started
camera.started
camera.frames.sampled
camera.observation
camera.complete
fusion.started
evidence.linked
triangulation.updated
orchestrator.started
tool.started
tool.completed
hypothesis.updated
run.complete
run.failed
```

Each event includes `run_id`, `seq`, `ts`, `type`, and a typed `payload`.

The UI should show tool/activity trace and evidence, not hidden chain-of-thought text.

## Run storage

Start with in-memory state plus JSON artifacts under `data/runs/` or `/tmp/ambient-mirror-runs`. No external DB is required for the MVP.
