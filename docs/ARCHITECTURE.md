# Architecture

## Prebuild architecture

```text
Prepared real camera videos
        |
        +--> FFmpeg sampler / short clip extractor
        |            |
        |            v
        |       Qwen local VLM adapter
        |            |
        |       Observation JSON
        |            |
        +--> deterministic temporal correlation
        |            |
        +--> deterministic coarse triangulation
                     |
                     v
          non-agent development harness
                     |
             Mistral reasoner adapter
                     |
              Hypothesis JSON
                     |
                FastAPI/SSE
                     |
                 Next.js UI
```

This complete path is built/tested before the event.

## Event-day architecture

The development harness is replaced by the newly created OpenClaw agent while the tested tools and schemas stay stable:

```text
Qwen observations + deterministic tools
                 |
                 v
        OpenClaw agent (built on day)
        via NemoClaw + OpenShell
                 |
          Mistral reasoner adapter
                 |
          same Hypothesis JSON
                 |
          same FastAPI/SSE/UI
```

## Model separation

### Qwen = perception
Reports visible cues only: motion/traffic changes, human orientation shifts, smoke/dust, reflection/illumination changes, animal movement, emergency response entering frame, etc. It returns timestamps from supplied media metadata, cue type, confidence, and supporting frames.

### Deterministic code = time and geometry
Python correlates cue windows and transforms approximate camera-relative directions/scene zones. Do not ask an LLM to calculate camera intersection geometry.

### Mistral = bounded evidence reasoning
Consumes only fused evidence and returns a hypothesis, region, confidence, supporting evidence IDs, alternatives, limitations, and `unknown` when appropriate.

### OpenClaw = event-day orchestration
The event-day agent decides which allowed tools to call, can request additional supporting frames, and submits the final structured hypothesis. Tool implementations are already tested libraries; registration/policy is created on the day.

## Security boundary for withheld ground truth

The ground-truth camera exists in the scenario manifest but `model_access=false` is enforced in:
- schema validation
- scenario service filtering
- tool whitelist / event-day registration
- integration tests

The UI can read a separate judge-only route or bundled asset, but neither development harness nor event-day agent receives its path.
