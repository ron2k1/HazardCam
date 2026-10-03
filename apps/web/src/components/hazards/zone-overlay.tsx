"use client";

import { useEffect, useState, type RefObject } from "react";

import { cn } from "@/lib/utils";

import type { ZoneBox } from "./derive";

export interface ContentRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * Where an object-fit: contain picture of aspect `aspect` (w/h) sits inside `ref`'s box, kept in
 * step with resizes, so overlays drawn in 0-1 picture coordinates stay on their objects.
 */
export function useContainRect(ref: RefObject<HTMLElement | null>, aspect: number | null): ContentRect | null {
  const [rect, setRect] = useState<ContentRect | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || !aspect || !Number.isFinite(aspect)) return;
    const measure = () => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (!w || !h) return;
      let width = w;
      let height = w / aspect;
      if (height > h) {
        height = h;
        width = h * aspect;
      }
      setRect({ left: (w - width) / 2, top: (h - height) / 2, width, height });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref, aspect]);
  return aspect ? rect : null;
}

export type ZoneMode = "relevant" | "all";

/** Hazard zones and zones with pictures by default; every zone with "Show all zones". */
export function visibleZones(zones: readonly ZoneBox[], mode: ZoneMode): ZoneBox[] {
  return mode === "all" ? [...zones] : zones.filter((z) => z.has_hazard || z.has_pictures);
}

export interface ZoneOverlayProps {
  zones: readonly ZoneBox[];
  rect: ContentRect | null;
  /** Zone numbers to emphasise (e.g. the hazard picked with "Show on video"). */
  focus?: readonly number[];
  compact?: boolean;
  className?: string;
}

const AMBER = "var(--warning, #ffb340)";
const WHITE = "rgba(241, 241, 239, 0.85)";

/** "ZONE 3" boxes over a video: hazard zones amber with a warning mark, the others thin white. */
export function ZoneOverlay({ zones, rect, focus = [], compact = false, className }: ZoneOverlayProps) {
  if (!rect || !zones.length) return null;
  const { width: W, height: H } = rect;
  const fs = compact ? 9 : 11;
  const tagH = fs + 6;
  // hazards last, so their tags sit on top
  const ordered = [...zones].sort((a, b) => Number(a.has_hazard) - Number(b.has_hazard));
  return (
    <svg
      aria-hidden
      className={cn("pointer-events-none absolute", className)}
      style={{ left: rect.left, top: rect.top, width: W, height: H }}
      viewBox={`0 0 ${W} ${H}`}
      data-testid="zone-overlay"
    >
      {ordered.map((z) => {
        const x = Math.max(0, z.box[0] * W);
        const y = Math.max(0, z.box[1] * H);
        const w = Math.max(2, Math.min(W, z.box[2] * W) - x);
        const h = Math.max(2, Math.min(H, z.box[3] * H) - y);
        const hot = z.has_hazard;
        const focused = focus.includes(z.number);
        const label = `ZONE ${z.number}`;
        const tagW = label.length * fs * 0.62 + (hot ? tagH + 6 : 8);
        const tagX = Math.min(x, W - tagW);
        const tagY = y >= tagH + 1 ? y - tagH : Math.min(y + 1, H - tagH);
        return (
          <g key={z.number} data-zone={z.number} data-hazard={hot || undefined}>
            <rect
              x={x}
              y={y}
              width={w}
              height={h}
              fill={hot ? "rgba(255, 179, 64, 0.08)" : "none"}
              stroke={hot ? AMBER : WHITE}
              strokeWidth={hot ? (focused ? 3 : 2) : 1}
              strokeDasharray={hot ? undefined : "4 3"}
            />
            <rect x={tagX} y={tagY} width={tagW} height={tagH} fill={hot ? AMBER : "rgba(5, 5, 5, 0.8)"} stroke={hot ? "#050505" : WHITE} strokeWidth={0.75} />
            {hot ? (
              <g transform={`translate(${tagX + 3} ${tagY + 2})`}>
                <path d={`M${(tagH - 4) / 2} 0 L${tagH - 4} ${tagH - 4} L0 ${tagH - 4} Z`} fill="#050505" />
                <rect x={(tagH - 4) / 2 - 0.6} y={(tagH - 4) * 0.35} width={1.2} height={(tagH - 4) * 0.35} fill={AMBER} />
                <rect x={(tagH - 4) / 2 - 0.6} y={(tagH - 4) * 0.78} width={1.2} height={1.2} fill={AMBER} />
              </g>
            ) : null}
            <text
              x={tagX + (hot ? tagH + 2 : 4)}
              y={tagY + tagH - 4}
              fontSize={fs}
              fontWeight={700}
              letterSpacing="0.06em"
              fill={hot ? "#050505" : WHITE}
              style={{ fontFamily: "var(--font-mono-hud), ui-monospace, monospace" }}
            >
              {label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
