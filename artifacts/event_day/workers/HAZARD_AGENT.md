# HAZARD_AGENT: the /hazards review runs through the OpenClaw agent (event day, 2026-10-03)

Written fresh in the event-day working tree, 13:07 to 14:20 CDT, against the existing tested
interfaces: `ToolGateway`/`McpServer` (D01), `OpenClawCliLauncher` (D01/D02),
`hazards.pipeline.review_clip` and the API's `hazard_review_runner` seam. No prewritten agent was
copied. Nothing was committed or pushed.

## What changed

New files:

- `contracts/hazard_tools.schema.json`: the three tools. Input schemas are `$defs/<tool>_args`
  and result schemas are `$defs/<tool>_result`.
  - `hazard_scan_clip {clip_id}`
  - `hazard_review_clip {clip_id}`
  - `hazard_submit_summary {clip_id, headline, first_action, priority, confirmed_finding_ids}`
- `agent/event_day/hazard_tools.py`: `HazardJobSession` (what the gateway lease holds during a
  hazard job), `HazardTrace` (the `agent_trace.json` entries and `progress(0, 6, text)`
  narration), argument checks, and the summary rules.
  - The scan calls `review_clip(skip_model=True)` with the scratch root `<output_root>/agent_scan`.
    That keeps a scan from ever replacing a clip's current report.
  - The review calls `review_clip(skip_model=False)` with the real root, and returns the audited
    findings.
  - The submit validates the summary and writes `agent_summary.json`.
- `agent/event_day/hazard_runner.py`: `AgentHazardRunner`, name `openclaw-agent`. For each clip
  it:
  - takes the gateway lease;
  - starts one OpenClaw turn with a HAZARD BRIEF through the same launcher as runs (session key
    `hazard-<clip>-<8 hex>`, timeout 600 s);
  - sends review_clip's numbered steps through `progress`, and narration through
    `progress(0, 6, ...)`;
  - writes `agent_trace.json`, `agent_turn.json` and, on submit, `agent_summary.json`.
  - If there is no summary but the review ran, it keeps the run dir and records the failure in
    the trace. It raises `AgentRunError` only if nothing ran.
- `tests/integration/agent/test_hazard_agent.py`: 24 tests. A scripted launcher drives the tool
  calls over HTTP through the real MCP server, with a fake `review_clip`.

Edited files:

- `agent/event_day/registration.py`:
  - added `HAZARD_TOOL_NAMES` and `REGISTERED_TOOLS` (the 7 contract tools first, unchanged,
    then the 3 hazard tools);
  - hazard specs come from the new contract, with `$ref`s inlined;
  - `toolFilter.include` lists all 10 tools;
  - the MCP `timeout` went from 300 s to 600 s, so a review call (repeat scan, Qwen review and
    audit) fits.
- `agent/event_day/mcp_server.py`:
  - a lease holds any `ToolPolicy`, either `AgentPolicy` or `HazardJobSession`;
  - a lease serves only its own tool set. During a hazard job the 7 run tools are refused, and
    during a run the hazard tools are refused (`OTHER_JOB`);
  - `tools/call` accepts `REGISTERED_TOOLS`.
- `agent/event_day/app.py`: `create_agent_app` sets `app.state.hazard_review_runner` and sets
  `app.state.hazard_review_runner_name = "openclaw-agent"`. The runner shares the launcher and
  gateway with the run executor, and its profile is `settings.model_profile`.
- `agent/event_day/openclaw/agent.json`: `alsoAllow` adds `mirror__hazard_scan_clip`,
  `mirror__hazard_review_clip` and `mirror__hazard_submit_summary`. Nothing else is granted.
- Workspace files:
  - `AGENTS.md` gets a "Safety hazard review" section. It covers:
    - call order: scan, then review, then submit;
    - never invent a hazard;
    - plain words, most urgent action first;
    - if the review failed, submit priority `none` and say plainly that the check did not finish;
    - a blind-spot line (operator update 13:47).
  - `TOOLS.md`, `USER.md` and `IDENTITY.md` each get a line about HAZARD BRIEF.
- `agent/event_day/README.md` lists the two new modules.
- Tests updated for 10 registered tools:
  - `tests/integration/agent/test_tool_schemas.py`
  - `tests/integration/agent/test_agent_run.py`
  - `tests/integration/runtime/test_runtime_wiring.py`
  - `agent/event_day/tests/test_openclaw_definition.py` (also gained a playbook-section test)

I did not touch any of these: `apps/**`, `hazards/**`, `config/hazards.yaml`,
`contracts/hazard_view*`, `contracts/tools.schema.json`, `tests/unit/**` or `scripts/data/**`.

## Rules enforced by the tool surface

- Every call names the leased clip. A well-formed id for another clip is refused, and the refusal
  names only the leased id. A traversal or an extra field fails the contract, and the error
  quotes no value.
