/**
 * Hand-written TypeScript mirrors of contracts/*.schema.json and contracts/SSE_EVENTS.md.
 * The JSON Schemas are the source of truth; keep this file in step with them.
 *
 * Coordinates: local metric frame, position = [x_east_m, y_north_m(, z_up_m)].
 * heading_deg / bearing_deg are compass bearings: 0 = north (+y), 90 = east (+x), clockwise.
 * Scenario time = camera media time + camera.time_offset_s.
 */

/* ------------------------------------------------------------------ scenario */

/** scenario.schema.json $defs/camera */
export interface Camera {
  id: string;
  file: string;
  model_access: boolean;
  label?: string | null;
  position?: number[] | null;
  heading_deg?: number | null;
  fov_deg?: number | null;
  time_offset_s?: number;
}

/** scenario.schema.json $defs/zone */
export interface Zone {
  id: string;
  label?: string | null;
  center: [number, number];
  radius_m: number;
}

/** scenario.schema.json (full scenario; server/judge side only, contains the GT camera). */
export interface Scenario {
  id: string;
  title?: string | null;
  duration_seconds?: number | null;
  coordinate_frame?: string | null;
  visible_cameras: Camera[];
  ground_truth_camera: Camera;
  zones?: Zone[];
  provenance?: Record<string, unknown> | null;
}

/**
 * A visible camera as the public API returns it (apps/api/services/scenarios.py public_view):
 * model-accessible only, never a file path.
 */
export interface PublicCamera {
  id: string;
  label?: string | null;
  position?: number[] | null;
  heading_deg?: number | null;
  fov_deg?: number | null;
  time_offset_s?: number;
  /** "/media/scenarios/{id}/cameras/{camera_id}", HTTP Range capable. Always set; 404s when media_available is false. */
  media_url: string;
  /** False when the file is missing on the API host; the tile then shows NO SIGNAL. */
  media_available: boolean;
}

/** apps/api/services/scenarios.py PUBLIC_PROVENANCE_KEYS: kept only when the value is a string. */
export const PUBLIC_PROVENANCE_KEYS = [
  "kind",
  "source",
  "dataset",
  "dataset_url",
  "url",
  "source_url",
  "license",
  "license_url",
  "attribution",
  "citation",
  "note",
] as const;

export type PublicProvenance = Partial<Record<(typeof PUBLIC_PROVENANCE_KEYS)[number], string>>;

/** GET /api/scenarios/{id}. Judge-safe and GT-redacted server-side; never contains the GT camera. */
export interface PublicScenario {
  id: string;
  title?: string | null;
  duration_seconds?: number | null;
  coordinate_frame?: string | null;
  cameras: PublicCamera[];
  zones: Zone[];
  has_ground_truth?: boolean;
  /** Always an object, possibly {}. */
  provenance: PublicProvenance;
}

/** GET /api/scenarios */
export interface ScenarioList {
  scenarios: PublicScenario[];
}

/** What the scenario selector needs; a PublicScenario satisfies it. */
export type ScenarioSummary = Pick<PublicScenario, "id" | "title" | "duration_seconds">;

/** GET /api/judge/scenarios/{id} ground_truth_camera (judge_view). */
export interface JudgeCamera {
  id: string;
  label?: string | null;
  position?: number[] | null;
  heading_deg?: number | null;
  fov_deg?: number | null;
  time_offset_s?: number;
  /** "/api/judge/scenarios/{id}/video", HTTP Range capable. */
  video_url: string;
  video_available: boolean;
}

/** GET /api/judge/scenarios/{id}. Judge-only; only the UI's reveal action reads it. */
export interface JudgeGroundTruth {
  judge_only: true;
  scenario_id: string;
  ground_truth_camera: JudgeCamera;
  /** prepared/<scenario_id>/expected.json, or null when absent/unreadable. */
  expected: Record<string, unknown> | null;
  /** The full manifest provenance, or {} when the manifest has none. */
  provenance: Record<string, unknown>;
}

/* --------------------------------------------------------------------- media */

/** media_manifest.schema.json frames[] */
export interface FrameRef {
  /** Position in frames[]; what Observation.supporting_frames cites. */
  index: number;
  /** Source video frame number. */
  frame_id: number;
  /** Seconds on the camera media clock (UI seek target). */
  t: number;
  path?: string | null;
}

/** media_manifest.schema.json */
export interface MediaManifest {
  camera_id: string;
  source: string;
  source_sha256?: string | null;
  duration_s: number;
  src_fps: number;
  width: number;
  height: number;
  sample_fps: number;
  start_s?: number;
  end_s?: number | null;
  clip_path?: string | null;
  frames: FrameRef[];
}

