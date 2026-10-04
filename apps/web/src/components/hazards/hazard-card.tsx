"use client";

import { HazardText } from "@/components/alerts/hazard-terms";
import { CornerTicks } from "@/components/hud/panel";
import { byTime, priorityKey, type HazardImage, type WorkerHazard } from "@/lib/hazards-v1";
import { cn } from "@/lib/utils";

import { PRIORITY_TONE } from "./hazard-timeline";
import { Thumb } from "./picture-grid";

export interface HazardCardProps {
  hazard: WorkerHazard;
  /** 1-based position, matching the timeline row. */
  index: number;
  active: boolean;
  onShow: () => void;
  onPicture: (image: HazardImage) => void;
}

const LABEL = "text-[14px] leading-[22px] font-semibold text-fg";

/**
 * One hazard as a short structured message: priority, title, what we saw, why it matters, a
 * numbered "what to do" checklist and the pictures the AI used.
 */
export function HazardCard({ hazard: h, index, active, onShow, onPicture }: HazardCardProps) {
  const tone = PRIORITY_TONE[priorityKey(h.priority)];
  const headingId = `hazard-${h.id}-title`;
  const pictures = byTime(h.evidence);

  return (
    <article
      aria-labelledby={headingId}
      data-testid="hazard-card"
      data-hazard-id={h.id}
      data-priority={priorityKey(h.priority)}
      data-needs-check={h.needs_check || undefined}
      className={cn("relative min-w-0 border bg-panel pl-4 sm:pl-5", active ? "border-fg/70" : "border-line-strong")}
    >
      <span aria-hidden className={cn("absolute inset-y-0 left-0 w-[3px]", tone.edge)} />
      <CornerTicks size={8} />

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 pt-3.5 pr-4">
        <span className={cn("border px-2 py-0.5 text-[13px] leading-[20px] font-bold tracking-[0.12em]", tone.badge)} data-testid="hazard-priority">
          {h.priority.toUpperCase()} PRIORITY
        </span>
        {h.needs_check ? (
          <span className="border border-fg/70 bg-fg/10 px-2 py-0.5 text-[13px] leading-[20px] text-fg" data-testid="needs-check">
            Needs a check
          </span>
        ) : null}
        <span className="ml-auto text-[13px] text-fg/55 tabular-nums" aria-hidden>
          Hazard {index}
        </span>
      </div>

      <h3 id={headingId} className="pt-2.5 pr-4 text-[20px] leading-[1.25] font-bold text-danger sm:text-[22px]">
        {h.title}
      </h3>

      <div className="rule-dotted mt-3 mr-4" aria-hidden />

      <div className="flex flex-col gap-3 pt-3 pr-4 text-[15px] leading-[23px] text-fg/95">
        <p>
          <span className={LABEL}>What we saw — </span>
          <HazardText text={h.what_we_saw} />
        </p>
        <p>
          <span className={LABEL}>Why it matters — </span>
          <HazardText text={h.why_it_matters} />
        </p>
        {h.what_to_do.length ? (
          <div>
            <p className={LABEL}>What to do —</p>
            <ol className="mt-1.5 flex flex-col gap-1.5" data-testid="what-to-do">
              {h.what_to_do.map((step, i) => (
                <li key={i} className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-1">
                  <span aria-hidden className="mt-[3px] inline-flex size-[18px] items-center justify-center border border-fg/60 text-[11px] leading-none text-fg tabular-nums">
                    {i + 1}
                  </span>
                  <span className="font-semibold text-fg">
                    <HazardText text={step} />
                  </span>
                </li>
              ))}
            </ol>
          </div>
        ) : null}
      </div>

      {pictures.length ? (
        <div className="mt-3 border-t border-line pt-3 pr-4">
          <p className="mb-1.5 text-[13px] text-fg/60">Pictures the AI used</p>
          <ul className="grid max-w-[30rem] grid-cols-3 gap-2">
            {pictures.map((im, i) => (
              <li key={`${im.image_url}-${i}`} className="min-w-0">
                <Thumb image={im} onClick={() => onPicture(im)} className="h-full w-full" />
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <footer className="mt-3 flex items-center justify-end border-t border-line py-3 pr-4">
        <button
          type="button"
          onClick={onShow}
          aria-pressed={active}
          data-testid="show-on-video"
          data-seek-t={h.start_s}
          className={cn(
            "flex h-10 shrink-0 items-center gap-2 border px-4 text-[14px] transition-colors",
            active ? "border-fg bg-fg text-bg" : "border-fg/80 text-fg hover:bg-fg hover:text-bg",
          )}
        >
          <span aria-hidden className="text-[11px]">▶</span>
          Show on video
        </button>
      </footer>
    </article>
  );
}
