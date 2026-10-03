# Final verification (event day)

2026-10-03, about 14:57 CDT (19:57 UTC), on the Dell Pro Max GB10. Checked at commit
`d4dd22c` (local `feat/prebuild`, not pushed). Prebuild snapshot: `6806046`. Event-day start:
16:04 UTC (`artifacts/event_day/START.txt`). Every line below names the file that shows it.
What is not verified is listed at the end.

## Event-day done

| item | result | evidence |
|---|---|---|
| OpenClaw agent built on the day, through NemoClaw/OpenShell | D00–D03 commits `07cdf5e`, `d4e4943`, `0710265`, `fc49486` and `86cb7e0`, then `d4dd22c` (site-lead plus 6 checker agents, hazard tools). Agents `urban-mirror` and `site-lead` run on `inference/nvidia/Qwen3.6-35B-A3B-NVFP4`, with no fallbacks. | `artifacts/event_day/workers/D00–D03.md`, `artifacts/event_day/d04/runtime_status_20261003T195705Z.txt` |
| NemoClaw/OpenShell status | nemoclaw v0.0.124, openshell 0.0.116. Sandbox `ambient-mirror` is Ready, inference.local is healthy, and OpenClaw is running. | same runtime status file. demo-check prints `nemoclaw status` on each run |
| Local model health | `nvidia/Qwen3.6-35B-A3B-NVFP4` on `127.0.0.1:8000` (`/health` 200, max_model_len 262144). Both gb10 slots use it. `RESULT: OK no cloud route`. | runtime status file |
| Status visible in the app | `/api/runtime/status`: 7 of 7 rows ok (NemoClaw sandbox, OpenClaw agent, OpenShell gateway, tool server, Qwen, detector, network), `local_only: true`. They are shown on `/hazards/process`. | `artifacts/event_day/d04/demo_check_final_run{1,2,3}.txt` |
| `make demo-check` 3× | 3 of 3 passed, each with 21 OK and 0 BAD: pages `/`, `/hazards`, `/hazards/process`, `/ops`; API; Qwen; runtime status; 7 of 7 hazard clips reviewed, with media served and the worker text free of leaked ids or scores; NemoClaw. | same files (three earlier runs on `0db0851` also passed: `demo_check_run{1,2,3}.txt`) |
| `make verify-event-delta` | exit 0, and no event-day code imports `eval/`. | `artifacts/event_day/d04/verify_event_delta.txt`, `artifacts/event_day/DELTA_REPORT.txt` |
| Ground-truth exclusion | D03: 6 of 6 surfaces clean on the scenario_001 judged run, plus 75 hermetic boundary tests. D04 re-checked a fresh gb10 run (`run_20261003T183005Z_fa3d1d`, harness `openclaw-agent`): 6 of 6 OK, including the agent's sandbox transcript. | `artifacts/event_day/d03/README.md`, `artifacts/event_day/d04/ops_beat/judged_run_run_20261003T183005Z_fa3d1d.json` |
| Playwright judged-path screenshot | From D03: `eval_001 [gb10]` passed (40.7 s). It was not re-run in D04 (see below). | `artifacts/e2e/ops-gb10-eval_001-*.png` |
| End-to-end latency | `/ops` eval_001 on gb10: 36.3 s click to done, with the GPU otherwise idle (D04). D03: 37.2 s alone, and 155.1 s for scenario_001 under shared-GPU load. Hazard agent turns: hz_00 74.5 s, bs_03 97.6 s. | `artifacts/event_day/d04/ops_beat/ops_beat.json`, `artifacts/event_day/d03/README.md`, `data/hazards/reports/{hz_00,bs_03}/*/agent_trace.json` |
| Backup demo recording | `artifacts/hazards/demo/hazards_demo.mp4`: 121.1 s, 1920×1080, H.264. No frozen stretch of 6 s or more and no black frames. No mock data or leaked ids on the worker screens, and the new layout throughout. It replays real GB10 runs `f12f98a9f3b78349` (hz_00) and `4d233e56fc45a9bc` (bs_03), which ran on local Qwen through the OpenClaw agent, and the process tab says it is a replay. | `artifacts/event_day/d04/inspect_hazards_demo/` |
| Demo script | `docs/DEMO_SCRIPT.md`: 2:00, factory and warehouse only, timed to the backup video. 212 words of narration, about 91 s at 140 wpm. | `artifacts/event_day/d04/script_timing.txt` |
| Offline | `offline_check.py`: all required checks ok. The fixture run had non-loopback sockets refused (0 network attempts), and no remote font or CDN host was found. The Ollama probe is not required: the GB10 uses vLLM. | `artifacts/event_day/d04/offline/OFFLINE_CHECK.md` |
| Tests | pytest (not `live_model`) on `d4dd22c`: 1636 passed, 2 failed, 3 skipped. | `artifacts/event_day/d04/pytest_final.txt` |

## Not verified, or not clean (stated plainly)

- **2 pytest failures.**
  - `tests/unit/contracts/test_hazard_view_contract.py::test_examples_match_the_composer`: the
    committed hazard view examples no longer match the rebuilt composer. This is a stale
    fixture in the hazard rebuild's paths, not a runtime failure.
  - `tests/unit/media/test_probe.py::test_probe_reports_late_video_start`: this predates D04.
    D00 recorded it against the GB10's apt ffmpeg 6.1.1.
- **Telegram is on.** `config/telegram.yaml` has `enabled: true`, and the token and chat files
  exist in `~/.config/ambient-mirror/`. So the host API sends a best-effort ping to
  api.telegram.org when a check finishes with findings (daemon thread, 6 s timeout, it never
  blocks the job). That is internet egress outside the model path. "No cloud route" covers the
  model routes only. The judged path does not wait on it.
- **Reasoning slot is Qwen, not Mistral.** This is the operator's documented choice in D02/D03:
  the Mistral weights are not on the box.
- **Accuracy is not measured.** These are single runs. On `/ops` eval_001 the D04 run named the
  accepted event type but placed it about 28.6 m from the judge's point (region_01 against
  `z_east_pocket`). On the D03 flagship, scenario_001 came back `no_event` (a miss). The hazard
  findings only partly match the dataset labels (`artifacts/hazards/GB10_REVIEW_RUNS.md`).
- **Not re-run in D04.** The Playwright suites, the 22-scenario eval and a fresh
  `boundary-check`. On :8088 every run goes through the OpenClaw agent (fixture runs too), so
  22+ agent turns would have competed for the shared GPU during the hazard rebuild.
- **The rehearsal was a timing read-through**, not a spoken run by a person
  (`script_timing.txt`).
- **The backup video predates the 14:41 polish fixes**: the Steps panel label, the wall that
  keeps finished checks, and the 6-camera rail. So it ends on a wall that is restarting its
  checks. The user plans their own take.
