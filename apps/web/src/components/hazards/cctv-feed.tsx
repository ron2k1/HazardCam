"use client";

import { useRef, useState } from "react";

import { StatusDot } from "@/components/hud/barcode";
import { CornerTicks } from "@/components/hud/panel";
import { cn } from "@/lib/utils";

import type { ZoneBox } from "./derive";
import { useClock } from "./hazards-header";
import { useContainRect, ZoneOverlay } from "./zone-overlay";

export interface CctvFeedProps {
  /** Raw camera footage (source.mp4), already resolved to a full URL. */
  src: string | null;
  /** "CAM 01" */
  cam: string;
  title: string;
  /** "Watching" | "Checking" | "Hazard found" ... */
  state: string;
  stateTone?: "fg" | "warning";
  /** Zone outlines (only after a check has finished). */
  zones?: readonly ZoneBox[];
  /** w/h of the footage, for the zone overlay. */
  aspect?: number | null;
  compact?: boolean;
  onFirstPlay?: () => void;
  onFailed?: () => void;
  className?: string;
}

/**
 * The live-looking camera feed: raw footage, autoplay muted loop, with a CCTV overlay (camera,
 * a watching dot, a running clock, corner brackets). No AI markings until a check has finished.
 */
export function CctvFeed({ src, cam, title, state, stateTone = "fg", zones, aspect, compact = false, onFirstPlay, onFailed, className }: CctvFeedProps) {
  const boxRef = useRef<HTMLDivElement>(null);
  const played = useRef(false);
  const [failed, setFailed] = useState(false);
  const now = useClock();
  const rect = useContainRect(boxRef, zones?.length ? (aspect ?? 16 / 9) : null);

  return (
    <figure
      className={cn("relative m-0 min-w-0 overflow-hidden border border-line-strong bg-black", className)}
      data-testid="cctv-feed"
      aria-label={`${cam}, ${title}: live camera view`}
    >
      <div ref={boxRef} className="absolute inset-0">
        {src && !failed ? (
          <video
            key={src}
            src={src}
            className="absolute inset-0 h-full w-full object-contain"
            autoPlay
            muted
            loop
            playsInline
            preload="auto"
            onPlaying={() => {
              if (played.current) return;
              played.current = true;
              onFirstPlay?.();
            }}
            onError={() => {
              setFailed(true);
              onFailed?.();
            }}
            data-testid="cctv-video"
          />
        ) : (
          <div className="dot-field absolute inset-0 flex items-center justify-center text-[13px] tracking-[0.14em] text-fg/60 uppercase">
            No signal
          </div>
        )}
        {zones?.length ? <ZoneOverlay zones={zones} rect={rect} compact={compact} /> : null}
      </div>

      {/* CCTV overlay */}
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <CornerTicks size={compact ? 10 : 18} className={compact ? "m-1.5" : "m-3"} />
        <div className={cn("absolute flex items-center gap-2 bg-black/55 px-1.5 py-0.5", compact ? "top-2 left-2" : "top-4 left-4")}>
          <span className={cn("font-bold tracking-[0.14em] text-fg", compact ? "text-[10px]" : "text-[13px]")}>{cam}</span>
          {!compact ? <span className="max-w-[24ch] truncate text-[12px] text-fg/80">{title}</span> : null}
        </div>
        <div className={cn("absolute flex items-center gap-1.5 bg-black/55 px-1.5 py-0.5", compact ? "top-2 right-2" : "top-4 right-4")}>
          <span className={cn("tabular-nums text-fg/90", compact ? "text-[10px]" : "text-[12px]")} suppressHydrationWarning>
            {now ? now.toLocaleString([], { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : ""}
          </span>
        </div>
        <div className={cn("absolute flex items-center gap-1.5 bg-black/55 px-1.5 py-0.5", compact ? "bottom-2 left-2" : "bottom-4 left-4")}>
          <StatusDot tone={stateTone === "warning" ? "fg" : "fg"} pulse className={cn(stateTone === "warning" && "bg-warning", compact ? "size-1.5" : "size-2")} />
          <span className={cn("tracking-[0.14em] uppercase", stateTone === "warning" ? "text-warning" : "text-fg", compact ? "text-[10px]" : "text-[12px]")} data-testid="cctv-state">
            {state}
          </span>
        </div>
      </div>
    </figure>
  );
}