/* -------------------------------------------------------------- observations */

export type ImageDirection =
  | "left"
  | "center_left"
  | "center"
  | "center_right"
  | "right"
  | "toward_camera"
  | "away_from_camera";
export type CompassDirection =
  | "north"
  | "northeast"
  | "east"
  | "southeast"
  | "south"
  | "southwest"
  | "west"
  | "northwest";

/** observation.schema.json $defs/observation. Times are camera media seconds. */
export interface Observation {
  id: string;
  t_start: number;
  t_end: number;
  cue_type: string;
  description: string;
  direction?: ImageDirection | CompassDirection | string | null;
  confidence: number;
  supporting_frames: number[];
}

/** observation.schema.json */
export interface ObservationBatch {
  camera_id: string;
  observations: Observation[];
}

/* ------------------------------------------------------------------ evidence */

/** evidence.schema.json cameras[] */
export interface EvidenceCamera {
  id: string;
  label?: string | null;
  model_access: true;
  position?: number[] | null;
  heading_deg?: number | null;
  fov_deg?: number | null;
}

/** evidence.schema.json $defs/evidence_item. Times are scenario seconds. */
export interface EvidenceItem {
  id: string;
  camera_id: string;
  t_start: number;
  t_end: number;
  cue_type: string;
  description: string;
  direction?: string | null;
  bearing_deg?: number | null;
  confidence: number;
  supporting_frames: number[];
}

/** evidence.schema.json $defs/cluster */
export interface EvidenceCluster {
  id: string;
  t_start: number;
  t_end: number;
  evidence_ids: string[];
  camera_ids: string[];
  score: number;
}

export type RegionMethod = "ray_intersection" | "single_ray" | "zone_prior" | "none";

/** evidence.schema.json $defs/region_candidate */
export interface RegionCandidate {
  id: string;
  label?: string | null;
  center?: [number, number] | number[] | null;
  radius_m?: number | null;
  score: number;
  camera_ids: string[];
  evidence_ids: string[];
  method: RegionMethod;
}

/** evidence.schema.json */
export interface EvidenceBundle {
  scenario_id: string;
  status: "ok" | "insufficient";
  cameras: EvidenceCamera[];
  evidence: EvidenceItem[];
  clusters: EvidenceCluster[];
  region_candidates: RegionCandidate[];
  notes?: string[];
}

/* ---------------------------------------------------------------- hypothesis */

export interface Alternative {
  event_type: string;
  confidence: number;
}

/** hypothesis.schema.json. event_type "unknown" is the abstain path. */
export interface Hypothesis {
  event_type: string;
  region: string;
  confidence: number;
  evidence_ids: string[];
  reason: string;
  alternatives: Alternative[];
  limitations: string[];
}

export const ABSTAIN_EVENT_TYPE = "unknown";

export function isAbstain(h: Hypothesis | null | undefined): boolean {
  return !!h && h.event_type === ABSTAIN_EVENT_TYPE;
}

/* ----------------------------------------------------------------------- run */

export type RunState = "queued" | "running" | "complete" | "failed";

/** run.schema.json */
export interface RunRecord {
  run_id: string;
  scenario_id: string;
  profile: string;
  state: RunState;
  created_at: string;
  updated_at: string;
  finished_at?: string | null;
  hypothesis?: Hypothesis | null;
  error?: string | null;
  last_seq: number;
}

/** POST /api/runs body (apps/api/schemas/run.py RunRequest). pace_s must be 0..5. */
export interface RunRequest {
  scenario_id: string;
  profile?: string | null;
  pace_s?: number | null;
}

/** POST /api/runs (202, Location header) and GET /api/runs/{run_id}. */
export interface RunResponse extends RunRecord {
  run_url: string;
  /** Open with EventSource; resumes via Last-Event-ID on reconnect. */
  events_url: string;
}

/* ----------------------------------------------------------------------- SSE */

export const EVENT_TYPES = [
  "run.started",
  "camera.started",
  "camera.frames.sampled",
  "camera.observation",
  "camera.complete",
  "fusion.started",
  "evidence.linked",
  "triangulation.updated",
  "orchestrator.started",
  "tool.started",
  "tool.completed",
  "hypothesis.updated",
  "run.complete",
  "run.failed",
] as const;

export type EventType = (typeof EVENT_TYPES)[number];

export const TERMINAL_EVENT_TYPES: ReadonlySet<EventType> = new Set(["run.complete", "run.failed"]);

/** SSE_EVENTS.md does not fix the summary shape; render strings verbatim, objects as k=v. */
export type ToolSummary = string | Record<string, unknown> | null;

