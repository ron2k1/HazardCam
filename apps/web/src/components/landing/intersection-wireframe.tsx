"use client";

import { useAmbientMotion } from "@/hooks/use-animate";

/*
 * Wireframe urban intersection: the landing's stand-in for the reference's Vitruvian figure.
 * Circle + square + diagonals (architectural frame), two crossing roads, three visible
 * camera FOV cones, one withheld camera, and rays converging on a blind-zone reticle.
 * Pure SVG; ambient motion is SMIL and only mounts when motion is allowed.
 */

const S = 640;
const C = S / 2;
const ROAD = 34; // half-width of each road band
const CURB = 14;

type XY = [number, number];

/** Screen direction for a compass bearing (north up). */
const sdir = (b: number): XY => [Math.sin((b * Math.PI) / 180), -Math.cos((b * Math.PI) / 180)];

function wedge(o: XY, heading: number, fov: number, r: number): string {
  const [x0, y0] = sdir(heading - fov / 2);
  const [x1, y1] = sdir(heading + fov / 2);
  return `M${o[0]},${o[1]} L${o[0] + x0 * r},${o[1] + y0 * r} A${r},${r} 0 0 1 ${o[0] + x1 * r},${o[1] + y1 * r} Z`;
}

const CAMS: { id: string; at: XY; heading: number; fov: number; labelDx: number; labelDy: number }[] = [
  { id: "CAM_01", at: [168, 214], heading: 112, fov: 70, labelDx: -10, labelDy: -14 },
  { id: "CAM_02", at: [474, 168], heading: 214, fov: 65, labelDx: 12, labelDy: -10 },
  { id: "CAM_03", at: [396, 492], heading: 338, fov: 80, labelDx: 14, labelDy: 18 },
];
const GT = { at: [212, 446] as XY, heading: 52, fov: 70 };
const TARGET: XY = [336, 330];

function Crosswalk({ axis, at }: { axis: "h" | "v"; at: number }) {
  const stripes = [];
  for (let k = C - ROAD + 5; k <= C + ROAD - 7; k += 7) {
    stripes.push(
      axis === "h" ? (
        <rect key={k} x={at} y={k} width={14} height={3} />
      ) : (
        <rect key={k} x={k} y={at} width={3} height={14} />
      ),
    );
  }
  return <g className="fill-fg/30">{stripes}</g>;
}

