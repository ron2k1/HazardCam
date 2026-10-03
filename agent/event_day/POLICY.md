# Urban Mirror agent policy (event day, D00; D01 registration)

Written on 2026-10-03, after the event-day start marker (`artifacts/event_day/START.txt`). This
is the OpenClaw agent `urban-mirror`: its definition, its playbook, and the bounded policy
between it and the tested tools.

| File | What it is |
|---|---|
| `openclaw/agent.json` | The `agents.list[]` entry for OpenClaw 2026.7.1 (the build inside the NemoClaw v0.0.124 `ambient-mirror` sandbox) |
| `openclaw/workspace/AGENTS.md` | The playbook. OpenClaw injects it into the system prompt on every turn, together with `SOUL.md`, `IDENTITY.md`, `USER.md` and `TOOLS.md` |
| `policy.py` | `AgentPolicy`: the guard every agent tool call goes through, the abstention rules, and the Telegram alert (switched off by default) |
| `registration.py`, `mcp_server.py`, `executor.py`, `app.py`, `register.py` | D01: the `mirror` MCP server, its OpenClaw registration, and the run executor (see "Tool registration (D01)") |
| `openclaw/schema/…agents-list-entry.schema.json` | The `agents.list[]` schema taken from that build's `openclaw config schema`. The tests validate `agent.json` against it |
| `tests/` | D00 tests (`python -m pytest agent/event_day/tests`) |

## Division of labour

The agent decides which tool to call next. The policy decides whether that call may run. The
tools do all perception, time alignment, geometry and reasoning. The agent never concludes
anything on its own: the claim comes from `reason_hypothesis`, and the agent can only submit it
as it is or weaken it.

Brain: `inference/nvidia/Qwen3.6-35B-A3B-NVFP4`, reached through OpenShell's
`https://inference.local` route to the local vLLM server. No fallbacks, no thinking, no memory
search (no embedding calls), no skills, no subagents, no heartbeat.

## Tool policy (OpenClaw side, `agent.json`)

- Profile `minimal`, minus `session_status`. Every other tool group is denied: `group:messaging`,
  `group:fs`, `group:runtime`, `group:web`, `group:ui`, `group:sessions`, `group:memory`,
  `group:nodes`, `group:automation`, `group:media`, `group:agents`.
- `alsoAllow` holds exactly the seven registered tools, `mirror__sample_video` …
  `mirror__submit_hypothesis` (D01). They keep the schemas in `contracts/tools.schema.json`.
- No messaging capability. D00 granted `message` for the Telegram alert; D01 removed that grant
  and its `tools.message` block (operator addendum, 2026-10-03: Telegram deferred).
- Loop detection is on (warning 3, critical 5, circuit breaker 8).

## Call policy (`AgentPolicy.call`)

1. **Contract.** Only the seven contract tools exist. Malformed arguments go to the session,
   which reports them from the schema without echoing values.
2. **Closed run.** After a successful `submit_hypothesis`, every call is refused.
3. **Budget.** `4 × cameras + 12` calls in total and a 900 s deadline. Four failed or refused
   calls in a row also stop the run. A stopped run accepts only `submit_hypothesis`.
4. **Cameras.** `camera_id` must be a visible camera of the run's `ModelScenarioView`. A
   refusal lists the allowed ids and never repeats the rejected one. In traces and events, a
   non-visible id shows as `not_visible`.
5. **Caps.** At most 2 calls per camera for each camera tool, 3 each of
   `correlate_observations` and `triangulate_region`, 2 of `reason_hypothesis`, 2 submit
   attempts.
6. **Submission.** An explicit hypothesis may only weaken the reasoner's: same `event_type`
   (or an abstention), the same region or `unknown`, no higher confidence, evidence ids and
   alternatives taken from the reasoner's. It keeps every one of the reasoner's alternatives
   at the reasoner's confidence, and every one of its limitations: dropping or lowering a
   rival would strengthen the claim and hide the rival from abstention rule 2. Before
   `reason_hypothesis` has answered, only an abstention may be submitted.
7. **Refusals** come back as `{"ok": false, "refused": true, "error": "refused by policy: …"}`,
   and the error says what to do next. When the policy has an `emit`, each refusal also shows
   in the agent trace as a failed `tool.started`/`tool.completed` pair (`policy_NNN`). After
   the runner has published `run.complete`, `emit` raises; the refusal is still returned and
   kept in `summary()`, only not emitted. `call` never raises for a bad call.

D03 may tune the `Budget` numbers. The rules stay as they are.

