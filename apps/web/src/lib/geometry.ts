/**
 * Plan-view geometry for the blind-zone visualization. World frame: x east, y north (metres);
 * bearings are compass degrees (0 = +y, 90 = +x, clockwise). SVG y grows downward, so
 * world y is flipped when projecting.
 */

export type Pt = readonly [number, number];

export interface Bounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

export function boundsOf(points: readonly Pt[], circles: readonly { c: Pt; r: number }[], pad: number): Bounds {
  const xs: number[] = [];
  const ys: number[] = [];
  for (const [x, y] of points) {
    xs.push(x);
    ys.push(y);
  }
  for (const { c, r } of circles) {
    xs.push(c[0] - r, c[0] + r);
    ys.push(c[1] - r, c[1] + r);
  }
  if (xs.length === 0) return { minX: -10, maxX: 10, minY: -10, maxY: 10 };
  const b = {
    minX: Math.min(...xs) - pad,
    maxX: Math.max(...xs) + pad,
    minY: Math.min(...ys) - pad,
    maxY: Math.max(...ys) + pad,
  };
  // square it so metres are isotropic in a square viewBox
  const w = b.maxX - b.minX;
  const h = b.maxY - b.minY;
  if (w > h) {
    const d = (w - h) / 2;
    b.minY -= d;
    b.maxY += d;
  } else {
    const d = (h - w) / 2;
    b.minX -= d;
    b.maxX += d;
  }
  return b;
}

/** Unit direction for a compass bearing, in world coordinates. */
export function dir(bearingDeg: number): Pt {
  const r = (bearingDeg * Math.PI) / 180;
  return [Math.sin(r), Math.cos(r)];
}

export interface Projector {
  size: number;
  scale: number;
  /** world -> svg */
  p: (pt: Pt) => [number, number];
  /** metres -> svg units */
  m: (metres: number) => number;
}

export function projector(b: Bounds, size: number): Projector {
  const scale = size / (b.maxX - b.minX);
  return {
    size,
    scale,
    p: ([x, y]) => [(x - b.minX) * scale, (b.maxY - y) * scale],
    m: (metres) => metres * scale,
  };
}

/** SVG path of a FOV wedge from `origin`, centred on `heading`, of angular width `fov`. */
export function wedgePath(proj: Projector, origin: Pt, heading: number, fov: number, range: number): string {
  const [ox, oy] = proj.p(origin);
  const a0 = heading - fov / 2;
  const a1 = heading + fov / 2;
  const e0 = proj.p([origin[0] + dir(a0)[0] * range, origin[1] + dir(a0)[1] * range]);
  const e1 = proj.p([origin[0] + dir(a1)[0] * range, origin[1] + dir(a1)[1] * range]);
  const r = proj.m(range);
  const large = fov > 180 ? 1 : 0;
  // compass bearings increase clockwise and SVG sweep-flag 1 is clockwise on screen
  return `M${ox},${oy} L${e0[0]},${e0[1]} A${r},${r} 0 ${large} 1 ${e1[0]},${e1[1]} Z`;
}

/** Far end of a ray from origin along bearing, clipped to the bounds box. */
export function rayEnd(b: Bounds, origin: Pt, bearingDeg: number): Pt {
  const [dx, dy] = dir(bearingDeg);
  const ts: number[] = [];
  if (dx > 1e-9) ts.push((b.maxX - origin[0]) / dx);
  if (dx < -1e-9) ts.push((b.minX - origin[0]) / dx);
  if (dy > 1e-9) ts.push((b.maxY - origin[1]) / dy);
  if (dy < -1e-9) ts.push((b.minY - origin[1]) / dy);
  const t = ts.length ? Math.max(0, Math.min(...ts)) : 0;
  return [origin[0] + dx * t, origin[1] + dy * t];
}

