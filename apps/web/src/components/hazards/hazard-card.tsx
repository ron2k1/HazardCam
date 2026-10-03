"use client";

import { useState } from "react";

import { CornerTicks } from "@/components/hud/panel";
import { priorityKey, type WorkerHazard } from "@/lib/hazards";
import { cn } from "@/lib/utils";

import type { Pic } from "./derive";
import { PRIORITY_TONE } from "./hazard-timeline";
import { PicButton } from "./picture-grid";
import { WarningSign, WarningTriangle } from "./warning-sign";

export interface HazardCardProps {
  hazard: WorkerHazard;
  /** ["Zone 3"] */
  zones: string[];
  /** "Where", starting with the zone name. */
  where: string;
  pictures: Pic[];
  active: boolean;
  /** "Blind spot" or "Hazard" (headings only). */
  kindWord: string;
  reasoningHref: string | null;
  onShow: () => void;
  onPicture: (pic: Pic) => void;
}

const ACTION_WORDS = 8;

/**
 * One short action line: the API's short action if it sends one, else the first clause of the first
 * recommended step, cut at a word boundary (ellipsis only when the cut lands mid-phrase).
 */
export function shortAction(h: WorkerHazard): string | null {
  const given = (h as WorkerHazard & { short_action?: string | null }).short_action?.trim();
  if (given) return given;
  const first = h.what_to_do.find((s) => s.trim())?.trim();
  if (!first) return null;
  const clause = first.split(/[.;:!?]\s|[,—–(]|\s-\s/)[0].trim().replace(/[.;:,!?]+$/, "");
  const words = clause.split(/\s+/).filter(Boolean);
  if (words.length <= ACTION_WORDS) return clause;
  return `${words.slice(0, ACTION_WORDS).join(" ").replace(/[.;:,!?]+$/, "")}…`;
}
/** Pictures shown in the card's first row (two rows of two on a phone). */
const FIRST_ROW = 4;

/**
 * One hazard at a glance: warning sign, zone, priority, one action line, "Show on video" and the
 * cited pictures. The model's prose (what we saw, why it matters, uncertainty) lives on the
 * reasoning page (/hazards/process).
 */
export function HazardCard({ hazard: h, zones, pictures, active, kindWord, onShow, onPicture }: HazardCardProps) {
  const pk = priorityKey(h.priority);
  const tone = PRIORITY_TONE[pk];
  const headingId = `${h.id}-title`;
  const title = h.short_title || h.title;
  const sign = h.sign;
  const action = shortAction(h);
  // one row of pictures at a glance; the rest on request
  const [allPictures, setAllPictures] = useState(false);
  const shown = allPictures ? pictures : pictures.slice(0, FIRST_ROW);
  const hidden = pictures.length - FIRST_ROW;

  return (
    <article
      aria-labelledby={headingId}
      data-testid="hazard-card"
      data-priority={pk}
      data-needs-check={h.needs_check || undefined}
      className={cn("relative min-w-0 border bg-panel pl-4 sm:pl-5", active ? "border-fg/70" : pk === "high" ? "border-danger/60" : pk === "medium" ? "border-warning/50" : "border-line-strong")}
    >
      <span aria-hidden className={cn("absolute inset-y-0 left-0 w-1", tone.edge)} />
      <CornerTicks size={8} />

      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2 pt-3 pr-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {sign ? (
            <WarningSign label={sign.label} glyph={sign.glyph} size="md" />
          ) : (
            <span className="flex items-center gap-2">
              <WarningTriangle className="size-8" />
              <span className="text-[15px] font-extrabold tracking-[0.08em] text-fg uppercase">{title}</span>
            </span>
          )}
          <span className={cn("border px-2 text-[13px] leading-[30px] font-bold tracking-[0.12em]", tone.badge)} data-testid="hazard-priority">
            {h.priority.toUpperCase()} PRIORITY
          </span>
        </div>
        {zones.length ? (
          <span className="flex shrink-0 flex-wrap justify-end gap-1.5" data-testid="zone-tag">
            {zones.map((z) => (
              <span key={z} className="border-2 border-warning bg-bg px-2.5 text-[18px] leading-[30px] font-extrabold tracking-[0.08em] text-warning uppercase">
                {z}
              </span>
            ))}
          </span>
        ) : null}
      </div>

      <h3 id={headingId} className="sr-only">
        {title}
      </h3>
      {action ? (
        <p className="pt-2 pr-3 text-[18px] leading-[1.3] font-bold text-fg" data-testid="hazard-action">
          {action}
        </p>
      ) : null}

      {pictures.length ? (
        <div className="pt-2.5 pr-3">
          <p className="sr-only">Pictures the AI used for this {kindWord.toLowerCase()}</p>
          <ul
            className={cn("grid gap-2", pictures.length >= FIRST_ROW ? "grid-cols-2 sm:grid-cols-4" : "grid-cols-2 sm:grid-cols-3")}
            data-testid="hazard-pictures"
          >
            {shown.map((p) => (
              <li key={p.key} className="min-w-0">
                <PicButton pic={p} size="lg" onClick={() => onPicture(p)} className="h-full w-full" />
              </li>
            ))}
          </ul>
          {hidden > 0 ? (
            <button
              type="button"
              onClick={() => setAllPictures((v) => !v)}
              aria-expanded={allPictures}
              className="mt-1.5 text-[13px] text-fg/70 underline decoration-line-strong underline-offset-2 hover:text-fg"
              data-testid="more-pictures"
            >
              {allPictures ? "Show fewer pictures" : `Show ${hidden} more picture${hidden === 1 ? "" : "s"}`}
            </button>
          ) : null}
        </div>
      ) : null}

      <footer className="mt-3 flex flex-wrap items-center justify-end gap-2 border-t border-line py-2.5 pr-3">
        <button
          type="button"
          onClick={onShow}
          aria-pressed={active}
          data-testid="show-on-video"
          data-seek-t={h.start_s}
          className={cn(
            "flex h-9 shrink-0 items-center gap-2 border px-4 text-[14px] transition-colors",
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
