/**
 * /hazards: single-camera safety hazard review. Types mirror the API's HazardView / ClipSummary
 * (contracts/hazard_view.schema.json); fetchers and the job-progress SSE go to the local FastAPI
 * only (API_BASE_URL). Nothing here reaches a non-local host.
 */
import { ApiError } from "./api";
import { apiUrl, LIVE } from "./config";

/* -------------------------------------------------------------------- types */

export type HazardClipStatus = "reviewed" | "not_reviewed" | "reviewing" | "failed";
export type HazardPriorityKey = "high" | "medium" | "low";
/** Worker-facing level words, as the API writes them. */
export type PlainLevel = "High" | "Medium" | "Low";
export type EvidenceKindLabel = "Whole view" | "Close-up" | "Section";

export interface ClipSummary {
  clip_id: string;
  title: string;
  duration_s: number;
  status: HazardClipStatus;
  hazard_count: number;
  top_priority: HazardPriorityKey | null;
  needs_check_count: number;
  reviewed_at: string | null;
}

export interface ClipList {
  clips: ClipSummary[];
}

/** One picture sent to the AI. */
export interface HazardImage {
  image_url: string;
  time_s: number;
  time_label: string;
  kind_label: EvidenceKindLabel;
}

export interface WorkerHazard {
  id: string;
  title: string;
  priority: PlainLevel;
  needs_check: boolean;
  what_we_saw: string;
  why_it_matters: string;
  what_to_do: string[];
  where: string;
  /** "0:00–0:12 of the clip" */
  when: string;
  start_s: number;
  end_s: number;
  how_sure: PlainLevel;
  /** "Aisles and material handling (OSHA 1910.176(a))" */
  safety_rule: string | null;
  not_sure_about: string[];
  evidence: HazardImage[];
}

export interface RuledOut {
  what: string;
  why: string;
}

export interface HazardWorker {
  /** "2 safety hazards found" | "No hazards seen in this clip" */
  headline: string;
  summary: string;
  hazards: WorkerHazard[];
  ruled_out: RuledOut[];
  cannot_tell: string[];
}

export interface PlainInstructions {
  checks: string[];
  rules: string[];
}

export interface HazardVision {
  processed_video_url: string | null;
  source_video_url: string | null;
  frames_scanned: number;
  duration_s: number;
  images_sent: number;
  areas_marked: number;
  /** Exactly the images sent to the AI, in order. */
  shown_images: HazardImage[];
  instructions: PlainInstructions;
}

/** zones.json entry from the CV stage (movement or possible_obstruction). */
export interface HazardZone {
  zone_id: string;
  kind: string;
  bbox_analysis?: number[];
  bbox_source?: number[];
  bbox_normalized?: number[];
  proposal_score?: number;
  peak_frame?: number;
  active_start_s?: number;
  active_end_s?: number;
  stability?: number;
  floor_contact?: number;
  paint_proximity?: number;
}

/** evidence_manifest.json entry. */
export interface HazardEvidenceRecord {
  evidence_id: string;
  frame_index: number;
  timestamp_s: number;
  kind: string;
  zone_id: string | null;
  bbox_source?: number[];
  path?: string;
  sha256?: string;
}

/** A finding exactly as the model returned it (after validation and audit). */
export interface HazardFindingRaw {
  finding_id: string;
  title: string;
  status: string;
  severity: string;
  confidence: string;
  zone_ids: string[];
  evidence_ids: string[];
  location: string;
  observation: string;
  risk_interpretation: string;
  standards: string[];
  applicability_reason: string;
  unknowns: string[];
  recommended_actions: string[];
  first_observed_s: number;
  last_observed_s: number;
  observed_times_s?: number[];
  evidence_paths?: string[];
  standard_links?: string[];
}

export interface HazardZoneReview {
  zone_id: string;
  interpretation: string;
  disposition: string;
  evidence_ids: string[];
}

export interface HazardDismissed {
  concern: string;
  reason: string;
  evidence_ids: string[];
}

export interface HazardStandard {
  title: string;
  summary: string;
  section?: string;
  url: string;
  checked_on?: string;
}

