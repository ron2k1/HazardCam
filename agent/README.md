# Agent directory

Before the event, keep only notes/templates/interfaces here. The finished OpenClaw agent definition, actual agent playbook/system prompt, tool registrations, and final decision loop are created on event day.

The ordinary Python/library tool implementations themselves are built and tested during prebuild under `tools/`, `inference/`, and `harness/`.

Run `scripts/event_day_start.sh` before creating the finished agent files, then `scripts/verify_event_delta.sh` before the judged demo.
