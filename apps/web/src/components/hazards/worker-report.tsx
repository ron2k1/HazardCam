"use client";

import type { HazardView, HazardWorker, WorkerHazard } from "@/lib/hazards";
import { cn } from "@/lib/utils";

import { hazardPictures, hazardZoneNames, whereLine, type Pic } from "./derive";
import { HazardCard } from "./hazard-card";

const SUMMARY = "flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-[15px] font-bold text-fg [&::-webkit-details-marker]:hidden";

/** "Safety agent's summary": headline + "Do this first: …" (only when the agent wrote one). */
export function AgentSummary({ worker }: { worker: HazardWorker }) {
  const s = worker.agent_summary;
  if (!s?.headline) return null;
  return (
    <section aria-labelledby="hz-agent-summary" className="relative border border-fg/40 bg-fg/[0.04] px-4 py-3" data-testid="agent-summary">
      <h3 id="hz-agent-summary" className="text-[12px] font-bold tracking-[0.16em] text-fg/70 uppercase">
        Safety agent&apos;s summary
      </h3>
      <p className="mt-1 text-[17px] leading-[24px] font-bold text-fg">{s.headline}</p>
      {s.first_action ? (
        <p className="mt-1 text-[15px] leading-[22px] text-fg">
          <span className="font-semibold">Do this first: </span>
          {s.first_action}
        </p>
      ) : null}
    </section>
  );
}

export interface HazardListProps {
  view: HazardView;
  hazards: readonly WorkerHazard[];
  activeHazardId: string | null;
  kindWord: string;
  reasoningHref: string | null;
  onShow: (hazard: WorkerHazard, zones: number[]) => void;
  onPicture: (pic: Pic, hazard: WorkerHazard) => void;
}

/** The hazard messages, highest priority first. */
export function HazardList({ view, hazards, activeHazardId, kindWord, reasoningHref, onShow, onPicture }: HazardListProps) {
  return (
    <section aria-label={`${kindWord}s found`} className="flex flex-col gap-3" data-testid="hazard-list">
      {hazards.map((h) => {
        const zones = hazardZoneNames(view, h);
        const numbers = zones.map((z) => Number(/(\d+)$/.exec(z)?.[1])).filter((n) => Number.isFinite(n));
        return (
          <HazardCard
            key={h.id}
            hazard={h}
            zones={zones}
            where={whereLine(h, zones)}
            pictures={hazardPictures(view, h)}
            active={activeHazardId === h.id}
            kindWord={kindWord}
            reasoningHref={reasoningHref}
            onShow={() => onShow(h, numbers)}
            onPicture={(p) => onPicture(p, h)}
          />
        );
      })}
    </section>
  );
}

/** "Things we checked and ruled out" and "What we could not tell", collapsed. */
export function ReportFootnotes({ worker, className }: { worker: HazardWorker; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-3", className)}>
      <details className="group border border-line bg-panel/60" data-testid="ruled-out">
        <summary className={SUMMARY}>
          <span>Things we checked and ruled out</span>
          <span className="flex items-center gap-3 text-[13px] font-normal text-fg/60">
            {worker.ruled_out.length}
            <span aria-hidden className="inline-block transition-transform group-open:rotate-90">▸</span>
          </span>
        </summary>
        <ul className="flex flex-col border-t border-line">
          {worker.ruled_out.length === 0 ? <li className="px-4 py-3 text-[14px] text-fg/70">Nothing was ruled out on this camera.</li> : null}
          {worker.ruled_out.map((r, i) => (
            <li key={i} className={cn("px-4 py-3 text-[14px] leading-[22px]", i > 0 && "border-t border-line")}>
              <p className="font-semibold text-fg">{r.what}</p>
              <p className="text-fg/80">{r.why}</p>
            </li>
          ))}
        </ul>
      </details>

      <details className="group border border-line bg-panel/60" data-testid="cannot-tell">
        <summary className={SUMMARY}>
          <span>What we could not tell</span>
          <span className="flex items-center gap-3 text-[13px] font-normal text-fg/60">
            {worker.cannot_tell.length}
            <span aria-hidden className="inline-block transition-transform group-open:rotate-90">▸</span>
          </span>
        </summary>
        <ul className="flex flex-col gap-2 border-t border-line px-4 py-3">
          {worker.cannot_tell.map((c, i) => (
            <li key={i} className="flex gap-2 text-[14px] leading-[22px] text-fg/90">
              <span aria-hidden className="text-fg/40">–</span>
              <span className="min-w-0">{c}</span>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
