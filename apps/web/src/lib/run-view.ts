/**
 * Pure SSE -> view-state reducer. The mock replays contract examples through it, and the
 * live path (P11) can feed EventSource envelopes through the same function.
 */
import type {
  EvidenceCluster,
  EvidenceItem,
  Hypothesis,
  Observation,
  PublicCamera,
  Ray,
  RegionCandidate,
  RunState,
  SampledFrame,
  SseEnvelope,
  ToolSummary,
} from "./contracts";

export type CameraPhase = "idle" | "sampling" | "analyzing" | "complete";

export interface CameraRunState {
  phase: CameraPhase;
  observationCount: number;
  latencyMs: number | null;
  adapter: string | null;
  sampleFps: number | null;
  samples: SampledFrame[];
}

export type TraceStatus = "running" | "ok" | "error";

export interface TraceRow {
  callId: string;
  tool: string;
  status: TraceStatus;
  argsSummary: ToolSummary;
  resultSummary: ToolSummary;
  error: string | null;
  latencyMs: number | null;
  /** seq of the tool.started event. */
  seq: number;
  /** Wall-clock ISO timestamp of tool.started. */
  ts: string;
}

export interface HarnessInfo {
  name: string;
  agent: boolean;
  sequence: string[];
}

export type RunPhase = "idle" | RunState;

export interface RunView {
  runId: string | null;
  scenarioId: string | null;
  profile: string | null;
  phase: RunPhase;
  lastSeq: number;
  startedAt: string | null;
  lastTs: string | null;
  harness: HarnessInfo | null;
  cameraIds: string[];
  cameras: Record<string, CameraRunState>;
  /** Raw perception output per camera (camera media seconds). */
  observations: Record<string, Observation[]>;
  /** Fused evidence (scenario seconds), keyed by id. */
  evidence: Record<string, EvidenceItem>;
  clusters: EvidenceCluster[];
  candidates: RegionCandidate[];
  rays: Ray[];
  trace: TraceRow[];
  hypothesis: Hypothesis | null;
  hypothesisFinal: boolean;
  durationMs: number | null;
  failure: { stage: string; error: string } | null;
}

export const EMPTY_RUN_VIEW: RunView = {
  runId: null,
  scenarioId: null,
  profile: null,
  phase: "idle",
  lastSeq: 0,
  startedAt: null,
  lastTs: null,
  harness: null,
  cameraIds: [],
  cameras: {},
  observations: {},
  evidence: {},
  clusters: [],
  candidates: [],
  rays: [],
  trace: [],
  hypothesis: null,
  hypothesisFinal: false,
  durationMs: null,
  failure: null,
};

function emptyCamera(): CameraRunState {
  return {
    phase: "idle",
    observationCount: 0,
    latencyMs: null,
    adapter: null,
    sampleFps: null,
    samples: [],
  };
}

function patchCamera(
  view: RunView,
  cameraId: string,
  patch: (cam: CameraRunState) => CameraRunState,
): Record<string, CameraRunState> {
  return { ...view.cameras, [cameraId]: patch(view.cameras[cameraId] ?? emptyCamera()) };
}

/**
 * Apply one envelope. Duplicate or out-of-order events (seq <= lastSeq) and events from a
 * different run are ignored, per contracts/SSE_EVENTS.md.
 */
