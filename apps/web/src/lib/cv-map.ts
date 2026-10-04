/**
 * The wall's technical layer: what the computer-vision pass of one stored run actually marked,
 * read from the same HazardView the tile already fetches (technical.zones, zone_reviews,
 * evidence, video, pipeline) plus the run's motion_timeline.csv. Everything is in image space:
 * the clips carry no camera calibration, so nothing here is placed on a floor plan.
 *
 * Unlike the worker text in wall.ts this layer shows ids, model names and scores on purpose.
 * It never reads dataset_label (judge-only).
 */

export type Box01 = [number, number, number, number];

/** How far a marked area got: CV marked it, Qwen flagged it, the audited answer kept it. */
export type ZoneStage = "marked" | "flagged" | "confirmed";

export interface CvZone {
  number: number;
  /** "Z03" as the pipeline names it. */
  id: string;
  box: Box01;
  /** "yolo" when a YOLO box seeded the area, "edge" for an edge contour. */
  sourceKind: "yolo" | "edge" | "other";
  /** "YOLO11S · PERSON 0.80" / "EDGE CONTOUR". */
  source: string;
  stage: ZoneStage;
  activeStart: number | null;
  activeEnd: number | null;
}

export interface CvEvidence {
  id: string;
  t: number;
  kind: string;
  /** Crop footprint for zone crops; null for whole-scene and tile images. */
  box: Box01 | null;
}

export interface CvMapping {
  zones: CvZone[];
  evidence: CvEvidence[];
  funnel: { proposals: number | null; areas: number; flagged: number; confirmed: number };
  detector: { model: string; device: string; ms: number | null } | null;
  frames: number | null;
  fps: number | null;
  durationS: number | null;
  source: [number, number] | null;
  analysis: [number, number] | null;
  imagesSent: number | null;
}

/** The HazardView fields this layer reads (structural; the wall's own view type is a subset). */
export interface CvViewInput {
  clip?: { duration_s?: number | null } | null;
  vision?: { images_sent?: number | null } | null;
  technical?: {
    zones?: { zone_id?: string; bbox_normalized?: number[]; active_start_s?: number; active_end_s?: number }[];
    zone_reviews?: { zone_id?: string; disposition?: string }[];
    evidence?: { evidence_id?: string; timestamp_s?: number; kind?: string; bbox_source?: number[] }[];
    video?: {
      decoded_frames?: number;
      fps?: number;
      duration_s?: number;
      source_width?: number;
      source_height?: number;
      analysis_width?: number;
      analysis_height?: number;
    } | null;
    pipeline?: {
      detector?: { used_models?: string[]; device?: string; elapsed_ms?: number } | null;
      zone_sources?: Record<string, string> | null;
      candidate_counts?: { movement?: number; static?: number } | null;
      images_sent?: number;
    } | null;
  } | null;
}

const num = (x: unknown): number | null => (typeof x === "number" && Number.isFinite(x) ? x : null);

const ZONE_ID_RE = /^Z0*(\d+)$/i;

function box01(b: unknown, w = 1, h = 1): Box01 | null {
  if (!Array.isArray(b) || b.length < 4 || !(w > 0) || !(h > 0)) return null;
  const v = b.slice(0, 4).map(Number);
  if (v.some((x) => !Number.isFinite(x))) return null;
  const c = [v[0] / w, v[1] / h, v[2] / w, v[3] / h].map((x) => Math.min(1, Math.max(0, x))) as Box01;
  return c[2] > c[0] && c[3] > c[1] ? c : null;
}

/** "yolo11s: person (0.80)" -> YOLO11S · PERSON 0.80; "edge contour" -> EDGE CONTOUR. */
function zoneSource(raw: string | undefined): { sourceKind: CvZone["sourceKind"]; source: string } {
  const text = (raw ?? "").trim();
  const yolo = /^(yolo[\w.-]*)\s*:\s*(.+?)\s*\(([\d.]+)\)$/i.exec(text);
  if (yolo) return { sourceKind: "yolo", source: `${yolo[1]} · ${yolo[2]} ${yolo[3]}`.toUpperCase() };
  if (/edge/i.test(text)) return { sourceKind: "edge", source: text.toUpperCase() };
  return { sourceKind: "other", source: text ? text.toUpperCase() : "—" };
}

/** "cuda:0 (NVIDIA GB10)" -> "CUDA:0 · NVIDIA GB10". */
function deviceLabel(raw: string | undefined): string {
  return (raw ?? "").replace(/\s*\((.+)\)\s*$/, " · $1").trim().toUpperCase();
}

