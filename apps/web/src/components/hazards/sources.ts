/**
 * Where /hazards gets its data: the local API (live) or src/mocks/hazards (?mock=1). Both expose
 * the same calls, so the screen does not know which one it is talking to.
 */
import { API_BASE_URL } from "@/lib/config";
import {
  hazardsApi,
  STEP_MESSAGES,
  STEP_WORDS,
  subscribeJob,
  type ClipSummary,
  type HazardInstructions,
  type HazardView,
  type JobHandlers,
} from "@/lib/hazards-v1";
import { MOCK_INSTRUCTIONS, MOCK_STEP_MS, MOCK_VIEWS, summarize } from "@/mocks/hazards";

export interface HazardsSource {
  kind: "live" | "mock";
  clips: (signal?: AbortSignal) => Promise<ClipSummary[]>;
  view: (clipId: string, signal?: AbortSignal) => Promise<HazardView>;
  instructions: (signal?: AbortSignal) => Promise<HazardInstructions>;
  /** Starts a review job and returns its id. */
  review: (clipId: string, refresh: boolean) => Promise<string>;
  /** Streams the job's progress; returns a closer. */
  subscribe: (jobId: string, handlers: JobHandlers) => () => void;
}

export const liveSource: HazardsSource = {
  kind: "live",
  // Event day (demo): only the clips on the wall (config/wall.yaml: the drive's safety_hazard videos).
  clips: async (signal) => {
    const all = (await hazardsApi.clips(signal)).clips;
    const wall = await fetch(`${API_BASE_URL}/api/wall`, { signal }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const ids = new Set<string>((wall?.hazard_tiles ?? []).map((t: { clip_id: string }) => t.clip_id));
    return ids.size ? all.filter((c) => ids.has(c.clip_id)) : all.filter((c) => !c.clip_id.startsWith("bs_"));
  },
  view: (clipId, signal) => hazardsApi.view(clipId, signal),
  instructions: (signal) => hazardsApi.instructions(signal),
  review: async (clipId, refresh) => (await hazardsApi.review(clipId, refresh)).job_id,
  subscribe: subscribeJob,
};

/**
 * Offline replay: a "check" walks the six steps on a timer and then shows the stored report again.
 * Clips without a stored report end in the plain failed state; nothing is invented for them.
 * `empty` lists no clips (the empty state).
 */
export function mockSource(variant: "default" | "empty" = "default"): HazardsSource {
  const views: Record<string, HazardView> = variant === "empty" ? {} : { ...MOCK_VIEWS };
  const reviewing = new Set<string>();
  let jobs = 0;
  const statusOf = (v: HazardView): HazardView =>
    reviewing.has(v.clip.clip_id) ? { ...v, status: "reviewing" } : v;

  return {
    kind: "mock",
    clips: async () => Object.values(views).map((v) => summarize(statusOf(v))),
    view: async (clipId) => {
      const v = views[clipId];
      if (!v) throw new Error("unknown clip");
      return statusOf(v);
    },
    instructions: async () => MOCK_INSTRUCTIONS,
    review: async (clipId) => {
      if (!views[clipId]) throw new Error("unknown clip");
      reviewing.add(clipId);
      jobs += 1;
      return `mock:${clipId}:${jobs}`;
    },
    subscribe: (jobId, handlers) => {
      const clipId = jobId.split(":")[1] ?? "";
      const timers: ReturnType<typeof setTimeout>[] = [];
      const total = STEP_WORDS.length;
      // a clip without a stored report stops where the AI would have started
      const stored = views[clipId]?.worker != null;
      const lastStep = stored ? total : 4;
      for (let i = 0; i < lastStep; i++) {
        timers.push(
          setTimeout(
            () => handlers.onProgress({ step: i + 1, total, message: STEP_MESSAGES[i], plain_message: STEP_WORDS[i] }),
            i * MOCK_STEP_MS,
          ),
        );
      }
      timers.push(
        setTimeout(() => {
          reviewing.delete(clipId);
          if (stored) handlers.onDone(clipId);
          else handlers.onFailed("This is demo data, so this clip can't be checked here.");
        }, lastStep * MOCK_STEP_MS),
      );
      return () => {
        for (const t of timers) clearTimeout(t);
        reviewing.delete(clipId);
      };
    },
  };
}
