# Local inference

Prebuild owns stable perception/reasoning adapters and model profiles. The app must support fixture, lite-local, remote16gb, full-local, and gb10 modes without changing frontend/backend contracts.

Keep model base URLs, checkpoint IDs, timeouts, quantization labels, sampling, and concurrency configurable. Prefer a wrapped OpenAI-compatible local endpoint when practical.

See `docs/MODEL_HARNESS.md` and `config/models/`.
