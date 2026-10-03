/**
 * Standalone mock data for the /ops shell, built only from contracts/examples (synced into
 * ./contract-examples). Values are ILLUSTRATIVE contract examples, not a real run. The UI
 * labels this source as MOCK wherever it is shown. P11 replaces it with the live API + SSE.
 */
import {
  PUBLIC_PROVENANCE_KEYS,
  type AlertDelivery,
  type AlertMessage,
  type EvidenceBundle,
  type Hypothesis,
  type JudgeGroundTruth,
  type ModelsHealth,
  type PublicScenario,
  type Ray,
  type RunRecord,
  type Scenario,
  type ScenarioSummary,
  type SseEnvelope,
} from "@/lib/contracts";
import { cameraName } from "@/lib/plain";

import alertDeliveryJson from "./contract-examples/alert_delivery.json";
import alertMessageJson from "./contract-examples/alert_message.json";
import alertPingJson from "./contract-examples/alert_message_ping.json";
import alertUnconfirmedJson from "./contract-examples/alert_message_unconfirmed.json";
import evidenceJson from "./contract-examples/evidence_bundle.json";
import hypothesisAbstainJson from "./contract-examples/hypothesis_abstain.json";
import hypothesisJson from "./contract-examples/hypothesis.json";
import runJson from "./contract-examples/run.json";
import scenarioJson from "./contract-examples/scenario_001.json";

const scenario = scenarioJson as unknown as Scenario;
const bundle = evidenceJson as unknown as EvidenceBundle;
const hypothesis = hypothesisJson as Hypothesis;
const hypothesisAbstain = hypothesisAbstainJson as Hypothesis;
const run = runJson as unknown as RunRecord;
const alertPing = alertPingJson as AlertMessage;
const alertFinal = alertMessageJson as AlertMessage;
const alertUnconfirmed = alertUnconfirmedJson as AlertMessage;
const alertDelivery = alertDeliveryJson as AlertDelivery;
/** The early heads-up fires on the first observation of this cue (config/alerts.yaml ping: true). */
const PING_CUE = "traffic_reaction";
/**
 * What this build's API reports for every heads-up and alert: no Telegram channel is connected
 * (alerts are on screen only), so the worker view shows no delivery line. The contract example
 * keeps the "sent" shape for a connected setup.
 */
const delivered = (messageId: string): AlertDelivery => ({
  ...alertDelivery,
  message_id: messageId,
  status: "not_connected",
  detail: "Telegram is not connected in this setup.",
});

export const MOCK_SOURCE_LABEL = "MOCK · contracts/examples · ILLUSTRATIVE";

/**
 * Public view, shaped exactly like the API's public_view: real media routes, but
 * media_available false so the mock never requests them (offline, no failed requests).
 */
export const mockScenario: PublicScenario = {
  id: scenario.id,
  title: scenario.title,
  duration_seconds: scenario.duration_seconds,
  coordinate_frame: scenario.coordinate_frame,
  start_wallclock: null,
  cameras: scenario.visible_cameras.map((c, i) => ({
    id: c.id,
    display_name: cameraName(c.id, i),
    label: c.label ?? null,
    position: c.position ?? null,
    heading_deg: c.heading_deg ?? null,
    fov_deg: c.fov_deg ?? null,
    time_offset_s: c.time_offset_s ?? 0,
    media_url: `/media/scenarios/${scenario.id}/cameras/${c.id}`,
    media_available: false,
  })),
  zones: scenario.zones ?? [],
  has_ground_truth: true,
  // same filter as the API's _provenance_summary: whitelisted keys with string values
  provenance: Object.fromEntries(
    PUBLIC_PROVENANCE_KEYS.flatMap((k) => {
      const v = scenario.provenance?.[k];
      return typeof v === "string" ? [[k, v]] : [];
    }),
  ),
};

export const mockScenarios: ScenarioSummary[] = [mockScenario];

const gt = scenario.ground_truth_camera;
export const mockJudge: JudgeGroundTruth = {
  judge_only: true,
  scenario_id: scenario.id,
  ground_truth_camera: {
    id: gt.id,
    label: gt.label ?? null,
    position: gt.position ?? null,
    heading_deg: gt.heading_deg ?? null,
    fov_deg: gt.fov_deg ?? null,
    time_offset_s: gt.time_offset_s ?? 0,
    video_url: `/api/judge/scenarios/${scenario.id}/video`,
    video_available: false,
  },
  expected: null,
  provenance: scenario.provenance ?? {},
};

const fixtureRole = { backend: "fixture", base_url: null, model: null, status: "fixture", reachable: null } as const;

/** What GET /api/models/health?profile=fixture returns (config/models/fixture.yaml). */
export const mockHealth: ModelsHealth = {
  profile: run.profile,
  mode: "fixture",
  source: "yaml",
  status: "fixture",
  perception: fixtureRole,
  reasoning: fixtureRole,
};

/** Compass bearing from a to b (0 = north/+y, 90 = east/+x). */
function bearing(a: number[], b: number[]): number {
  const deg = (Math.atan2(b[0] - a[0], b[1] - a[1]) * 180) / Math.PI;
  return (deg + 360) % 360;
}

/** Rays from each candidate's cameras toward its centre, so the plan view has geometry to draw. */
function mockRays(): Ray[] {
  const rays: Ray[] = [];
  for (const cand of bundle.region_candidates) {
    if (!cand.center) continue;
    cand.camera_ids.forEach((camId, i) => {
      const cam = bundle.cameras.find((c) => c.id === camId);
      if (!cam?.position) return;
      rays.push({
        camera_id: camId,
        evidence_id: cand.evidence_ids[i] ?? cand.evidence_ids[0] ?? "",
        origin: [cam.position[0], cam.position[1]],
        bearing_deg: bearing(cam.position, cand.center as number[]),
      });
    });
  }
  return rays;
}

