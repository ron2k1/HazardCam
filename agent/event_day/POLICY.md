# Urban Mirror agent policy (event day, D00)

Written on 2026-10-03, after the event-day start marker (`artifacts/event_day/START.txt`). This
is the OpenClaw agent `urban-mirror`: its definition, its playbook, and the bounded policy
between it and the tested tools.

| File | What it is |
|---|---|
| `openclaw/agent.json` | The `agents.list[]` entry for OpenClaw 2026.7.1 (the build inside the NemoClaw v0.0.124 `ambient-mirror` sandbox) |
| `openclaw/workspace/AGENTS.md` | The playbook. OpenClaw injects it into the system prompt on every turn, together with `SOUL.md`, `IDENTITY.md`, `USER.md` and `TOOLS.md` |
| `policy.py` | `AgentPolicy`: the guard every agent tool call goes through, the abstention rules, and the Telegram alert |
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

- Profile `minimal`, minus `session_status`. Every other tool group is denied: `group:fs`,
  `group:runtime`, `group:web`, `group:ui`, `group:sessions`, `group:memory`, `group:nodes`,
  `group:automation`, `group:media`, `group:agents`.
- `alsoAllow: ["message"]` is the one messaging capability, used for the alert. `message` is
  limited to action `send` (`tools.message.actions.allow`), cross-context sends are off, and
  broadcast is off.
- Loop detection is on (warning 3, critical 5, circuit breaker 8).
- D01 adds its registered tool surface (plugin or MCP id) to `alsoAllow`. The seven tools keep
  the names and schemas in `contracts/tools.schema.json`.

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
- **At most one per run.** `authorize_alert(params)` is the guard D01 puts in front of
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

## Hand-off to D01 / D02

D01 (tool registration):
- Build one `AgentPolicy(session, emit=…, run_id=<run dir name>, alert_route=…)` per run. Expose
  each contract tool as `policy.call(name, args).to_json()`.
- Wire `authorize_alert` into a `before_tool_call` hook for `message`. Pass it the call's params
  exactly as received. Return `{block: true, blockReason: grant.reason}` when `allowed` is false.
  Otherwise return `{params: grant.arguments}`. OpenClaw merges these over the agent's params
  rather than replacing them, so safety rests on the guard refusing every non-conforming call,
  not on replacement. Never strip extra keys and then grant. Wire `after_tool_call` to
  `record_alert` for the granted call, and call `expire_alert()` when the agent's turn ends.
- Start the agent with `policy.brief()`, one session per run (for example session key
  `agent:urban-mirror:<run_id>`). The executor returns `policy.final_hypothesis` as soon as
  `wait_closed()` returns, or `policy.finalize()` when the turn ends without a submit.
- Upload `openclaw/workspace/*` to the agent workspace (`/sandbox/.openclaw/workspace-urban-mirror`).

D02 (channel and runtime):
- Telegram channel: `actions.sendMessage: true`. Turn off `deleteMessage`, `editMessage`,
  `reactions`, `sticker`, `poll`, `createForumTopic` and `editForumTopic`. Use DM
  `allowlist` with no groups.
- Egress: the Telegram preset only. The alert target comes from operator env, never from a repo
  file. Show the alert as `skipped` in the UI when Telegram is unreachable.
