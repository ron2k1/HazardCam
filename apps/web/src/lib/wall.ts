/**
 * "/" — the site camera wall. Which clips sit on the wall is configuration (config/wall.yaml,
 * served by GET /api/wall); every check result comes from the stored runs through the hazards
 * API after that check completes in this browser. Nothing here holds a finding, a sentence about
 * a scene, a time or a picture of its own, and nothing reaches a non-local host.
 *
 * The wall reads only the few HazardView fields it draws, typed here on purpose so the wall
 * keeps working while the /hazards types evolve.
 */
import { ApiError } from "./api";
import { apiUrl, LIVE } from "./config";

/* -------------------------------------------------------------- wall config */

export type WatchKind = "hazard" | "blindspot";

/** One camera on the wall: a stored clip whose raw source plays as a CCTV feed. */
export interface WallTile {
  cam: number;
  clip_id: string;
  title: string;
  /** API path of the raw source video (no AI markings). */
  source_url: string;
  /** The clip's frame rate (clip.json), for frame numbers on the tile; null when unknown. */
  fps?: number | null;
  /** Optional, from config/wall.yaml: the overlay watch label and when this tile's check starts. */
  watch?: string | null;
  check_after_s?: number | null;
}

/** GET /api/wall */
export interface WallConfig {
  hazard_tiles: WallTile[];
  blindspot_tiles?: WallTile[];
  /** Optional titles from configuration (config/wall.yaml). */
  title?: string | null;
  hazard_title?: string | null;
  blindspot_title?: string | null;
}

export interface WallCamera extends WallTile {
  kind: WatchKind;
}

/** Orchestrator timing (seconds after the wall loads). Timing only: no content lives here. */
export const WALL = {
  /** The header switches from "starting" to "watching N cameras" at this point. */
  watchingAfterS: 3,
  /** Checks start 1.5 s apart (CAM 1, 4, 2, 5, 3, 6) so all six land within about 25 s. */
  hazardStartS: [2, 5, 8],
  blindspotStartS: [3.5, 6.5, 9.5],
  /** A camera that joins the wall late starts this long after it appears, then every gapS. */
  lateStartS: 2,
  lateGapS: 5,
  tilesPerRow: 4,
  /** Re-read the wall config this often while a row is still empty. */
  configRetryMs: 8_000,
  runtimePollMs: 15_000,
  toastMs: 5_000,
} as const;

/* ------------------------------------------------------- HazardView subset */

export interface SignData {
  label: string;
  glyph: string;
}

/** The worker-facing fields of one hazard card that the wall draws. */
export interface ViewHazard {
  id: string;
  title: string;
  short_title?: string | null;
  priority: string;
  sign?: SignData | null;
  zone_names?: string[] | null;
  what_we_saw?: string | null;
  why_it_matters?: string | null;
  short_action?: string | null;
  explain?: string | null;
}

/** worker.zones[] (box normalised 0-1 in video coordinates). */
export interface ViewZone {
  number: number;
  name: string;
  kind_word?: string;
  box: number[];
  has_hazard: boolean;
  has_pictures?: boolean;
}

interface RawZone {
  zone_id?: string;
  bbox_normalized?: number[];
}

interface RawFinding {
  finding_id?: string;
  zone_ids?: string[];
}

export interface WallHazardView {
  clip: { clip_id: string; title: string; duration_s: number };
  status: string;
  reviewed_at: string | null;
  worker: {
    headline: string;
    hazards: ViewHazard[];
    zones?: ViewZone[] | null;
  } | null;
  technical?: {
    zones?: RawZone[];
    findings_raw?: RawFinding[];
  } | null;
}

interface ClipRow {
  clip_id: string;
  title: string;
  kind?: string | null;
}

/* ------------------------------------------------------------------ fetch */

function detailOf(body: unknown, fallback: string): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  return typeof d === "string" ? d : fallback;
}

async function call(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<{ status: number; body: unknown }> {
  const timeout = AbortSignal.timeout(Math.max(LIVE.requestTimeoutMs, 10_000));
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
  } catch {
    body = null;
  }
  return { status: res.status, body };
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const { status, body } = await call(path, {}, signal);
  if (status < 200 || status >= 300 || body === null) throw new ApiError(status, detailOf(body, "error"));
  return body as T;
}

const enc = encodeURIComponent;

/** The raw source feed of a stored clip. */
export function sourcePath(clipId: string): string {
  return `/api/hazards/clips/${enc(clipId)}/media/source.mp4`;
}