export type MockVariant = "default" | "abstain";

/** The fixed dev-sequence event log, in the order SSE_EVENTS.md describes. */
export function buildMockEvents(variant: MockVariant = "default"): SseEnvelope[] {
  const finalHypothesis = variant === "abstain" ? hypothesisAbstain : hypothesis;
  const finalMessage = variant === "abstain" ? alertUnconfirmed : alertFinal;
  // an unconfirmed result is not offered to Telegram, so it has no delivery; the alert does
  const finalDelivery: AlertDelivery | null = variant === "abstain" ? null : delivered(finalMessage.id);
  const runId = run.run_id;
  const t0 = Date.parse(run.created_at);
  const out: SseEnvelope[] = [];
  let seq = 0;
  let call = 0;
  const push = (type: SseEnvelope["type"], payload: SseEnvelope["payload"]) => {
    seq += 1;
    out.push({
      run_id: runId,
      seq,
      ts: new Date(t0 + seq * 180).toISOString(),
      type,
      payload,
    } as SseEnvelope);
  };
  // created_at follows the mock clock, so the card's time matches the event's ts
  const alert = (message: AlertMessage, delivery: AlertDelivery | null) => {
    push("alert.message", { message: { ...message, created_at: new Date(t0 + (seq + 1) * 180).toISOString() } });
    if (delivery) push("alert.delivery", delivery);
  };
  let pinged = false;
  const tool = (
    name: string,
    args: string,
    result: string,
    latencyMs: number,
    inner?: () => void,
  ) => {
    call += 1;
    const callId = `call_${String(call).padStart(2, "0")}`;
    push("tool.started", { call_id: callId, tool: name, args_summary: args });
    inner?.();
    push("tool.completed", {
      call_id: callId,
      tool: name,
      ok: true,
      latency_ms: latencyMs,
      result_summary: result,
    });
  };

  const cams = scenario.visible_cameras;
  const duration = scenario.duration_seconds ?? 15;
  push("run.started", {
    scenario_id: scenario.id,
    profile: run.profile,
    camera_ids: cams.map((c) => c.id),
    harness: "dev-sequence",
  });
  push("orchestrator.started", {
    harness: "dev-sequence",
    agent: false,
    sequence: [
      "sample_video",
      "inspect_camera",
      "correlate_observations",
      "triangulate_region",
      "get_supporting_frames",
      "reason_hypothesis",
      "submit_hypothesis",
    ],
  });

  for (const cam of cams) {
    const frames = Array.from({ length: Math.floor(duration) }, (_, i) => ({
      index: i,
      frame_id: i * 30,
      t: i,
      url: `/media/runs/${runId}/frames/${cam.id}/${i}.jpg`,
    }));
    tool("sample_video", `${cam.id} · 1.0 fps`, `${frames.length} frames`, 140, undefined);
    const obs = bundle.evidence.filter((e) => e.camera_id === cam.id);
    tool("inspect_camera", cam.id, `${obs.length} observation(s)`, 920, () => {
      push("camera.started", { camera_id: cam.id });
      push("camera.frames.sampled", { camera_id: cam.id, sample_fps: 1, frames });
      for (const e of obs) {
        const off = cam.time_offset_s ?? 0;
        push("camera.observation", {
          camera_id: cam.id,
          observation: {
            id: e.id,
            t_start: e.t_start - off,
            t_end: e.t_end - off,
            cue_type: e.cue_type,
            description: e.description,
            direction: e.direction ?? null,
            confidence: e.confidence,
            supporting_frames: e.supporting_frames,
          },
        });
        if (!pinged && e.cue_type === PING_CUE) {
          pinged = true;
          alert(alertPing, delivered(alertPing.id));
        }
      }
      push("camera.complete", {
        camera_id: cam.id,
        observation_count: obs.length,
        latency_ms: 910,
        adapter: "fixture",
      });
    });
  }

  tool(
    "correlate_observations",
    `${bundle.evidence.length} obs · tol 1.5s`,
    `${bundle.clusters.length} cluster(s)`,
    6,
    () => {
      push("fusion.started", { evidence_count: bundle.evidence.length });
      for (const cluster of bundle.clusters) {
        push("evidence.linked", {
          cluster,
          evidence: bundle.evidence.filter((e) => cluster.evidence_ids.includes(e.id)),
        });
      }
    },
  );
  tool(
    "triangulate_region",
    `${bundle.clusters.length} cluster(s)`,
    `${bundle.region_candidates.length} candidate(s)`,
    4,
    () => push("triangulation.updated", { candidates: bundle.region_candidates, rays: mockRays() }),
  );
  tool("get_supporting_frames", "obs_a_001, obs_b_001, obs_c_001", "5 frame refs", 2);
  tool("reason_hypothesis", `bundle ${bundle.status}`, finalHypothesis.event_type, 1480, () =>
    push("hypothesis.updated", { hypothesis: finalHypothesis, final: false }),
  );
  tool("submit_hypothesis", finalHypothesis.event_type, "validated", 3, () =>
    push("hypothesis.updated", { hypothesis: finalHypothesis, final: true }),
  );
  alert(finalMessage, finalDelivery);
  push("run.complete", { hypothesis: finalHypothesis, duration_ms: seq * 180 });
  return out;
}

export const mockEvents: SseEnvelope[] = buildMockEvents("default");
