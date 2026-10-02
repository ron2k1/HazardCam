"use client";

import { motion } from "motion/react";
import { useState } from "react";

import { Panel } from "@/components/hud/panel";
import type { EvidenceCluster, PublicCamera, SampledFrame } from "@/lib/contracts";
import { fixed, label, timecode } from "@/lib/format";
import { niceStep } from "@/lib/geometry";
import type { TimelineItem } from "@/lib/run-view";
import { cn } from "@/lib/utils";

export interface EvidenceTimelineProps {
  /** Visible (model-input) cameras, one lane each. */
  cameras: readonly PublicCamera[];
  /** Observation/evidence bars in scenario seconds. */
  items: readonly TimelineItem[];
  clusters: readonly EvidenceCluster[];
  /** Scenario duration in seconds (x-axis extent). */
  duration: number;
  /** Sampled frames per camera (camera media seconds); drawn as ticks under each lane. */
  samples?: Readonly<Record<string, readonly SampledFrame[]>>;
  selectedId?: string | null;
  /** Called with scenario time; the console converts to media time per camera. */
  onSeek: (cameraId: string, t: number) => void;
  onSelect?: (evidenceId: string | null) => void;
  className?: string;
}

const LANE_H = 38;
const LABEL_ROW = 14;
/** Row pitch / bar height / padding when overlapping bars are stacked within one lane. */
const ROW_PITCH = 10;
const ROW_BAR_H = 8;
const ROW_PAD = 4;

/**
 * Greedy interval packing: bars that overlap in time go to separate rows of their lane,
 * so every observation stays visible and clickable (real runs often emit several cues
 * over the same span).
 */
function packLane(items: readonly TimelineItem[]): { row: Map<string, number>; rows: number } {
  const ends: number[] = [];
  const row = new Map<string, number>();
  for (const it of [...items].sort((a, b) => a.tStart - b.tStart || a.tEnd - b.tEnd)) {
    let r = ends.findIndex((end) => end <= it.tStart + 1e-6);
    if (r === -1) {
      r = ends.length;
      ends.push(it.tEnd);
    } else {
      ends[r] = it.tEnd;
    }
    row.set(it.id, r);
  }
  return { row, rows: Math.max(ends.length, 1) };
}