## Abstention, alternatives and limitations

These rules run on every submission, before the deterministic gate in `tools/submit.py`:

1. Confidence below `ABSTAIN_BELOW = 0.3`: abstain.
2. The reasoner ranked an alternative at or above its own claim: abstain.
3. No alternatives were ranked: add a limitation saying so.
4. An alternative within `CLOSE_MARGIN = 0.1` of the claim: add a limitation saying so.

An abstention is `event_type`/`region` `unknown`, with confidence at most 0.2. It keeps the
reasoner's claim as an alternative and the reason as a limitation, so the judge still sees what
was considered. An abstention the agent writes itself is rebuilt in this same form
(`normalize_abstention`): the policy builds `abstain(raw, …)` from the reasoner's hypothesis,
with the agent's reason and limitations added as limitations. The agent's own confidence,
evidence ids and alternatives are not used. The gate then adds its own rules (evidence ids, region candidates, confidence
caps, the not-directly-visible limitation). `finalize()` closes a run the agent left without a
submission by abstaining through the same gate.

## Telegram alert (operator addendum)

**Switched off (operator addendum, 2026-10-03).** The guard below stays in `policy.py`, disarmed
behind one setting, `AUM_AGENT_TELEGRAM_ALERT` (`1`/`true`/`on`/`yes` arms it; unset is off).
While it is off, the brief has no alert line, the submit reply has no `alert` key,
`authorize_alert` refuses every call, and the summary shows `enabled: false`, status `skipped`
(or `not_due`) with the reason. Turning the alert back on needs the setting, plus three things
D01 deliberately left out: the `message` grant in `agent.json`, a Telegram channel (D02) and the
`before_tool_call` hook described below.

- **When.** Only after a successful `submit_hypothesis`, and only if the final (gated)
  hypothesis is a known event type (`inference.vocab.EVENT_TYPES`, so not `unknown` or
  `no_event`) at or above the abstention threshold. Abstentions send nothing.
- **What.** The policy composes the text from the final hypothesis and the evidence bundle:
  event type, confidence, coarse region id, each cited visible camera with the scenario-time
  span of its cited evidence, and the run id. It holds no ground truth (the policy has none), no
  frames, no URLs and no tokens. A content check refuses URLs and token-shaped strings.
- **How.** The submit reply carries `alert: {send: true, tool: "message", arguments: {action:
  "send", channel: "telegram", target, message}}` next to the contract result. The playbook tells
  the agent to call `message` once with exactly those arguments.
- **At most one per run.** `authorize_alert(params)` is the guard to put in front of
  OpenClaw's `message` tool, as a `before_tool_call` hook. It grants one `send` to Telegram, only
  while the alert is due, and the granted arguments are always the policy's own.
- **No extra keys.** OpenClaw 2026.7.1 does not replace a call's params with the hook's. It
  merges them, `{...agentParams, ...hookParams}` (`mergeParamsWithApprovalOverrides` in
  `dist/agent-tools.before-tool-call-*.js`). Every key the agent typed that the hook does not
  set would reach the send, for example `media`, `buffer`, `attachments`, `caption`, `filename`,
  `presentation` buttons, `targets`, `accountId` or `dryRun`. So `authorize_alert` refuses any
  call whose params hold a key outside `action`, `channel`, `target` and `message`, including
  `dryRun: false`. The refusal does not echo the keys. For a call it grants, the hook's four
  keys win the merge, so the call that runs is exactly `grant.arguments`. Any other call is
  refused as well: a second send, another action or channel, a send before the submit, a send
  for an abstention. A refused call does not use up the one grant.
- **Best effort.** The run closes at the submit. `wait_closed()` wakes the runner, which
  completes the run (`run.complete`) right away, so it never waits for Telegram or for the
  agent's last reply. `record_alert(delivered, error)` settles the alert as `sent`, or as
  `skipped` with a redacted reason (URLs and token-shaped strings removed). `expire_alert()`
  skips an alert the agent never sent. Alert states are `pending`, `not_due`, `due`, `sending`,
  `sent` and `skipped`, never "failed". A Telegram failure cannot change the hypothesis, the run
  state or the SSE stream.
- **Visibility.** `alert_summary()` (also in `summary()["alert"]`) gives status, reason, event
  type, text and grant counts. It has no chat id and no token. `alert_listener` receives it on
  every change, outside the policy lock, and its errors are only logged.