/**
 * The CV mapping of one finished check. `confirmed` is the zone numbers the wall already draws
 * as findings (worker.zones has_hazard, or a hazard's cited zone), so the plan and the tile agree.
 */
export function cvMapping(view: CvViewInput, confirmed: ReadonlySet<number>): CvMapping | null {
  const t = view.technical;
  if (!t || !Array.isArray(t.zones)) return null;
  const sources = t.pipeline?.zone_sources ?? {};
  const flaggedIds = new Set(
    (t.zone_reviews ?? []).filter((r) => r.disposition === "hazard_candidate").map((r) => String(r.zone_id ?? "")),
  );

  const zones: CvZone[] = [];
  for (const z of t.zones) {
    const id = String(z.zone_id ?? "");
    const m = ZONE_ID_RE.exec(id);
    const box = box01(z.bbox_normalized);
    if (!m || !box) continue;
    const n = Number(m[1]);
    zones.push({
      number: n,
      id: `Z${String(n).padStart(2, "0")}`,
      box,
      ...zoneSource(sources[id]),
      stage: confirmed.has(n) ? "confirmed" : flaggedIds.has(id) ? "flagged" : "marked",
      activeStart: num(z.active_start_s),
      activeEnd: num(z.active_end_s),
    });
  }
  zones.sort((a, b) => a.number - b.number);

  const v = t.video ?? {};
  const sw = num(v.source_width);
  const sh = num(v.source_height);
  const evidence: CvEvidence[] = (t.evidence ?? [])
    .map((e) => {
      const time = num(e.timestamp_s);
      if (time === null || !e.evidence_id) return null;
      const kind = String(e.kind ?? "");
      const box = kind === "zone crop" && sw && sh ? box01(e.bbox_source, sw, sh) : null;
      return { id: e.evidence_id, t: time, kind, box };
    })
    .filter((e): e is CvEvidence => e !== null)
    .sort((a, b) => a.t - b.t);

  const counts = t.pipeline?.candidate_counts;
  const movement = num(counts?.movement);
  const stat = num(counts?.static);
  const det = t.pipeline?.detector;
  const models = (det?.used_models ?? []).filter((s) => typeof s === "string" && s);

  return {
    zones,
    evidence,
    funnel: {
      proposals: movement === null && stat === null ? null : (movement ?? 0) + (stat ?? 0),
      areas: zones.length,
      flagged: zones.filter((z) => z.stage !== "marked").length,
      confirmed: zones.filter((z) => z.stage === "confirmed").length,
    },
    detector: models.length
      ? { model: models.join(" + ").toUpperCase(), device: deviceLabel(det?.device), ms: num(det?.elapsed_ms) }
      : null,
    frames: num(v.decoded_frames),
    fps: num(v.fps),
    durationS: num(v.duration_s) ?? num(view.clip?.duration_s),
    source: sw && sh ? [sw, sh] : null,
    analysis: num(v.analysis_width) && num(v.analysis_height) ? [v.analysis_width!, v.analysis_height!] : null,
    imagesSent: num(view.vision?.images_sent) ?? num(t.pipeline?.images_sent),
  };
}

export interface MotionSeries {
  t: number[];
  m: number[];
  peak: number;
}

/** motion_timeline.csv -> per-frame motion_fraction; rows that do not parse are skipped. */
export function parseMotionCsv(text: string): MotionSeries | null {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (lines.length < 2) return null;
  const head = lines[0].split(",").map((h) => h.trim());
  const ti = head.indexOf("time_s");
  const mi = head.indexOf("motion_fraction");
  if (ti < 0 || mi < 0) return null;
  const t: number[] = [];
  const m: number[] = [];
  for (const line of lines.slice(1)) {
    const cells = line.split(",");
    const a = Number(cells[ti]);
    const b = Number(cells[mi]);
    if (!Number.isFinite(a) || !Number.isFinite(b)) continue;
    t.push(a);
    m.push(Math.max(0, b));
  }
  if (!t.length) return null;
  return { t, m, peak: Math.max(...m) };
}

/** SVG path of the series in a w x h box over [0, span] seconds, scaled to its own peak. */
export function motionPath(s: MotionSeries, span: number, w: number, h: number): string {
  if (!s.t.length || !(span > 0)) return "";
  const peak = s.peak > 0 ? s.peak : 1;
  return s.t
    .map((t, i) => {
      const x = (Math.min(span, Math.max(0, t)) / span) * w;
      const y = h - (s.m[i] / peak) * h;
      return `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join("");
}