export interface SampledFrame {
  index: number;
  frame_id: number;
  /** Camera media seconds. */
  t: number;
  /** API path to the sampled JPEG. */
  url: string;
}

export interface Ray {
  camera_id: string;
  evidence_id: string;
  origin: [number, number] | number[];
  bearing_deg: number;
}

/** Payload catalog from contracts/SSE_EVENTS.md. */
export interface EventPayloads {
  "run.started": { scenario_id: string; profile: string; camera_ids: string[]; harness: string };
  "camera.started": { camera_id: string };
  "camera.frames.sampled": { camera_id: string; sample_fps: number; frames: SampledFrame[] };
  "camera.observation": { camera_id: string; observation: Observation };
  "camera.complete": {
    camera_id: string;
    observation_count: number;
    latency_ms: number;
    adapter: string;
  };
  "fusion.started": { evidence_count: number };
  "evidence.linked": { cluster: EvidenceCluster; evidence: EvidenceItem[] };
  "triangulation.updated": { candidates: RegionCandidate[]; rays: Ray[] };
  "orchestrator.started": { harness: string; agent: boolean; sequence: string[] };
  "tool.started": { call_id: string; tool: string; args_summary: ToolSummary };
  "tool.completed": {
    call_id: string;
    tool: string;
    ok: boolean;
    latency_ms: number;
    result_summary: ToolSummary;
    error?: string | null;
  };
  "hypothesis.updated": { hypothesis: Hypothesis; final: boolean };
  "run.complete": { hypothesis: Hypothesis; duration_ms: number };
  "run.failed": { stage: string; error: string };
}

export interface SseEnvelopeOf<K extends EventType> {
  run_id: string;
  /** Starts at 1, +1 per event. Clients ignore seq <= lastSeq. */
  seq: number;
  /** Wall-clock ISO timestamp. Payload times are scenario seconds. */
  ts: string;
  type: K;
  payload: EventPayloads[K];
}

/** sse_envelope.schema.json, discriminated on `type`. */
export type SseEnvelope = { [K in EventType]: SseEnvelopeOf<K> }[EventType];

const EVENT_TYPE_SET: ReadonlySet<string> = new Set(EVENT_TYPES);

/** Parse one SSE `data:` line. Returns null for anything that is not a well-formed envelope. */
export function parseEnvelope(data: string): SseEnvelope | null {
  let raw: unknown;
  try {
    raw = JSON.parse(data);
  } catch {
    return null;
  }
  if (!raw || typeof raw !== "object") return null;
  const env = raw as Record<string, unknown>;
  if (
    typeof env.run_id !== "string" ||
    typeof env.seq !== "number" ||
    !Number.isInteger(env.seq) ||
    env.seq < 1 ||
    typeof env.ts !== "string" ||
    typeof env.type !== "string" ||
    !EVENT_TYPE_SET.has(env.type) ||
    !env.payload ||
    typeof env.payload !== "object"
  ) {
    return null;
  }
  return env as unknown as SseEnvelope;
}

/* -------------------------------------------------------------------- health */

/** apps/api/services/model_health.py probe_role status. */
export type ModelRoleStatus = "fixture" | "unconfigured" | "unreachable" | "http_error" | "ok";

/** One inference role from GET /api/models/health. */
export interface ModelRoleHealth {
  backend: string | null;
  /** Userinfo stripped server-side. */
  base_url: string | null;
  model: string | null;
  status: ModelRoleStatus;
  /** null when not probed (fixture / unconfigured). */
  reachable: boolean | null;
  /** unconfigured: which of base_url / model are unset or REPLACE*. */
  missing?: string[];
  /** unreachable: exception type name only. */
  error?: string;
  http_status?: number;
  latency_ms?: number;
  /** ok: whether GET {base_url}/models listed the configured model; null when the body is not JSON, lists no ids, or no model is set. */
  model_listed?: boolean | null;
}

/** GET /api/models/health?profile= */
export interface ModelsHealth {
  profile: string;
  mode: string | null;
  source: "inference.profiles" | "yaml";
  /** fixture: every role fixture; ok: every role ok|fixture; else degraded. */
  status: "fixture" | "ok" | "degraded";
  perception: ModelRoleHealth;
  reasoning: ModelRoleHealth;
}

/** GET /healthz. Always HTTP 200; status degraded when any dependency is not ok. */
export interface ServiceHealth {
  status: "ok" | "degraded";
  service: string;
  version: string;
  profile: string;
  dependencies: Record<string, { ok: boolean } & Record<string, unknown>>;
}
