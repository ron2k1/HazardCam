"use client";

import { motion } from "motion/react";
import { useEffect, useRef } from "react";

import { Panel } from "@/components/hud/panel";
import { elapsed, ms, seqId, summary, wallClock } from "@/lib/format";
import type { HarnessInfo, RunPhase, TraceRow } from "@/lib/run-view";
import { cn } from "@/lib/utils";

export interface TracePanelProps {
  rows: readonly TraceRow[];
  harness: HarnessInfo | null;
  phase: RunPhase;
  lastSeq: number;
  /** run.started ts; rows show time relative to it (wall clock on hover). */
  startedAt?: string | null;
  className?: string;
}

/** Harness identity line. The dev harness is a fixed sequence, not an agent; say so. */
export function harnessLabel(h: HarnessInfo | null): string {
  if (!h) return "NO ORCHESTRATOR";
  if (!h.agent) return h.name === "dev-sequence" ? "DEV SEQUENCE · NON-AGENT" : `${h.name.toUpperCase()} · NON-AGENT`;
  return `AGENT · ${h.name.toUpperCase()}`;
}

const STATUS_GLYPH = { running: "▸", ok: "■", error: "✕" } as const;

export function TracePanel({ rows, harness, phase, lastSeq, startedAt = null, className }: TracePanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [rows]);

  const done = new Set(rows.filter((r) => r.status === "ok").map((r) => r.tool));
  const active = new Set(rows.filter((r) => r.status === "running").map((r) => r.tool));

  return (
    <Panel
      index="05"
      title="Agent Trace"
      className={className}
      bodyClassName="flex flex-col"
      meta={
        <>
          <span>SEQ {seqId(lastSeq)}</span>
          <span>{rows.length} CALLS</span>
        </>
      }
    >
      <div className="flex shrink-0 flex-col gap-1.5 border-b border-line px-2.5 py-2">
        <span
          className={cn(
            "w-fit border px-1.5 py-0.5 text-[9px] tracking-[0.16em]",
            harness?.agent ? "border-fg/70 text-fg" : "border-line-strong text-fg/85",
          )}
        >
          {harnessLabel(harness)}
        </span>
        {harness?.sequence.length ? (
          <ol className="micro flex flex-wrap items-center gap-x-1 gap-y-0.5" aria-label="Planned tool sequence">
            {harness.sequence.map((tool, i) => (
              <li key={`${i}-${tool}`} className="flex items-center gap-1">
                <span className={cn(done.has(tool) ? "text-fg/85" : active.has(tool) ? "text-fg" : "text-dim")}>
                  {tool}
                </span>
                {i < harness.sequence.length - 1 ? <span className="text-dim">→</span> : null}
              </li>
            ))}
          </ol>
        ) : null}
      </div>

      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
        }}
        className="thin-scroll min-h-0 flex-1 overflow-y-auto [mask-image:linear-gradient(to_bottom,transparent_0,#000_14px,#000_calc(100%-10px),transparent_100%)] pt-1 pb-2"
      >
        {rows.length === 0 ? (
          <p className="micro px-2.5 py-3">{phase === "idle" ? "NO RUN · TRACE EMPTY" : "WAITING FOR TOOL EVENTS"}</p>
        ) : (
          <ol className="divide-y divide-line/60" aria-live="polite" aria-label="Tool calls">
            {rows.map((r) => (
              <motion.li
                key={r.callId}
                initial={{ opacity: 0, x: -4 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.18 }}
                data-status={r.status}
                className="grid grid-cols-[34px_minmax(0,1fr)_auto] gap-x-2 gap-y-0.5 px-2.5 py-1.5"
              >
                <span className="micro row-span-2 pt-px text-dim">{seqId(r.seq)}</span>
                <span className="flex min-w-0 items-center gap-1.5 text-[11px] text-fg">
                  <span
                    aria-hidden
                    className={cn(
                      "text-[9px]",
                      r.status === "error" ? "text-danger" : r.status === "running" ? "blink text-fg" : "text-muted",
                    )}
                  >
                    {STATUS_GLYPH[r.status]}
                  </span>
                  <span className="truncate">{r.tool}</span>
                </span>
                <span className="micro flex items-center gap-2 pt-px whitespace-nowrap">
                  <span className="text-fg/75">{r.status === "running" ? "RUN" : ms(r.latencyMs)}</span>
                  <span className="text-dim" title={`${wallClock(r.ts)} UTC`}>
                    {elapsed(r.ts, startedAt)}
                  </span>
                </span>
                <span
                  className="micro col-span-2 line-clamp-2 normal-case break-words"
                  title={summary(r.argsSummary)}
                >
                  {summary(r.argsSummary) || "—"}
                  {r.status !== "running" ? (
                    <span className={r.status === "error" ? "text-danger" : "text-fg/70"}>
                      {" → "}
                      {r.status === "error" ? r.error ?? "error" : summary(r.resultSummary)}
                    </span>
                  ) : null}
                </span>
              </motion.li>
            ))}
          </ol>
        )}
      </div>
    </Panel>
  );
}
