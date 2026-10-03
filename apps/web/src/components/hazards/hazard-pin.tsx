"use client";

/*
 * HazardPin: warning labels that show exactly WHERE on a video or still a hazard / blind spot is.
 *
 * Drop it inside the media's positioned container (it is `absolute inset-0`). Boxes are normalised
 * 0-1 against the intrinsic media size; mediaWidth/mediaHeight let it undo object-fit letterboxing.
 * A ResizeObserver keeps boxes and label chips aligned on resize. Every label comes from props.
 * Reduced motion: no marching ants or beacon pulse; solid amber outline and a static ring instead.
 */

import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";

import { WarningTriangle, type AlertTone } from "@/components/alerts/warning-triangle";
import { usePrefersReducedMotion } from "@/components/alerts/use-reduced-motion";
import { cn } from "@/lib/utils";

export interface HazardPinItem {
  /** [x0, y0, x1, y1], normalised 0-1 against the intrinsic media size. */
  box: [number, number, number, number];
  /** Short sign label, e.g. "BLOCKED AISLE". */
  label: string;
  /** Zone name, e.g. "Zone 3"; shown after the label. */
  zoneName?: string;
  /** warning | eye-off | forklift; defaults by tone. */
  glyph?: string;
  tone?: AlertTone;
}

export interface HazardPinProps {
  items: HazardPinItem[];
  /** Intrinsic media size (video.videoWidth / img.naturalWidth), for object-fit maths. */
  mediaWidth: number;
  mediaHeight: number;
  /** Highlight one item; the others are dimmed. Omit to show all at full strength. */
  activeIndex?: number | null;
  /** How the media is fitted in its container. Default "contain". */
  fit?: "contain" | "cover" | "fill";
  /** Show micro X/Y telemetry under each box. Default true. */
  showCoords?: boolean;
  className?: string;
}

type Size = { w: number; h: number };
type Rect = { x: number; y: number; w: number; h: number };

const AMBER = "var(--warning, #ffb340)";
const M = 4; // chip margin from the container edge
const GAP = 16; // box to chip distance

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), Math.max(lo, hi));
const clamp01 = (v: number) => clamp(Number.isFinite(v) ? v : 0, 0, 1);

/** Where the media's pixels actually land inside a W x H container. */
export function mediaContentRect(W: number, H: number, mw: number, mh: number, fit: HazardPinProps["fit"] = "contain"): Rect {
  if (fit === "fill" || !(mw > 0) || !(mh > 0) || !(W > 0) || !(H > 0)) return { x: 0, y: 0, w: W, h: H };
  const s = fit === "cover" ? Math.max(W / mw, H / mh) : Math.min(W / mw, H / mh);
  const w = mw * s;
  const h = mh * s;
  return { x: (W - w) / 2, y: (H - h) / 2, w, h };
}

function chipText(item: HazardPinItem) {
  const label = (item.label ?? "").trim().toUpperCase();
  const zone = (item.zoneName ?? "").trim().toUpperCase();
  return zone ? `${label} · ${zone}` : label;
}

const overlaps = (a: Rect, b: Rect) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

interface Placed {
  box: Rect;
  cx: number;
  cy: number;
  chip: Rect;
  anchor: { x: number; y: number } | null;
}

