# Prebuild verification

Each point of "Definition of prebuild done" (`CLAUDE.md`) mapped to the run that shows
it. Every number below comes from a file committed in this repo. Date: 2026-10-02.
Hardware: Dell G15 laptop, RTX 4060 8 GB, 16 GB RAM, Windows 11, Ollama 0.22.1.

Data: 22 scenarios from MEVA KF1 (CC BY 4.0), video from the public S3 bucket and
annotations from the public GitLab repo, no credentials (`artifacts/data/`). Each
scenario has three input cameras and one withheld ground-truth camera.

## Definition of prebuild done

| # | requirement | evidence |
|---|---|---|
| 1 | open `/ops` | `scripts/run.sh start --smoke` starts the API and a production web build, checks both answer, stops them (`artifacts/workers/P16.md`). 21 of the 22 fixture e2e tests open `/ops`; the 22nd checks the leak detector on a blank page (`artifacts/e2e/results.json`). |
| 2 | select a prepared real-data scenario | The e2e picks scenarios through the scenario dropdown (`tests/e2e/ops-fixture.spec.ts`: eval_001, eval_012; eval_005 through `?scenario=`). The API lists all 22 (`/healthz` shows `22 scenarios` in the stack-health panel). |
| 3 | run fixture mode end to end | Fixture e2e 22/22 at 4990f36, 88 s (`artifacts/e2e/results.json`, `fixture-run-timing.json`). Fixture eval 22/22 complete and schema-valid, scored at b036324 (`artifacts/eval/fixture/summary.json`). |
| 4 | run a real-model profile end to end | lite-local e2e 8/8 at f9e4736 (the whole suite then): `qwen3-vl:4b-instruct` + `ministral-3:3b`, 29.1 s from RUN to complete (`artifacts/workers/P14.md`). At 4990f36 the eval_001 test passes on lite-local (29.9 s from RUN to complete, `results-lite-local.json`) and on full-local with `qwen3.5:9b` + `ministral-3:8b` (91.4 s, `results-full-local.json`), every tool call ok. full-local eval 22/22 complete and schema-valid (`artifacts/eval/full-local/summary.json`). |
| 5 | stream camera observations and correlation steps | The eval_001 e2e checks that trace rows arrive while the run is live, in tool order, over SSE: 51 events, rows seen 0 to 12 on lite-local (`lite-local-run-timing.json`). SSE resume and replay tests pass (`ops-resilience.spec.ts`). |
| 6 | show hypothesis, alternatives and limitations | Rendered by `apps/web/src/components/ops/hypothesis-panel.tsx`. The eval_001 e2e checks every alternative (event type and confidence, in order) and every limitation against the run's final hypothesis, on each profile; visible in `artifacts/e2e/ops-fixture-eval_001-narrow-390.png`. |
| 7 | click evidence and seek the timestamp | The e2e clicks a timeline bar and a hypothesis evidence chip; both seeks landed within 1 ms of the 23 s target on lite-local (23.000539 s, 23.000345 s) and of 19 s / 8 s on full-local. |
| 8 | show withheld ground truth for judge comparison | Before REVEAL no judge request is made, and from the loaded scenario on nothing identifies the withheld camera. The tokens come from its manifest on disk: id, file stem, label, MEVA camera id, and what only a revealed console draws (the plan marker, `GT · JUDGE`, the position readout). A MutationObserver armed before RUN, with the page checked as it arms, scans added nodes, attribute and text values, and the old values of anything overwritten in between. After REVEAL, the only `/api/judge/scenarios/<id>` call, the same detector, with the same bounds, must find each reveal token, so it is shown able to fire; a blank-page test checks it sees a token written and overwritten in one task, also when the node is then moved. Race tests: a judge reply landing after RE-RUN shows nothing, a reveal dropped by RE-RUN neither stays FETCHING nor unlocks the next one, a reply dropped by a scenario change reveals nothing even back on its own scenario and is not kept, and RE-RUN after a reveal withholds the camera again (`ops-races.spec.ts`, `ops-*-revealed-desktop.png`). |
| 9 | pass evaluation and Playwright checks | Eval `pipeline_ok` true for fixture and full-local (completion 22/22, schema-valid 22/22, 0 ground-truth leaks). Playwright 22/22 fixture; eval_001 on lite-local and full-local (row 4). See "What the scores say" below. |
| 10 | run without internet | `scripts/run.sh offline-check` at 4990f36: 6/6 ok. Python dependencies, ffmpeg, 22 scenarios with 88 media files, labels and recordings, the web build (no remote font or CDN host), the four Ollama models, and an eval_001 fixture run with non-loopback sockets refused (1.8 s, 0 network attempts) (`artifacts/offline/OFFLINE_CHECK.md`). |

