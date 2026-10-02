"use client";

import { motion } from "motion/react";
import { useId } from "react";

import { Panel } from "@/components/hud/panel";
import { useAmbientMotion } from "@/hooks/use-animate";
import { UI } from "@/lib/config";
import type { Camera, PublicCamera, Ray, RegionCandidate, Zone } from "@/lib/contracts";
import { deg, fixed, label } from "@/lib/format";
import {
  asPt,
  boundsOf,
  niceStep,
  placeLabels,
  projector,
  rayEnd,
  wedgePath,
  type Box,
  type LabelRequest,
  type PlacedLabel,
  type Pt,
} from "@/lib/geometry";

export interface BlindZonePlanProps {
  /** Visible (model-input) cameras with position/heading/FOV. */
  cameras: readonly PublicCamera[];
  zones: readonly Zone[];
  candidates: readonly RegionCandidate[];
  rays: readonly Ray[];
  /** Judge-only GT camera; pass only after reveal. */
  groundTruth?: Pick<Camera, "id" | "position" | "heading_deg" | "fov_deg"> | null;
  /** Evidence to emphasise (rays whose evidence_id is in the set). */
  activeEvidenceIds?: ReadonlySet<string>;
  highlightCameraId?: string | null;
  className?: string;
}

const SIZE = 400;
const FG = "#f1f1ef";
const HALO = "#090909";
const FRAME: Box = { x: 0, y: 0, w: SIZE, h: SIZE };

/** Label text with a panel-coloured halo so it stays legible over rays and wedge edges. */
function LabelText({
  placed,
  lines,
}: {
  placed: PlacedLabel | undefined;
  lines: readonly { text: string; className: string }[];
}) {
  if (!placed) return null;
  const { leader } = placed;
  return (
    <>
      {leader ? (
        <line
          x1={leader.from[0]}
          y1={leader.from[1]}
          x2={leader.to[0]}
          y2={leader.to[1]}
          stroke={FG}
          strokeOpacity="0.55"
          strokeWidth="0.75"
        />
      ) : null}
      <g stroke={HALO} strokeWidth={3} strokeLinejoin="round" paintOrder="stroke">
        {lines.map((l, i) => (
          <text key={i} x={placed.x} y={placed.baselines[i]} className={l.className}>
            {l.text}
          </text>
        ))}
      </g>
    </>
  );
}

const ID_CLS = "fill-fg font-mono text-[9px] tracking-[0.1em]";
const SUB_CLS = "fill-muted font-mono text-[8px] tracking-[0.1em]";

