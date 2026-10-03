"use client";

import { useMemo } from "react";

import { clock, priorityKey, type HazardImage, type WorkerHazard } from "@/lib/hazards";
import { cn } from "@/lib/utils";

export interface HazardTimelineProps {
  duration: number;
  /** Hazards in display order; row labels are their 1-based position. */
  hazards: readonly WorkerHazard[];
  /** The pictures sent to the AI. */
  images: readonly HazardImage[];
  currentT: number;
  activeHazardId: string | null;
  onSeek: (t: number, hazardId: string | null) => void;
}

export const PRIORITY_TONE: Record<"high" | "medium" | "low", { band: string; bandActive: string; badge: string; edge: string; text: string }> = {
  high: {
    band: "border-danger/80 bg-danger/25",
    bandActive: "border-danger bg-danger/60",
    badge: "border-danger text-danger",
    edge: "bg-danger",
    text: "text-danger",
  },
  medium: {
    band: "border-warning/80 bg-warning/20",
    bandActive: "border-warning bg-warning/55",
    badge: "border-warning text-warning",
    edge: "bg-warning",
    text: "text-warning",
  },
  low: {
    band: "border-fg/60 bg-fg/15",
    bandActive: "border-fg bg-fg/45",
    badge: "border-fg/70 text-fg",
    edge: "bg-fg/50",
    text: "text-fg",
  },
};

/** Pictures closer than this share one mark (as a fraction of the clip). */
const MERGE_FRACTION = 0.015;

interface PictureGroup {
  t: number;
  count: number;
  kinds: string[];
}

function groupPictures(images: readonly HazardImage[], duration: number): PictureGroup[] {
  const sorted = [...images].sort((a, b) => a.time_s - b.time_s);
  const groups: PictureGroup[] = [];
  for (const im of sorted) {
    const last = groups[groups.length - 1];
    if (last && im.time_s - last.t <= duration * MERGE_FRACTION) {
      last.count += 1;
      if (!last.kinds.includes(im.kind_label)) last.kinds.push(im.kind_label);
    } else {
      groups.push({ t: im.time_s, count: 1, kinds: [im.kind_label] });
    }
  }
  return groups;
}

function tickStep(duration: number): number {
  if (duration <= 8) return 1;
  if (duration <= 20) return 2;
  if (duration <= 60) return 5;
  if (duration <= 180) return 15;
  return 30;
}

const LABEL = "flex min-w-0 items-center gap-1.5 pr-1 text-[12px] text-fg/80";

/**
 * The clip as a strip: one row per hazard (the span of its pictures), one row of marks for the
 * pictures sent to the AI, and a playhead. Every mark is a button that seeks the video.
 */
export function HazardTimeline({ duration, hazards, images, currentT, activeHazardId, onSeek }: HazardTimelineProps) {
  const d = Math.max(duration, 0.001);
  const frac = (t: number) => Math.min(Math.max(t / d, 0), 1);
  const pct = (t: number) => `${frac(t) * 100}%`;
  const groups = useMemo(() => groupPictures(images, d), [images, d]);
  const step = tickStep(d);
  const ticks = Array.from({ length: Math.floor(d / step + 1e-6) + 1 }, (_, i) => i * step);

  return (
    <div
      role="group"
      aria-label="Clip timeline"
      className="grid grid-cols-[5rem_minmax(0,1fr)] select-none sm:grid-cols-[6rem_minmax(0,1fr)]"
      data-testid="hazard-timeline"
    >
      {/* labels */}
      <div className="flex flex-col">
        <span className="micro flex h-6 items-end pb-1">Time</span>
        {hazards.map((h, i) => (
          <span key={h.id} className={cn(LABEL, "h-9 border-b border-line")}>
            <span
              aria-hidden
              className={cn(
                "inline-flex size-5 shrink-0 items-center justify-center border text-[11px] font-bold",
                PRIORITY_TONE[priorityKey(h.priority)].badge,
              )}
            >
              {i + 1}
            </span>
            Hazard
          </span>
        ))}
        <span className={cn(LABEL, "h-10")}>Pictures</span>
      </div>

      {/* tracks */}
      <div className="relative mx-2.5 flex min-w-0 flex-col">
        <div className="relative h-6 border-b border-line-strong" aria-hidden>
          {ticks.map((t, i) => (
            <span
              key={t}
              className={cn(
                "absolute bottom-0 flex flex-col items-center",
                frac(t) === 0 ? "items-start" : frac(t) === 1 ? "-translate-x-full items-end" : "-translate-x-1/2",
              )}
              style={{ left: pct(t) }}
            >
              {/* every other label on a phone, so they never touch */}
              <span className={cn("text-[10px] leading-3 text-fg/55 tabular-nums", i % 2 === 1 && "invisible sm:visible")}>{clock(t)}</span>
              <span className="mt-1 h-1.5 w-px bg-line-strong" />
            </span>
          ))}
        </div>

        {hazards.map((h, i) => {
          const tone = PRIORITY_TONE[priorityKey(h.priority)];
          const active = activeHazardId === h.id;
          const start = Math.min(h.start_s, h.end_s);
          const end = Math.max(h.start_s, h.end_s);
          return (
            <div key={h.id} className="relative flex h-9 items-center border-b border-line">
              <span aria-hidden className="dot-field absolute inset-x-0 inset-y-2" />
              <button
                type="button"
                aria-label={`Hazard ${i + 1}: ${h.title}, seen ${clock(start)} to ${clock(end)}. Go to this moment in the video`}
                aria-pressed={active}
                onClick={() => onSeek(start, h.id)}
                className={cn("absolute h-5 border transition-colors hover:bg-fg/35", active ? tone.bandActive : tone.band)}
                style={{ left: pct(start), width: `max(0.5rem, ${(frac(end) - frac(start)) * 100}%)` }}
              />
            </div>
          );
        })}

        <div className="relative h-10">
          <span aria-hidden className="absolute inset-x-0 top-1/2 h-px bg-line" />
          {groups.map((g) => (
            <button
              key={g.t}
              type="button"
              aria-label={`${g.count} picture${g.count === 1 ? "" : "s"} sent to the AI at ${clock(g.t)}. Go to this moment in the video`}
              title={`${g.count} × ${g.kinds.join(", ")} · ${clock(g.t)}`}
              onClick={() => onSeek(g.t, null)}
              className="group absolute top-1/2 flex h-9 w-4 -translate-x-1/2 -translate-y-1/2 items-end justify-center pb-1"
              style={{ left: pct(g.t) }}
            >
              <span
                aria-hidden
                className="block w-[3px] bg-fg/70 transition-colors group-hover:bg-fg"
                style={{ height: `${Math.min(8 + g.count * 2, 24)}px` }}
              />
            </button>
          ))}
        </div>

        {/* playhead */}
        <span aria-hidden className="pointer-events-none absolute top-6 bottom-0 w-px bg-fg/90" style={{ left: pct(currentT) }} />
        <span
          aria-hidden
          className="pointer-events-none absolute top-[1.3rem] size-[7px] -translate-x-[3px] bg-fg"
          style={{ left: pct(currentT) }}
        />
      </div>
    </div>
  );
}
