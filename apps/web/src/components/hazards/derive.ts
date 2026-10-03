/**
 * Plain, display-ready shapes for the /hazards screens, built only from what the API sent.
 *
 * The API composes the worker fields (zones, signs, zone names, cited pictures, gallery captions).
 * When an older API build leaves one out, the same thing is derived here from the run's own zone
 * and evidence manifests in `technical` (never invented): "Z03" is "Zone 3" everywhere.
 */
import {
  clock,
  type ClipKind,
  type HazardEvidenceRecord,
  type HazardFindingRaw,
  type HazardImage,
  type HazardView,
  type WorkerHazard,
} from "@/lib/hazards";

export interface ZoneBox {
  number: number;
  /** "Zone 3" */
  name: string;
  /** "Movement area" | "Fixed object" (API wording) */
  kind_word: string;
  movement: boolean;
  /** [x0, y0, x1, y1], 0-1 of the video frame */
  box: [number, number, number, number];
  has_hazard: boolean;
  has_pictures: boolean;
}

/** One picture as shown: a clean source (or the raw one plus a CSS crop), and plain captions. */
export interface Pic {
  key: string;
  /** What to show first (the clean copy when there is one). */
  src: string;
  /** The labelled original: shown cropped when the clean copy is missing. */
  raw: string | null;
  time_s: number;
  time_label: string;
  /** "Zone 3" | "Whole view" */
  zone_name: string;
  /** "Close-up" | "Whole view" | ... */
  kind_word: string;
  /** "Zone 3 · 0:04" */
  caption: string;
  cited: boolean;
}

const ZONE_ID = /^Z0*(\d+)$/;
const EVIDENCE_IN_URL = /\/(E\d{3})\.jpg(?:$|\?)/;
const WHOLE_VIEW = "Whole view";

export function zoneNumber(zoneId: string | null | undefined): number | null {
  const m = zoneId ? ZONE_ID.exec(zoneId) : null;
  return m ? Number(m[1]) : null;
}

export function zoneName(zoneId: string | null | undefined): string | null {
  const n = zoneNumber(zoneId);
  return n == null ? null : `Zone ${n}`;
}

export function isBlindspot(kind: ClipKind | null | undefined): boolean {
  return kind === "blindspot";
}

/** The evidence id a media URL points at (used only to join records, never shown). */
export function evidenceIdOf(url: string | null | undefined): string | null {
  const m = url ? EVIDENCE_IN_URL.exec(url) : null;
  return m ? m[1] : null;
}

function cleanToRaw(url: string): string | null {
  return url.includes("/evidence_clean/") ? url.replace("/evidence_clean/", "/evidence/") : null;
}

/** True when a URL is the labelled original (it needs the label strip cropped). */
export function isRawEvidence(url: string): boolean {
  return /\/evidence\/E\d{3}\.jpg/.test(url);
}

/** hazard-2 -> the model's H02 finding. */
export function findingFor(view: HazardView, hazard: WorkerHazard): HazardFindingRaw | undefined {
  const n = Number(/(\d+)$/.exec(hazard.id)?.[1] ?? NaN);
  const list = view.technical?.findings_raw ?? [];
  return list.find((f) => Number(/(\d+)$/.exec(f.finding_id)?.[1] ?? NaN) === n);
}

function evidenceById(view: HazardView): Map<string, HazardEvidenceRecord> {
  return new Map((view.technical?.evidence ?? []).map((e) => [e.evidence_id, e]));
}

function citedIds(view: HazardView): Set<string> {
  const ids = new Set<string>();
  for (const f of view.technical?.findings_raw ?? []) for (const e of f.evidence_ids ?? []) ids.add(e);
  return ids;
}

/** Every marked area with its plain name and box. */
export function viewZones(view: HazardView | null): ZoneBox[] {
  if (!view) return [];
  const given = view.worker?.zones;
  const techZones = view.technical?.zones ?? [];
  const movementByNumber = new Map(techZones.map((z) => [zoneNumber(z.zone_id), z.kind === "movement"]));
  if (given?.length) {
    return given
      .filter((z) => Array.isArray(z.box) && z.box.length === 4)
      .map((z) => ({
        number: z.number,
        name: z.name,
        kind_word: z.kind_word,
        movement: movementByNumber.get(z.number) ?? /movement/i.test(z.kind_word),
        box: z.box as [number, number, number, number],
        has_hazard: z.has_hazard,
        has_pictures: z.has_pictures,
      }));
  }
  const hazardZones = new Set((view.technical?.findings_raw ?? []).flatMap((f) => f.zone_ids ?? []));
  const pictureZones = new Set((view.technical?.evidence ?? []).map((e) => e.zone_id).filter(Boolean));
  const out: ZoneBox[] = [];
  for (const z of techZones) {
    const n = zoneNumber(z.zone_id);
    const b = z.bbox_normalized;
    if (n == null || !b || b.length !== 4) continue;
    const movement = z.kind === "movement";
    out.push({
      number: n,
      name: `Zone ${n}`,
      kind_word: movement ? "Movement area" : "Fixed object",
      movement,
      box: [b[0], b[1], b[2], b[3]],
      has_hazard: hazardZones.has(z.zone_id),
      has_pictures: pictureZones.has(z.zone_id),
    });
  }
  return out;
}

