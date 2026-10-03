# SSE Envelope

```json
{
  "run_id": "run_abc",
  "seq": 12,
  "ts": "2026-10-02T12:00:00.123Z",
  "type": "camera.observation",
  "payload": {}
}
```

Schema: `contracts/sse_envelope.schema.json` (Python: `apps.api.schemas.SseEnvelope`).

- `seq` starts at 1 and increases by exactly 1 per run. The frontend must ignore duplicate or out-of-order events (`seq <= lastSeq`).
- Wire format: each SSE message carries `id: <seq>` and `data: <envelope JSON>`. There is no `event:` field, so clients dispatch on `envelope.type`.
- `GET /api/runs/{id}/events` replays the full log from seq 1, or after `Last-Event-ID` / `?after_seq=N`, then streams live events. The server closes the stream after a terminal event (`run.complete` or `run.failed`).
- Times inside payloads are scenario seconds. Wall-clock time is only in `ts` and in an alert message's `created_at` (and, as text, its "When" line).
- No payload ever contains the ground-truth camera id, its file path, or `expected.json` content.

## Payload catalog

| type | payload |
|---|---|
| `run.started` | `{scenario_id, profile, camera_ids: [..visible only..], harness: "dev-sequence"}` |
| `camera.started` | `{camera_id}` |
| `camera.frames.sampled` | `{camera_id, sample_fps, frames: [{index, frame_id, t, url}]}` where `url` is an API path to the JPEG |
| `camera.observation` | `{camera_id, observation: Observation}` (one event per observation) |
| `camera.complete` | `{camera_id, observation_count, latency_ms, adapter}` |
| `fusion.started` | `{evidence_count}` |
| `evidence.linked` | `{cluster: EvidenceCluster, evidence: [EvidenceItem]}` (one per cluster) |
| `triangulation.updated` | `{candidates: [RegionCandidate], rays: [{camera_id, evidence_id, origin: [x,y], bearing_deg}]}` |
| `orchestrator.started` | `{harness: "dev-sequence", agent: false, sequence: [tool names]}` |
| `tool.started` | `{call_id, tool, args_summary}` |
| `tool.completed` | `{call_id, tool, ok, latency_ms, result_summary, error?}` |
| `hypothesis.updated` | `{hypothesis: Hypothesis, final: bool}` |
| `alert.message` | `{message: AlertMessage}` (plain-language message; see [Alert messages](#alert-messages)) |
| `alert.delivery` | `{message_id, channel: "telegram", status: "sent" \| "skipped" \| "failed" \| "not_connected", detail}` |
| `run.complete` | `{hypothesis: Hypothesis, duration_ms}` |
| `run.failed` | `{stage, error}` where `error` is a short message with no stack traces or secrets |

`args_summary` and `result_summary` are a string or a flat object (the UI renders objects as `k=v`); keep frame URLs and large payloads out of them.

Every domain event is emitted while the tool call that produced it is open, i.e. between that call's `tool.started` and `tool.completed`. Tool calls never nest: the session serializes them, even when a runtime calls tools from several threads.

| domain event | emitted inside |
|---|---|
| `camera.started`, `camera.frames.sampled` | `sample_video` |
| `camera.observation`, `camera.complete` | `inspect_camera` |
| `fusion.started`, `evidence.linked` | `correlate_observations` |
| `triangulation.updated` | `triangulate_region` |
| `hypothesis.updated` (`final: false`) | `reason_hypothesis` |
| `hypothesis.updated` (`final: true`) | `submit_hypothesis` |

A rejected call (unknown tool, arguments that violate `contracts/tools.schema.json`, a tool called before the one it depends on, or a camera that is not a visible input camera) emits only its failed pair: `tool.completed` with `ok: false` and an `error` that says how to correct the call, and no domain events. An unknown tool name is reported as `unknown_tool`. A camera id that is not a visible camera never appears in any payload; `args_summary.camera_id` shows `not_visible` instead. The `error` for a malformed call is built from the schema (what was expected at which argument), never from the argument values. If a failure message is still refused for naming the withheld camera, the pair closes with `<ExceptionType>: details withheld`.

A call that fails leaves the session state as it was: a tool commits its result only after its domain events are emitted. Re-running a tool clears everything downstream of it, including the submitted hypothesis and the supporting frames fetched for it.

The `orchestrator.*` and `tool.*` events form the agent trace panel. On event day the OpenClaw agent calls the same tool functions through the same event-emitting bindings, so the UI does not change.

## Alert messages

`alert.message` and `alert.delivery` are published by the run manager (`apps/api/services/runs.py` with `alert_feed.py`), never by a harness or tool, so every executor gets the same messages. An executor that emits `alert.message` is refused. They are the worker view's message feed and the Telegram text. Composition is deterministic local code (`apps/api/services/alert_messages.py`, wording in `config/alerts.yaml`): no model call and no network.

When they are published:

| kind | when | `alert.delivery` |
|---|---|---|
| `ping` | right after the first `camera.observation` whose cue has `ping: true` in `config/alerts.yaml` (at most one per run; a `transit` cue never pings) | yes |
| `alert` | right before `run.complete`, when the final hypothesis claims an event (any confidence: "How sure" says how likely it is, and a weak claim reads "Unsure (n%)") | yes |
| `unconfirmed` | right before `run.complete`, for an abstention (`unknown`) only; calm wording | no |
| `all_clear` | right before `run.complete`, for `no_event` | no |

A run that ends in `run.failed`, or whose final hypothesis is refused by the ground-truth guard, has no closing message. A composed message whose JSON still names the withheld camera is skipped and logged, never redacted, so no `[withheld]` placeholder reaches a worker. Composing a message is best effort: a failure is logged and skipped, and never fails a tool call or the run.

`AlertMessage` (`$defs/alert_message`, Python `apps.api.schemas.AlertMessage`):

```json
{
  "id": "msg_02",
  "kind": "alert",
  "level": "warning",
  "headline": "Traffic obstruction or collision: Intersection core",
  "lines": [
    {"key": "what", "label": "What happened", "value": "Camera 1: Several visible vehicles brake abruptly. Not seen directly; pieced together from the other cameras."},
    {"key": "where", "label": "Where", "value": "Intersection core (near Camera 2)"},
    {"key": "when", "label": "When", "value": "0:08–0:10 into the clip"},
    {"key": "how_sure", "label": "How sure", "value": "Likely (74%)"},
    {"key": "seen_on", "label": "Seen on", "value": "Camera 1, Camera 2 and Camera 3"},
    {"key": "what_to_do", "label": "What to do", "value": "Check the area and confirm what happened."}
  ],
  "evidence_ids": ["obs_a_001", "obs_b_001", "obs_c_001"],
  "camera_ids": ["cam_01", "cam_02", "cam_03"],
  "t_start": 8.0,
  "t_end": 10.5,
  "created_at": "2026-10-02T12:00:07Z",
  "text": "CHECK SOON — Traffic obstruction or collision: Intersection core\nWhat to do: Check the area and confirm what happened.\nWhat happened: ...\nWhere: ...\nWhen: ...\nHow sure: Likely (74%)\nSeen on: ...\n— CameraVision"
}
```

- `id`: `msg_01`, `msg_02`, ... in publish order within the run.
- `level`: `danger` / `warning` / `info`, from the event type's (or cue's) entry in `config/alerts.yaml`; `unconfirmed` and `all_clear` are always `info`.
- `lines`: in this order, each key at most once, with these fixed labels: `what` "What happened", `where` "Where", `when` "When", `how_sure` "How sure", `seen_on` "Seen on", `what_to_do` "What to do". A line without a value is left out.
- `evidence_ids`: the cited evidence (a ping: its observation id). For click-to-seek only; never displayed. `camera_ids`: visible cameras only. `t_start` / `t_end`: scenario seconds, or null.
- `headline`: the event and where it is. A named zone reads `"<event>: <zone>"` ("Vehicle stopped: Loading dock"); a computed region `"<event> in the blind spot <compass> of <Camera>"` (or "right next to <Camera>" under 5 m); otherwise the event label alone. A ping reads `"Heads-up from <Camera>: <cue>"`.
- `text`: the full plain-text rendering, exactly what Telegram receives. The first row is what a lock-screen preview shows: for `ping` and `alert`, the urgency word from `levels` in `config/alerts.yaml` (`ACT NOW` / `CHECK SOON` / `NO RUSH`), `" — "` and the headline (a dash, since headlines often hold a colon); for `unconfirmed` and `all_clear`, the headline alone. Then the "What to do" row, the other `"<label>: <value>"` rows in `lines` order, and `"— <product>"`.

Wording rules:

- **What happened**: at most one sanitized perception (Qwen) description of a cited observation, prefixed with its camera ("Camera 1: ..."), then a note that the event was not seen directly. The headline already names the event, so the label is not repeated. With no usable description the top cited camera's cue label stands in ("Camera 1: Vehicles braking or swerving."), and with nothing cited, the event label. The reasoning model's `reason` and `limitations` are never used. A description keeps only its first sentence, loses markup, emoji, control characters and a leading frame or camera echo, and is clipped to about 110 characters at a sentence or clause break (else at a word break with "…"). A description that addresses the reader, gives orders ("call", "evacuate", "ignore instructions") or shouts is not used.
- **Where**: a named zone's label with its nearest visible camera ("Intersection core (near Camera 2)"); for a computed region (`region_01`, ...) the nearest visible camera with a compass word and a rough distance ("In the blind spot about 30 m north-east of Camera C"); otherwise "Exact spot unclear".
- **When**: wall clock when the scenario provenance has a start time (`scenario_time_zero_wallclock`), else "0:07–0:27 into the clip". Times are clamped to the clip.
- **How sure**: the whole percent, banded: 80+ "Very likely", 60+ "Likely", 30+ "Possible", else "Unsure", e.g. "Likely (60%)". A ping says "Not confirmed yet"; an abstention "Not confirmed".
- **Seen on**: friendly camera names. `cam_b` is "Camera B", `cam_02` is "Camera 2", any other id is "Camera N" by its 1-based slot. The public scenario view carries the same name as `cameras[].display_name`.
- **What to do**: the event type's action from config, else "Check the area and confirm what happened."; a ping: "Be ready to check the area. The other cameras are still being checked."; `unconfirmed`: "No action needed now. A supervisor can review the footage."; `all_clear`: "Nothing to do."
- Unknown plain snake_case types read as words ("forklift_near_miss" is "Forklift near miss") with the default level and action. Anything else that is not a plain type name (ids, numbers, URLs, markup, odd shapes) reads "Something unusual". Configured labels go through the same leak check.
- Sanitizing works per sentence (`sanitize_text`): a sentence that holds anything technical (an internal id, snake_case name, coordinate, bearing or compass code, score, decimal, URL, path, token, frame or pixel talk, dataset code, pipeline jargon, or a ground-truth word) is dropped whole, never cut into fragments. Only visible camera ids and zone ids are rewritten inline to their names; a sentence that mentions a camera that is not on screen is dropped.
- No headline, line or `text` contains an internal id, coordinate, bearing, score, decimal (other than whole percents), URL, or anything about the withheld ground-truth camera. The worker view checks every string again (`apps/web/src/lib/plain.ts`) and hides a sentence that still leaks rather than rewriting it.

`alert.delivery` follows the `alert.message` of every `ping` and `alert`. Without the executor capability `delivers_alerts = True` (the prebuild default) its status is `not_connected`. An executor with the capability either exposes `deliver_alert(message) -> {"status", "detail"}` (called synchronously, so keep it quick; an exception is reported as `failed`) or emits `alert.delivery` itself for a `message_id` the manager has published. `detail` is a short reason for logs and the technical view, or null: a leading exception class, URLs, paths, bearer tokens, `key=value` secrets, bot tokens, JWTs, long digit runs and long opaque strings are removed, and a detail that names the withheld camera becomes null. The worker view never shows `detail`; it shows fixed words for `sent` and `failed` only.
