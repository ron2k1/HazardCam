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

`seq` is monotonically increasing per run. The frontend must be able to ignore duplicate/out-of-order events.