/** ["Zone 3"] for a hazard. */
export function hazardZoneNames(view: HazardView, hazard: WorkerHazard): string[] {
  if (hazard.zone_names?.length) return hazard.zone_names;
  const f = findingFor(view, hazard);
  return (f?.zone_ids ?? []).map(zoneName).filter((x): x is string => !!x);
}

/** "Where" starting with the zone name (the API does this; older builds did not). */
export function whereLine(hazard: WorkerHazard, zones: string[]): string {
  if (!zones.length || hazard.where.startsWith(zones[0])) return hazard.where;
  return `${zones.join(", ")} · ${hazard.where}`;
}

function picFromImage(view: HazardView, im: HazardImage, i: number, rec: HazardEvidenceRecord | undefined, cited: Set<string>): Pic {
  const src = im.clean_url || im.image_url;
  const id = evidenceIdOf(src) ?? evidenceIdOf(im.image_url);
  const record = rec ?? (id ? evidenceById(view).get(id) : undefined);
  const zone = im.zone_name ?? (record ? zoneName(record.zone_id) : null) ?? WHOLE_VIEW;
  const kind = im.kind_word ?? im.kind_label ?? "Picture";
  return {
    key: `${src}#${i}`,
    src,
    raw: im.raw_url ?? (isRawEvidence(src) ? null : cleanToRaw(src)) ?? record?.image_url ?? null,
    time_s: im.time_s,
    time_label: im.time_label || clock(im.time_s),
    zone_name: zone,
    kind_word: kind,
    caption: `${zone} · ${im.time_label || clock(im.time_s)}`,
    cited: im.cited ?? (id ? cited.has(id) : false),
  };
}

/** The full set of pictures sent to the model, in the order sent. */
export function galleryPictures(view: HazardView | null): Pic[] {
  if (!view?.vision) return [];
  const images = view.vision.shown_images ?? [];
  const tech = view.technical?.evidence ?? [];
  const sameOrder = tech.length === images.length;
  const cited = citedIds(view);
  return images.map((im, i) => picFromImage(view, im, i, sameOrder ? tech[i] : undefined, cited));
}

/** Gallery groups: "Whole view" first, then Zone 1, Zone 2, ... */
export function groupByZone(pics: readonly Pic[]): { name: string; pics: Pic[] }[] {
  const groups = new Map<string, Pic[]>();
  for (const p of pics) {
    const list = groups.get(p.zone_name);
    if (list) list.push(p);
    else groups.set(p.zone_name, [p]);
  }
  const rank = (name: string) => (name === WHOLE_VIEW ? -1 : Number(/(\d+)$/.exec(name)?.[1] ?? 9999));
  return [...groups.entries()].sort((a, b) => rank(a[0]) - rank(b[0])).map(([name, list]) => ({ name, pics: list }));
}

/** The exact pictures a hazard cites, in clip order. */
export function hazardPictures(view: HazardView, hazard: WorkerHazard): Pic[] {
  if (hazard.pictures?.length) {
    return hazard.pictures
      .map((p, i) => {
        const src = p.clean_url || p.url;
        const zone = p.zone_name ?? (p.caption.split(" · ")[0] || WHOLE_VIEW);
        const t = p.time_label ?? clock(p.time_s);
        return {
          key: `${src}#${i}`,
          src,
          raw: p.clean_url ? p.url : cleanToRaw(src),
          time_s: p.time_s,
          time_label: t,
          zone_name: zone,
          kind_word: p.kind_word ?? "",
          caption: p.caption || `${zone} · ${t}`,
          cited: true,
        } satisfies Pic;
      })
      .sort((a, b) => a.time_s - b.time_s);
  }
  const byId = evidenceById(view);
  const cited = citedIds(view);
  return [...hazard.evidence]
    .map((im, i) => picFromImage(view, im, i, byId.get(evidenceIdOf(im.image_url) ?? ""), cited))
    .map((p) => ({ ...p, cited: true }))
    .sort((a, b) => a.time_s - b.time_s);
}

/** The video frame's source size (for the zone overlay maths). */
export function sourceSize(view: HazardView | null): { w: number; h: number } | null {
  const v = view?.technical?.video as { source_width?: unknown; source_height?: unknown } | null | undefined;
  const w = Number(v?.source_width);
  const h = Number(v?.source_height);
  return w > 0 && h > 0 ? { w, h } : null;
}
