# Tools

`sample_video.py`, `correlate.py`, `triangulate.py`, `supporting_frames.py` and `submit.py` are ordinary deterministic code. `inspect_camera.py` and `reason_hypothesis.py` call the perception (Qwen) and reasoning (Mistral) adapters in `inference/`.

`session.py` binds them to one run: a `ToolSession` holds the run state and exposes each tool with the small arguments in `contracts/tools.schema.json`, emitting the `tool.*` and domain events in `contracts/SSE_EVENTS.md`. The dev harness and the event-day agent both call tools through it.
