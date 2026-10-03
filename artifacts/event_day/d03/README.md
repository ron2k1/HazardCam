# D03: judged-path run, latency and ground-truth exclusion (event day, 2026-10-03)

Stack: API 127.0.0.1:8088 (`scripts/runtime/start_api.sh`, agent executor, shared, not restarted),
OpenClaw agent `urban-mirror` in NemoClaw sandbox `ambient-mirror`, brain = local Qwen via
`inference.local`. Both model slots use `nvidia/Qwen3.6-35B-A3B-NVFP4` on `http://127.0.0.1:8000/v1`
(thinking off, json_schema, 262144 ctx). This is the operator's choice: "Qwen+Mistral" means Qwen in both slots.

## Runs

| run | scenario | driver | harness | result | judge expected | total |
|---|---|---|---|---|---|---|
| `run_20261003T181121Z_77ad6e` | `scenario_001` (flagship) | `scripts/runtime/judged_run.py` (API + SSE) | openclaw-agent | `no_event` / `z_north_road` / 0.45 | positive drop-off, east curb pocket | 155.1 s |
| `run_20261003T181947Z_0cc24a` | `eval_001` | Playwright, RUN click on `/ops` (:3000) | openclaw-agent | `passenger_dropoff_pickup` / `z_north_lot` / 0.60 | `passenger_dropoff_pickup` / `z_east_pocket` / positive | 37.2 s (click to complete 37.4 s) |

Both runs reached `run.complete` and the agent submitted. Neither was finalized by the policy, and the agent turn
ended with exit 0 and a `FINAL` line. The flagship verdict is a miss: the agent did not infer the hidden drop-off.

## Latency per stage (s, from the run's own envelope timestamps)

| stage | scenario_001 (contended) | eval_001 UI run |
|---|---|---|
| agent start-up (`run.started` to first tool call: sandbox exec, OpenClaw, first Qwen turn) | 5.67 | 3.88 |
| perception: `sample_video` + `inspect_camera` (tool time) | 64.06 (7 calls; inspect 9.34 / **44.97** / 8.15) | 13.54 (6 calls; max 5.57) |
| fusion: `correlate_observations` + `triangulate_region` (deterministic) | 0.004 | 0.003 |
| reasoning: `reason_hypothesis` (Qwen, reasoning slot) | 7.74 | 3.43 |
| evidence: `get_supporting_frames` | 0.00 (3 calls) | 0.00 (1 call) |
| submit | 0.00 | 0.00 |
| agent model time between tool calls (Qwen choosing the next call) | 77.67 (34.3 in one gap) | 16.37 |
| close (last tool to `run.complete`) | 0.004 | 0.003 |
| **total** | **155.15** | **37.23** |
| first observation / triangulation / first hypothesis | 17.9 / 135.1 / 144.9 | 10.2 / – / 31.4 |
| agent turn (OpenClaw process, incl. FINAL reply) | 157.0 | 38.7 |

Why scenario_001 was slow: vLLM's own log for 18:11:48–18:13:28 shows `Running: 3–4 reqs, Waiting: 1–2,
Deferred: 1–2` with GPU KV at ≤ 19%. This run issues one request at a time, so other sessions on the shared
Qwen server caused it. The 45 s `inspect_camera cam_b` and the 34 s agent gap fall in that window. No call
timed out or retried.

## Calibration (deployment parameters, `config/models/gb10.yaml`)

Measured and left unchanged:
- `timeout_seconds: 120`: the worst call was 45 s under 4+2 load, so there is 2.7× headroom. With no
  contention, inspect calls take 2.3–9.3 s.
- `max_tokens: 1024`: every inspect/reason call returned valid json_schema output, with 0 tool failures in
  either run apart from the one rejected call noted below.
- `context_tokens: 262144`: equals the served `max_model_len` (`/v1/models`).
- `sample_fps: 1`, `max_frames_per_camera: 12`, `max_width: 768`: 12 frames per camera, so an inspect is
  2–9 s without contention.

The server's request concurrency (≥ 4 running, then queued) is a vLLM launch flag, not a profile field.
D03 did not change it: the server is shared, and restarting it would interrupt other sessions.

## Ground-truth exclusion proof (`judged_run_run_20261003T181121Z_77ad6e.json`, `gt_exclusion`)

Withheld camera `cam_gt` (`data/prepared/scenario_001/hidden_ground_truth.mp4`). The tokens are the app's
`GtGuard` list (id, path, basename) plus the camera label, its MEVA id `G341` and `/api/judge`. Each scan
counts visible camera ids as a positive control, so an empty or wrong target cannot pass.

| surface | result | control hits (cam_a/b/c) |
|---|---|---|
| public scenario view `GET /api/scenarios/scenario_001` (what runs are built from) | 0 GT hits | 2/2/2 |
| media route `GET /media/scenarios/scenario_001/cameras/cam_gt` | **403** "the ground-truth camera is judge-only" | – |
| SSE stream (54 events) | 0 GT hits | 35/66/80 |
| run dir: `events.jsonl`, `run.json`, `agent_turn.json`, `agent_policy.json` | 0 GT hits | 40/76/92 |
| **the agent's own OpenClaw session transcript + trajectory in the sandbox** (system prompt, brief, every tool call/result Qwen saw), session `done` | 0 GT hits, run id present | 110/205/253 |
| sandbox filesystem: `find /` for `hidden_ground_truth.mp4` and a `scenario_001` dir | nothing found | – |

UI side: the Playwright eval_001 [gb10] test passed its GT watch. There was no `/api/judge` request before
REVEAL, and a MutationObserver found no GT token on the page until then. After REVEAL it found every token,
which proves the detector works.

Hermetic tests of the same boundary (`pytest_gt_exclusion.txt`): `test_least_privilege`, `test_media_api`,
`test_tool_session`, `test_run_handle`: **75 passed**.

## Files

- `judged_run_run_20261003T181121Z_77ad6e.json`: run record, per-call latency, agent policy/turn, GT proof
- `sse_run_20261003T181121Z_77ad6e.txt`: the raw SSE stream
- `judged_run_console.txt` (live run), `judged_run_reverify_console.txt` (`--run-id` re-scan after the turn ended)
- `latency_run_20261003T181947Z_0cc24a_ui_eval_001.json`: per-stage latency of the Playwright run
- `playwright_gb10_eval_001.txt`; screenshots `artifacts/e2e/ops-gb10-eval_001-{desktop,revealed-desktop,narrow-390}.png`,
  `artifacts/e2e/gb10-run-timing.json`, `artifacts/e2e/results-gb10.json`
- `runtime_status_20261003T182018Z.txt`: NemoClaw/OpenShell/OpenClaw status, model health, `RESULT: OK no cloud route`