export function BlindZonePlan({
  cameras,
  zones,
  candidates,
  rays,
  groundTruth,
  activeEvidenceIds,
  highlightCameraId,
  className,
}: BlindZonePlanProps) {
  const uid = useId().replace(/:/g, "");
  const animate = useAmbientMotion();

  const camPts = cameras
    .map((c) => ({ cam: c, pt: asPt(c.position) }))
    .filter((c): c is { cam: PublicCamera; pt: Pt } => c.pt !== null);
  const gtPt = groundTruth ? asPt(groundTruth.position) : null;
  const candPts = candidates
    .map((c) => ({ cand: c, pt: asPt(c.center) }))
    .filter((c): c is { cand: RegionCandidate; pt: Pt } => c.pt !== null);

  const b = boundsOf(
    [...camPts.map((c) => c.pt), ...(gtPt ? [gtPt] : [])],
    [
      ...zones.map((z) => ({ c: z.center as Pt, r: z.radius_m })),
      ...candPts.map((c) => ({ c: c.pt, r: c.cand.radius_m ?? 0 })),
    ],
    UI.planPaddingM,
  );
  const proj = projector(b, SIZE);
  const extent = b.maxX - b.minX;
  const range = extent * UI.fovRangeFraction;
  const step = niceStep(extent, 8);
  const gridX: number[] = [];
  const gridY: number[] = [];
  for (let v = Math.ceil(b.minX / step) * step; v <= b.maxX; v += step) gridX.push(Number(v.toFixed(6)));
  for (let v = Math.ceil(b.minY / step) * step; v <= b.maxY; v += step) gridY.push(Number(v.toFixed(6)));

  const best = candPts.reduce<{ cand: RegionCandidate; pt: Pt } | null>(
    (acc, c) => (!acc || c.cand.score > acc.cand.score ? c : acc),
    null,
  );
  const wedges = camPts.filter((c) => c.cam.heading_deg != null && c.cam.fov_deg != null);

  // projected markers (svg units)
  const camXY = camPts.map(({ cam, pt }) => ({ cam, xy: proj.p(pt) }));
  const candXY = candPts.map(({ cand, pt }) => {
    const xy = proj.p(pt);
    const r = Math.max(proj.m(cand.radius_m ?? 0), 10);
    return { cand, xy, r, k: r + 8 };
  });
  const gtXY = groundTruth && gtPt ? proj.p(gtPt) : null;

  /** Clearance that gets a marker's label out of any reticle box the marker sits inside. */
  const escapeFrom = ([x, y]: readonly [number, number]): number | undefined => {
    const inside = candXY.filter(({ xy: [cx, cy], k }) => Math.abs(x - cx) <= k && Math.abs(y - cy) <= k);
    if (!inside.length) return undefined;
    return Math.max(...inside.map(({ xy: [cx, cy], k }) => k + Math.max(Math.abs(x - cx), Math.abs(y - cy))));
  };

  const obstacles: Box[] = [
    ...camXY.map(({ xy: [x, y] }) => ({ x: x - 5, y: y - 5, w: 10, h: 10 })),
    ...candXY.map(({ xy: [x, y], k }) => ({ x: x - k, y: y - k, w: 2 * k, h: 2 * k })),
    ...(gtXY ? [{ x: gtXY[0] - 5, y: gtXY[1] - 5, w: 10, h: 10 }] : []),
    { x: SIZE - 22, y: 2, w: 16, h: 26 }, // north arrow
  ];
  const requests: LabelRequest[] = [
    ...camXY.map(({ cam, xy }) => ({
      key: `cam:${cam.id}`,
      at: xy,
      clear: 5,
      escape: escapeFrom(xy),
      lines: [
        { chars: cam.id.length, size: 9 },
        { chars: 4, size: 8 },
      ],
      sides: ["ne", "se", "nw", "sw", "e", "w", "n", "s"] as const,
    })),
    ...candXY.map(({ cand, xy, k }) => ({
      key: `cand:${cand.id}`,
      at: xy,
      clear: k,
      lines: [
        { chars: cand.id.length, size: 9 },
        { chars: label(cand.method).length + 7, size: 8 },
      ],
      sides: ["e", "w", "s", "n", "se", "ne", "sw", "nw"] as const,
    })),
    ...zones.map((z) => ({
      key: `zone:${z.id}`,
      at: proj.p(z.center as Pt),
      // just outside the circle and outside a concentric reticle's brackets (k = r + 8)
      clear: proj.m(z.radius_m) + 9,
      lines: [{ chars: (z.label ?? z.id).length, size: 8 }],
      sides: ["n", "s", "ne", "nw", "se", "sw", "e", "w"] as const,
    })),
    ...(gtXY
      ? [
          {
            key: "gt",
            at: gtXY,
            clear: 5,
            escape: escapeFrom(gtXY),
            lines: [{ chars: 10, size: 8 }],
            sides: ["se", "sw", "s", "e", "w", "ne", "nw", "n"] as const,
          },
        ]
      : []),
  ];
  const placed = placeLabels(requests, obstacles, FRAME);

  return (
    <Panel
      index="03"
      title="Blind-Zone Plan"
      className={className}
      bodyClassName="flex items-center justify-center p-1.5"
      meta={
        <>
          <span>{rays.length} RAYS</span>
          <span>{candidates.length} CAND</span>
          <span className="hidden @min-[350px]:inline">GRID {fixed(step, step < 1 ? 1 : 0)}M</span>
        </>
      }
    >
      <svg
        viewBox={`-28 -14 ${SIZE + 42} ${SIZE + 46}`}
        className="h-full max-h-full w-full"
        role="img"
        aria-label={`Plan view: ${cameras.length} input cameras, ${candidates.length} region candidates, ${zones.length} zones`}
      >
        <defs>
          <pattern id={`dots-${uid}`} width="6" height="6" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="0.7" fill={FG} fillOpacity="0.45" />
          </pattern>
          <pattern id={`hatch-${uid}`} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="7" stroke={FG} strokeOpacity="0.09" strokeWidth="1" />
          </pattern>
          <clipPath id={`frame-${uid}`}>
            <rect x="0" y="0" width={SIZE} height={SIZE} />
          </clipPath>
          {/* blind area = plan minus every input camera's (range-capped) FOV wedge */}
          <mask id={`blind-${uid}`}>
            <rect x="0" y="0" width={SIZE} height={SIZE} fill="white" />
            {wedges.map(({ cam, pt }) => (
              <path key={cam.id} d={wedgePath(proj, pt, cam.heading_deg!, cam.fov_deg!, range)} fill="black" />
            ))}
          </mask>
        </defs>

        {/* frame + metric grid */}
        <rect x="0" y="0" width={SIZE} height={SIZE} fill="none" stroke={FG} strokeOpacity="0.28" />
        {gridX.map((v) => {
          const [px] = proj.p([v, b.minY]);
          return (
            <g key={`x${v}`}>
              <line x1={px} y1={0} x2={px} y2={SIZE} stroke={FG} strokeOpacity={v === 0 ? 0.22 : 0.07} />
              <text x={px} y={SIZE + 11} textAnchor="middle" className="fill-dim font-mono text-[8px]">
                {fixed(v, step < 1 ? 1 : 0)}
              </text>
            </g>
          );
        })}
        {gridY.map((v) => {
          const [, py] = proj.p([b.minX, v]);
          return (
            <g key={`y${v}`}>
              <line x1={0} y1={py} x2={SIZE} y2={py} stroke={FG} strokeOpacity={v === 0 ? 0.22 : 0.07} />
              <text x={-5} y={py + 3} textAnchor="end" className="fill-dim font-mono text-[8px]">
                {fixed(v, step < 1 ? 1 : 0)}
              </text>
            </g>
          );
        })}
        <text x={-5} y={-5} textAnchor="end" className="fill-muted font-mono text-[8px] tracking-[0.12em]">
          Y_N
        </text>

        <g clipPath={`url(#frame-${uid})`}>
          {/* blind area hatch */}
          <rect x="0" y="0" width={SIZE} height={SIZE} fill={`url(#hatch-${uid})`} mask={`url(#blind-${uid})`} />

          {/* zones */}
          {zones.map((z) => {
            const [cx, cy] = proj.p(z.center as Pt);
            return (
              <circle
                key={z.id}
                cx={cx}
                cy={cy}
                r={proj.m(z.radius_m)}
                fill="none"
                stroke={FG}
                strokeOpacity="0.4"
                strokeDasharray="1.5 4"
              />
            );
          })}

          {/* FOV wedges */}
          {wedges.map(({ cam, pt }) => {
            const d = wedgePath(proj, pt, cam.heading_deg!, cam.fov_deg!, range);
            const hi = cam.id === highlightCameraId;
            return (
              <g key={cam.id}>
                <path d={d} fill={`url(#dots-${uid})`} opacity={hi ? 0.55 : 0.32} />
                <path d={d} fill="none" stroke={FG} strokeOpacity={hi ? 0.85 : 0.45} />
              </g>
            );
          })}

          {/* judge-only GT wedge, after reveal */}
          {groundTruth && gtPt && groundTruth.heading_deg != null && groundTruth.fov_deg != null ? (
            <path
              d={wedgePath(proj, gtPt, groundTruth.heading_deg, groundTruth.fov_deg, range * 0.6)}
              fill="none"
              stroke={FG}
              strokeOpacity="0.55"
              strokeDasharray="2 3"
            />
          ) : null}

          {/* rays */}
          {rays.map((r, i) => {
            const o = asPt(r.origin);
            if (!o) return null;
            const [x1, y1] = proj.p(o);
            const [x2, y2] = proj.p(rayEnd(b, o, r.bearing_deg));
            const hot = activeEvidenceIds?.has(r.evidence_id) ?? false;
            return (
              <motion.line
                key={`${r.camera_id}-${r.evidence_id}-${i}`}
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke={FG}
                strokeOpacity={hot ? 0.95 : 0.6}
                strokeWidth={hot ? 1.3 : 1}
                strokeDasharray="4 4"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.5, delay: i * 0.08 }}
              />
            );
          })}

          {/* region candidates as targeting reticles */}
          {candXY.map(({ cand, xy: [cx, cy], r, k }) => {
            const top = cand === best?.cand;
            return (
              <motion.g
                key={cand.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.5 }}
                data-candidate={cand.id}
              >
                <circle cx={cx} cy={cy} r={r} fill={FG} fillOpacity={top ? 0.06 : 0.03} stroke={FG} strokeOpacity={top ? 0.95 : 0.5} />
                <path
                  d={`M${cx - k},${cy - k + 6} v-6 h6 M${cx + k - 6},${cy - k} h6 v6 M${cx + k},${cy + k - 6} v6 h-6 M${cx - k + 6},${cy + k} h-6 v-6`}
                  fill="none"
                  stroke={FG}
                  strokeWidth={1.2}
                  strokeOpacity={top ? 1 : 0.55}
                />
                <path d={`M${cx - 4},${cy} h8 M${cx},${cy - 4} v8`} stroke={FG} />
                {top ? (
                  <circle cx={cx} cy={cy} r={r + 4} fill="none" stroke={FG} strokeOpacity="0.5" strokeDasharray="2 5">
                    {animate ? (
                      <animateTransform attributeName="transform" type="rotate" values={`0 ${cx} ${cy}; 360 ${cx} ${cy}`} dur="30s" repeatCount="indefinite" />
                    ) : null}
                  </circle>
                ) : null}
              </motion.g>
            );
          })}
        </g>

        {/* markers */}
        {camXY.map(({ cam, xy: [x, y] }) => (
          <rect
            key={cam.id}
            data-camera={cam.id}
            x={x - 4}
            y={y - 4}
            width={8}
            height={8}
            fill={cam.id === highlightCameraId ? FG : "#050505"}
            stroke={FG}
          />
        ))}
        {gtXY ? (
          <rect data-camera="ground-truth" x={gtXY[0] - 4} y={gtXY[1] - 4} width={8} height={8} fill="#050505" stroke={FG} strokeDasharray="2 2" />
        ) : null}

        {/* labels (placed to avoid markers and each other) */}
        {zones.map((z) => (
          <LabelText key={z.id} placed={placed.get(`zone:${z.id}`)} lines={[{ text: (z.label ?? z.id).toUpperCase(), className: SUB_CLS }]} />
        ))}
        {candXY.map(({ cand }) => (
          <LabelText
            key={cand.id}
            placed={placed.get(`cand:${cand.id}`)}
            lines={[
              { text: cand.id.toUpperCase(), className: ID_CLS },
              { text: `${label(cand.method)} · ${fixed(cand.score)}`, className: SUB_CLS },
            ]}
          />
        ))}
        {camXY.map(({ cam }) => (
          <LabelText
            key={cam.id}
            placed={placed.get(`cam:${cam.id}`)}
            lines={[
              { text: cam.id.toUpperCase(), className: ID_CLS },
              { text: deg(cam.heading_deg), className: SUB_CLS },
            ]}
          />
        ))}
        {gtXY ? (
          <LabelText placed={placed.get("gt")} lines={[{ text: "GT · JUDGE", className: "fill-fg font-mono text-[8px] tracking-[0.1em]" }]} />
        ) : null}

        {/* legend row */}
        <g className="font-mono text-[8px] tracking-[0.1em]">
          <rect x={0} y={SIZE + 21} width={9} height={7} fill={`url(#hatch-${uid})`} stroke={FG} strokeOpacity="0.3" />
          <text x={14} y={SIZE + 28} className="fill-muted">
            OUTSIDE ALL INPUT FOV · RANGE CAP {fixed(range, 0)}M
          </text>
          <text x={SIZE} y={SIZE + 28} textAnchor="end" className="fill-muted tracking-[0.12em]">
            X_EAST M
          </text>
        </g>

        {/* north arrow */}
        <g transform={`translate(${SIZE - 14}, 14)`}>
          <path d="M0,-9 l-4,9 h8 z" fill={FG} />
          <text x="0" y="11" textAnchor="middle" className="fill-muted font-mono text-[8px]">
            N
          </text>
        </g>
      </svg>
    </Panel>
  );
}