- **Route.** `AlertRoute(target)` takes a Telegram chat id, `@channel` or forum-topic target
  from operator configuration. A bot token does not match the target pattern, so one pasted by
  mistake is rejected. The bot token itself never reaches this code: it lives only in the
  OpenShell gateway credential store (`nemoclaw ambient-mirror channels add telegram`).

## Ground truth

The policy holds the session's `ModelScenarioView` only. It holds no `Scenario`, no media or
label paths, and it imports nothing from the judge-side package. The run brief (`brief()`)
lists only visible cameras. The playbook forbids asking for other cameras, labels, expected
answers or judge data, and the agent has no file, shell or web tools to look for them.

## Tool registration (D01)

The seven tools reach OpenClaw as one MCP server, `mirror`, which the API process serves while
it owns a run. OpenClaw names MCP tools `<server>__<tool>`, hence `mirror__sample_video`.

- `registration.py`: the `tools/list` entries come from `contracts/tools.schema.json`
  (`$defs/<tool>_args`, with every `$ref` inlined). `agent_reply` blanks the host paths of a
  media manifest (`source` becomes `camera:<id>`, `clip_path` and `frames[].path` become
  `null`, as the contract allows), replaces absolute paths in error text with `<path>`, and
  withholds any reply that names the ground-truth camera. `merge_registration` writes
  `mcp.servers.mirror` (`streamable-http`, `toolFilter.include` = the seven tools, bearer token
  as the `${AUM_TOOLS_TOKEN}` env reference) and the agent entry, and adds `mirror__*` to every
  other agent's `tools.deny`: NemoClaw's global `tools.alsoAllow: ["bundle-mcp"]` would
  otherwise hand the tools to `main`.
- `mcp_server.py`: a stdlib Streamable HTTP server on exactly one path, `POST /mcp`
  (`initialize`, `ping`, `tools/list`, `tools/call`). Any other path is 404, `GET` is 405,
  there are no resources or prompts. With a token every request needs the bearer header; a
  foreign `Origin` is refused. `ToolGateway` binds it to one run at a time. Without a run every
  call is refused.
- `executor.py`: `OpenClawAgentExecutor` is the API's `RunExecutor`. Per run it builds the leak
  guard, reduces the scenario to its model view, opens the `ToolSession` and `AgentPolicy`,
  takes the gateway lease, emits `run.started`/`orchestrator.started` (harness
  `openclaw-agent`) and starts one agent turn with `policy.brief()` (session key = run id). It
  returns the final hypothesis once the policy closes on a submit; a turn that ends without one
  is finalized as an abstention, and a turn that failed before any call fails the run at stage
  `agent`. The lease lasts until the turn has ended, so a late call from an old turn can never
  reach the next run. `OpenClawCliLauncher` runs `openclaw agent --agent urban-mirror …`.
- `app.py`: `uvicorn --factory agent.event_day.app:create_agent_app` is the API with the agent
  executor and the tool server in one process. `register.py` merges the registration into an
  `openclaw.json` (`--fragment` prints only the D01 part, which holds no credential).
- Tests: `tests/integration/agent/` (schemas, a full API run, least privilege; the live
  OpenClaw checks run when `AUM_OPENCLAW_CLI` is set).

## Hand-off to D02

D02 wires the runtime (`runtime/nemoclaw/README.md`, `scripts/runtime/`). What it needs from D01:

- Run `create_agent_app` with `AUM_OPENCLAW_CMD` set to the sandboxed CLI (for example
  `openshell sandbox exec -n ambient-mirror -- openclaw`), `AUM_TOOLS_BIND` set to loopback plus
  the bridge gateway the sandbox reaches (`127.0.0.1:8090,172.18.0.1:8090`), and
  `AUM_TOOLS_TOKEN` set to a fresh random token. The token is required once the server listens
  beyond loopback.
- Merge the registration with `merge_registration` (or `python -m agent.event_day.register`)
  into the sandbox's `openclaw.json`, never into the repo, and upload `openclaw/workspace/*` to
  `/sandbox/.openclaw/workspace-urban-mirror`. The server entry carries the token as the
  `${AUM_TOOLS_TOKEN}` reference. Where the OpenClaw process does not have that variable (the
  NemoClaw-started gateway does not), the token has to be written into the private config
  instead. NemoClaw's managed `mcp add` needs `https://` and rejects `host.openshell.internal`,
  so the registration uses OpenClaw's own `mcp.servers` entry.
- Egress: one preset for the tool port on the host (8090, `/mcp`) and nothing else new.
- Telegram stays deferred (see the alert section): no channel, egress or token.
