/**
 * /hazards?mock=1 data. hz_00.json is the real original run (Ollama qwen3.6:35b-a3b on macOS,
 * FastSAM-s, 35 evidence images) rewritten into the HazardView shape: the worker text is plain
 * (ids, model names and schema words stripped), the technical block keeps the report verbatim
 * and the prompts are the original script's own. Media live in public/mock-hazards/ (browser
 * H.264 copies of the processed and source video, and display-size copies of the 35 pictures).
 * hz_01 / hz_02 are listed un-reviewed, so the "not checked" state is honest: no results exist.
 */
import type { ClipSummary, HazardInstructions, HazardView } from "@/lib/hazards";

import hz00 from "./hz_00.json";
import instructions from "./instructions.json";

export const MOCK_VIEW_HZ00 = hz00 as HazardView;

export const MOCK_INSTRUCTIONS = instructions as HazardInstructions;

const notReviewed = (clip_id: string, title: string, duration_s: number): HazardView => ({
  clip: { clip_id, title, duration_s },
  status: "not_reviewed",
  reviewed_at: null,
  worker: null,
  vision: null,
  technical: null,
});

/** Reviewed views by clip id; the clip list is derived from them. */
export const MOCK_VIEWS: Record<string, HazardView> = {
  hz_00: MOCK_VIEW_HZ00,
  // durations of the first test clip of the first two dataset folders (ffprobe); not reviewed
  hz_01: notReviewed("hz_01", "Floor camera 01", 14.98),
  hz_02: notReviewed("hz_02", "Floor camera 02", 16.98),
};

export function summarize(view: HazardView): ClipSummary {
  const hazards = view.worker?.hazards ?? [];
  const order = ["High", "Medium", "Low"] as const;
  const top = order.find((p) => hazards.some((h) => h.priority === p)) ?? null;
  return {
    clip_id: view.clip.clip_id,
    title: view.clip.title,
    duration_s: view.clip.duration_s,
    status: view.status,
    hazard_count: hazards.length,
    top_priority: top ? (top.toLowerCase() as ClipSummary["top_priority"]) : null,
    needs_check_count: hazards.filter((h) => h.needs_check).length,
    reviewed_at: view.reviewed_at,
  };
}

export const MOCK_CLIPS: ClipSummary[] = Object.values(MOCK_VIEWS).map(summarize);

/** Plain progress replay for a mock "Check this clip": the six step messages, no model calls. */
export const MOCK_STEP_MS = 650;
