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

`camera.*` events are emitted inside the matching `tool.started`/`tool.completed` pair for `inspect_camera`.
The `orchestrator.*` and `tool.*` events form the agent trace panel. On event day the OpenClaw agent emits the same `tool.*` events, so the UI does not change.