export function applyEvent(view: RunView, env: SseEnvelope): RunView {
  if (env.type !== "run.started" && view.runId !== null && env.run_id !== view.runId) return view;
  if (env.run_id === view.runId && env.seq <= view.lastSeq) return view;

  const base: RunView = { ...view, runId: view.runId ?? env.run_id, lastSeq: env.seq, lastTs: env.ts };

  switch (env.type) {
    case "run.started": {
      const p = env.payload;
      const cameras: Record<string, CameraRunState> = {};
      for (const id of p.camera_ids) cameras[id] = emptyCamera();
      return {
        ...EMPTY_RUN_VIEW,
        runId: env.run_id,
        scenarioId: p.scenario_id,
        profile: p.profile,
        phase: "running",
        lastSeq: env.seq,
        lastTs: env.ts,
        startedAt: env.ts,
        harness: { name: p.harness, agent: false, sequence: [] },
        cameraIds: p.camera_ids,
        cameras,
      };
    }
    case "orchestrator.started": {
      const p = env.payload;
      return { ...base, harness: { name: p.harness, agent: p.agent, sequence: p.sequence } };
    }
    case "camera.started":
      return {
        ...base,
        cameras: patchCamera(view, env.payload.camera_id, (c) => ({ ...c, phase: "sampling" })),
      };
    case "camera.frames.sampled": {
      const p = env.payload;
      return {
        ...base,
        cameras: patchCamera(view, p.camera_id, (c) => ({
          ...c,
          phase: "analyzing",
          sampleFps: p.sample_fps,
          samples: p.frames,
        })),
      };
    }
    case "camera.observation": {
      const p = env.payload;
      const prev = view.observations[p.camera_id] ?? [];
      if (prev.some((o) => o.id === p.observation.id)) return base;
      return {
        ...base,
        observations: { ...view.observations, [p.camera_id]: [...prev, p.observation] },
        cameras: patchCamera(view, p.camera_id, (c) => ({
          ...c,
          observationCount: c.observationCount + 1,
        })),
      };
    }
    case "camera.complete": {
      const p = env.payload;
      return {
        ...base,
        cameras: patchCamera(view, p.camera_id, (c) => ({
          ...c,
          phase: "complete",
          observationCount: p.observation_count,
          latencyMs: p.latency_ms,
          adapter: p.adapter,
        })),
      };
    }
    case "fusion.started":
      return base;
    case "evidence.linked": {
      const p = env.payload;
      const evidence = { ...view.evidence };
      for (const item of p.evidence) evidence[item.id] = item;
      const clusters = [...view.clusters.filter((c) => c.id !== p.cluster.id), p.cluster];
      return { ...base, evidence, clusters };
    }
    case "triangulation.updated":
      return { ...base, candidates: env.payload.candidates, rays: env.payload.rays };
    case "tool.started": {
      const p = env.payload;
      const row: TraceRow = {
        callId: p.call_id,
        tool: p.tool,
        status: "running",
        argsSummary: p.args_summary,
        resultSummary: null,
        error: null,
        latencyMs: null,
        seq: env.seq,
        ts: env.ts,
      };
      return { ...base, trace: [...view.trace.filter((r) => r.callId !== p.call_id), row] };
    }
    case "tool.completed": {
      const p = env.payload;
      const exists = view.trace.some((r) => r.callId === p.call_id);
      const done = (r: TraceRow): TraceRow => ({
        ...r,
        status: p.ok ? "ok" : "error",
        resultSummary: p.result_summary,
        error: p.error ?? null,
        latencyMs: p.latency_ms,
      });
      const trace = exists
        ? view.trace.map((r) => (r.callId === p.call_id ? done(r) : r))
        : [
            ...view.trace,
            done({
              callId: p.call_id,
              tool: p.tool,
              status: "running",
              argsSummary: null,
              resultSummary: null,
              error: null,
              latencyMs: null,
              seq: env.seq,
              ts: env.ts,
            }),
          ];
      return { ...base, trace };
    }
    case "hypothesis.updated":
      return { ...base, hypothesis: env.payload.hypothesis, hypothesisFinal: env.payload.final };
    case "run.complete":
      return {
        ...base,
        phase: "complete",
        hypothesis: env.payload.hypothesis,
        hypothesisFinal: true,
        durationMs: env.payload.duration_ms,
      };
    case "run.failed":
      return { ...base, phase: "failed", failure: env.payload };
    default:
      return base;
  }
}

export function replayEvents(events: readonly SseEnvelope[], from: RunView = EMPTY_RUN_VIEW): RunView {
  return events.reduce(applyEvent, from);
}

/* ------------------------------------------------------------- derived views */

/** One bar on the evidence timeline, in scenario seconds. */
export interface TimelineItem {
  id: string;
  cameraId: string;
  tStart: number;
  tEnd: number;
  confidence: number;
  cueType: string;
  description: string;
  /** True once fusion linked it into the evidence bundle. */
  linked: boolean;
}

/**
 * Merge raw observations (media time, shifted by each camera's time_offset_s) with fused
 * evidence (already scenario time). Fused evidence wins on id collision.
 */
export function timelineItems(view: RunView, cameras: readonly PublicCamera[]): TimelineItem[] {
  const offset = new Map(cameras.map((c) => [c.id, c.time_offset_s ?? 0]));
  const byId = new Map<string, TimelineItem>();
  for (const [cameraId, list] of Object.entries(view.observations)) {
    const off = offset.get(cameraId) ?? 0;
    for (const o of list) {
      byId.set(o.id, {
        id: o.id,
        cameraId,
        tStart: o.t_start + off,
        tEnd: o.t_end + off,
        confidence: o.confidence,
        cueType: o.cue_type,
        description: o.description,
        linked: false,
      });
    }
  }
  for (const e of Object.values(view.evidence)) {
    byId.set(e.id, {
      id: e.id,
      cameraId: e.camera_id,
      tStart: e.t_start,
      tEnd: e.t_end,
      confidence: e.confidence,
      cueType: e.cue_type,
      description: e.description,
      linked: true,
    });
  }
  return [...byId.values()].sort((a, b) => a.tStart - b.tStart);
}

/** Scenario seconds -> a camera's media seconds (the <video> seek target). */
export function scenarioToMediaTime(camera: Pick<PublicCamera, "time_offset_s">, t: number): number {
  return Math.max(0, t - (camera.time_offset_s ?? 0));
}