- Order: review before scan is refused, and so is submit before review. Repeat scan or review
  calls return the cached result. The call cap is 16, plus 6 extra submit attempts.
- Summary checks:
  - `headline` and `first_action` are at most 160 characters each;
  - neither may contain `/\b[EZH]\d{2,3}\b/`, `bbox`, `sha256`, `http`, `qwen`, `1910`/`osha`,
    or the clip id;
  - `confirmed_finding_ids` must come from the review;
  - a failed review requires priority `none` with no ids;
  - priority may not be higher than the highest severity among the confirmed findings.
  - A bad summary gets a tool error with the reason, so the agent retries.
- Agent replies carry no host paths, no dataset labels and no original file names. The brief
  names only the clip id.
- A new review deletes any stale `agent_summary.json` in its run dir before the agent submits.

## Commands and real outputs

```
.venv/bin/python -m pytest tests/integration/agent agent/event_day/tests -p no:cacheprovider -o addopts="--import-mode=importlib"
  -> 175 passed, 1 skipped in 42.50s          (skip: the opt-in live OpenClaw test)
.venv/bin/python -m pytest tests/integration/runtime -p no:cacheprovider -o addopts="--import-mode=importlib"
  -> 5 passed, 1 skipped in 0.66s
.venv/bin/ruff check agent/event_day tests/integration/agent tests/integration/runtime   -> All checks passed!
.venv/bin/ruff format --check agent/event_day tests/integration/agent                    -> 25 files already formatted
.venv/bin/python scripts/runtime/deploy_agent.py
  -> sandbox=ambient-mirror agents=['main', 'urban-mirror'] mcp=['mirror']
     policy: mirror-tools applied / workspace: 5 files -> /sandbox/.openclaw/workspace-urban-mirror
     openclaw.json: merged and hash refreshed
```

In-sandbox check of the deployed config:

- `toolFilter.include` lists all 10 tools, and `timeout` is 600;
- `urban-mirror` `alsoAllow` holds the 10 `mirror__*` tools;
- `AGENTS.md` contains "Safety hazard review".

API restart at 13:52 CDT (stop pid 833109; 8088 and 8090 were free after 2 s), using
`HAZARDS_DEMO_REPLAY=1 setsid nohup scripts/runtime/start_api.sh`. First log line:
`executor: openclaw agent urban-mirror in sandbox ambient-mirror on 127.0.0.1:8088`.

INTEGRATE-API restarted :8088 again at 14:01 with the same agent app, and
`/api/runtime/status` shows `openclaw ... safety checks: openclaw-agent`. That restart came after
my bs_02 #1 run finished and before bs_01/bs_03, so it interrupted none of my runs.

## Live agent runs

Every run below was `POST /api/hazards/clips/{id}/review` with `{"mode": "live"}`. Runs marked
refresh also sent `"refresh": true`, which forces a fresh Qwen review and audit. Each SSE stream
was read through to `done`.

- Every run's `done` carries `"runner": "openclaw-agent", "replay": false`.
- Every run made the three tool calls in order and ended with a `FINAL hazard ...` reply.
- No run had a refusal or a rejected submit.
- The API's run lock lets only one review run at a time, so I posted two at a time; "queue"
  below is how long a job waited.

| clip | job | request | started (CDT) | queue | agent turn | review call | total | Qwen review |
|---|---|---|---|---|---|---|---|---|
| hz_01 #1 | hzjob_199ec335c2fc | live | 13:53:38 | 0 s | 58.8 s | 6.5 s | 59.0 s | cache (from an earlier GB10 run) |
| hz_02 #1 | hzjob_98a32ef3a8f1 | live | 13:53:40 | 56.9 s | ~37 s | 12.3 s | 94.3 s | cache |
| hz_03 | hzjob_db86158d28bd | live+refresh | 13:55:23 | 0 s | 87.4 s | 60.8 s | 87.5 s | fresh (review 26.8 s, audit 20.2 s) |
| hz_00 | hzjob_900aaf5c351e | live+refresh | 13:55:24 | 86.4 s | 74.5 s | 54.6 s | 160.9 s | fresh |
| bs_02 #1 | hzjob_972d5d3a7920 | live | 13:58:06 | 0 s | 32.5 s | 10.9 s | 32.5 s | cache (superseded, see gaps) |
| bs_01 | hzjob_aafb36854d29 | live+refresh | 14:09:20 | 0 s | 116.3 s | 92.9 s | 116.4 s | fresh |
| bs_03 | hzjob_9942f37f2fc2 | live+refresh | 14:09:21 | 115.3 s | 97.6 s | 75.3 s | 213.0 s | fresh |
| hz_01 #2 | hzjob_3cd0b5e80c38 | live+refresh | 14:13:31 | 0 s | 62.5 s | 43.5 s | 62.5 s | fresh |
| hz_02 #2 | hzjob_55f82b182a97 | live+refresh | 14:13:35 | 58.4 s | 71.0 s | 47.3 s | 129.4 s | fresh |
| bs_02 #2 | hzjob_333315cfefe9 | live+refresh | 14:16:14 | 0 s | 80.2 s | 59.5 s | 80.2 s | fresh |

