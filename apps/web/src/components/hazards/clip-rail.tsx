"use client";

import { StatusDot } from "@/components/hud/barcode";
import { clock, countLine, STATUS_WORD, type ClipSummary } from "@/lib/hazards";
import { cn } from "@/lib/utils";

import { PRIORITY_TONE } from "./hazard-timeline";

export interface ClipRailProps {
  clips: readonly ClipSummary[];
  selectedId: string | null;
  onSelect: (clipId: string) => void;
  technical: boolean;
}

const CHIP: Record<ClipSummary["status"], string> = {
  reviewed: "border-fg/60 text-fg",
  not_reviewed: "border-line-strong text-fg/65",
  reviewing: "border-fg text-fg",
  failed: "border-danger/70 text-danger",
};

/** Desktop: the clip list as a left rail. */
export function ClipRail({ clips, selectedId, onSelect, technical }: ClipRailProps) {
  return (
    <nav aria-label="Camera clips" className="flex min-h-0 flex-col" data-testid="clip-rail">
      <h2 className="flex h-10 shrink-0 items-center justify-between border-b border-line px-4">
        <span className="text-[13px] font-bold tracking-[0.14em] text-fg uppercase">Camera clips</span>
        <span className="text-[12px] text-fg/55 tabular-nums">{clips.length}</span>
      </h2>
      <ul className="thin-scroll min-h-0 flex-1 overflow-y-auto">
        {clips.map((c, i) => {
          const selected = c.clip_id === selectedId;
          const count = countLine(c);
          const tone = c.top_priority ? PRIORITY_TONE[c.top_priority] : null;
          return (
            <li key={c.clip_id} className="border-b border-line">
              <button
                type="button"
                onClick={() => onSelect(c.clip_id)}
                aria-current={selected ? "true" : undefined}
                data-testid="clip-item"
                data-clip-id={c.clip_id}
                data-status={c.status}
                className={cn(
                  "relative flex w-full flex-col gap-1.5 px-4 py-3 text-left transition-colors",
                  selected ? "bg-fg/[0.07]" : "hover:bg-fg/[0.04]",
                )}
              >
                {selected ? <span aria-hidden className="absolute inset-y-0 left-0 w-[3px] bg-fg" /> : null}
                <span className="flex items-start justify-between gap-2">
                  <span className="min-w-0 text-[14px] leading-[19px] font-bold text-fg">{c.title}</span>
                  <span className="shrink-0 text-[12px] leading-[19px] text-fg/50 tabular-nums">{clock(c.duration_s)}</span>
                </span>
                <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className={cn("flex items-center gap-1.5 border px-1.5 text-[11px] leading-[18px] tracking-[0.08em] uppercase", CHIP[c.status])}>
                    {c.status === "reviewing" ? <StatusDot tone="fg" pulse /> : null}
                    {STATUS_WORD[c.status]}
                  </span>
                  {count ? (
                    <span className="flex items-center gap-1.5 text-[12px] text-fg/75">
                      {tone && c.hazard_count > 0 ? <span aria-hidden className={cn("inline-block size-2", tone.edge)} /> : null}
                      {count}
                    </span>
                  ) : null}
                </span>
                {technical ? (
                  <span className="micro">
                    {c.clip_id} · #{String(i + 1).padStart(2, "0")}
                  </span>
                ) : null}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** Narrow screens: the same list as a select. */
export function ClipSelect({ clips, selectedId, onSelect }: Omit<ClipRailProps, "technical">) {
  return (
    <label htmlFor="hazard-clip" className="flex w-full min-w-0 flex-col gap-1.5">
      <span className="text-[13px] text-fg/65">Camera clip</span>
      <select
        id="hazard-clip"
        data-testid="clip-select"
        className="hud-select h-11 w-full min-w-0 border border-line-strong bg-bg pr-8 pl-2.5 text-[14px] text-fg outline-none hover:border-fg/70 focus-visible:border-fg"
        value={selectedId ?? ""}
        onChange={(e) => onSelect(e.target.value)}
      >
        {clips.map((c) => {
          const count = countLine(c);
          return (
            <option key={c.clip_id} value={c.clip_id}>
              {c.title} — {STATUS_WORD[c.status]}
              {count ? ` · ${count}` : ""}
            </option>
          );
        })}
      </select>
    </label>
  );
}
