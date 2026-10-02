# Four-Hour Event-Day Runbook

The application should already be built/tested before this clock starts. The four hours are for the actual OpenClaw agent, required runtime wiring, GB10 calibration, and rehearsal.

## 00:00–00:20 — baseline + hardware/runtime probe
- run `make event-day-start`
- inspect GB10, disk, model files, ffmpeg, Python/Node
- verify fixture path still passes
- start/warm local model endpoints using the GB10 profile
- record any deployment-only config changes

## 00:20–01:10 — build actual OpenClaw agent
- create agent definition
- write event-day system prompt/playbook
- register tested tool interfaces
- enforce allowed-camera whitelist
- implement bounded loop with alternatives/abstention

**Gate:** agent can run against fixture tool outputs.

## 01:10–01:50 — NemoClaw/OpenShell integration
- run agent through required stack
- route all inference locally
- capture runtime/status output
- surface runtime failures to backend/UI

**Gate:** fixture scenario passes through the real agent/runtime stack.

## 01:50–02:40 — GB10 real-model E2E
- run selected real scenario
- tune only deployment parameters first: sample count/fps, concurrency, timeouts, serving/quantization profile
- preserve schemas/interfaces

**Gate:** real Qwen observations -> real OpenClaw/Mistral hypothesis -> UI.

## 02:40–03:20 — reliability and evidence proof
- verify ground-truth exclusion
- evidence click/seek
- record E2E latency
- run primary + fallback scenario
- run `verify_event_delta.sh`

## 03:20–04:00 — stop architecture work
- run `make demo-check` three times
- warm models
- polish copy/animations only
- rehearse 3-minute story
- create backup recording
- test judged path with network disconnected