function layout(items: HazardPinItem[], size: Size, chips: Record<number, Size>, mw: number, mh: number, fit: HazardPinProps["fit"]): Placed[] {
  const { w: W, h: H } = size;
  const r = mediaContentRect(W, H, mw, mh, fit);
  const placed: Placed[] = [];
  items.forEach((item, i) => {
    const [a, b, c, d] = item.box;
    const x0 = r.x + clamp01(Math.min(a, c)) * r.w;
    const x1 = r.x + clamp01(Math.max(a, c)) * r.w;
    const y0 = r.y + clamp01(Math.min(b, d)) * r.h;
    const y1 = r.y + clamp01(Math.max(b, d)) * r.h;
    const box = { x: x0, y: y0, w: Math.max(2, x1 - x0), h: Math.max(2, y1 - y0) };
    const cx = box.x + box.w / 2;
    const cy = box.y + box.h / 2;
    const est = chips[i] ?? { w: Math.min(W - 2 * M, 44 + chipText(item).length * 7.4), h: 26 };
    const cw = Math.min(est.w, Math.max(0, W - 2 * M));
    const ch = est.h;
    const x = clamp(box.x, M, W - cw - M);
    const above = { x, y: box.y - GAP - ch, w: cw, h: ch };
    const below = { x, y: box.y + box.h + GAP, w: cw, h: ch };
    const fitsAbove = above.y >= M;
    const fitsBelow = below.y + ch <= H - M;
    const taken = placed.map((p) => p.chip);
    const free = (rc: Rect) => !taken.some((t) => overlaps(t, rc));
    let chip: Rect;
    let side: "above" | "below" | "inside";
    if (fitsAbove && free(above)) [chip, side] = [above, "above"];
    else if (fitsBelow && free(below)) [chip, side] = [below, "below"];
    else if (fitsAbove) [chip, side] = [above, "above"];
    else if (fitsBelow) [chip, side] = [below, "below"];
    else [chip, side] = [{ x, y: clamp(box.y + 6, M, H - ch - M), w: cw, h: ch }, "inside"];
    // nudge away from earlier chips, staying inside the container
    for (let k = 0; k < 4 && !free(chip); k++) {
      const ny = side === "above" ? chip.y - ch - 4 : chip.y + ch + 4;
      if (ny < M || ny + ch > H - M) break;
      chip = { ...chip, y: ny };
    }
    const anchorX = clamp(cx, chip.x + 10, chip.x + chip.w - 10);
    const anchor = side === "inside" ? null : { x: anchorX, y: side === "above" ? chip.y + chip.h : chip.y };
    placed.push({ box, cx, cy, chip, anchor });
  });
  return placed;
}

