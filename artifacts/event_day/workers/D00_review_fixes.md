# D00 review fixes: OpenClaw agent policy

- Date: 2026-10-03 (event day). Base: `07cdf5e` (D00: OpenClaw agent definition, playbook and policy), branch `feat/prebuild`.
- Input: the independent D00 review and its adversarial verification (workflow `wf_99111532-eca`). Five findings were confirmed and are fixed here. The refuted findings were left alone, including "abstention rules run before the gate's confidence caps".
- Scope: edits only under `agent/event_day/**` and `artifacts/event_day/**`. Nothing was imported from `eval/`. Nothing was copied in from outside: every change was written in this session against the tested interfaces (`tools/`, `apps/api/schemas`) and the OpenClaw 2026.7.1 build in the sandbox. No git add, commit, reset or stash.

## Findings and fixes

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | major | `_authorize_alert` checked only `action` and `channel`. OpenClaw 2026.7.1 merges `before_tool_call` hook params into the agent's (`mergeParamsWithApprovalOverrides`: `{...originalParams, ...approvalParams}`, `dist/agent-tools.before-tool-call-84fX7TrL.js` lines 938-946 and 1735). So keys the agent added, such as `media`, `buffer`, `attachments`, `caption`, `filename`, `presentation`, `targets`, `accountId` or `dryRun`, survived the grant. | New `ALERT_PARAM_KEYS = {action, channel, target, message}`. `authorize_alert` refuses any call whose params hold another key, including `dryRun: false`. The refusal gives only a count and never echoes the keys, which are agent text. A refused call does not use up the one grant. For a granted call the hook's four keys win the merge, so the call that runs is exactly `grant.arguments`. The `AlertGrant` and `authorize_alert` docstrings, the module docstring, `POLICY.md` and `TOOLS.md` now describe the merge. POLICY.md's D01 hand-off no longer says "replace". It now says: pass the params unchanged, block on refusal, return `{params: grant.arguments}`, never strip keys and then grant. Safety rests on the guard rejecting non-conforming calls, not on replacement. |
| 2 | major | `weakening_violations` set only an upper bound on alternatives. The agent could drop or lower the reasoner's rival, and the rival rule (rule 2) then never saw it. Example: reasoner `vehicle_stop 0.5` against `vehicle_turnaround 0.7`. Submitted with `alternatives: []`, it was accepted at 0.5 and alerted. | A non-abstaining claim must now keep every reasoner alternative at no lower confidence. Together with the existing upper bound, that means at exactly the reasoner's confidence. So rule 2 always sees the reasoner's rivals. The same check requires every reasoner limitation to be kept, which closes the same "may only weaken" gap and matches AGENTS.md's "every claim keeps its alternatives and limitations". The refusal tells the agent to submit `{}` or abstain. |
| 3 | minor | An abstention the agent wrote after `reason_hypothesis` passed through unchanged. It could drop the reasoner's claim and alternatives and carry any confidence: the playbook template gave `unknown` with `alternatives: []`, and confidence 1.0 was accepted. | New pure `normalize_abstention(claim, raw)` rebuilds every agent abstention in the policy's own `abstain(raw, why)` form. It keeps the reasoner's claim as an alternative, along with its alternatives, evidence ids and limitations. Confidence is at most `ABSTENTION_CONFIDENCE` (0.0 before the reasoner answered). The agent's reason and limitations are added as limitations. `_vet_submission` applies it after the weakening check. POLICY.md and the AGENTS.md abstention note say so. |
| 4 | minor | After the runner published `run.complete`, the closed-run refusal made `AgentPolicy.call` raise: `RunHandle._publish` throws `RuntimeError` and `_refuse` emitted without a guard. The refusal was also missing from the ledger trace. | `_refuse` now wraps its `tool.started`/`tool.completed` emits. If `emit` raises, the refusal is still returned and recorded in `summary()`, only not emitted. The failure is logged at debug level on a closed run and at warning level otherwise. The class docstring and POLICY.md call policy item 7 describe this. |
| 5 | minor | `artifacts/event_day/DELTA_REPORT.txt` was stale: it listed only `agent/event_day/README.md` in the diff and `current_commit=98453c9`. | Regenerated at the end of this task with `./scripts/verify_event_delta.sh`. See below. |

## Tests added (agent/event_day/tests)

