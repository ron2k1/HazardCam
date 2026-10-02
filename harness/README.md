# Non-Agent Development Harness

This harness exists so the entire product can be built and evaluated before event day without prebuilding the OpenClaw agent.

`dev_sequence.py` calls the run-scoped tools in `tools/session.py` (the same bindings the event-day agent will call) in one fixed, explicit sequence:

1. `sample_video` then `inspect_camera`, for each visible camera in scenario order
2. `correlate_observations`
3. `triangulate_region` (assembles the evidence bundle)
4. `reason_hypothesis`
5. `get_supporting_frames`, for each camera the hypothesis cites
6. `submit_hypothesis` (the deterministic gate)

It announces itself as `harness: "dev-sequence"`, `agent: false` in `orchestrator.started`. It must not claim to be OpenClaw and does not implement autonomous agent planning or tool registration.
