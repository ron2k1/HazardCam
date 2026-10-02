# Quick Commands — v3

## Prebuild now

```bash
make preflight

# optional SSH worker
cp config/remote.env.example config/remote.env
$EDITOR config/remote.env
make remote-probe

# orchestrated implementation
make prebuild-ultracode

# parallel isolated workers when useful
./scripts/spawn_code_worker.sh P02 claude local
./scripts/spawn_code_worker.sh P03 claude local
./scripts/spawn_code_worker.sh P05 claude remote
./scripts/spawn_code_worker.sh P08 claude local

make status
```

Before freezing:

```bash
make boundary-check
make snapshot-prebuild
```

## Event day — fresh agent build

```bash
make event-day-start
make boundary-check
```

Either launch one orchestrator:

```bash
make event-day-ultracode
```

or run small sequential coding tasks:

```bash
for task in D00 D01 D02 D03 D04; do
  ./scripts/event_day_task_runner.sh "$task" claude
  ./scripts/event_day_commit.sh "$task"
done
```

Finish with:

```bash
make verify-event-delta
make demo-check
```