function isBlindspotClip(c: ClipRow): boolean {
  if (c.kind) return c.kind === "blindspot";
  return /^bs_/i.test(c.clip_id);
}

const byId = (a: ClipRow, b: ClipRow) => a.clip_id.localeCompare(b.clip_id, undefined, { numeric: true });

/**
 * Until GET /api/wall exists (404), the wall follows the same defaults config/wall.yaml documents:
 * the first three hazard clips by id, then every blind-spot clip in id order.
 */
function wallFromClips(clips: ClipRow[]): WallConfig {
  const hazard = clips.filter((c) => !isBlindspotClip(c)).sort(byId).slice(0, WALL.tilesPerRow);
  const blind = clips.filter(isBlindspotClip).sort(byId).slice(0, WALL.tilesPerRow);
  return {
    hazard_tiles: hazard.map((c, i) => ({ cam: i + 1, clip_id: c.clip_id, title: c.title, source_url: sourcePath(c.clip_id) })),
    blindspot_tiles: blind.map((c, i) => ({
      cam: WALL.tilesPerRow + i + 1,
      clip_id: c.clip_id,
      title: c.title,
      source_url: sourcePath(c.clip_id),
    })),
  };
}

export async function fetchWall(signal?: AbortSignal): Promise<{ config: WallConfig; from: "wall" | "clips" }> {
  const { status, body } = await call("/api/wall", {}, signal);
  if (status === 200 && body && Array.isArray((body as WallConfig).hazard_tiles)) {
    return { config: body as WallConfig, from: "wall" };
  }
  if (status !== 404) throw new ApiError(status, detailOf(body, "error"));
  const list = await getJson<{ clips: ClipRow[] }>("/api/hazards/clips", signal);
  return { config: wallFromClips(list.clips ?? []), from: "clips" };
}

/** The wall's cameras in CAM order, each with its watch kind. */
export function wallCameras(config: WallConfig): WallCamera[] {
  const pick = (tiles: WallTile[] | undefined, kind: WatchKind): WallCamera[] =>
    (tiles ?? []).slice(0, WALL.tilesPerRow).map((t) => ({ ...t, kind }));
  return [...pick(config.hazard_tiles, "hazard"), ...pick(config.blindspot_tiles, "blindspot")];
}

/** A configured label, if it is plain text; otherwise the wall's own default. */
export function configured(value: unknown, fallback: string): string {
  return isPlainText(value) ? value.trim() : fallback;
}

export function fetchView(clipId: string, signal?: AbortSignal): Promise<WallHazardView> {
  return getJson<WallHazardView>(`/api/hazards/clips/${enc(clipId)}`, signal);
}

/**
 * POST a check of one clip. In demo replay the API replays that clip's stored real run; otherwise
 * it runs live. 409 means the clip is already being checked: attach to that job.
 */
export async function startCheck(clipId: string, signal?: AbortSignal): Promise<string> {
  const { status, body } = await call(
    `/api/hazards/clips/${enc(clipId)}/review`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
    signal,
  );
  const jobId = (body as { job_id?: unknown } | null)?.job_id;
  if ((status === 202 || status === 200 || status === 409) && typeof jobId === "string" && jobId) return jobId;
  throw new ApiError(status, detailOf(body, "error"));
}

/**
 * Start a camera's check, or follow the one already running for that clip (another tab or the
 * /hazards screen may have started it). Looking first avoids a needless 409.
 */
export async function beginCheck(clipId: string, signal?: AbortSignal): Promise<string> {
  try {
    const list = await getJson<{ clips: (ClipRow & { status?: string })[] }>("/api/hazards/clips", signal);
    if (list.clips?.find((c) => c.clip_id === clipId)?.status === "reviewing") {
      const job = await getJson<{ job_id?: unknown; state?: unknown }>(`/api/hazards/clips/${enc(clipId)}/jobs/latest`, signal);
      if (typeof job.job_id === "string" && job.job_id && job.state !== "done" && job.state !== "failed") return job.job_id;
    }
  } catch (err) {
    if (signal?.aborted) throw err;
    // fall through: the POST below answers 409 with the running job when there is one
  }
  return startCheck(clipId, signal);
}

/* -------------------------------------------------------------- job events */

export interface JobProgress {
  step: number;
  total: number;
  plain_message: string;
}

export interface JobHandlers {
  onProgress: (p: JobProgress) => void;
  onAgent: (text: string) => void;
  onDone: () => void;
  onFailed: (plainMessage: string | null) => void;
  onLost: () => void;
}

