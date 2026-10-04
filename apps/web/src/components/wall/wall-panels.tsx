"use client";

import { useEffect, useRef } from "react";

import { HazardText } from "@/components/alerts/hazard-terms";
import { Panel } from "@/components/hud/panel";
import type { WallCamera } from "@/lib/wall";
import { cn } from "@/lib/utils";

import type { LogRow, LogTag } from "./use-agent-log";
import { useNow } from "./use-now";
import type { TileRun } from "./use-wall-orchestrator";

/** "+00:04.2": seconds since the wall loaded. Whole tenths first, so 59.96 s is +01:00.0. */
function sinceLoad(at: number, origin: number | null): string {
  const tenths = Math.round(Math.max(0, (at - (origin ?? at)) / 100));
  const m = Math.floor(tenths / 600);
  return `+${String(m).padStart(2, "0")}:${((tenths % 600) / 10).toFixed(1).padStart(4, "0")}`;
}

const TAG_TONE: Record<LogTag, string> = {
  LEAD: "text-fg/55",
  START: "text-fg",
  STEP: "text-fg/55",
  AGENT: "text-fg/80",
  FOUND: "text-danger",
  CLEAR: "text-fg/70",
  FAULT: "text-danger",
};

/** 03: every check event the wall has seen, oldest first, pinned to the newest row. */
export function AgentLogPanel({
  rows,
  origin,
  emptyText,
  className,
}: {
  rows: LogRow[];
  origin: number | null;
  /** What the empty log says: waiting, or that the checks ran before this page load. */
  emptyText: string;
  className?: string;
}) {
  const scroller = useRef<HTMLOListElement>(null);
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [rows]);
  const found = rows.filter((r) => r.tag === "FOUND").length;

  return (
    <Panel
      index="03"
      title="Agent log"
      className={className}
      bodyClassName="flex flex-col"
      meta={
        <>
          <span className="tabular-nums">SEQ {String(rows.at(-1)?.seq ?? 0).padStart(4, "0")}</span>
          {found ? <span className="text-danger tabular-nums">{found} ALERT</span> : null}
        </>
      }
    >
      {rows.length ? (
        <ol ref={scroller} className="thin-scroll min-h-0 flex-1 overflow-y-auto py-1" aria-live="off" data-testid="agent-log">
          {rows.map((r) => (
            <li
              key={r.seq}
              className="grid grid-cols-[3.9rem_2.6rem_2.9rem_minmax(0,1fr)] items-baseline gap-x-1.5 px-2.5 py-[1.5px] text-[10px] leading-[14px] duration-300 animate-in fade-in"
              data-tag={r.tag}
            >
              <span className="text-muted tabular-nums">{sinceLoad(r.at, origin)}</span>
              <span className="text-fg/85">{r.cam ? `CAM ${r.cam}` : "SITE"}</span>
              <span className={cn("tracking-[0.12em]", TAG_TONE[r.tag])}>{r.tag}</span>
              <span className={cn("truncate", r.tag === "FOUND" ? "text-fg" : "text-fg/70")} title={r.text}>
                {r.tag === "FOUND" ? <HazardText text={r.text} /> : r.text}
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="hatch flex flex-1 items-center justify-center text-[10px] tracking-[0.16em] text-fg/50 uppercase">{emptyText}</p>
      )}
    </Panel>
  );
}

/** Time window the timeline starts with; it widens once checks run past it. */
const MIN_SPAN_S = 30;
/** Tick spacing: the smallest step that keeps the axis to about six labels (a live run is ~100 s). */
const TICK_STEPS_S = [5, 10, 15, 30, 60, 120, 300, 600];

/** 04: one lane per camera, a bar from each check's start to its result, against wall time. */
export function CheckTimelinePanel({
  cameras,
  runs,
  origin,
  className,
}: {
  cameras: WallCamera[];
  runs: Record<string, TileRun>;
  origin: number | null;
  className?: string;
}) {
  const running = cameras.some((c) => runs[c.clip_id]?.phase === "checking");
  const now = useNow(250, running || origin === null)?.getTime() ?? origin ?? 0;
  const ends = cameras.map((c) => runs[c.clip_id]?.finishedAt ?? (runs[c.clip_id]?.phase === "checking" ? now : 0));
  const lastS = origin ? Math.max(...ends, running ? now : 0, origin) / 1000 - origin / 1000 : 0;
  const wanted = Math.max(MIN_SPAN_S, lastS + 3);
  const step = TICK_STEPS_S.find((s) => wanted / s <= 6) ?? 1800;
  const span = Math.ceil(wanted / step) * step;
  const ticks = Array.from({ length: span / step + 1 }, (_, i) => i * step);
  const pct = (ms: number) => `${Math.min(100, Math.max(0, ((ms - (origin ?? ms)) / 1000 / span) * 100))}%`;
  const done = cameras.filter((c) => runs[c.clip_id]?.phase === "done").length;

  return (
    <Panel
      index="04"
      title="Check timeline"
      className={className}
      meta={
        <span className="tabular-nums">
          {done}/{cameras.length} DONE · {span}S WINDOW
        </span>
      }
    >
      <div className="flex flex-col gap-1 px-2.5 pt-2 pb-1.5" data-testid="check-timeline">
        {cameras.map((cam) => {
          const r = runs[cam.clip_id];
          const start = r?.startedAt ?? null;
          const end = r?.finishedAt ?? (r?.phase === "checking" ? now : null);
          const found = (r?.result?.detections.length ?? 0) > 0;
          return (
            <div key={cam.clip_id} className="grid grid-cols-[2.6rem_minmax(0,1fr)] items-center gap-2">
              <span className="text-[10px] tracking-[0.1em] text-fg/85">CAM {cam.cam}</span>
              <div className="relative h-3 border-y border-line/60 bg-fg/[0.02]">
                {start !== null && end !== null && origin !== null ? (
                  <span
                    className={cn(
                      "absolute inset-y-0",
                      r?.phase === "checking" && "bg-fg/35",
                      r?.phase === "done" && (found ? "bg-danger/75" : "bg-fg/60"),
                      r?.phase === "failed" && "hatch border border-danger/70",
                    )}
                    style={{ left: pct(start), width: `max(2px, calc(${pct(end)} - ${pct(start)}))` }}
                  >
                    {r?.phase === "checking" ? <span className="blink absolute inset-y-0 right-0 w-[2px] bg-fg" /> : null}
                  </span>
                ) : null}
                {r?.phase === "done" && end !== null ? (
                  <span
                    className={cn("micro absolute top-1/2 ml-1.5 -translate-y-1/2 leading-none", found ? "text-danger" : "text-fg/60")}
                    style={{ left: pct(end) }}
                  >
                    {found ? "ALERT" : "CLEAR"}
                  </span>
                ) : null}
              </div>
            </div>
          );
        })}
        <div className="grid grid-cols-[2.6rem_minmax(0,1fr)] gap-2">
          <span />
          <div className="relative h-3">
            {ticks.map((t) => (
              <span key={t} className="micro absolute top-0 -translate-x-1/2 leading-none" style={{ left: `${(t / span) * 100}%` }}>
                {t === 0 ? "0" : `+${t}S`}
              </span>
            ))}
          </div>
        </div>
      </div>
    </Panel>
  );
}
