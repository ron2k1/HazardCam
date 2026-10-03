"use client";

import { useEffect, useRef, useState, type Ref } from "react";

import { CornerTicks } from "@/components/hud/panel";
import { clock, type HazardImage, type WorkerHazard } from "@/lib/hazards";
import { cn } from "@/lib/utils";

import type { ZoneBox } from "./derive";
import { HazardPin, type HazardPinItem } from "./hazard-pin";
import { HazardTimeline } from "./hazard-timeline";
import { cropTopStyle } from "./picture-grid";
import { useContainRect, visibleZones, ZoneOverlay, type ZoneMode } from "./zone-overlay";

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
  zones: readonly ZoneBox[];
  /** Source frame size (w/h), for the zone overlay and the processed video's banner crop. */
  source: { w: number; h: number } | null;
  seek: SeekRequest | null;
  activeHazardId: string | null;
  /** Zone numbers of the hazard picked last. */
  focusZones?: readonly number[];
  onSeek: (t: number, hazardId: string | null) => void;
  kindWord: string;
  className?: string;
  ref?: Ref<HTMLDivElement>;
}

type Track = "processed" | "source";

/**
 * The evidence video: the processed clip with the computer-vision markings (or the original),
 * "ZONE n" outlines kept on their objects, a plain legend, a timeline of hazard windows and of
 * the pictures sent to the AI, and seek-on-request (seeking pauses on that moment).
 */
export function EvidencePlayer({
  processedUrl,
  sourceUrl,
  duration,
  hazards,
  images,
  zones,
  source,
  seek,
  activeHazardId,
  focusZones = [],
  onSeek,
  kindWord,
  className,
  ref,
}: EvidencePlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  /** A seek that arrived before the video had metadata, or a track switch's resume point. */
  const pending = useRef<{ t: number; play: boolean } | null>(null);
  const [track, setTrack] = useState<Track>(processedUrl ? "processed" : "source");
  const [zoneMode, setZoneMode] = useState<ZoneMode>("relevant");
  const [currentT, setCurrentT] = useState(0);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);

  const effective: Track = track === "processed" ? (processedUrl ? "processed" : "source") : sourceUrl ? "source" : "processed";
  const src = effective === "processed" ? processedUrl : sourceUrl;
  const playable = !!src && failedSrc !== src;

  // The processed video carries a dark banner above the frame; crop it so boxes line up.
  const srcAspect = source ? source.w / source.h : 16 / 9;
  const banner = effective === "processed" && natural ? Math.max(0, Math.round(natural.h - natural.w / srcAspect)) : 0;
  const shown = visibleZones(zones, zoneMode);
  const rect = useContainRect(boxRef, srcAspect);
  // A warning label pinned at each hazard's first zone; the picked hazard is highlighted.
  const pinned = hazards.flatMap((h) => {
    const name = h.zone_names?.[0];
    const z = name ? zones.find((zz) => zz.name === name) : undefined;
    return z ? [{ id: h.id, item: { box: z.box, label: h.sign?.label ?? kindWord.toUpperCase(), zoneName: z.name, glyph: h.sign?.glyph ?? undefined, tone: kindWord.toLowerCase().includes("blind") ? "blindspot" : "hazard" } as HazardPinItem }] : [];
  });
  const activePin = pinned.findIndex((p) => p.id === activeHazardId);

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
    setNatural(null);
    setTrack(next);
  };

  const onLoadedMetadata = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.videoWidth && v.videoHeight) setNatural({ w: v.videoWidth, h: v.videoHeight });
    const p = pending.current;
    if (!p) return;
    pending.current = null;
    v.currentTime = p.t;
    if (p.play) void v.play().catch(() => undefined);
  };

  const segBtn = (on: boolean) =>
    cn("h-8 px-2.5 text-[13px] transition-colors disabled:opacity-35", on ? "bg-fg text-bg" : "text-fg/80 hover:bg-fg/10 hover:text-fg");

  return (
    <div ref={ref} className={cn("flex min-w-0 flex-col gap-2.5", className)} data-testid="evidence-player">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {processedUrl && sourceUrl ? (
            <div role="group" aria-label="Video" className="flex border border-line-strong">
              <button type="button" aria-pressed={effective === "processed"} onClick={() => switchTrack("processed")} className={segBtn(effective === "processed")} data-testid="track-processed">
                With AI markings
              </button>
              <button type="button" aria-pressed={effective === "source"} onClick={() => switchTrack("source")} className={segBtn(effective === "source")} data-testid="track-source">
                Original
              </button>
            </div>
          ) : null}
          {zones.length ? (
            <button
              type="button"
              role="switch"
              aria-checked={zoneMode === "all"}
              onClick={() => setZoneMode((m) => (m === "all" ? "relevant" : "all"))}
              className={cn("h-8 border border-line-strong px-2.5 text-[13px]", zoneMode === "all" ? "bg-fg/15 text-fg" : "text-fg/80 hover:text-fg")}
              data-testid="zones-toggle"
            >
              <span aria-hidden className={cn("mr-1.5 inline-block size-2.5 border align-[-1px]", zoneMode === "all" ? "border-fg bg-fg" : "border-fg/60")} />
              Show all zones
            </button>
          ) : null}
        </div>
        <span className="text-[13px] text-fg/65 tabular-nums" aria-live="off">
          {clock(currentT)} / {clock(duration)}
        </span>
      </div>

      <figure className="relative m-0 aspect-video min-w-0 overflow-hidden border border-line bg-black">
        <div ref={boxRef} className="absolute inset-0">
          {playable ? (
            <video
              ref={videoRef}
              key={src}
              src={src ?? undefined}
              className="absolute inset-0 h-full w-full"
              style={cropTopStyle(banner)}
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
            </div>
          )}
          {playable ? <ZoneOverlay zones={shown} rect={rect} focus={focusZones} /> : null}
          {playable && source && pinned.length ? (
            <HazardPin
              items={pinned.map((p) => p.item)}
              mediaWidth={source.w}
              mediaHeight={source.h}
              activeIndex={activePin >= 0 ? activePin : null}
              showCoords={false}
              className="pointer-events-none"
            />
          ) : null}
        </div>
        <CornerTicks size={10} className="m-1.5" />
        <figcaption className="sr-only">
          {effective === "processed" ? "Clip with the areas the computer marked for a closer look" : "Original clip"}
        </figcaption>
      </figure>

      <ul className="flex flex-col gap-1 text-[13px] leading-5 text-fg/75" data-testid="video-legend">
        {effective === "processed" ? <li>Orange boxes: things that might be in the way. Blue boxes: movement.</li> : null}
        <li className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-3 w-4 border-2 border-warning bg-warning/10" />
            Zone with a {kindWord.toLowerCase()}
          </span>
          <span className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-3 w-4 border border-dashed border-fg/80" />
            Other zone the computer marked
          </span>
        </li>
      </ul>

      <HazardTimeline
        duration={duration}
        hazards={hazards}
        images={images}
        currentT={currentT}
        activeHazardId={activeHazardId}
        onSeek={onSeek}
        kindWord={kindWord}
      />
    </div>
  );
}