export function EvidenceTimeline({
  cameras,
  items,
  clusters,
  duration,
  samples,
  selectedId,
  onSeek,
  onSelect,
  className,
}: EvidenceTimelineProps) {
  const [hoverId, setHoverId] = useState<string | null>(null);
  const span = Math.max(duration, 1);
  const x = (t: number) => `${(Math.min(Math.max(t, 0), span) / span) * 100}%`;
  const w = (a: number, b: number) => `${Math.max(((Math.min(b, span) - Math.max(a, 0)) / span) * 100, 0.6)}%`;
  const step = niceStep(span, 10);
  const ticks: number[] = [];
  for (let t = 0; t <= span + 1e-9; t += step) ticks.push(Number(t.toFixed(6)));

  const focusId = hoverId ?? selectedId ?? null;
  const focus = items.find((i) => i.id === focusId) ?? null;
  const clusterOf = (id: string) => clusters.find((c) => c.evidence_ids.includes(id));
  const offsetOf = new Map(cameras.map((c) => [c.id, c.time_offset_s ?? 0]));
  const linkedCount = items.filter((i) => i.linked).length;

  const lanes = cameras.map((cam) => {
    const laneItems = items.filter((it) => it.cameraId === cam.id);
    const { row, rows } = packLane(laneItems);
    return { cam, laneItems, row, rows, height: rows > 1 ? Math.max(LANE_H, rows * ROW_PITCH + ROW_PAD * 2) : LANE_H };
  });
  const laneTops: number[] = [];
  let laneTop = LABEL_ROW;
  for (const l of lanes) {
    laneTops.push(laneTop);
    laneTop += l.height;
  }
  const lanesHeight = laneTop - LABEL_ROW;

  return (
    <Panel
      index="02"
      title="Evidence Timeline"
      className={className}
      bodyClassName="flex flex-col"
      meta={
        <>
          <span>{items.length} OBS</span>
          <span>{linkedCount} LINKED</span>
          <span>{clusters.length} CLU</span>
          <span>T 0–{fixed(span, 1)}S</span>
        </>
      }
    >
      <div className="flex min-h-0 flex-1 flex-col px-2.5 pt-2">
        {/* axis */}
        <div className="grid grid-cols-[64px_minmax(0,1fr)] gap-x-2">
          <span className="micro">SCENARIO T</span>
          <div className="relative h-4 border-b border-line">
            {ticks.map((t) => (
              <span key={t} className="absolute top-0 h-full" style={{ left: x(t) }}>
                <span className="absolute bottom-0 h-1.5 w-px bg-line-strong" />
                <span className="micro absolute -top-0.5 left-1 whitespace-nowrap text-dim">{fixed(t, step < 1 ? 1 : 0)}</span>
              </span>
            ))}
          </div>
        </div>

        {/* lanes */}
        <div className="relative mt-1 grid grid-cols-[64px_minmax(0,1fr)] gap-x-2">
          <div className="flex flex-col" style={{ paddingTop: LABEL_ROW }}>
            {lanes.map(({ cam, height }) => (
              <span key={cam.id} className="flex items-center text-[10px] tracking-[0.14em] text-fg/85" style={{ height }}>
                {cam.id.toUpperCase()}
              </span>
            ))}
          </div>

          <div className="relative" style={{ height: LABEL_ROW + lanesHeight }}>
            {/* vertical grid */}
            {ticks.map((t) => (
              <span key={t} aria-hidden className="absolute bottom-0 w-px bg-line/50" style={{ left: x(t), top: LABEL_ROW }} />
            ))}

            {/* clusters: highlighted spans across all lanes */}
            {clusters.map((c) => (
              <motion.div
                key={c.id}
                aria-hidden
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.4 }}
                className={cn(
                  "absolute inset-y-0 border-x border-dashed bg-fg/[0.045]",
                  focus && clusterOf(focus.id)?.id === c.id ? "border-fg/60" : "border-line-strong",
                )}
                style={{ left: x(c.t_start), width: w(c.t_start, c.t_end) }}
              >
                <span className="micro absolute top-0.5 left-1 whitespace-nowrap text-fg/80">
                  {c.id.toUpperCase()} · {fixed(c.score)}
                </span>
              </motion.div>
            ))}

            {lanes.map(({ cam, laneItems, row, rows, height }, lane) => (
              <div
                key={cam.id}
                className="absolute inset-x-0 border-b border-line/60"
                style={{ top: laneTops[lane], height }}
              >
                {/* sampled frame ticks (media time -> scenario time) */}
                {(samples?.[cam.id] ?? []).map((f) => (
                  <span
                    key={f.index}
                    aria-hidden
                    className="absolute bottom-0 h-1 w-px bg-muted/60"
                    style={{ left: x(f.t + (offsetOf.get(cam.id) ?? 0)) }}
                  />
                ))}
                {laneItems.map((it) => {
                  const active = it.id === focusId;
                  const stacked = rows > 1;
                  return (
                    <motion.button
                      key={it.id}
                      type="button"
                      initial={{ opacity: 0, scaleX: 0.2 }}
                      animate={{ opacity: 1, scaleX: 1 }}
                      transition={{ duration: 0.35 }}
                      onClick={() => {
                        onSelect?.(it.id);
                        onSeek(it.cameraId, it.tStart);
                      }}
                      onMouseEnter={() => setHoverId(it.id)}
                      onMouseLeave={() => setHoverId(null)}
                      onFocus={() => setHoverId(it.id)}
                      onBlur={() => setHoverId(null)}
                      aria-label={`${it.id} ${it.cueType} at ${timecode(it.tStart)}, seek ${cam.id}`}
                      data-evidence-id={it.id}
                      data-camera-id={it.cameraId}
                      data-t-start={it.tStart}
                      className={cn(
                        "absolute origin-left cursor-pointer border outline-none",
                        stacked ? "" : "top-1/2 h-3 -translate-y-1/2",
                        it.linked ? "border-fg/80" : "border-dashed border-fg/50",
                        active && "border-fg",
                        active && !stacked && "h-4",
                      )}
                      style={{
                        left: x(it.tStart),
                        width: w(it.tStart, it.tEnd),
                        ...(stacked ? { top: ROW_PAD + (row.get(it.id) ?? 0) * ROW_PITCH, height: ROW_BAR_H } : {}),
                        backgroundColor: `rgba(241,241,239,${(it.linked ? 0.2 : 0.06) + it.confidence * (it.linked ? 0.65 : 0.2)})`,
                      }}
                    />
                  );
                })}
              </div>
            ))}
          </div>
        </div>

        {/* inspector */}
        <div className="mt-2 flex min-h-[50px] flex-col justify-center gap-0.5 border-t border-line py-2">
          {focus ? (
            <>
              <span className="micro flex flex-wrap gap-x-3 text-fg/85">
                <span className="text-fg">{focus.id.toUpperCase()}</span>
                <span>{focus.cameraId.toUpperCase()}</span>
                <span>{label(focus.cueType)}</span>
                <span>
                  T {timecode(focus.tStart)}–{timecode(focus.tEnd)}
                </span>
                <span>CONF {fixed(focus.confidence)}</span>
                <span>{focus.linked ? `LINKED ${clusterOf(focus.id)?.id.toUpperCase() ?? ""}` : "UNLINKED"}</span>
              </span>
              <span className="truncate text-[11px] text-fg/80">{focus.description}</span>
            </>
          ) : (
            <span className="micro">
              {items.length ? "SELECT OBS → SEEK CAMERA" : "NO OBSERVATIONS YET"}
            </span>
          )}
        </div>
      </div>
    </Panel>
  );
}
