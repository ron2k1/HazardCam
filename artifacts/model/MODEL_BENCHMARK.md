# Model benchmark (P15)

What ran, on what, with which settings, and what it scored. Scoring rules are
`eval/SCORING.md`, fixed before any run was scored. Rates are k/n = rate [Wilson 95%].

## Hardware and serving

| item | value |
|---|---|
| machine | Dell G15 5530 laptop, i7-13650HX, 16 GB DDR5 |
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU, 8188 MiB, driver 616.92 |
| server | Ollama 0.22.1, OpenAI-compatible `/v1` on `127.0.0.1:11434` |
| context | 4096 tokens (Ollama default; longer prompts are truncated silently, so the adapter budgets frames) |

## Exact models

Digests from `GET /api/tags` on 2026-10-02.

| profile | role | tag | digest | params | quant | size |
|---|---|---|---|---|---|---|
| lite-local | perception | `qwen3-vl:4b-instruct` | `ee4b975b58c1` | 4.4B | Q4_K_M | 3.30 GB |
| lite-local | reasoning | `ministral-3:3b` | `f04aa1c738f6` | 3.8B | Q4_K_M | 2.95 GB |
| full-local | perception | `qwen3.5:9b` | `6488c96fa5fa` | 9.7B | Q4_K_M | 6.59 GB |
| full-local | reasoning | `ministral-3:8b` | `1922accd5827` | 8.9B | Q4_K_M | 6.02 GB |

Sampling and limits per profile are in `config/models/<profile>.yaml` and are the
record: temperature 0.0, thinking off, json_schema structured output, 2 retries,
1 fps sampling, at most 8 frames per camera, frames sent at 512 px.

Settings that matter and are easy to lose:

- `qwen3.5:9b` is a hybrid-thinking model. With thinking on it spends the whole token
  budget reasoning and returns empty content, so `think: false` is required.
- Ollama 0.22.1 ignores `response_format` for `qwen3.5:9b`. Its JSON comes from the
  prompt plus the adapter's parse and one repair turn.
- The two full-local models together exceed 8 GB of VRAM. Ollama swaps them one at a
  time, which is part of the per-scenario latency below.

## Intended stack: not run here

The intended 35B-class Qwen (`qwen3.5:35b-a3b` or `Qwen3-VL-30B-A3B-Instruct`) and a
larger Mistral do not fit 8 GB VRAM + 16 GB RAM at a usable speed. They belong to the
`gb10` profile, whose model ids stay `REPLACE_ON_GB10` until the GB10 is probed on
event day. Selecting `gb10` before that fails on purpose. No aarch64 bundle (Python
wheels, node_modules, model weights) was built for the GB10 from this x86_64 laptop; the
GB10 serving setup is in `docs/EVENT_DAY_RUNTIME.md`.

## Results: all 22 manifest scenarios

| run | decision acc | balanced | positive | negative | ambiguous | full hit | Brier | median s |
|---|---|---|---|---|---|---|---|---|
| always `unknown` (baseline) | 14/22 = 0.64 | 0.67 | | | | | | |
| lite-local, replayed (fixture eval) | 9/22 = 0.41 [0.23, 0.61] | 0.42 | 2/8 | 5/7 | 2/7 | 0/8 | 0.504 | 1.1 |
| full-local, live | 10/22 = 0.45 [0.27, 0.65] | 0.46 | 3/8 | 5/7 | 2/7 | 0/8 | 0.341 | 77.2 |

Both runs: pipeline_ok True (22/22 complete and schema-valid, 0 GT leaks, 0 failed
adapter calls). Neither beats the constant baselines. Sources:
`artifacts/eval/fixture/`, `artifacts/eval/full-local/`, `artifacts/eval/COMPARISON.md`.

Reading:

- The larger pair is better calibrated (Brier 0.504 to 0.341) but makes about the same
  decisions. The one-scenario gain in decision accuracy is far inside the interval width.
- Its errors lean towards over-claiming `passenger_dropoff_pickup` (6 of 12 failures)
  and towards `no_event` on positives and ambiguous scenarios (3).
- Region is 0/9 for a structural reason, not a model one: every labelled scenario's
  accepted zone (`z_east_pocket`) lies outside all visible cameras' fields of view, so
  in-frame bearings cannot reach it. Fusion offered an accepted zone as a candidate in
  0/14 scenarios that have one. Better models do not change this.

The full-local run was scored on `b51f3d7`. Later scoring clarifications (`44cad8e`,
`c844627`) only change runs with a leak, a failed run, or a subset; this run has none
of those, so its numbers stand.

## Latency (full-local)

Scenario median 77.2 s, max 177.4 s. Perception call median 13.2 s, max 90.5 s.
Reasoning call median 17.4 s, max 32.8 s.

These are pessimistic. The GPU was shared during the run: a reviewer's live-model tests
called the same Ollama server, and the two full-local models swap in and out of 8 GB.
Treat them as an upper bound for this laptop, not as the pipeline's cost.

## Agent model: tool-call probe

A single-turn probe (`eval/tool_probe.py`, results in `artifacts/eval/tool_probe/`) asks
the reasoning model for the next tool call at each step of a recorded `eval_001` run,
plus one recovery case after a rejected call. It is not an agent loop.

| model | pass | schema-valid call | median s |
|---|---|---|---|
| `ministral-3:8b` | 13/13 = 1.00 [0.77, 1.00] | 13/13 | 0.62 |
| `ministral-3:3b` | 10/13 = 0.77 [0.50, 0.92] | 10/13 | 0.33 |

The 3B model returned no tool call at three late steps and made parallel calls twice.
Stock OpenClaw on the same 3B returned an empty reply (`artifacts/runtime/runtime_smoke.md`).
So `ministral-3:8b` is the smallest local model to try as the event-day agent model; the
3B is not. Caveat: the 13 cases share one transcript, so they are correlated, and a
single turn says nothing about stability over a long multi-turn loop.

## Fallback (docs/FAILURE_LADDER.md)

| situation | fall back to | evidence it works |
|---|---|---|
| intended Qwen unavailable (prebuild C, event-day 2) | `full-local`, then `lite-local` perception through the same Observation schema | both profiles completed 22/22 schema-valid runs |
| model serving blocked (prebuild D, event-day 4) | `fixture` profile: recorded per-scenario observations and hypotheses | fixture eval 22/22, 0 replay mismatches |
| agent model unreliable | `ministral-3:8b`; never `ministral-3:3b` | probe and OpenClaw smoke above |

A fixture run must never be presented as a live model run.

## Operational notes

- This Ollama server keeps every loaded model resident (`/api/ps` reports
  `expires_at` in 2319, keep_alive -1). That is server configuration, not repo code.
  Loading a second model can evict a pinned one, so warm the exact tags first and check
  `/api/ps` before a judged run.
- Reproduce: `scripts/run.sh eval --profile full-local` (about 30 minutes on this
  laptop) and `scripts/run.sh tool-probe --profile full-local lite-local`.
