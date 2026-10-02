# Failure Ladder

Fall down a level instead of spending the event on one broken dependency.

## Prebuild levels

### A — intended development path
Real prepared videos -> sampled frames/clips -> local Qwen -> deterministic fusion -> Mistral adapter -> dev harness -> UI

### B — decoder/media issue
Pre-extracted timestamped frame sets -> same pipeline

### C — intended Qwen unavailable
Smaller local Qwen-compatible VLM -> same Observation schema

### D — model serving blocked
Fixture observations + fixture/fallback hypothesis -> complete UI/E2E while model worker repairs serving

## Event-day levels

### 1 — desired judged path
Real videos -> local Qwen -> deterministic fusion -> newly built OpenClaw agent/Mistral -> NemoClaw/OpenShell -> UI

### 2 — large Qwen unstable
Use prevalidated smaller local perception profile with the real event-day agent.

### 3 — live video decode unstable
Use pre-extracted timestamped frames with the real event-day agent.

### 4 — runtime integration temporarily broken
Use fixture model outputs through the real newly built OpenClaw agent to debug NemoClaw/OpenShell.

### 5 — presentation fallback
Use backup recording only as a fallback and describe it accurately. Do not present fixture output as a successful live real-model run.
