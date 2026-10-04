"use client";

import { useEffect, useRef } from "react";

import { timecode } from "@/lib/format";
import { dateStamp, timeOfDay } from "@/lib/wall";
import { cn } from "@/lib/utils";

import { useNow } from "./use-now";

/* The CCTV tile's HUD chrome: corner brackets, date stamp, live feed telemetry, reticle. */

/** Thin CCTV corner brackets, inset from the picture edge. */
export function Brackets({ className }: { className?: string }) {
  const base = "absolute size-3.5 border-fg/70";
  return (
    <span aria-hidden className={cn("pointer-events-none absolute inset-2", className)}>
      <span className={cn(base, "top-0 left-0 border-t border-l")} />
      <span className={cn(base, "top-0 right-0 border-t border-r")} />
      <span className={cn(base, "bottom-0 left-0 border-b border-l")} />
      <span className={cn(base, "right-0 bottom-0 border-r border-b")} />
    </span>
  );
}

/** The running CCTV date/time stamp. */
export function Stamp() {
  const now = useNow(1000);
  return (
    <span className="tabular-nums" data-testid="tile-clock">
      {now ? `${dateStamp(now)} ${timeOfDay(now)}` : "––––-––-–– ––:––:––"}
    </span>
  );
}

/**
 * Live feed telemetry read straight off the playing video: media timecode, frame number (from the
 * clip's own frame rate) and the decoded resolution. Written to the DOM once per animation frame
 * without React state, so four tiles do not re-render sixty times a second.
 */
export function FeedTelemetry({ video, fps }: { video: HTMLVideoElement | null; fps: number | null }) {
  const tc = useRef<HTMLSpanElement>(null);
  const fr = useRef<HTMLSpanElement>(null);
  const res = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    let raf = 0;
    const write = (el: HTMLSpanElement | null, text: string) => {
      if (el && el.textContent !== text) el.textContent = text;
    };
    const tick = () => {
      const v = video;
      if (v) {
        write(tc.current, `T ${timecode(v.currentTime)}`);
        write(fr.current, fps ? `F${String(Math.floor(v.currentTime * fps)).padStart(6, "0")} · ${Math.round(fps)} FPS` : "F ------");
        write(res.current, v.videoWidth ? `${v.videoWidth}×${v.videoHeight}` : "–––×–––");
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [video, fps]);
  return (
    <div className="micro pointer-events-none absolute right-4 bottom-2.5 left-4 flex items-end justify-between gap-2">
      <span className="flex flex-col gap-0.5">
        <span ref={tc} className="w-fit bg-black/70 px-1 text-[11px] tracking-[0.12em] text-fg tabular-nums">
          T --:--.--
        </span>
        <span ref={fr} className="w-fit bg-black/70 px-1 text-fg/75 tabular-nums">
          F ------
        </span>
      </span>
      <span ref={res} className="bg-black/70 px-1 text-fg/75 tabular-nums">
        –––×–––
      </span>
    </div>
  );
}

/** Targeting reticle shown while a camera is being analyzed. */
export function Reticle() {
  return (
    <span aria-hidden className="pointer-events-none absolute top-1/2 left-1/2 size-14 -translate-x-1/2 -translate-y-1/2">
      <span className="absolute inset-3 border border-fg/45" />
      <span className="absolute top-1/2 left-0 h-px w-3 bg-fg/60" />
      <span className="absolute top-1/2 right-0 h-px w-3 bg-fg/60" />
      <span className="absolute top-0 left-1/2 h-3 w-px bg-fg/60" />
      <span className="absolute bottom-0 left-1/2 h-3 w-px bg-fg/60" />
      <span className="blink absolute top-1/2 left-1/2 size-1 -translate-x-1/2 -translate-y-1/2 bg-fg" />
    </span>
  );
}