export function HazardPin({ items, mediaWidth, mediaHeight, activeIndex = null, fit = "contain", showCoords = true, className }: HazardPinProps) {
  const reduce = usePrefersReducedMotion();
  const rootRef = useRef<HTMLDivElement>(null);
  const chipEls = useRef<(HTMLDivElement | null)[]>([]);
  const [size, setSize] = useState<Size>({ w: 0, h: 0 });
  const [chips, setChips] = useState<Record<number, Size>>({});

  useEffect(() => {
    const root = rootRef.current;
    if (!root || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      // layout size, not getBoundingClientRect: a parent scale animation must not skew the maths
      const w = root.clientWidth;
      const h = root.clientHeight;
      setSize((s) => (s.w === w && s.h === h ? s : { w, h }));
      const next: Record<number, Size> = {};
      chipEls.current.forEach((el, i) => {
        if (el) next[i] = { w: el.offsetWidth, h: el.offsetHeight };
      });
      setChips((prev) => {
        const same = Object.keys(next).length === Object.keys(prev).length && Object.entries(next).every(([k, v]) => prev[+k]?.w === v.w && prev[+k]?.h === v.h);
        return same ? prev : next;
      });
    });
    ro.observe(root);
    chipEls.current.forEach((el) => el && ro.observe(el));
    return () => ro.disconnect();
  }, [items.length]);

  const ready = size.w > 0 && size.h > 0;
  const placed = ready ? layout(items, size, chips, mediaWidth, mediaHeight, fit) : [];
  const hasActive = activeIndex !== null && activeIndex !== undefined && activeIndex >= 0 && activeIndex < items.length;

  return (
    <div
      ref={rootRef}
      className={cn("pointer-events-none absolute inset-0 z-10 overflow-hidden select-none", className)}
      role="group"
      aria-label={items.map(chipText).join("; ")}
      data-testid="hazard-pin"
    >
      {ready ? (
        <svg className="absolute inset-0 h-full w-full overflow-visible" width={size.w} height={size.h} aria-hidden>
          <defs>
            <pattern id="hp-hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="8" height="8" fill="rgba(255,179,64,0.06)" />
              <rect width="2.5" height="8" fill="rgba(255,179,64,0.28)" />
            </pattern>
          </defs>
          {placed.map((p, i) => {
            const item = items[i];
            const on = !hasActive || activeIndex === i;
            const blind = item.tone === "blindspot";
            const L = Math.max(6, Math.min(16, p.box.w / 3, p.box.h / 3));
            const { x, y, w, h } = p.box;
            const corners = `M${x} ${y + L} V${y} H${x + L} M${x + w - L} ${y} H${x + w} V${y + L} M${x + w} ${y + h - L} V${y + h} H${x + w - L} M${x + L} ${y + h} H${x} V${y + h - L}`;
            return (
              <g key={i} opacity={on ? 1 : 0.4} data-pin-index={i}>
                <rect x={x} y={y} width={w} height={h} fill={blind ? "url(#hp-hatch)" : "rgba(255,179,64,0.12)"} />
                <rect x={x} y={y} width={w} height={h} fill="none" stroke="#050505" strokeOpacity={0.85} strokeWidth={4} />
                {reduce ? (
                  <rect x={x} y={y} width={w} height={h} fill="none" stroke={AMBER} strokeWidth={2} />
                ) : (
                  <motion.rect
                    x={x}
                    y={y}
                    width={w}
                    height={h}
                    fill="none"
                    stroke={AMBER}
                    strokeWidth={2}
                    strokeDasharray={blind ? "3 5" : "9 6"}
                    initial={{ strokeDashoffset: 0 }}
                    animate={{ strokeDashoffset: blind ? -16 : -30 }}
                    transition={{ duration: 0.9, ease: "linear", repeat: Infinity }}
                  />
                )}
                <path d={corners} fill="none" stroke={AMBER} strokeWidth={on ? 4 : 3} strokeLinecap="square" />
                {p.anchor ? (
                  <>
                    <line x1={p.cx} y1={p.cy} x2={p.anchor.x} y2={p.anchor.y} stroke="#050505" strokeOpacity={0.8} strokeWidth={3.5} />
                    <line x1={p.cx} y1={p.cy} x2={p.anchor.x} y2={p.anchor.y} stroke={AMBER} strokeWidth={1.5} strokeDasharray={on ? undefined : "3 3"} />
                    <rect x={p.anchor.x - 3} y={p.anchor.y - 3} width={6} height={6} fill={AMBER} stroke="#050505" strokeWidth={1} />
                  </>
                ) : null}
                {/* beacon at the box centre */}
                {on && !reduce ? (
                  [0, 1].map((k) => (
                    <motion.circle
                      key={k}
                      cx={p.cx}
                      cy={p.cy}
                      fill="none"
                      stroke={AMBER}
                      strokeWidth={2}
                      initial={{ r: 5, opacity: 0.9 }}
                      animate={{ r: [5, 26], opacity: [0.9, 0] }}
                      transition={{ duration: 1.5, ease: "easeOut", repeat: Infinity, delay: k * 0.75 }}
                    />
                  ))
                ) : (
                  <circle cx={p.cx} cy={p.cy} r={11} fill="none" stroke={AMBER} strokeOpacity={0.6} strokeWidth={1.5} />
                )}
                <circle cx={p.cx} cy={p.cy} r={5} fill={AMBER} stroke="#050505" strokeWidth={1.5} />
                {showCoords && w >= 84 && y + h + 14 <= size.h ? (
                  <text
                    x={x}
                    y={y + h + 11}
                    fill="rgba(241,241,239,0.75)"
                    fontSize={9}
                    letterSpacing="0.08em"
                    style={{ fontFamily: "inherit", paintOrder: "stroke" }}
                    stroke="#050505"
                    strokeWidth={3}
                  >
                    {`X${item.box[0].toFixed(2)} Y${item.box[1].toFixed(2)} · ${(Math.abs(item.box[2] - item.box[0]) * 100).toFixed(0)}×${(Math.abs(item.box[3] - item.box[1]) * 100).toFixed(0)}%`}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
      ) : null}

      {items.map((item, i) => {
        const p = placed[i];
        const on = !hasActive || activeIndex === i;
        return (
          <div
            key={i}
            ref={(el) => {
              chipEls.current[i] = el;
            }}
            className={cn(
              "absolute top-0 left-0 flex h-[26px] items-center gap-1.5 overflow-hidden border pr-2 pl-1 text-[11px] leading-none font-bold tracking-[0.12em] whitespace-nowrap uppercase shadow-[0_0_0_1px_#050505,0_6px_18px_rgba(0,0,0,0.6)]",
              on ? "border-warning bg-warning text-[#050505]" : "border-warning/70 bg-[#050505]/90 text-warning",
            )}
            style={{
              transform: p ? `translate(${Math.round(p.chip.x)}px, ${Math.round(p.chip.y)}px)` : undefined,
              maxWidth: size.w > 0 ? size.w - 2 * M : undefined,
              visibility: p ? "visible" : "hidden",
            }}
            data-testid="hazard-pin-chip"
          >
            <WarningTriangle glyph={item.glyph} tone={item.tone} size="sm" />
            <span className="truncate">{chipText(item)}</span>
          </div>
        );
      })}
    </div>
  );
}
