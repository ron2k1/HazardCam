"use client";

import { useEffect, useRef, useState } from "react";

import { StatusDot } from "@/components/hud/barcode";
import { CornerTicks } from "@/components/hud/panel";
import type { PublicCamera } from "@/lib/contracts";
import type { CameraPhase, CameraRunState } from "@/lib/run-view";
import { cn } from "@/lib/utils";

import type { SeekRequest } from "./camera-tile";

export interface WorkerCameraProps {
  camera: PublicCamera;
  /** Friendly name, e.g. "Camera B"; the raw id is never shown. */
  name: string;
  /** Resolved media URL, or null when there is no video to play. */
  src: string | null;
  run?: CameraRunState | null;
  seek?: SeekRequest | null;
  /** The message shown on the videos cites this camera. */
  highlighted?: boolean;
  className?: string;
}

const STATUS: Record<CameraPhase, string> = {
  idle: "Waiting",
  sampling: "Checking…",
  analyzing: "Checking…",
  complete: "Checked",
};

/** Whole seconds as m:ss, the same clock the messages' "When" line uses. */
function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** A camera for the worker view: the video, its friendly name and a one-word status. */
export function WorkerCamera({ camera, name, src, run, seek, highlighted = false, className }: WorkerCameraProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [mediaT, setMediaT] = useState(0);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const phase: CameraPhase = run?.phase ?? "idle";
  const busy = phase === "sampling" || phase === "analyzing";
  const hasSignal = !!src && failedSrc !== src;

  useEffect(() => {
    const v = videoRef.current;
    if (!v || !seek) return;
    v.currentTime = seek.t;
    void v.play().catch(() => undefined);
  }, [seek]);

  return (
    <figure
      aria-label={`${name} video`}
      data-camera-id={camera.id}
      data-highlighted={highlighted || undefined}
      className={cn(
        "relative min-h-0 min-w-0 overflow-hidden border bg-bg",
        highlighted ? "border-fg" : "border-line",
        className,
      )}
    >
      {hasSignal ? (
        <video
          ref={videoRef}
          key={src}
          src={src ?? undefined}
          className="absolute inset-0 h-full w-full object-contain"
          muted
          playsInline
          autoPlay
          loop
          preload="metadata"
          onTimeUpdate={(e) => setMediaT(e.currentTarget.currentTime)}
          onError={() => setFailedSrc(src)}
        />
      ) : (
        <div className="dot-field absolute inset-0 flex flex-col items-center justify-center gap-1">
          <span className="text-[15px] font-semibold tracking-[0.12em] text-fg/75">NO VIDEO</span>
          <span className="text-[13px] text-fg/55">Video not available</span>
        </div>
      )}

      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,rgba(5,5,5,0.72)_0%,transparent_26%,transparent_70%,rgba(5,5,5,0.78)_100%)]" />
      {busy ? <span className="scanline" aria-hidden /> : null}
      <CornerTicks size={10} className="m-1.5" />

      <figcaption className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between gap-2 px-3 pt-2.5">
        <span className="bg-bg/60 px-1.5 text-[15px] leading-[22px] font-bold tracking-[0.04em] text-fg">{name}</span>
        <span className="flex items-center gap-1.5 bg-bg/60 px-1.5 text-[14px] leading-[22px] text-fg/90" data-phase={phase}>
          <StatusDot tone={busy ? "fg" : phase === "complete" ? "muted" : "dim"} pulse={busy} className="size-2" />
          {STATUS[phase]}
        </span>
      </figcaption>

      <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between gap-2 px-3 pb-2.5">
        <span className="bg-bg/60 px-1.5 text-[14px] leading-[22px] text-fg/90 tabular-nums">{hasSignal ? clock(mediaT) : ""}</span>
        {highlighted ? (
          <span className="border border-fg bg-bg/80 px-1.5 text-[13px] leading-[20px] text-fg">Showing the moment</span>
        ) : null}
      </div>
    </figure>
  );
}
