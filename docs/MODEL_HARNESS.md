# Model Harness Architecture

The application uses stable adapters so model correctness can be tested on free/smaller hardware and then moved to the GB10 without changing frontend/backend contracts.

## Modes

### fixture
No model runtime. Responses come from deterministic JSON fixtures. Used for frontend/backend/E2E development.

### lite-local
Use small quantized local models supported by the available development machine. Same schemas and prompts, lower capability. Used to prove real multimodal/model calls.

### remote16gb
Use the SSH desktop only after probing it. If it has insufficient accelerator memory, use it for data/media/test jobs and optionally tiny CPU/GPU models. Never make it a required inference dependency.

### full-local
Use the intended or closest practical Qwen/Mistral checkpoints on any capable development hardware.

### gb10
Competition profile. Same adapter interfaces; only serving commands, checkpoint identifiers, quantization/sampling, and endpoints differ.

## Adapter contracts

Perception:

```text
inspect_camera(camera_id, media_manifest, perception_options) -> ObservationBatch
```

Reasoning:

```text
reason_hypothesis(evidence_bundle, reasoning_options) -> Hypothesis
```

Neither frontend nor scenario orchestration should know the serving framework.

## Compatibility target

Prefer an OpenAI-compatible local endpoint when practical, but wrap it. Do not leak provider-specific payload shapes beyond the inference package.

Environment variables/profile fields should control:
- base URL
- model/checkpoint name
- timeout
- max tokens
- temperature
- quantization label
- video/frame sampling settings
- concurrency

## Reproducibility

Record for every benchmark:
- checkpoint exact identifier/hash when available
- quantization
- serving runtime/version
- prompt/template version
- image/video preprocessing parameters
- sampling parameters
- machine/GPU details
- latency
