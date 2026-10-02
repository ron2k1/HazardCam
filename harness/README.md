# Non-Agent Development Harness

This harness exists so the entire product can be built and evaluated before event day without prebuilding the OpenClaw agent.

It should call the same ordinary Python/library functions that will later be registered as OpenClaw tools, in a fixed explicit sequence:

1. inspect allowed cameras
2. correlate observations
3. triangulate region candidates
4. call reasoning adapter
5. validate/submit final hypothesis

It must not claim to be OpenClaw and should not implement autonomous agent planning/tool registration.