## Required final evidence (`PREBUILD_ORCHESTRATOR_PROMPT.md` section 6)

| item | file |
|---|---|
| preflight report | `artifacts/PREFLIGHT_REPORT.md` |
| this verification | `artifacts/PREBUILD_VERIFICATION.md` |
| eval summary | `artifacts/eval/summary.json`, `artifacts/eval/COMPARISON.md` |
| fixture Playwright screenshot | `artifacts/e2e/ops-fixture-eval_001-{desktop,narrow-390,revealed-desktop}.png` |
| model integration log | `artifacts/model/MODEL_BENCHMARK.md` (tags, digests, settings, latency), `artifacts/eval/full-local/scenarios.json` (22 real runs), `artifacts/eval/tool_probe/`, `artifacts/workers/P14.md` |
| offline-dependency check output | `artifacts/offline/OFFLINE_CHECK.{md,json}` |
| ground-truth camera excluded from model and tool payloads | See the next section. |
| prebuild snapshot metadata | `artifacts/PREBUILD_SNAPSHOT.json`, written last by `scripts/run.sh snapshot-prebuild` on the clean tree and committed on its own |

## Ground-truth exclusion

- Real runs: `gt_leaks` is 0 over 22 fixture runs and 22 full-local runs. The eval checks
  every event a run emits for the ground-truth camera's id, file path and file name
  (`scripts/eval/run_eval.py`, `apps/api/services/gt_guard.py`); a leak makes the run
  invalid and fails `pipeline_ok` (`eval/SCORING.md`, Clarification 1).
- Contracts: a scenario cannot mark the ground-truth camera model-accessible or alias it to
  a visible camera; the model view carries no trace of it
  (`tests/unit/contracts/test_contracts.py`).
- Tools and inference: `inspect_camera` refuses the withheld camera before any model call
  (`tests/unit/inference/test_tools.py`); prompts carry no ground-truth handles
  (`test_prompts.py`); correlate, triangulate and bundle reject ground-truth evidence
  (`tests/unit/fusion/`).
- API: the media and frame routes refuse the ground-truth camera; a hypothesis citing it
  fails the run; no public JSON contains it; only `/api/judge/` exposes it
  (`tests/integration/api/`).
- Harness: the dev sequence never puts it in events or in the run's files on disk
  (`tests/integration/harness/test_dev_sequence.py`).
- Browser: covered by row 8 above.

## What the scores say

`pipeline_ok` means the system works: every run completes, every output is
schema-valid, and nothing leaks. It does not mean the models are good at the task.
Neither model pair beats answering `unknown` every time:

| profile | decision accuracy | balanced | Brier |
|---|---|---|---|
| always `unknown` | 14/22 | | |
| lite-local (replayed) | 9/22 | 0.42 | 0.504 |
| full-local | 10/22 | 0.46 | 0.341 |

Region accuracy is 0 for a structural reason: every labelled scenario's accepted zone
(`z_east_pocket`) lies outside every input camera's field of view, so no region
triangulated from the visible cameras can match it
(`artifacts/model/MODEL_BENCHMARK.md`).

## Event-day boundary

- `agent/` holds templates and READMEs only; no OpenClaw agent definition, tool
  registration, system prompt or decision loop exists. D00-D04 are untouched.
- Event-day code paths (`agent/`, `runtime/`, `scripts/runtime/`) do not import `eval/`.
- `scripts/run.sh boundary-check` at 4990f36: PASS, 2026-10-02T19:39:08Z (`artifacts/PREBUILD_BOUNDARY_CHECK.txt`).
- The non-agent harness is labelled `DEV SEQUENCE · NON-AGENT` in the UI.

## Final checks at the frozen commit

Code at 4990f36; the commits after it change only evidence and docs.

- pytest `-m "not live_model"`: 789 passed, 8 deselected (the live-model tests), 84 s.
- ruff check and ruff format: clean, 205 files.
- web: eslint clean; tsc clean for `apps/web` and for `tests/e2e`.
- Playwright: fixture 22/22; eval_001 on lite-local and full-local (rows 3 and 4).
- offline check 6/6 ok; boundary check PASS.
- `scripts/run.sh snapshot-prebuild` last, on the clean tree.