export function IntersectionWireframe({ className }: { className?: string }) {
  const animate = useAmbientMotion();
  const lo = C - ROAD;
  const hi = C + ROAD;

  return (
    <svg
      viewBox={`0 0 ${S} ${S}`}
      className={className}
      role="img"
      aria-label="Wireframe intersection: three input camera fields of view, one withheld camera, rays converging on an unseen region"
    >
      <defs>
        <pattern id="iw-dots" width="9" height="9" patternUnits="userSpaceOnUse">
          <circle cx="1.5" cy="1.5" r="0.9" fill="#f1f1ef" fillOpacity="0.32" />
        </pattern>
        <pattern id="iw-dots-dense" width="5" height="5" patternUnits="userSpaceOnUse">
          <circle cx="1" cy="1" r="0.8" fill="#f1f1ef" fillOpacity="0.55" />
        </pattern>
        <clipPath id="iw-circle">
          <circle cx={C} cy={C} r={262} />
        </clipPath>
      </defs>

      {/* architectural frame */}
      <circle cx={C} cy={C} r={262} fill="url(#iw-dots)" opacity={0.55} />
      <circle cx={C} cy={C} r={262} fill="none" stroke="#f1f1ef" strokeOpacity={0.7} strokeWidth={1.2} />
      <circle cx={C} cy={C} r={276} fill="none" stroke="#f1f1ef" strokeOpacity={0.35} strokeDasharray="1 5" />
      <rect x={120} y={120} width={400} height={400} fill="none" stroke="#f1f1ef" strokeOpacity={0.6} />
      <path d="M120,120 L520,520 M520,120 L120,520" stroke="#f1f1ef" strokeOpacity={0.22} strokeDasharray="2 6" />
      <path d={`M${C},40 V600 M40,${C} H600`} stroke="#f1f1ef" strokeOpacity={0.12} />

      {/* ruler ticks on the square */}
      <g stroke="#f1f1ef" strokeOpacity={0.4}>
        {Array.from({ length: 21 }, (_, i) => 120 + i * 20).map((v, i) => (
          <g key={v}>
            <line x1={v} y1={120} x2={v} y2={i % 5 === 0 ? 110 : 115} />
            <line x1={120} y1={v} x2={i % 5 === 0 ? 110 : 115} y2={v} />
          </g>
        ))}
      </g>

      {/* roads, clipped to the circle */}
      <g clipPath="url(#iw-circle)" fill="none" stroke="#f1f1ef" strokeOpacity={0.85} strokeWidth={1.1}>
        <path d={`M40,${lo} H${lo - CURB} A${CURB},${CURB} 0 0 0 ${lo},${lo - CURB} V40`} />
        <path d={`M${hi},40 V${lo - CURB} A${CURB},${CURB} 0 0 0 ${hi + CURB},${lo} H600`} />
        <path d={`M600,${hi} H${hi + CURB} A${CURB},${CURB} 0 0 0 ${hi},${hi + CURB} V600`} />
        <path d={`M${lo},600 V${hi + CURB} A${CURB},${CURB} 0 0 0 ${lo - CURB},${hi} H40`} />
        <g strokeOpacity={0.35} strokeDasharray="8 8">
          <path d={`M40,${C} H${lo - 26} M${hi + 26},${C} H600 M${C},40 V${lo - 26} M${C},${hi + 26} V600`} />
        </g>
      </g>
      <Crosswalk axis="h" at={lo - 22} />
      <Crosswalk axis="h" at={hi + 8} />
      <Crosswalk axis="v" at={lo - 22} />
      <Crosswalk axis="v" at={hi + 8} />

      {/* building blocks (faint) */}
      <g fill="url(#iw-dots-dense)" opacity={0.18}>
        <rect x={150} y={150} width={lo - 182} height={lo - 182} />
        <rect x={hi + 32} y={150} width={lo - 182} height={lo - 182} />
        <rect x={hi + 32} y={hi + 32} width={lo - 182} height={lo - 182} />
        <rect x={150} y={hi + 32} width={lo - 182} height={lo - 182} />
      </g>

      {/* visible cameras: FOV cones */}
      {CAMS.map((cam, i) => (
        <g key={cam.id}>
          <g>
            <path d={wedge(cam.at, cam.heading, cam.fov, 128)} fill="url(#iw-dots-dense)" opacity={0.5} />
            <path
              d={wedge(cam.at, cam.heading, cam.fov, 128)}
              fill="none"
              stroke="#f1f1ef"
              strokeOpacity={0.75}
            />
            {animate ? (
              <animateTransform
                attributeName="transform"
                type="rotate"
                values={`-3 ${cam.at[0]} ${cam.at[1]}; 3 ${cam.at[0]} ${cam.at[1]}; -3 ${cam.at[0]} ${cam.at[1]}`}
                dur={`${9 + i * 2}s`}
                repeatCount="indefinite"
              />
            ) : null}
          </g>
          <rect x={cam.at[0] - 4} y={cam.at[1] - 4} width={8} height={8} fill="#050505" stroke="#f1f1ef" />
          <text
            x={cam.at[0] + cam.labelDx}
            y={cam.at[1] + cam.labelDy}
            textAnchor={cam.labelDx < 0 ? "end" : "start"}
            className="fill-fg font-mono text-[10px] tracking-[0.14em]"
            stroke="#050505"
            strokeWidth={3}
            strokeLinejoin="round"
            paintOrder="stroke"
          >
            {cam.id}
          </text>
          {/* ray toward the unseen region */}
          <line
            x1={cam.at[0]}
            y1={cam.at[1]}
            x2={TARGET[0]}
            y2={TARGET[1]}
            stroke="#f1f1ef"
            strokeOpacity={0.55}
            strokeDasharray="3 5"
          >
            {animate ? (
              <animate attributeName="stroke-dashoffset" values="16;0" dur="1.6s" repeatCount="indefinite" />
            ) : null}
          </line>
        </g>
      ))}

      {/* withheld judge camera: hollow, dashed */}
      <g>
        <path
          d={wedge(GT.at, GT.heading, GT.fov, 96)}
          fill="none"
          stroke="#f1f1ef"
          strokeOpacity={0.4}
          strokeDasharray="2 4"
        />
        <rect
          x={GT.at[0] - 4}
          y={GT.at[1] - 4}
          width={8}
          height={8}
          fill="none"
          stroke="#f1f1ef"
          strokeOpacity={0.6}
          strokeDasharray="2 2"
        />
        <text x={GT.at[0]} y={GT.at[1] + 22} textAnchor="middle" className="fill-muted font-mono text-[9px] tracking-[0.14em]">
          GT · WITHHELD
        </text>
      </g>

      {/* blind-zone reticle */}
      <g>
        <rect x={TARGET[0] - 46} y={TARGET[1] - 46} width={92} height={92} fill="none" stroke="#f1f1ef" strokeOpacity={0.18} />
        <path
          d={`M${TARGET[0] - 46},${TARGET[1] - 34} v-12 h12 M${TARGET[0] + 34},${TARGET[1] - 46} h12 v12 M${TARGET[0] + 46},${TARGET[1] + 34} v12 h-12 M${TARGET[0] - 34},${TARGET[1] + 46} h-12 v-12`}
          fill="none"
          stroke="#f1f1ef"
          strokeWidth={1.4}
        />
        <circle cx={TARGET[0]} cy={TARGET[1]} r={26} fill="none" stroke="#f1f1ef" strokeOpacity={0.9} />
        <circle cx={TARGET[0]} cy={TARGET[1]} r={3} fill="#f1f1ef" />
        <g>
          <circle
            cx={TARGET[0]}
            cy={TARGET[1]}
            r={36}
            fill="none"
            stroke="#f1f1ef"
            strokeOpacity={0.5}
            strokeDasharray="2 7"
          />
          <path
            d={`M${TARGET[0]},${TARGET[1] - 40} v-8 M${TARGET[0] + 40},${TARGET[1]} h8 M${TARGET[0]},${TARGET[1] + 40} v8 M${TARGET[0] - 40},${TARGET[1]} h-8`}
            stroke="#f1f1ef"
          />
          {animate ? (
            <animateTransform
              attributeName="transform"
              type="rotate"
              values={`0 ${TARGET[0]} ${TARGET[1]}; 360 ${TARGET[0]} ${TARGET[1]}`}
              dur="40s"
              repeatCount="indefinite"
            />
          ) : null}
        </g>
        <path d={`M${TARGET[0] + 46},${TARGET[1] - 46} L${TARGET[0] + 92},${TARGET[1] - 92} H${TARGET[0] + 178}`} fill="none" stroke="#f1f1ef" strokeOpacity={0.5} />
        {/* backing plate so the callout reads over CAM_02's cone */}
        <rect x={TARGET[0] + 92} y={TARGET[1] - 110} width={102} height={16} fill="#050505" fillOpacity={0.85} />
        <rect x={TARGET[0] + 92} y={TARGET[1] - 90} width={102} height={15} fill="#050505" fillOpacity={0.85} />
        <text x={TARGET[0] + 96} y={TARGET[1] - 98} className="fill-fg font-mono text-[10px] tracking-[0.16em]">
          UNSEEN REGION
        </text>
        <text x={TARGET[0] + 96} y={TARGET[1] - 80} className="fill-muted font-mono text-[9px] tracking-[0.14em]">
          RAY ∩ · 3 CAMS
        </text>
      </g>

      {/* compass + scale */}
      <g className="font-mono text-[9px] tracking-[0.14em]">
        <path d={`M${C},22 l-4,9 h8 z`} fill="#f1f1ef" />
        <text x={C + 8} y={30} className="fill-muted">
          N
        </text>
        <path d="M120,552 h80 M120,548 v8 M160,550 v4 M200,548 v8" stroke="#f1f1ef" strokeOpacity={0.6} />
        <text x={120} y={572} className="fill-muted">
          0
        </text>
        <text x={196} y={572} className="fill-muted">
          10 M
        </text>
        {/* top-right corner sits outside both rings */}
        <text x={630} y={30} textAnchor="end" className="fill-muted">
          PLAN · LOCAL METRIC
        </text>
      </g>
    </svg>
  );
}
