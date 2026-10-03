# Tool notes

The tools come from the Ambient Urban Mirror tool contract (`contracts/tools.schema.json`).
Their names and argument schemas are exactly the contract's. A bounded policy wraps every
call: it checks the camera id, call caps, the deadline and what a submitted hypothesis may
contain. It refuses with an error that says what to do next. This file is guidance only. The
tool policy in `agent.json` decides what is callable.

- `camera_id` is always one of the brief's visible cameras.
- Times in results are scenario seconds. Frame indices are per camera.
- `triangulate_region` returns the evidence bundle: `status`, `cameras`, `evidence`,
  `clusters`, `region_candidates`, `notes`.
- `reason_hypothesis` and `submit_hypothesis` return a hypothesis: `event_type`, `region`,
  `confidence`, `evidence_ids`, `reason`, `alternatives`, `limitations`. `event_type` `unknown`
  is an abstention.
- `submit_hypothesis` closes the run. Its reply also carries `alert`.
- `message` (OpenClaw built-in) only allows action `send`. The alert guard grants one send
  per run, with the policy's own text and target. It refuses a call that passes anything
  besides `action`, `channel`, `target` and `message`: pass exactly `alert.arguments`, with no
  media, attachments, buttons, extra targets or `dryRun`.
