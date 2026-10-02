# SSE Envelope

```json
{
  "run_id": "run_abc",
  "seq": 12,
  "ts": "2026-10-02T12:00:00.123Z",
  "type": "camera.observation",
  "payload": {}
}
```

Schema: `contracts/sse_envelope.schema.json` (Python: `apps.api.schemas.SseEnvelope`).

- `seq` starts at 1 and increases by exactly 1 per run. The frontend must ignore duplicate or out-of-order events (`seq <= lastSeq`).
- Wire format: each SSE message carries `id: <seq>` and `data: <envelope JSON>`. There is no `event:` field, so clients dispatch on `envelope.type`.
- `GET /api/runs/{id}/events` replays the full log from seq 1, or after `Last-Event-ID` / `?after_seq=N`, then streams live events. The server closes the stream after a terminal event (`run.complete` or `run.failed`).
- Times inside payloads are scenario seconds. Wall-clock time is only in `ts`.
- No payload ever contains the ground-truth camera id, its file path, or `expected.json` content.

## Payload catalog

| type | payload |
|---|---|
| `run.started` | `{scenario_id, profile, camera_ids: [..visible only..], harness: "dev-sequence"}` |
| `camera.started` | `{camera_id}` |
| `camera.frames.sampled` | `{camera_id, sample_fps, frames: [{index, frame_id, t, url}]}` where `url` is an API path to the JPEG |
| `camera.observation` | `{camera_id, observation: Observation}` (one event per observation) |
| `camera.complete` | `{camera_id, observation_count, latency_ms, adapter}` |
| `fusion.started` | `{evidence_count}` |
| `evidence.linked` | `{cluster: EvidenceCluster, evidence: [EvidenceItem]}` (one per cluster) |
| `triangulation.updated` | `{candidates: [RegionCandidate], rays: [{camera_id, evidence_id, origin: [x,y], bearing_deg}]}` |
| `orchestrator.started` | `{harness: "dev-sequence", agent: false, sequence: [tool names]}` |
| `tool.started` | `{call_id, tool, args_summary}` |
| `tool.completed` | `{call_id, tool, ok, latency_ms, result_summary, error?}` |
| `hypothesis.updated` | `{hypothesis: Hypothesis, final: bool}` |
| `run.complete` | `{hypothesis: Hypothesis, duration_ms}` |
| `run.failed` | `{stage, error}` where `error` is a short message with no stack traces or secrets |

`args_summary` and `result_summary` are a string or a flat object (the UI renders objects as `k=v`); keep frame URLs and large payloads out of them.

Every domain event is emitted while the tool call that produced it is open, i.e. between that call's `tool.started` and `tool.completed`. Tool calls never nest.

| domain event | emitted inside |
|---|---|
| `camera.started`, `camera.frames.sampled` | `sample_video` |
| `camera.observation`, `camera.complete` | `inspect_camera` |
| `fusion.started`, `evidence.linked` | `correlate_observations` |
| `triangulation.updated` | `triangulate_region` |
| `hypothesis.updated` (`final: false`) | `reason_hypothesis` |
| `hypothesis.updated` (`final: true`) | `submit_hypothesis` |

A rejected call (unknown tool, arguments that violate `contracts/tools.schema.json`, a tool called before the one it depends on, or a camera that is not a visible input camera) emits only its failed pair: `tool.completed` with `ok: false` and an `error` that says how to correct the call, and no domain events. An unknown tool name is reported as `unknown_tool`. A camera id that is not a visible camera never appears in any payload; `args_summary.camera_id` shows `not_visible` instead.

The `orchestrator.*` and `tool.*` events form the agent trace panel. On event day the OpenClaw agent calls the same tool functions through the same event-emitting bindings, so the UI does not change.
