"use client";

/*
 * DetectionPopoutStack: the attention-grabbing moment when a hazard / blind spot is detected.
 * A fixed top-centre stack (newest first) that never blocks the rest of the page: the stack's
 * container ignores pointer events; only the cards take them.
 *
 * Stack enter/exit/layout is adapted from Magic UI "Animated List" (MIT, (c) Magic UI), listed on
 * 21st.dev as https://21st.dev/r/magicui/animated-list (source: https://magicui.design/r/animated-list.json,
 * since the 21st.dev registry requires authentication): spring scale-in, AnimatePresence, layout.
 * The card edge uses components/ui/border-beam.tsx (Magic UI Border Beam via 21st.dev).
 *
 * Every visible string comes from props. Reduced motion: no slide/scale, no flash, no beam, no pulse.
 */

import Link from "next/link";
import { useEffect, useRef, useState, type FocusEvent, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";

import { WarningTriangle, type AlertTone } from "@/components/alerts/warning-triangle";
import { HazardPin, type HazardPinItem } from "@/components/hazards/hazard-pin";
import { BorderBeam } from "@/components/ui/border-beam";
import { usePrefersReducedMotion } from "@/components/alerts/use-reduced-motion";
import { cn } from "@/lib/utils";

export interface DetectionPopoutItem {
  /** Stable id (e.g. job id + card id); used as the React key and passed to callbacks. */
  id: string;
  /** e.g. "HAZARD DETECTED" or "BLIND SPOT FOUND". */
  kicker: string;
  /** Sign label, e.g. "BLOCKED AISLE". */
  label: string;
  /** e.g. "CAM 2". */
  cameraLabel?: string;
  /** e.g. "Zone 3". */
  zoneName?: string;
  /** One plain sentence for the worker. */
  detail?: string;
  /** Micro telemetry, e.g. "13:52:04" or "T+00:12.4". */
  timestamp?: string;
  /** Extra micro telemetry chips, e.g. ["CONF 0.82", "F 000312"]. */
  meta?: string[];
  glyph?: string;
  tone?: AlertTone;
  /** Snapshot of the moment; pins are drawn over it. */
  imageUrl?: string;
  imageAlt?: string;
  /** Intrinsic snapshot size (needed for exact pin placement). */
  imageWidth?: number;
  imageHeight?: number;
  /** Where on the snapshot; defaults to nothing. */
  pins?: HazardPinItem[];
  /** "View": internal link (e.g. /hazards?clip=..&job=..) or a callback. */
  viewHref?: string;
  /** "Open reasoning": opens in a new tab (target=_blank rel=noopener) or a callback. */
  reasoningHref?: string;
}

export interface DetectionPopoutStackProps {
  /** Newest first. */
  items: DetectionPopoutItem[];
  /** Called when a card times out or is dismissed; remove it from `items`. */
  onCollapse: (id: string) => void;
  onView?: (item: DetectionPopoutItem) => void;
  onOpenReasoning?: (item: DetectionPopoutItem) => void;
  /** Auto-collapse after this many ms (paused on hover/focus). 0 disables. Default 7000. */
  autoCollapseMs?: number;
  /** Cards beyond this are not rendered. Default 3. */
  maxVisible?: number;
  /** Button labels (chrome); pass localised text if needed. */
  viewLabel?: string;
  reasoningLabel?: string;
  dismissLabel?: string;
  /** Full-screen amber edge flash when a new card arrives. Default true. */
  screenFlash?: boolean;
  className?: string;
}

const STRIPES = "repeating-linear-gradient(-45deg, #050505 0 7px, var(--warning, #ffb340) 7px 14px)";

export function DetectionPopoutStack({
  items,
  onCollapse,
  onView,
  onOpenReasoning,
  autoCollapseMs = 7000,
  maxVisible = 3,
  viewLabel = "View",
  reasoningLabel = "Open reasoning",
  dismissLabel = "Dismiss",
  screenFlash = true,
  className,
}: DetectionPopoutStackProps) {
  const reduce = usePrefersReducedMotion();
  const visible = items.slice(0, Math.max(1, maxVisible));
  const newest = visible[0]?.id;

  return (
    <>
      {screenFlash && !reduce && newest ? (
        <motion.div
          key={`flash-${newest}`}
          aria-hidden
          className="pointer-events-none fixed inset-0 z-[90]"
          style={{ boxShadow: "inset 0 0 0 4px var(--warning, #ffb340), inset 0 0 160px rgba(255,179,64,0.45)" }}
          initial={{ opacity: 1 }}
          animate={{ opacity: [1, 0.2, 0.8, 0] }}
          transition={{ duration: 1.3, times: [0, 0.3, 0.5, 1], ease: "easeOut" }}
        />
      ) : null}
      <div
        className={cn(
          "pointer-events-none fixed top-3 left-1/2 z-[100] flex w-[min(600px,calc(100vw-32px))] -translate-x-1/2 flex-col gap-2",
          className,
        )}
        data-testid="detection-popout-stack"
      >
        <AnimatePresence initial={true}>
          {visible.map((item, i) => (
            <motion.div
              key={item.id}
              layout={!reduce}
              initial={reduce ? { opacity: 0 } : { opacity: 0, y: -40, scale: 0.86 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.9, y: -16, transition: { duration: 0.2 } }}
              transition={{ type: "spring", stiffness: 380, damping: 30 }}
              style={{ originY: 0 }}
              className="pointer-events-auto w-full"
            >
              <DetectionPopout
                item={item}
                compact={i > 0}
                autoCollapseMs={autoCollapseMs}
                onCollapse={() => onCollapse(item.id)}
                onView={onView}
                onOpenReasoning={onOpenReasoning}
                viewLabel={viewLabel}
                reasoningLabel={reasoningLabel}
                dismissLabel={dismissLabel}
              />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </>
  );
}

export interface DetectionPopoutProps {
  item: DetectionPopoutItem;
  /** Older cards in a stack: header + actions only. */
  compact?: boolean;
  autoCollapseMs?: number;
  onCollapse?: () => void;
  onView?: (item: DetectionPopoutItem) => void;
  onOpenReasoning?: (item: DetectionPopoutItem) => void;
  viewLabel?: string;
  reasoningLabel?: string;
  dismissLabel?: string;
}

const ACTION =
  "inline-flex h-9 items-center gap-2 border px-3.5 text-[12px] font-bold tracking-[0.14em] uppercase transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-warning";

export function DetectionPopout({
  item,
  compact = false,
  autoCollapseMs = 7000,
  onCollapse,
  onView,
  onOpenReasoning,
  viewLabel = "View",
  reasoningLabel = "Open reasoning",
  dismissLabel = "Dismiss",
}: DetectionPopoutProps) {
  const reduce = usePrefersReducedMotion();
  const [paused, setPaused] = useState(false);
  const [remaining, setRemaining] = useState(autoCollapseMs);
  const remainingRef = useRef(autoCollapseMs);
  const startedRef = useRef(0);
  const collapseRef = useRef(onCollapse);

  useEffect(() => {
    collapseRef.current = onCollapse;
  });

  useEffect(() => {
    if (paused || !(autoCollapseMs > 0)) return;
    startedRef.current = performance.now();
    const t = window.setTimeout(() => collapseRef.current?.(), remainingRef.current);
    return () => {
      window.clearTimeout(t);
      remainingRef.current = Math.max(0, remainingRef.current - (performance.now() - startedRef.current));
    };
  }, [paused, autoCollapseMs]);

  const pause = () => {
    if (paused) return;
    setRemaining(Math.max(0, remainingRef.current - (performance.now() - startedRef.current)));
    setPaused(true);
  };
  const resume = () => setPaused(false);
  const onBlur = (e: FocusEvent<HTMLDivElement>) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) resume();
  };

  const tone = item.tone ?? "hazard";
  const where = [item.cameraLabel, item.zoneName].filter(Boolean).join(" · ");
  const hasImage = !compact && !!item.imageUrl;
  const iw = item.imageWidth ?? 16;
  const ih = item.imageHeight ?? 9;

  const view = item.viewHref ? (
    <Link href={item.viewHref} onClick={() => onView?.(item)} className={cn(ACTION, "border-warning bg-warning text-[#050505] hover:bg-[#ffc56a]")} data-testid="popout-view">
      {viewLabel} <span aria-hidden>→</span>
    </Link>
  ) : onView ? (
    <button type="button" onClick={() => onView(item)} className={cn(ACTION, "border-warning bg-warning text-[#050505] hover:bg-[#ffc56a]")} data-testid="popout-view">
      {viewLabel} <span aria-hidden>→</span>
    </button>
  ) : null;

  const reasoning = item.reasoningHref ? (
    <a
      href={item.reasoningHref}
      target="_blank"
      rel="noopener"
      onClick={() => onOpenReasoning?.(item)}
      className={cn(ACTION, "border-line-strong bg-transparent text-fg hover:border-fg")}
      data-testid="popout-reasoning"
    >
      {reasoningLabel} <span aria-hidden>↗</span>
    </a>
  ) : onOpenReasoning ? (
    <button type="button" onClick={() => onOpenReasoning(item)} className={cn(ACTION, "border-line-strong bg-transparent text-fg hover:border-fg")} data-testid="popout-reasoning">
      {reasoningLabel} <span aria-hidden>↗</span>
    </button>
  ) : null;

  return (
    <div
      role="alert"
      aria-live="assertive"
      onMouseEnter={pause}
      onMouseLeave={resume}
      onFocus={pause}
      onBlur={onBlur}
      className="relative overflow-hidden border border-warning bg-[#090909]/95 text-fg shadow-[0_0_0_1px_#050505,0_0_40px_rgba(255,179,64,0.35),0_24px_60px_rgba(0,0,0,0.75)] backdrop-blur-md"
      data-testid="detection-popout"
      data-tone={tone}
      data-paused={paused ? "true" : "false"}
    >
      {!reduce ? (
        <motion.div aria-hidden className="pointer-events-none absolute inset-0 z-10 bg-warning" initial={{ opacity: 0.7 }} animate={{ opacity: 0 }} transition={{ duration: 0.55, ease: "easeOut" }} />
      ) : null}
      <BorderBeam size={160} duration={3} borderWidth={2} />

      {/* kicker band */}
      <div className="flex h-7 items-stretch bg-warning text-[#050505]">
        <div className="flex min-w-0 items-center gap-2 px-2.5 text-[11px] leading-none font-bold tracking-[0.22em] uppercase">
          <span className="truncate">{item.kicker}</span>
        </div>
        <div className="min-w-6 flex-1" style={{ background: STRIPES }} aria-hidden />
        {item.timestamp ? (
          <div className="flex items-center px-2 text-[10px] leading-none font-bold tracking-[0.1em] tabular-nums">{item.timestamp}</div>
        ) : null}
        {onCollapse ? (
          <button
            type="button"
            onClick={onCollapse}
            aria-label={dismissLabel}
            className="flex w-8 items-center justify-center border-l border-[#050505]/40 text-[16px] leading-none font-bold hover:bg-[#050505] hover:text-warning focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[#050505]"
            data-testid="popout-dismiss"
          >
            ×
          </button>
        ) : null}
      </div>

      <div className={cn("flex items-center gap-4 px-4", compact ? "py-2.5" : "py-4")}>
        <div className={cn("flex shrink-0 items-center justify-center", compact ? "size-10" : "size-[92px]")}>
          <WarningTriangle glyph={item.glyph} tone={tone} size={compact ? 34 : 72} pulse={!compact} />
        </div>
        <div className="min-w-0 flex-1">
          <div className={cn("leading-[1.05] font-bold tracking-[0.04em] break-words text-warning uppercase", compact ? "text-[18px]" : "text-[26px] sm:text-[32px]")} data-testid="popout-label">
            {item.label}
          </div>
          {where ? (
            <div className={cn("mt-1.5 font-semibold tracking-[0.16em] text-fg uppercase", compact ? "text-[11px]" : "text-[13px]")} data-testid="popout-where">
              {where}
            </div>
          ) : null}
          {!compact && item.detail ? <p className="mt-2 text-[13px] leading-snug text-fg/80">{item.detail}</p> : null}
        </div>
        {compact ? <div className="flex shrink-0 gap-2">{view}</div> : null}
      </div>

      {hasImage ? (
        <div className="relative mx-4 h-[170px] border border-line-strong bg-[#050505] sm:h-[220px]" data-testid="popout-snapshot">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={item.imageUrl} alt={item.imageAlt ?? ""} className="absolute inset-0 h-full w-full object-contain" draggable={false} />
          {item.pins?.length ? <HazardPin items={item.pins} mediaWidth={iw} mediaHeight={ih} /> : null}
          <Corner className="top-0 left-0 border-t border-l" />
          <Corner className="top-0 right-0 border-t border-r" />
          <Corner className="bottom-0 left-0 border-b border-l" />
          <Corner className="right-0 bottom-0 border-r border-b" />
        </div>
      ) : null}

      {!compact ? (
        <div className="flex flex-wrap items-center gap-2 px-4 pt-3 pb-4">
          {view}
          {reasoning}
          {item.meta?.length ? (
            <div className="ml-auto flex flex-wrap justify-end gap-x-3 gap-y-1 text-[9px] leading-[12px] tracking-[0.14em] text-muted uppercase tabular-nums">
              {item.meta.map((m, k) => (
                <span key={k}>{m}</span>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {autoCollapseMs > 0 && onCollapse ? (
        <div className="absolute right-0 bottom-0 left-0 h-[3px] bg-warning/15" aria-hidden>
          <motion.div
            className="h-full bg-warning"
            initial={{ width: "100%" }}
            animate={paused ? { width: `${(remaining / autoCollapseMs) * 100}%` } : { width: "0%" }}
            transition={paused ? { duration: 0 } : { duration: remaining / 1000, ease: "linear" }}
          />
        </div>
      ) : null}
    </div>
  );
}

function Corner({ className }: { className: string }): ReactNode {
  return <span aria-hidden className={cn("pointer-events-none absolute size-3 border-warning", className)} />;
}
