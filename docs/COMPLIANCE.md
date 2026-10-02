# Hackathon Integrity / Compliance Guardrails

The event instructions provided by the team state that plans, scaffolds, and libraries may be prepared in advance while the agent itself must be built on the day.

## Prepare and fully test now
- UI and backend
- data and scenarios
- model weights/containers where permitted
- Qwen perception implementation
- Mistral reasoning implementation
- deterministic sampling/correlation/triangulation libraries
- schemas and tool interfaces
- non-agent development harness
- evaluation harness
- fixture/lite/full-model tests
- offline bundle

## Create on event day
- OpenClaw agent definition
- OpenClaw tool registration
- actual OpenClaw playbook/system prompt
- OpenClaw decision loop/policy
- final NemoClaw/OpenShell agent runtime wiring

## Do not stage a fake build

Do not pre-create the finished agent and later copy/type it in piece by piece to make it appear newly built. The package intentionally includes a prebuild snapshot and event-day diff workflow so the team can move fast while being transparent.

## Files

`agent/` may contain notes/templates/interfaces before the event, but finished event-day agent files should be created/changed after `scripts/event_day_start.sh` is run.
