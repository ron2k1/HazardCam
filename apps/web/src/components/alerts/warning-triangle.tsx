"use client";

/*
 * Shared ISO 7010 (W001-style) warning triangle for alerts: amber field, black border, black glyph.
 * Geometry matches components/hazards/warning-sign.tsx so both read as one sign family.
 *
 * The optional pulse is adapted from Magic UI "Ripple" (MIT, (c) Magic UI), listed on 21st.dev as
 * https://21st.dev/r/magicui/ripple (source: https://magicui.design/r/ripple.json, since the 21st.dev
 * registry requires authentication). Normalized: concentric triangles instead of circles, amber
 * token, motion/react instead of a CSS keyframe, and a single static outline under
 * prefers-reduced-motion.
 */

import type { CSSProperties } from "react";
import { motion } from "motion/react";

import { usePrefersReducedMotion } from "@/components/alerts/use-reduced-motion";
import { cn } from "@/lib/utils";

export type TriangleGlyph = "warning" | "eye-off" | "forklift";
export type AlertTone = "hazard" | "blindspot";
export type TriangleSize = "xs" | "sm" | "md" | "lg" | "xl" | number;

const SIZE_PX: Record<Exclude<TriangleSize, number>, number> = { xs: 14, sm: 18, md: 24, lg: 40, xl: 76 };

/** Resolve an arbitrary glyph string to one this component draws; unknown values fall back by tone. */
export function resolveGlyph(glyph: string | null | undefined, tone: AlertTone = "hazard"): TriangleGlyph {
  if (glyph === "warning" || glyph === "eye-off" || glyph === "forklift") return glyph;
  if (glyph === "eye" || glyph === "blindspot") return "eye-off";
  return tone === "blindspot" ? "eye-off" : "warning";
}

const INK = "#050505";
const AMBER = "var(--warning, #ffb340)";
const OUTER = "M12 1.8 L23 21.4 L1 21.4 Z";

function Glyph({ glyph }: { glyph: TriangleGlyph }) {
  switch (glyph) {
    case "eye-off":
      return (
        <g>
          <path d="M6.6 15.4 Q12 10.2 17.4 15.4 Q12 20.6 6.6 15.4 Z" fill="none" stroke={INK} strokeWidth="1.3" />
          <circle cx="12" cy="15.4" r="1.7" fill={INK} />
          <path d="M7.4 19.6 L16.8 10.6" stroke={AMBER} strokeWidth="2.4" />
          <path d="M7.4 19.6 L16.8 10.6" stroke={INK} strokeWidth="1.2" strokeLinecap="square" />
        </g>
      );
    case "forklift":
      return (
        <g fill={INK}>
          <rect x="7.2" y="13" width="5.6" height="3.8" />
          <rect x="8.2" y="10.6" width="2.6" height="2.6" fill="none" stroke={INK} strokeWidth="0.9" />
          <rect x="13.4" y="9.8" width="1.1" height="7.4" />
          <rect x="14.5" y="16.2" width="3" height="1" />
          <circle cx="8.6" cy="17.6" r="1.25" />
          <circle cx="12" cy="17.6" r="1.25" />
        </g>
      );
    case "warning":
    default:
      return (
        <g fill={INK}>
          <rect x="11" y="9" width="2" height="6.4" />
          <rect x="11" y="16.6" width="2" height="2" />
        </g>
      );
  }
}

export interface WarningTriangleProps {
  /** warning ("!"), eye-off, forklift; anything else falls back by tone. */
  glyph?: TriangleGlyph | string | null;
  tone?: AlertTone;
  size?: TriangleSize;
  /** Concentric amber triangles ripple outward (static outline under reduced motion). */
  pulse?: boolean;
  /** Accessible name; omitted means decorative (aria-hidden). */
  title?: string;
  className?: string;
}

export function WarningTriangle({ glyph, tone = "hazard", size = "md", pulse = false, title, className }: WarningTriangleProps) {
  const reduce = usePrefersReducedMotion();
  const px = typeof size === "number" ? size : SIZE_PX[size];
  const g = resolveGlyph(glyph ?? null, tone);
  const box: CSSProperties = { width: px, height: px };

  const svg = (
    <svg
      viewBox="0 0 24 24"
      width={px}
      height={px}
      className="relative block shrink-0 overflow-visible"
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      data-glyph={g}
    >
      <path d={OUTER} fill={AMBER} stroke={INK} strokeWidth="1.4" strokeLinejoin="miter" />
      <path d="M12 4.6 L20.6 19.9 L3.4 19.9 Z" fill="none" stroke={INK} strokeWidth="0.9" strokeLinejoin="miter" />
      <Glyph glyph={g} />
    </svg>
  );

  if (!pulse) {
    return (
      <span className={cn("inline-flex shrink-0", className)} style={box}>
        {svg}
      </span>
    );
  }

  return (
    <span className={cn("relative inline-flex shrink-0 items-center justify-center", className)} style={box} data-pulse={reduce ? "static" : "on"}>
      {reduce ? (
        <svg viewBox="0 0 24 24" aria-hidden className="pointer-events-none absolute inset-0 overflow-visible" style={{ transform: "scale(1.45)", transformOrigin: "50% 62%" }}>
          <path d={OUTER} fill="none" stroke={AMBER} strokeOpacity={0.45} strokeWidth={0.8} strokeLinejoin="miter" />
        </svg>
      ) : (
        [0, 1, 2].map((i) => (
          <motion.svg
            key={i}
            viewBox="0 0 24 24"
            aria-hidden
            className="pointer-events-none absolute inset-0 overflow-visible"
            style={{ transformOrigin: "50% 62%" }}
            initial={{ scale: 1, opacity: 0 }}
            animate={{ scale: [1, 2.3], opacity: [0.85, 0] }}
            transition={{ duration: 1.8, ease: "easeOut", repeat: Infinity, delay: i * 0.6 }}
          >
            <path d={OUTER} fill="none" stroke={AMBER} strokeWidth={i === 0 ? 1.2 : 0.8} strokeLinejoin="miter" vectorEffect="non-scaling-stroke" />
          </motion.svg>
        ))
      )}
      {svg}
    </span>
  );
}