/** "Nice" grid step (1/2/5 x 10^n metres) giving roughly `target` lines across `span`. */
export function niceStep(span: number, target = 8): number {
  const raw = span / target;
  const p = 10 ** Math.floor(Math.log10(raw));
  const n = raw / p;
  return (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * p;
}

export function asPt(v: readonly number[] | null | undefined): Pt | null {
  if (!v || v.length < 2 || !Number.isFinite(v[0]) || !Number.isFinite(v[1])) return null;
  return [v[0], v[1]];
}

/* ---------- plan label placement (svg units) ---------- */

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type LabelSide = "e" | "w" | "n" | "s" | "ne" | "se" | "nw" | "sw";

export interface LabelRequest {
  key: string;
  /** Anchor point and the half-extent of the marker the label must clear. */
  at: readonly [number, number];
  clear: number;
  /** Monospace lines: width = chars x size x advance. */
  lines: readonly { chars: number; size: number }[];
  /** Preferred sides, best first. */
  sides: readonly LabelSide[];
  /** Second ring tried when every side at `clear` collides; the label then gets a leader. */
  escape?: number;
}

export interface PlacedLabel {
  /** Left edge (text-anchor start). */
  x: number;
  /** One baseline per line. */
  baselines: number[];
  box: Box;
  /** Set when the label was pushed out to `escape`: draw a line from the anchor to `to`. */
  leader: { from: readonly [number, number]; to: readonly [number, number] } | null;
}

// JetBrains Mono advance (0.6em) + the ~0.1em tracking the plan labels use
const ADVANCE_EM = 0.7;
const LABEL_GAP = 3;

function overlapArea(a: Box, b: Box): number {
  const w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  return w > 0 && h > 0 ? w * h : 0;
}

/**
 * Greedy, deterministic label placement. Each label takes the first preferred side that hits
 * nothing already taken (marker boxes, earlier labels) and stays inside `frame`; failing that,
 * the side with the least overlap. Order of `reqs` is priority order.
 */
export function placeLabels(
  reqs: readonly LabelRequest[],
  obstacles: readonly Box[],
  frame: Box,
): Map<string, PlacedLabel> {
  const taken: Box[] = [...obstacles];
  const out = new Map<string, PlacedLabel>();
  for (const r of reqs) {
    const lineH = r.lines.map((l) => l.size + 2);
    const w = Math.max(...r.lines.map((l) => l.chars * l.size * ADVANCE_EM));
    const h = lineH.reduce((a, b) => a + b, 0);
    const [ax, ay] = r.at;
    let best: { box: Box; cost: number; ring: number } | null = null;
    const rings = r.escape != null ? [r.clear, r.escape] : [r.clear];
    for (const [ring, clear] of rings.entries()) {
      for (const side of r.sides) {
        const d = (side.length === 2 ? clear * 0.7 : clear) + LABEL_GAP;
        const x = side.includes("e") ? ax + d : side.includes("w") ? ax - d - w : ax - w / 2;
        const y = side.includes("n") ? ay - d - h : side.includes("s") ? ay + d : ay - h / 2;
        const box = { x, y, w, h };
        const offFrame = w * h - overlapArea(box, frame);
        const cost = taken.reduce((acc, t) => acc + overlapArea(box, t), 0) + offFrame * 4;
        if (!best || cost < best.cost) best = { box, cost, ring };
        if (cost === 0) break;
      }
      if (best?.cost === 0) break;
    }
    if (!best) continue;
    taken.push(best.box);
    let acc = best.box.y;
    const baselines = lineH.map((lh) => (acc += lh) - 3);
    const { box } = best;
    // leader ends at the nearest point of the label box
    const to: [number, number] = [
      Math.min(Math.max(ax, box.x), box.x + box.w),
      Math.min(Math.max(ay, box.y), box.y + box.h),
    ];
    out.set(r.key, { x: box.x, baselines, box, leader: best.ring > 0 ? { from: r.at, to } : null });
  }
  return out;
}
