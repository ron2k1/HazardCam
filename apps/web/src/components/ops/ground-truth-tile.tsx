"use client";

import { AnimatePresence, motion } from "motion/react";

import { CornerTicks } from "@/components/hud/panel";
import { Button } from "@/components/ui/button";
import type { JudgeGroundTruth } from "@/lib/contracts";
import { deg, label, signedCoord } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface GroundTruthTileProps {
  /** Judge-only metadata; null until fetched (never part of model input). */
  judge: JudgeGroundTruth | null;
  /** Resolved GT video URL (null when video_available is false); only rendered once revealed. */
  src: string | null;
  revealed: boolean;
  /** The judge request behind the reveal is in flight / failed. */
  pending?: boolean;
  error?: string | null;
  /** Typically: run complete. */
  canReveal: boolean;
  onReveal?: () => void;
  onHide?: () => void;
  className?: string;
}

const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);

/** The judge's expected outcome from expected.json, as far as it states one. */
function expectedSummary(expected: Record<string, unknown> | null): string | null {
  if (!expected) return null;
  const event = str(expected.event_type);
  const zone = str((expected.region as Record<string, unknown> | null | undefined)?.zone_id);
  const category = str(expected.category);
  const parts = [
    event ? `EXPECTED ${label(event)}` : null,
    zone ? `ZONE ${zone.toUpperCase()}` : null,
    category ? label(category) : null,
    expected.abstention_acceptable === true ? "ABSTAIN OK" : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

/** Fourth tile: the withheld judge camera. Visually distinct (dashed frame, hatch, inverted tag). */
export function GroundTruthTile({
  judge,
  src,
  revealed,
  pending = false,
  error = null,
  canReveal,
  onReveal,
  onHide,
  className,
}: GroundTruthTileProps) {
  const cam = judge?.ground_truth_camera;
  const expected = revealed ? expectedSummary(judge?.expected ?? null) : null;
  return (
    <figure
      aria-label="Judge ground truth camera, not model input"
      data-testid="ground-truth"
      data-state={revealed ? "revealed" : "withheld"}
      className={cn("relative min-h-0 min-w-0 overflow-hidden border border-dashed border-line-strong bg-bg", className)}
    >
      <AnimatePresence initial={false} mode="wait">
        {revealed ? (
          <motion.div
            key="revealed"
            className="absolute inset-0"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
          >
            {src ? (
              <video
                key={src}
                src={src}
                className="absolute inset-0 h-full w-full object-contain"
                muted
                playsInline
                autoPlay
                loop
                controls
                preload="metadata"
              />
            ) : (
              <div className="dot-field absolute inset-0 flex flex-col items-center justify-center gap-1.5">
                <span className="text-[11px] tracking-[0.3em] text-fg/70">GT MEDIA UNAVAILABLE</span>
                <span className="micro">JUDGE VIDEO NOT LOADED</span>
              </div>
            )}
          </motion.div>
        ) : (
          <motion.div
            key="withheld"
            className="hatch absolute inset-0 flex flex-col items-center justify-center gap-3"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
          >
            <span className="flex items-center gap-2 text-[12px] tracking-[0.34em] text-fg">
              <span aria-hidden className="inline-block size-2.5 border border-fg" />
              WITHHELD
            </span>
            <span className="micro">EXCLUDED FROM ALL MODEL + TOOL INPUT</span>
            <Button
              size="sm"
              variant={canReveal ? "default" : "ghost"}
              disabled={!canReveal || !onReveal || pending}
              onClick={onReveal}
              className="pointer-events-auto mt-1 bg-bg"
            >
              {pending ? "FETCHING JUDGE DATA" : canReveal ? "REVEAL FOR JUDGE" : "REVEAL AFTER RUN"}
            </Button>
            {error ? (
              <span role="alert" className="micro max-w-[90%] truncate text-danger normal-case" title={error}>
                REVEAL FAILED · {error}
              </span>
            ) : null}
          </motion.div>
        )}
      </AnimatePresence>

      <CornerTicks size={9} className="m-1.5" />
      <figcaption className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between gap-2 px-2.5 pt-2">
        <span className="flex min-w-0 flex-col items-start gap-1">
          <span className="bg-fg px-1.5 py-0.5 text-[9px] font-bold tracking-[0.16em] text-bg">
            JUDGE GROUND TRUTH — NOT MODEL INPUT
          </span>
          {expected ? (
            <span className="micro line-clamp-2 max-w-full bg-bg/80 px-1 text-fg/90" data-testid="gt-expected" title={expected}>
              {expected}
            </span>
          ) : null}
        </span>
        {revealed && onHide ? (
          <button
            type="button"
            onClick={onHide}
            className="micro pointer-events-auto border border-line bg-bg/80 px-1.5 py-0.5 hover:text-fg"
          >
            HIDE
          </button>
        ) : null}
      </figcaption>
      <div className="micro pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between px-2.5 pb-2">
        <span className="text-fg/80">{revealed && cam ? cam.id.toUpperCase() : "GT/--"}</span>
        <span className="text-right">
          {revealed && cam
            ? `X ${signedCoord(cam.position?.[0])} Y ${signedCoord(cam.position?.[1])} · HDG ${deg(cam.heading_deg)}`
            : "POSITION WITHHELD"}
        </span>
      </div>
    </figure>
  );
}
