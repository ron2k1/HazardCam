# Ambient Urban Mirror — Full Prebuild + Fresh Event-Day Agent v3

This package is optimized to have **the whole product working before the hackathon** while keeping the one component the supplied rules say must be built on the day—the OpenClaw agent itself—genuinely fresh.

## Phase A — build virtually everything now

A Claude Code / Ultracode prebuild session should finish and test:

`real multi-camera video -> Qwen observations -> deterministic temporal/spatial fusion -> Mistral hypothesis -> FastAPI/SSE -> polished Next.js/21st.dev dashboard -> withheld ground-truth comparison`

It also builds the stable tool functions that the future agent will call and a non-agent development harness that runs the same end-to-end path.

Start with:

```bash
cd ambient-mirror-ultracode-prebuild-v3
./scripts/preflight.sh
./scripts/start_prebuild_ultracode.sh
```

When hardened:

```bash
make boundary-check
make snapshot-prebuild
```

## Phase B — build only the actual agent at the venue

Start a fresh event-day session:

```bash
make event-day-start
make event-day-ultracode
```

Or drive the build one small task at a time:

```bash
./scripts/event_day_task_runner.sh D00 claude
./scripts/event_day_commit.sh D00
./scripts/event_day_task_runner.sh D01 claude
./scripts/event_day_commit.sh D01
./scripts/event_day_task_runner.sh D02 claude
./scripts/event_day_commit.sh D02
./scripts/event_day_task_runner.sh D03 claude
./scripts/event_day_commit.sh D03
./scripts/event_day_task_runner.sh D04 claude
./scripts/event_day_commit.sh D04
```

This is nearly as fast as copying prepared code because the interfaces, tests, prompts for Qwen/Mistral, datasets, UI, and deterministic tools already exist. The difference is that the OpenClaw-specific implementation is actually created at the event.

## Integrity boundary

Do not present prebuilt work as if it was authored at the venue. In particular, do not prewrite a hidden OpenClaw agent and copy it into the repo one file at a time. The package instead makes the real on-day agent build small and test-driven.

## Core demo line

> The event is not visible to the input cameras. The system infers it from its effects.
