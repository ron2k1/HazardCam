"use client";

import type { HazardImage, HazardWorker, WorkerHazard } from "@/lib/hazards";
import { cn } from "@/lib/utils";

import { HazardCard } from "./hazard-card";

export interface WorkerReportProps {
  worker: HazardWorker;
  /** Hazards already sorted for display (highest priority first). */
  hazards: readonly WorkerHazard[];
  imagesSent: number;
  activeHazardId: string | null;
  onShow: (hazard: WorkerHazard) => void;
  onPicture: (image: HazardImage, hazard: WorkerHazard) => void;
}

const SUMMARY = "flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-[15px] font-bold text-fg [&::-webkit-details-marker]:hidden";

/** Headline, summary, hazard messages, then what was ruled out and what could not be told. */
export function WorkerReport({ worker, hazards, imagesSent, activeHazardId, onShow, onPicture }: WorkerReportProps) {
  const none = hazards.length === 0;
  return (
    <div className="flex min-w-0 flex-col gap-4" data-testid="worker-report">
      <section aria-labelledby="hz-headline" className="flex flex-col gap-2">
        <h2
          id="hz-headline"
          className={cn("text-[24px] leading-[1.2] font-extrabold tracking-[0.02em] sm:text-[28px]", none ? "text-fg" : "text-fg")}
          data-testid="hazard-headline"
        >
          {worker.headline}
        </h2>
        {worker.summary ? <p className="max-w-[72ch] text-[15px] leading-[23px] text-fg/80">{worker.summary}</p> : null}
        {none ? (
          <p className="max-w-[72ch] border-l-2 border-fg/50 pl-3 text-[15px] leading-[23px] text-fg" data-testid="no-hazards-note">
            This doesn&apos;t mean the area is safe. The AI only looked at {imagesSent} still picture{imagesSent === 1 ? "" : "s"} from
            this clip.
          </p>
        ) : null}
      </section>

      {!none ? (
        <section aria-label="Hazards" className="flex flex-col gap-3" data-testid="hazard-list">
          {hazards.map((h, i) => (
            <HazardCard
              key={h.id}
              hazard={h}
              index={i + 1}
              active={activeHazardId === h.id}
              onShow={() => onShow(h)}
              onPicture={(im) => onPicture(im, h)}
            />
          ))}
        </section>
      ) : null}

      <details className="group border border-line bg-panel/60" data-testid="ruled-out">
        <summary className={SUMMARY}>
          <span>Things we checked and ruled out</span>
          <span className="flex items-center gap-3 text-[13px] font-normal text-fg/60">
            {worker.ruled_out.length}
            <span aria-hidden className="inline-block transition-transform group-open:rotate-90">▸</span>
          </span>
        </summary>
        <ul className="flex flex-col border-t border-line">
          {worker.ruled_out.length === 0 ? <li className="px-4 py-3 text-[14px] text-fg/70">Nothing was ruled out in this clip.</li> : null}
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
