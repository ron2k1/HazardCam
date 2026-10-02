# Quick Commands — v3

Every `make <target>` is also `scripts/run.sh <target>`, for machines without make.

## Run it

First time on a machine: `pnpm --dir apps/web install`, then `scripts/run.sh offline-check`
to confirm dependencies, media, labels, recordings and the web build are all local.

Fixture mode makes no model calls and needs no network:

```bash
scripts/run.sh start           # API 127.0.0.1:8080 + web 127.0.0.1:3000; Ctrl+C stops both
# open http://127.0.0.1:3000/ops, pick a scenario, RUN, then REVEAL for the ground truth
scripts/run.sh start --smoke   # start, check both answer, stop
```

Real local models go through Ollama on `127.0.0.1:11434`. Tags, digests and settings
are in `artifacts/model/MODEL_BENCHMARK.md`:

```bash
ollama pull qwen3-vl:4b-instruct; ollama pull ministral-3:3b   # lite-local, 6.3 GB
ollama pull qwen3.5:9b; ollama pull ministral-3:8b             # full-local, 12.6 GB
MODEL_PROFILE=lite-local scripts/run.sh start
```

`/ops` offers `fixture` plus the API's `MODEL_PROFILE` in its profile selector. A
lite-local scenario took 8-85 s on the RTX 4060 laptop, full-local 12-177 s (median 77 s).
`API_PORT` / `WEB_PORT` move the servers; `SKIP_BUILD=1` reuses a web build made for the
same API port.

Checks:

```bash
scripts/run.sh test -m "not live_model"       # pytest without model calls
scripts/run.sh eval                           # fixture eval, 22 scenarios, ~25 s
scripts/run.sh eval --profile full-local      # live models, ~30 min on the laptop
scripts/run.sh tool-probe                     # single-turn tool-call probe, 8B and 3B
scripts/run.sh offline-check                  # network refused during a fixture run
pnpm --dir apps/web e2e                       # Playwright on /ops, fixture profile
```

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
