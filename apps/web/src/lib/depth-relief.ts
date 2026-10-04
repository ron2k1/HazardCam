/**
 * A clip's relative depth grid (`depth.json`, written by scripts/hazards/depth_relief.py):
 * Depth Anything V2 Small, run on this machine over one real frame of the clip's source.mp4.
 *
 * The values are relative inverse depth (1 = nearest in that frame, 0 = farthest), with unknown
 * scale and shift: the wall clips carry no camera calibration, so this is never metres, and it
 * is not part of any review run. Pure: no imports, so it can be checked outside Next.
 */

import type { Box01 } from "./cv-map";

export interface DepthRelief {
  clipId: string;
  /** Grid size; values are row-major from the frame's top-left corner. */
  w: number;
  h: number;
  /** 0..255, 255 = nearest. */
  values: Uint8Array;
  frame: { index: number; timeS: number | null; of: number | null };
  model: { id: string; ms: number | null };
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

function decodeBase64(data: string): Uint8Array | null {
  try {
    const bin = atob(data);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  } catch {
    return null;
  }
}

/** The served depth.json as a grid, or null for anything that is not a whole relative-depth grid. */
export function parseDepthRelief(doc: unknown): DepthRelief | null {
  if (!doc || typeof doc !== "object") return null;
  const d = doc as Record<string, unknown>;
  if (d.kind !== "relative_inverse_depth" || typeof d.clip_id !== "string") return null;
  const grid = d.grid as Record<string, unknown> | undefined;
  const w = num(grid?.width);
  const h = num(grid?.height);
  if (!grid || !w || !h || w < 2 || h < 2 || typeof grid.data !== "string") return null;
  const values = decodeBase64(grid.data);
  if (!values || values.length !== w * h) return null;
  const frame = (d.frame ?? {}) as Record<string, unknown>;
  const model = (d.model ?? {}) as Record<string, unknown>;
  return {
    clipId: d.clip_id,
    w,
    h,
    values,
    frame: { index: num(frame.index) ?? 0, timeS: num(frame.time_s), of: num(frame.of_frames) },
    model: { id: typeof model.id === "string" ? model.id : "unknown", ms: num(model.inference_ms) },
  };
}

/**
 * Depth (0..1) at image point (u, v) in [0, 1], bilinear between grid values. Grid value (ix, iy)
 * sits at u = ix / (w - 1), v = iy / (h - 1): the same convention as a w x h vertex plane, so a
 * sampled outline lies on the displaced mesh. Points outside the frame clamp to its edge.
 */
export function depthAt(r: DepthRelief, u: number, v: number): number {
  const fx = Math.min(Math.max(u, 0), 1) * (r.w - 1);
  const fy = Math.min(Math.max(v, 0), 1) * (r.h - 1);
  const x0 = Math.min(Math.floor(fx), r.w - 2);
  const y0 = Math.min(Math.floor(fy), r.h - 2);
  const tx = fx - x0;
  const ty = fy - y0;
  const at = (x: number, y: number) => r.values[y * r.w + x];
  const top = at(x0, y0) * (1 - tx) + at(x0 + 1, y0) * tx;
  const bottom = at(x0, y0 + 1) * (1 - tx) + at(x0 + 1, y0 + 1) * tx;
  return (top * (1 - ty) + bottom * ty) / 255;
}

/**
 * A box's perimeter as [u, v, depth] samples, clockwise from its top-left corner, `perSide` per
 * edge, so the outline can follow the surface instead of cutting through it.
 */
export function boxLoop(r: DepthRelief, box: Box01, perSide: number): [number, number, number][] {
  const [x0, y0, x1, y1] = box;
  const corners: [number, number][] = [
    [x0, y0],
    [x1, y0],
    [x1, y1],
    [x0, y1],
  ];
  const out: [number, number, number][] = [];
  for (let side = 0; side < 4; side++) {
    const [ua, va] = corners[side];
    const [ub, vb] = corners[(side + 1) % 4];
    for (let i = 0; i < perSide; i++) {
      const t = i / perSide;
      const u = ua + (ub - ua) * t;
      const v = va + (vb - va) * t;
      out.push([u, v, depthAt(r, u, v)]);
    }
  }
  return out;
}
