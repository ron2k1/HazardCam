"use client";

import { useEffect, useRef, useState, type Ref } from "react";

import { CornerTicks } from "@/components/hud/panel";
import { clock, type HazardImage, type WorkerHazard } from "@/lib/hazards";
import { cn } from "@/lib/utils";

import { HazardTimeline } from "./hazard-timeline";

export interface SeekRequest {
  t: number;
  /** Bumped on every request, so seeking to the same time twice still seeks. */
  nonce: number;
}

export interface EvidencePlayerProps {
  /** Resolved URLs; either may be missing. */
  processedUrl: string | null;
  sourceUrl: string | null;
  duration: number;
  hazards: readonly WorkerHazard[];
  images: readonly HazardImage[];
  seek: SeekRequest | null;
  activeHazardId: string | null;
  onSeek: (t: number, hazardId: string | null) => void;
  /** Hide the timeline (a clip without a report has nothing to mark). */
  timeline?: boolean;
  className?: string;
  ref?: Ref<HTMLDivElement>;
}

type Track = "processed" | "source";

/**
 * The evidence video: the processed clip with the computer-vision markings (or the original),
 * a timeline of hazard spans and pictures sent to the AI, and seek-on-request. Seeking pauses
 * on that moment, so the frame the AI was shown stays on screen.
 */
export function EvidencePlayer({
  processedUrl,
  sourceUrl,
  duration,
  hazards,
  images,
  seek,
  activeHazardId,
  onSeek,
  timeline = true,
  className,
  ref,
}: EvidencePlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  /** A seek that arrived before the video had metadata, or a track switch's resume point. */
  const pending = useRef<{ t: number; play: boolean } | null>(null);
  const [track, setTrack] = useState<Track>(processedUrl ? "processed" : "source");
  const [currentT, setCurrentT] = useState(0);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);

  const effective: Track = track === "processed" ? (processedUrl ? "processed" : "source") : sourceUrl ? "source" : "processed";
  const src = effective === "processed" ? processedUrl : sourceUrl;
  const playable = !!src && failedSrc !== src;

  useEffect(() => {
    const v = videoRef.current;
    if (!seek) return;
    const t = Math.min(Math.max(seek.t, 0), Math.max(duration - 0.05, 0));
    if (v && v.readyState >= 1) {
      v.pause();
      v.currentTime = t;
    } else {
      pending.current = { t, play: false };
    }
  }, [seek, duration]);

  const switchTrack = (next: Track) => {
    if (next === effective) return;
    const v = videoRef.current;
    if (v) pending.current = { t: v.currentTime, play: !v.paused };
    setTrack(next);
  };

  const onLoadedMetadata = () => {
    const v = videoRef.current;
    const p = pending.current;
    if (!v || !p) return;
    pending.current = null;
    v.currentTime = p.t;
    if (p.play) void v.play().catch(() => undefined);
  };

  return (
    <div ref={ref} className={cn("flex min-w-0 flex-col gap-3", className)} data-testid="evidence-player">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {processedUrl && sourceUrl ? (
          <div role="group" aria-label="Video" className="flex border border-line-strong">
            {(
              [
                ["processed", "With AI markings", processedUrl],
                ["source", "Original", sourceUrl],
              ] as const
            ).map(([key, text, url]) => (
              <button
                key={key}
                type="button"
                aria-pressed={effective === key}
                disabled={!url}
                onClick={() => switchTrack(key)}
                data-testid={`track-${key}`}
                className={cn(
                  "h-9 px-3 text-[13px] transition-colors disabled:opacity-35",
                  effective === key ? "bg-fg text-bg" : "text-fg/80 hover:bg-fg/10 hover:text-fg",
                )}
              >
                {text}
              </button>
            ))}
          </div>
        ) : (
          <span className="text-[13px] text-fg/65">{!src ? "No video" : effective === "processed" ? "With AI markings" : "Original video"}</span>
        )}
        <span className="text-[13px] text-fg/65 tabular-nums" aria-live="off">
          {clock(currentT)} / {clock(duration)}
        </span>
      </div>

      <figure className="relative m-0 aspect-video min-w-0 overflow-hidden border border-line bg-bg">
        {playable ? (
          <video
            ref={videoRef}
            key={src}
            src={src ?? undefined}
            className="absolute inset-0 h-full w-full object-contain"
            controls
            muted
            playsInline
            preload="metadata"
            onLoadedMetadata={onLoadedMetadata}
            onTimeUpdate={(e) => setCurrentT(e.currentTarget.currentTime)}
            onSeeked={(e) => setCurrentT(e.currentTarget.currentTime)}
            onError={() => setFailedSrc(src)}
            data-track={effective}
            data-testid="evidence-video"
          />
        ) : (
          <div className="dot-field absolute inset-0 flex flex-col items-center justify-center gap-1">
            <span className="text-[15px] font-semibold tracking-[0.12em] text-fg/75">NO VIDEO</span>
            <span className="text-[13px] text-fg/55">Video not available</span>
          </div>
        )}
        <CornerTicks size={10} className="m-1.5" />
        {playable ? (
          <figcaption className="sr-only">
            {effective === "processed" ? "Clip with the areas the computer marked for a closer look" : "Original clip"}
          </figcaption>
        ) : null}
      </figure>

      {timeline ? (
        <HazardTimeline
          duration={duration}
          hazards={hazards}
          images={images}
          currentT={currentT}
          activeHazardId={activeHazardId}
          onSeek={onSeek}
        />
      ) : null}
    </div>
  );
}