- `test_policy_session.py`
  - `test_a_message_call_with_any_key_beyond_the_alerts_own_is_refused`, parametrized over `media`, `targets`, `dryRun: true`, `dryRun: false`, `caption`, `presentation` and an unknown key. Each is refused, the reason does not echo the key, and the alert stays `due`. The exact canonical call (`alert.arguments`) is then granted, and `{**args, **grant.arguments} == args` models OpenClaw's merge. The clean-run test also asserts the merge result for the garbled-text grant.
  - `test_dropping_or_lowering_the_reasoners_rival_is_refused`: the reviewers' scenario, `vehicle_stop 0.5` against `vehicle_turnaround 0.7`. `alternatives: []` and the rival lowered to 0.1 are both refused. A following `{}` abstains, with no alert.
  - `test_the_playbooks_abstention_keeps_the_reasoners_claim_and_alternatives[0.0, 1.0]`: the JSON template parsed from AGENTS.md, submitted after `reason_hypothesis`. The final result is `unknown` at 0.2 with alternatives `[(vehicle_stop, 0.74), (vehicle_turnaround, 0.39)]`, the reasoner's evidence ids, and the agent's reason as a limitation.
  - `test_a_call_after_the_run_completed_is_refused_not_raised`: the test emit raises exactly as `RunHandle._publish` does after `run.complete`. A later call returns the closed-run refusal, emits nothing, appears in the trace, and `finalize()` still returns the submitted hypothesis.
- `test_policy_rules.py`
  - Two new weakening cases: a dropped alternative and a lowered alternative.
  - `test_a_submitted_claim_keeps_the_reasoners_limitations`.
  - `test_dropping_the_reasoners_rival_cannot_get_around_the_rival_rule`.
  - `test_an_agent_abstention_is_rebuilt_in_the_policys_form`, with and without a reasoner hypothesis.

Regression check: I loaded the `07cdf5e` version of `policy.py` in place of the new one through a scratch pytest plugin (scratchpad only, not in the repo). All 11 new session tests fail against it, and all of them pass against the fixed policy. A separate scratch run used the real `apps.api.services.runs.RunHandle` with `GtGuard.for_scenario`. After `finish_complete`, a closed-run call returned the refusal and `summary()` held 11 calls with 11 trace entries. A `media` grant was refused and the canonical grant held exactly the four keys.

## Files changed

- `agent/event_day/policy.py`
- `agent/event_day/POLICY.md`
- `agent/event_day/openclaw/workspace/TOOLS.md` (the alert-guard wording)
- `agent/event_day/openclaw/workspace/AGENTS.md` (one sentence on how the policy keeps the reasoner's claim in an abstention)
- `agent/event_day/tests/test_policy_rules.py`
- `agent/event_day/tests/test_policy_session.py`
- `artifacts/event_day/DELTA_REPORT.txt` (regenerated)
- `artifacts/event_day/workers/D00_review_fixes.md` (this file)

## Commands and results

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest agent/event_day/tests -q` | exit 0. With pyproject's `addopts = "-q"` this is `-qq`, so it prints only the progress dots. |
| `.venv/bin/python -m pytest agent/event_day/tests` | `70 passed` (54 before, 16 new) |
| `.venv/bin/ruff check agent/event_day` | `All checks passed!` |
| `.venv/bin/ruff format --check agent/event_day` | `12 files already formatted` |
| `./scripts/verify_event_delta.sh` | exit 0. Rewrote `artifacts/event_day/DELTA_REPORT.txt` with `verified_at_utc=2026-10-03T17:04:35Z`, `prebuild_commit=68060460…`, `current_commit=bc0b164…`. The event-agent diff now lists all 14 D00 files under `agent/event_day/` (13 added, README modified; 14 files changed, 4846 insertions, 4 deletions). Imports of the judge-side eval package: `none`. |

## Notes

- Concurrent work: while this ran, another workflow had uncommitted changes under `apps/**`, `config/**`, `contracts/**` and `tests/e2e/**`, including `apps/api/schemas`, which the policy imports. They appear in the delta report's status section and are not part of this fix. The D00 suite passes with them in place.
- HEAD moved to `bc0b164` during this task (docs commit: D02 defers the Telegram alert and keeps the alert code switched off). The alert-guard fixes still hold whenever the alert is armed. With no `AlertRoute`, the policy already skips the alert.
- No ground-truth identifier, chat id or token appears in any refusal, test output or artifact written here.
