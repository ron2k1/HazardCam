# Tool notes

The tools come from the Ambient Urban Mirror tool contract (`contracts/tools.schema.json`),
served to you by the `mirror` MCP server. OpenClaw names them `mirror__<tool>`; their
argument schemas are exactly the contract's. A bounded policy wraps every call: it checks the
camera id, call caps, the deadline and what a submitted hypothesis may contain. It refuses with
an error that says what to do next. This file is guidance only. The tool policy in
`agent.json` decides what is callable.

- `camera_id` is always one of the brief's visible cameras.
- Times in results are scenario seconds. Frame indices are per camera. File paths in results
  are blanked: you never need them.
- `mirror__triangulate_region` returns the evidence bundle: `status`, `cameras`, `evidence`,
  `clusters`, `region_candidates`, `notes`.
- `mirror__reason_hypothesis` and `mirror__submit_hypothesis` return a hypothesis:
  `event_type`, `region`, `confidence`, `evidence_ids`, `reason`, `alternatives`,
  `limitations`. `event_type` `unknown` is an abstention.
- `mirror__submit_hypothesis` closes the run.
- `message` (OpenClaw built-in) is not granted while alerts are switched off. When an operator
  turns the alert back on, the alert guard grants one `send` per run, with the policy's own
  text and target, and refuses a call that passes anything besides `action`, `channel`,
  `target` and `message`.
- Safety hazard jobs (HAZARD BRIEF) use `mirror__hazard_scan_clip`,
  `mirror__hazard_review_clip` and `mirror__hazard_submit_summary` from the same server,
  for the one clip the brief names. During a hazard job the seven run tools are refused, and
  during a run the hazard tools are refused. The review result lists findings with `id`,
  `severity`, `title`, `start_s`/`end_s`, `confidence`, `audit_verdict` and
  `recommended_actions`; the summary may only confirm those ids.
