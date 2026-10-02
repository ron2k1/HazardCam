# Quick Commands — v3

Every `make <target>` is also `scripts/run.sh <target>`, for machines without make.

## Run it

First time on a machine (needs uv, Node with pnpm, and ffmpeg on PATH):

```bash
uv sync --frozen                 # .venv from uv.lock, Python 3.11-3.13
pnpm --dir apps/web install
scripts/run.sh offline-check     # dependencies, media, labels, recordings, web build all local
```

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
`API_PORT` / `WEB_PORT` move the servers; `SKIP_BUILD=1` reuses the web build the last
`start` made for the same API port (it refuses any other build). Ctrl+C gives the servers
`STOP_GRACE_S` (10, whole seconds) to exit before they are killed; a second Ctrl+C while
they stop is ignored.

Checks:

```bash
scripts/run.sh test -m "not live_model"       # pytest without model calls
scripts/run.sh eval                           # fixture eval, 22 scenarios, ~25 s
scripts/run.sh eval --profile full-local      # live models, ~30 min on the laptop
scripts/run.sh tool-probe                     # single-turn tool-call probe, 8B and 3B
scripts/run.sh offline-check                  # network refused during a fixture run
scripts/run.sh fixture-e2e                    # Playwright on /ops, fixture profile, 22 tests, ~1.5 min + build
scripts/run.sh lite-e2e                       # eval_001 alone on lite-local models, ~40 s + build
scripts/run.sh full-e2e                       # eval_001 alone on full-local models, ~2 min + build
```

`lite-e2e` / `full-e2e` keep `-g eval_001` under other options and their values (`--headed`,
`--output dir`); a `-g` / `--grep`, `--test-list` or spec path replaces it, and `--grep-invert`
narrows it. Playwright ignores test filters after `--`, so those keep it too.

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