export interface HazardTechnical {
  zones: HazardZone[];
  evidence: HazardEvidenceRecord[];
  findings_raw: HazardFindingRaw[];
  zone_reviews: HazardZoneReview[];
  standards: Record<string, HazardStandard>;
  /** Model metadata as recorded (model id, base_url, inference_source, elapsed, tokens, audit...). */
  model: Record<string, unknown> | null;
  request_sha256: string | null;
  config: Record<string, unknown>;
  segmentation_method: string | null;
  quality_warnings: string[];
  system_prompt: string;
  audit_prompt: string;
  /** JUDGE-ONLY, from data/hazards/labels/; never sent to the AI. */
  dataset_label: string | null;
  /** Optional extras: rendered when the API sends them. */
  dismissed?: HazardDismissed[];
  limitations?: string[];
}

export interface HazardView {
  clip: { clip_id: string; title: string; duration_s: number };
  status: HazardClipStatus;
  reviewed_at: string | null;
  /** null until a report exists for the clip. */
  worker: HazardWorker | null;
  vision: HazardVision | null;
  technical: HazardTechnical | null;
}

export interface HazardInstructions extends PlainInstructions {
  system_prompt: string;
  audit_prompt: string;
}

export interface ReviewJob {
  job_id: string;
}

export interface HazardProgress {
  step: number;
  total: number;
  message: string;
  plain_message: string;
}

/* ------------------------------------------------------------------- fetch */

/** The review job POST answers at once (202); everything else is a small local JSON read. */
const TIMEOUT_MS = Math.max(LIVE.requestTimeoutMs, 10_000);

function detailOf(body: unknown, fallback: string): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d.length && typeof d[0]?.msg === "string") return d[0].msg;
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  const timeout = AbortSignal.timeout(TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(apiUrl(path), {
      ...init,
      cache: "no-store",
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    });
  } catch (err) {
    if (signal?.aborted) throw err;
    throw new ApiError(0, timeout.aborted ? "timeout" : "unreachable");
  }
  let body: unknown = null;
  try {
    body = await res.json();
  } catch (err) {
    if (signal?.aborted) throw err;
    if (res.ok) throw new ApiError(res.status, "invalid JSON");
  }
  if (!res.ok) throw new ApiError(res.status, detailOf(body, res.statusText || "error"));
  return body as T;
}

const enc = encodeURIComponent;