function parse(data: unknown): Record<string, unknown> | null {
  if (typeof data !== "string") return null;
  try {
    const v = JSON.parse(data);
    return v && typeof v === "object" ? (v as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/** GET /api/hazards/jobs/{id}/events (late subscribers get the whole job). Returns a closer. */
export function followJob(jobId: string, h: JobHandlers): () => void {
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
      const d = parse((e as MessageEvent).data);
      if (!d) return;
      const step = Number(d.step);
      const total = Number(d.total) || 6;
      const plain = typeof d.plain_message === "string" ? d.plain_message : "";
      // step 0 is a waiting / narration line, not a pipeline step
      if (step >= 1) h.onProgress({ step, total, plain_message: plain });
      else if (plain) h.onAgent(plain);
    });
    es.addEventListener("agent", (e) => {
      if (source !== es) return;
      const d = parse((e as MessageEvent).data);
      const text = d ? [d.text, d.plain_message, d.message].find((v) => typeof v === "string" && v.trim()) : null;
      if (typeof text === "string") h.onAgent(text.trim());
    });
    es.addEventListener("done", () => {
      if (source !== es) return;
      close();
      h.onDone();
    });
    es.addEventListener("failed", (e) => {
      if (source !== es) return;
      const data = (e as MessageEvent).data;
      if (typeof data !== "string") return; // a transport error, handled by onerror
      const d = parse(data);
      close();
      h.onFailed(typeof d?.plain_message === "string" ? d.plain_message : null);
    });
    es.onerror = () => {
      if (source !== es || closed) return;
      if (retries >= LIVE.streamMaxRetries) {
        close();
        h.onLost();
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

/* ------------------------------------------------------------ runtime line */

interface RuntimeRow {
  key: string;
  status: string;
}

export interface RuntimeStatus {
  local_only?: boolean;
  rows: RuntimeRow[];
}

export function fetchRuntime(signal?: AbortSignal): Promise<RuntimeStatus> {
  return getJson<RuntimeStatus>("/api/runtime/status", signal);
}

export interface StackLine {
  tone: "ok" | "warn" | "unknown";
  parts: string[];
}

/** One plain line about the local stack, from GET /api/runtime/status (null while unknown). */
export function stackLine(rt: RuntimeStatus | null): StackLine | null {
  if (!rt || !Array.isArray(rt.rows)) return null;
  const row = (k: string) => rt.rows.find((r) => r.key === k || r.key.startsWith(k));
  const agent = row("openclaw")?.status;
  const sandbox = row("nemoclaw")?.status;
  const local = rt.local_only === true || row("network")?.status === "ok";
  const parts = [
    agent === "ok" ? "Safety agent on this computer" : agent === "down" ? "Safety agent not running" : "Safety agent starting",
    sandbox === "ok" ? "secure sandbox on" : sandbox === "down" ? "secure sandbox off" : "secure sandbox not confirmed",
    local ? "no internet needed" : "network not confirmed local",
  ];
  const tone = agent === "ok" && sandbox === "ok" && local ? "ok" : agent === "down" || sandbox === "down" ? "warn" : "unknown";
  return { tone, parts };
}

/* ------------------------------------------------------------ check result */

/** One detection as the wall shows it: sign, short label, the zones it is in. */
export interface Detection {
  key: string;
  sign: SignData | null;
  shortTitle: string;
  priority: string;
  zoneNames: string[];
  /** One short paragraph for the pop-out: what was seen, why it matters, what to do. */
  explain: string;
}

export interface ZoneMark {
  number: number;
  name: string;
  box: [number, number, number, number];
  sign: SignData | null;
}

export interface CheckResult {
  reviewedAt: string | null;
  detections: Detection[];
  /** Only the zones a detection is in (the wall never draws the others). */
  zones: ZoneMark[];
}

/**
 * Worker text guard for anything the wall prints from the API: no zone/evidence/hazard ids, box
 * numbers, hashes, URLs, internal ids, model names or decimal scores. The API already composes
 * plain text; this is a second, local net.
 */
const LEAK_RE = /\b[EZH]\d{2,3}\b|bbox|sha256|https?:|cam_|\bz_|hypothesis|qwen|\b\d+\.\d+\b/i;

export function isPlainText(text: unknown): text is string {
  return typeof text === "string" && text.trim() !== "" && !LEAK_RE.test(text);
}

const ZONE_ID_RE = /^Z0*(\d+)$/i;

function zoneNumber(id: unknown): number | null {
  const m = typeof id === "string" ? ZONE_ID_RE.exec(id.trim()) : null;
  return m ? Number(m[1]) : null;
}

/** "Zone 3" from a "Zone 3" name or a Z03 id; the same name every view uses. */
function zoneName(n: number): string {
  return `Zone ${n}`;
}

function zoneNameNumber(name: string): number | null {
  const m = /^zone\s+(\d+)$/i.exec(name.trim());
  return m ? Number(m[1]) : null;
}

function clampBox(b: unknown): [number, number, number, number] | null {
  if (!Array.isArray(b) || b.length < 4) return null;
  const v = b.slice(0, 4).map(Number);
  if (v.some((x) => !Number.isFinite(x))) return null;
  const c = v.map((x) => Math.min(1, Math.max(0, x))) as [number, number, number, number];
  return c[2] > c[0] && c[3] > c[1] ? c : null;
}

/**
 * The wall's view of a finished check. Prefers the worker block's zones and zone names; when the
 * API predates them, derives the same "Zone n" names and normalised boxes from the run's zone and
 * finding records (ids are only read, never shown).
 */
export function checkResult(view: WallHazardView): CheckResult {
  const hazards = view.worker?.hazards ?? [];
  const raw = view.technical ?? null;
  const findingZones = new Map<string, number[]>();
  for (const f of raw?.findings_raw ?? []) {
    const m = /^H0*(\d+)$/i.exec(String(f.finding_id ?? ""));
    if (!m) continue;
    findingZones.set(`hazard-${Number(m[1])}`, (f.zone_ids ?? []).map(zoneNumber).filter((n): n is number => n !== null));
  }

  const detections: Detection[] = hazards.map((h, i) => {
    let nums = (h.zone_names ?? []).map(zoneNameNumber).filter((n): n is number => n !== null);
    if (!nums.length) nums = findingZones.get(h.id) ?? [];
    const short = [h.short_title, h.title].find(isPlainText) ?? "";
    const why = (h.why_it_matters ?? "").split(/(?<=[.!?])\s+/)[0] ?? "";
    const act = h.short_action ?? "";
    const explain = h.explain && isPlainText(h.explain) ? h.explain : [h.what_we_saw, why, act].filter((t) => t && isPlainText(t)).join(" ");
    return {
      key: h.id || `hazard-${i + 1}`,
      sign: h.sign && h.sign.label ? h.sign : null,
      shortTitle: short,
      priority: h.priority,
      zoneNames: [...new Set(nums)].map(zoneName),
      explain,
    };
  });

  const signFor = (n: number) => detections.find((d) => d.zoneNames.includes(zoneName(n)))?.sign ?? null;
  const cited = new Set(detections.flatMap((d) => d.zoneNames.map(zoneNameNumber)).filter((n): n is number => n !== null));

  let zones: ZoneMark[] = [];
  const workerZones = view.worker?.zones;
  if (Array.isArray(workerZones) && workerZones.length) {
    zones = workerZones
      .filter((z) => z.has_hazard || cited.has(z.number))
      .map((z) => ({ number: z.number, name: zoneName(z.number), box: clampBox(z.box), sign: signFor(z.number) }))
      .filter((z): z is ZoneMark => z.box !== null);
  } else {
    zones = (raw?.zones ?? [])
      .map((z) => ({ n: zoneNumber(z.zone_id), box: clampBox(z.bbox_normalized) }))
      .filter((z): z is { n: number; box: [number, number, number, number] } => z.n !== null && z.box !== null && cited.has(z.n))
      .map((z) => ({ number: z.n, name: zoneName(z.n), box: z.box, sign: signFor(z.n) }));
  }
  zones.sort((a, b) => a.number - b.number);
  return { reviewedAt: view.reviewed_at, detections, zones };
}

/* ----------------------------------------------------------------- wording */

export function kindWord(kind: WatchKind): { watch: string; one: string; many: string; none: string } {
  return kind === "blindspot"
    ? { watch: "BLIND SPOT", one: "blind spot", many: "blind spots", none: "No blind spots seen" }
    : { watch: "HAZARD WATCH", one: "hazard", many: "hazards", none: "No hazards seen" };
}

/** m:ss for an elapsed check. */
export function elapsedClock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** 24 h wall-clock time, "14:32:05". */
export function timeOfDay(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** CCTV date stamp, "2026-10-03". */
export function dateStamp(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Links out of a notification: the structured result here, the reasoning in a second tab. */
export function viewHref(clipId: string, jobId: string): string {
  return `/hazards?clip=${enc(clipId)}&job=${enc(jobId)}`;
}

export function reasoningHref(clipId: string, jobId: string): string {
  return `/hazards/process?clip=${enc(clipId)}&job=${enc(jobId)}`;
}
