# Tool-call capability probe

Single-turn: one request per case, the reply is scored and never executed. Method,
cases and scoring in `eval/tool_probe.py`. Not an agent loop and not the event-day
playbook. Rates are k/n = rate [Wilson 95%].

| profile | model | pass | schema-valid call | outcomes | parallel | invisible camera | recovered | median s |
|---|---|---|---|---|---|---|---|---|
| full-local | `ministral-3:8b` | 13/13 = 1.00 [0.77, 1.00] | 13/13 = 1.00 [0.77, 1.00] | ok 13 | 0 | 0 | True | 0.62 |
| lite-local | `ministral-3:3b` | 10/13 = 0.77 [0.50, 0.92] | 10/13 = 0.77 [0.50, 0.92] | no_tool_call 3, ok 10 | 2 | 0 | True | 0.33 |

## Per case

| case | full-local | lite-local |
|---|---|---|
| 00_next_after_start | ok (sample_video) | ok (sample_video) |
| 01_next_after_sample_video | ok (sample_video) | ok (sample_video) |
| 02_next_after_inspect_camera | ok (sample_video) | ok (sample_video) |
| 03_next_after_sample_video | ok (inspect_camera) | ok (sample_video) |
| 04_next_after_inspect_camera | ok (sample_video) | ok (sample_video) |
| 05_next_after_sample_video | ok (inspect_camera) | ok (inspect_camera) |
| 06_next_after_inspect_camera | ok (correlate_observations) | ok (correlate_observations) |
| 07_next_after_correlate_observations | ok (triangulate_region) | ok (triangulate_region) |
| 08_next_after_triangulate_region | ok (reason_hypothesis) | no_tool_call (None) |
| 09_next_after_reason_hypothesis | ok (submit_hypothesis) | ok (get_supporting_frames) |
| 10_next_after_get_supporting_frames | ok (submit_hypothesis) | no_tool_call (None) |
| 11_next_after_get_supporting_frames | ok (submit_hypothesis) | no_tool_call (None) |
| recovery | ok (inspect_camera) | ok (sample_video) |

Transcript: fixture run of `eval_001`. System message: "You run a multi-camera video analysis by calling tools. Reply with exactly one tool call that continues the run."