Final state at 14:17:56 CDT (`artifacts/event_day/hazard_agent/final_state.txt`):

- For all 7 clips, `GET /api/hazards/clips/{id}` shows `technical.agent.runner = openclaw-agent`,
  an 11-entry `technical.agent.trace`, `technical.agent.summary` and `worker.agent_summary`.
- Every current report is `model_review_complete` with a fresh Qwen review.
- In every case the confirmed ids are a subset of the report's findings.

| clip | priority | confirmed | agent job | headline |
|---|---|---|---|---|
| hz_00 | high | H01, H02 | hazard-hz_00-af3c5eaf | Worker exposed to active press point of operation on the left side of the factory floor |
| hz_01 | medium | H01, H02 | hazard-hz_01-fef779c8 | Forklift operating near seated worker in central aisle; unsecured bin near hydraulic press |
| hz_02 | high | H01, H02, H03 | hazard-hz_02-19ec8d4d | Machinery on the left side may be running with workers nearby and no lockout-tagout procedures in place |
| hz_03 | high | H01, H02 | hazard-hz_03-565cac70 | Worker too close to an active mechanical power press with unverified guards at the blue press station |
| bs_01 | high | H01 to H05 | hazard-bs_01-dd88d92f | Blind spot at the cross-aisle intersection in the center of the main aisle. Pedestrians walking in vehicle lanes ... |
| bs_02 | high | H01, H02 | hazard-bs_02-f14a88ea | Blind spot at the aisle intersection where forklifts and pedestrians cross with no mirror or stop line. |
| bs_03 | high | H01, H02, H03 | hazard-bs_03-477482bd | Blind corner at aisle intersection blocked by barriers and stacked materials obscures visibility ... |

Sample narration (SSE `agent` events, hz_01 #1):

1. "The safety agent picked up this clip and is planning its check"
2. "... asked for the camera scan"
3. "... has the camera scan"
4. "... asked the local AI to review the pictures and check them"
5. "... is reading the review and writing a summary"
6. "... wrote its summary for the floor team"

vLLM: `docker logs --since 30m qwen | grep -c 'POST /v1/chat/completions'` gave 36 at 13:53
(before the runs) and 66 at 14:18. All 66 fall between 18:53Z and 19:17Z
(`vllm_posts_per_minute.txt`), which is my run window. Those counts include the agent's own
completions (through `inference.local`) and the review and audit calls. The 19:00–19:01Z
POSTs come from another workflow's direct bs_* runs.

Artifacts are in `artifacts/event_day/hazard_agent/`. For each job there is
`<clip>_<job>.sse.log` (timestamped SSE), `<clip>_<job>.timing.json` and
`<clip>_<job>.view.json` (the clip view right after `done`). Also there:
`final_state.txt` and `vllm_posts_per_minute.txt`.

## Honest gaps

- The summary checks cover format and provenance, not meaning. Ids must come from the review,
  priority is capped by severity, and the text must be plain. The tools cannot check what the
  words claim. Example: hz_02's headline says "no lockout-tagout procedures in place", which is
  stronger than the audited finding ("energy state unknown").
- A non-agent run can leave a stale summary. bs_02 #1 (13:58, cached review) was overwritten at
  14:00 by a non-agent run into the same run dir, which left an `agent_summary.json` confirming
  H01–H03 next to a report with H01, H02. My runner now deletes a stale summary when a new agent
  review starts, and bs_02 #2 restored consistency. That fix is live since INTEGRATE-API's
  14:22:47 restart of :8088 (`agent.event_day.app:create_agent_app`, pid 1202090; runtime status
  `openclaw ok agent urban-mirror · safety checks: openclaw-agent`). But a direct run outside the agent still
  leaves agent files in place. The API side should drop `agent_*` files when the direct runner
  writes a run dir, or the view should check summary ids against the report.
- `agent_trace.json` is per run dir. Re-running a clip overwrites the previous agent trace (same
  deterministic run id); the SSE logs here keep every job's narration.
- The review call scans again (about 6 to 14 s), because `review_clip` has no scan cache. The
  scratch scan keeps the current report safe, at the cost of that repeat scan.
- hz_01 #1, hz_02 #1 and bs_02 #1 used the Qwen cache, so their review calls made no model
  request. Each clip was then rerun with `refresh`, and every current report is fresh.
- The `hazard_review_clip` MCP call blocks for the whole review: up to 93 s here, with a 600 s
  timeout. I did not test the behaviour if OpenClaw dropped a call before 600 s; a retry would
  wait on the session lock and return the cached result.
- I could not reply to the INTEGRATE-UI agent's coordination message: its agent id was not
  reachable from this session. I edited no `apps/web` files.