export const hazardsApi = {
  clips: (signal?: AbortSignal) => request<ClipList>("/api/hazards/clips", {}, signal),
  view: (clipId: string, signal?: AbortSignal) => request<HazardView>(`/api/hazards/clips/${enc(clipId)}`, {}, signal),
  review: (clipId: string, refresh = false) =>
    request<ReviewJob>(`/api/hazards/clips/${enc(clipId)}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh }),
    }),
  instructions: (signal?: AbortSignal) => request<HazardInstructions>("/api/hazards/instructions", {}, signal),
};

/** The clip's source video, served by the API even before a review exists. */
export function sourceVideoPath(clipId: string): string {
  return `/api/hazards/clips/${enc(clipId)}/media/source.mp4`;
}

/**
 * Media URLs from the API are API paths ("/api/hazards/..."); mock media are app-relative
 * ("/mock-hazards/..."), served by Next from public/. Anything else passes through.
 */
export function mediaUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  return path.startsWith("/api/") ? apiUrl(path) : path;
}

/* --------------------------------------------------------------------- SSE */

export interface JobHandlers {
  onProgress: (p: HazardProgress) => void;
  onDone: (clipId: string) => void;
  onFailed: (plainMessage: string) => void;
  /** The stream could not be (re)opened; the job's server state is unknown. */
  onLost: () => void;
}

function parse<T>(data: string): T | null {
  try {
    return JSON.parse(data) as T;
  } catch {
    return null;
  }
}

/**
 * GET /api/hazards/jobs/{id}/events: named SSE events "progress", "done" and "failed".
 * Handlers are idempotent (the server may replay progress on reconnect). Returns a closer.
 */
export function subscribeJob(jobId: string, handlers: JobHandlers): () => void {
  let source: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let retries = 0;
  let closed = false;

  const close = () => {
    closed = true;
    source?.close();
    source = null;
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };

  const connect = () => {
    if (closed) return;
    const es = new EventSource(apiUrl(`/api/hazards/jobs/${enc(jobId)}/events`));
    source = es;
    es.onopen = () => {
      if (source === es) retries = 0;
    };
    es.addEventListener("progress", (e) => {
      if (source !== es) return;
      const p = parse<HazardProgress>((e as MessageEvent<string>).data);
      if (p) handlers.onProgress(p);
    });
    es.addEventListener("done", (e) => {
      if (source !== es) return;
      const d = parse<{ clip_id?: string }>((e as MessageEvent<string>).data);
      close();
      handlers.onDone(d?.clip_id ?? "");
    });
    es.addEventListener("failed", (e) => {
      if (source !== es) return;
      // a named "failed" event carries data; a transport error arrives as a plain Event
      const data = (e as MessageEvent<string>).data;
      if (typeof data !== "string") return;
      const d = parse<{ plain_message?: string }>(data);
      close();
      handlers.onFailed(d?.plain_message || "The check stopped before it finished.");
    });
    es.onerror = () => {
      if (source !== es || closed) return;
      if (retries >= LIVE.streamMaxRetries) {
        close();
        handlers.onLost();
        return;
      }
      retries += 1;
      if (es.readyState === EventSource.CONNECTING) return;
      es.close();
      source = null;
      timer = setTimeout(connect, LIVE.streamRetryBaseMs * 2 ** (retries - 1));
    };
  };

  connect();
  return close;
}

/* ------------------------------------------------------------------ wording */

/** The six pipeline steps in plain words (the script's [n/6] messages, for a worker). */
export const STEP_WORDS: readonly string[] = [
  "Reading the video",
  "Looking for movement",
  "Marking areas to check",
  "Preparing pictures for the AI",
  "AI is reviewing the pictures",
  "Writing the report",
];

/** The original script's own step messages (technical view; the fixture replay uses them too). */
export const STEP_MESSAGES: readonly string[] = [
  "[1/6] Scanning video frames...",
  "[2/6] Measuring motion...",
  "[3/6] Finding movement and obstruction zones...",
  "[4/6] Exporting annotated video and evidence...",
  "[5/6] Running Qwen 3.6 hazard review...",
  "[6/6] Writing and validating reports...",
];

export const STATUS_WORD: Record<HazardClipStatus, string> = {
  reviewed: "Checked",
  not_reviewed: "Not checked",
  reviewing: "Checking…",
  failed: "Didn't finish",
};

export const PRIORITY_RANK: Record<PlainLevel, number> = { High: 0, Medium: 1, Low: 2 };

export function priorityKey(p: PlainLevel | HazardPriorityKey): HazardPriorityKey {
  return p.toLowerCase() as HazardPriorityKey;
}

/** Whole seconds as m:ss, the same clock as the "When" line. */
export function clock(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "–:––";
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** "2 hazards · 1 needs a check" for the clip list. */
export function countLine(c: Pick<ClipSummary, "status" | "hazard_count" | "needs_check_count">): string {
  if (c.status !== "reviewed") return "";
  if (c.hazard_count === 0) return "No hazards seen";
  const hz = `${c.hazard_count} hazard${c.hazard_count === 1 ? "" : "s"}`;
  return c.needs_check_count > 0 ? `${hz} · ${c.needs_check_count} need${c.needs_check_count === 1 ? "s" : ""} a check` : hz;
}

/** Hazards highest priority first; stable otherwise (the API's order). */
export function sortHazards(list: readonly WorkerHazard[]): WorkerHazard[] {
  return list
    .map((h, i) => ({ h, i }))
    .sort((a, b) => (PRIORITY_RANK[a.h.priority] ?? 3) - (PRIORITY_RANK[b.h.priority] ?? 3) || a.i - b.i)
    .map((x) => x.h);
}

/** A hazard's pictures in time order (ties keep the cited order). */
export function byTime(list: readonly HazardImage[]): HazardImage[] {
  return list
    .map((x, i) => ({ x, i }))
    .sort((a, b) => a.x.time_s - b.x.time_s || a.i - b.i)
    .map((v) => v.x);
}

/** Plain wording for a failed API call. */
export function plainError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return "Can't reach the camera system.";
    if (err.status === 404) return "This clip is no longer available.";
    if (err.status === 409) return "This clip is already being checked.";
  }
  return "Something went wrong. Please try again.";
}
