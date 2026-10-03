# D02 — Wire NemoClaw/OpenShell and local model routes

**Phase:** event_day  
**Wave:** 12  
**Owner:** runtime  
**Remote OK:** false  
**Dependencies:** D01

## Goal

EVENT DAY: run the OpenClaw agent through the required NemoClaw/OpenShell stack and connect local inference routes.

## Allowed paths

- `runtime/**`
- `scripts/runtime/**`
- `config/models/gb10.yaml`
- `artifacts/event_day/**`
- `tests/integration/runtime/**`

## Acceptance criteria

- [ ] Required stack status captured
- [ ] No cloud model route
- [ ] Failure surfaced to UI
- [ ] Runtime command documented

## Worker report

Before marking complete, write `artifacts/workers/D02.md` with changed files, commands/tests run, results, assumptions, and blockers.

## Event-day integrity

This task must be performed on event day. Do not copy a prebuilt finished agent/runtime implementation into place and represent it as newly authored. Use the prepared libraries/interfaces, then create the agent integration now.

## Fresh-build requirement

Implement the OpenClaw-specific portion for this task from the current repository state during the event-day session. Reuse already-tested ordinary libraries/interfaces, but do not source or copy a prewritten hidden OpenClaw implementation from outside the event-day working tree. Record commands/tests in `artifacts/event_day/workers/`.

## Operator addendum (added on event day, 2026-10-03)

- The operator registers Telegram with `nemoclaw ambient-mirror channels add telegram` (token typed into a hidden prompt, never into chat or files). Wire the D00 alert to that channel, keep egress to the Telegram preset only, and capture `nemoclaw ambient-mirror channels status --channel telegram` (it prints no secrets) in `artifacts/event_day/`.
- When Telegram is unreachable the run must still complete and the UI must show the alert as skipped, not failed.
- Host model servers are published on `127.0.0.1` and on the OpenShell bridge gateway `172.18.0.1` (Qwen :8000 is the agent brain via `inference.local`; Cosmos-Reason2-8B on :8001 fills the reasoning slot, a user-approved deviation from Mistral because the bundle has no Mistral weights). Record this in `config/models/gb10.yaml` and the worker report.
- Pings and alerts (operator request, 2026-10-03). Two Telegram messages at most per run, both best effort and both sent by the agent through the operator-registered channel:
  1. **Ping** (heads-up): the first time a Qwen `inspect_camera` observation carries an abnormal cue for the scenario's domain (for example a safety violation, a fall, a collision, an unsafe vehicle or person interaction), send one short message: camera id, timestamp range, cue type and the observation's own confidence, labelled clearly as an unconfirmed perception cue, plus the run id. Ordinary transit cues (`person_edge_transit`, `vehicle_edge_transit`) never ping. Extend the D00 policy for this rather than adding a second notifier.
  2. **Alert** (confirmed): the D00 alert after a non-abstained `submit_hypothesis`.
  Emit each attempt as an SSE event so the UI can show `sent`, `skipped` or `failed` next to the run, and capture one real ping and one real alert (message text only, no token or chat id) in `artifacts/event_day/`.
- Port note: on the GB10 the OpenShell gateway owns `127.0.0.1:8080` and `172.18.0.1:8080`, so the app API runs on `8088` (`API_PORT=8088`). The served model ids are `nvidia/Qwen3.6-35B-A3B-NVFP4` (:8000) and `nvidia/Cosmos-Reason2-8B` (:8001); a dev-sequence run on `eval_001` with these ids via `QWEN_MODEL`/`MISTRAL_MODEL` overrides completed in 36 s.
- **Telegram deferred (operator decision, 2026-10-03, supersedes the Telegram bullets above).** Do not register a Telegram channel, add Telegram egress, or grant the `message` tool. Keep the D00 alert code but switched off by default behind one explicit setting, so it can be enabled later without code changes. The judged path stays fully local: alerts are the on-screen worker messages only, and the UI shows no Telegram status while no channel is connected.
- **Time budget (operator, 2026-10-03).** The demo deadline is about 60 minutes after this task starts. Priority order: (1) one real run on a prepared scenario where the app's run path drives the `urban-mirror` OpenClaw agent inside the `ambient-mirror` sandbox through NemoClaw/OpenShell with local Qwen via `inference.local`, and the SSE stream reaches the UI; (2) capture `nemoclaw ambient-mirror status` and local model health in `artifacts/event_day/`; (3) surface a failure to the UI as `run.failed`; (4) the dev-sequence executor stays selectable as the fallback. Skip polish. `sg docker -c` gives docker access; `openshell sandbox exec ... </dev/null` needs stdin closed. Do not edit `hazards/`, `apps/web/**` or the Safety hazard API files; other work is in progress there.
- **Overlap with D01 (operator, 2026-10-03).** To save time this task starts while D01 is still finishing. Treat `agent/**` and `tests/integration/agent/**` as read-only and build the runtime wiring against D01's current `agent/event_day/{registration,register,mcp_server,executor,app}.py`. Before writing the worker report, wait until `pgrep -f 'D01 — Register'` prints nothing (D01 has exited), then re-run your end-to-end check against D01's final code.
