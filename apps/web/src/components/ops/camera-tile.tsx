"use client";

import { useEffect, useRef, useState } from "react";

import { StatusDot } from "@/components/hud/barcode";
import { CornerTicks } from "@/components/hud/panel";
import type { PublicCamera, SampledFrame } from "@/lib/contracts";
import { deg, timecode } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { CameraPhase, CameraRunState } from "@/lib/run-view";

export interface SeekRequest {
  /** Camera media seconds. */
  t: number;
  /** Changes on every request so repeated seeks to the same t still fire. */
  nonce: number;
}

export interface CameraTileProps {
  camera: PublicCamera;
  /** 1-based display slot. */
  slot: number;
  /** Resolved media URL, or null for the no-signal state. */
  src: string | null;
  run?: CameraRunState | null;
  seek?: SeekRequest | null;
  highlighted?: boolean;
  /** Shown in the no-signal state, e.g. "MOCK · NO MEDIA". */
  noSignalNote?: string;
  className?: string;
}

const PHASE_LABEL: Record<CameraPhase, string> = {
  idle: "STANDBY",
  sampling: "SAMPLING",
  analyzing: "ANALYZING",
  complete: "OBSERVED",
};

/** Nearest sampled frame at or before media time t. */
function frameAt(samples: readonly SampledFrame[], t: number): SampledFrame | null {
  let best: SampledFrame | null = null;
  for (const f of samples) {
    if (f.t <= t + 1e-6 && (!best || f.t > best.t)) best = f;
  }
  return best;
}

export function CameraTile({
  camera,
  slot,
  src,
  run,
  seek,
  highlighted = false,
  noSignalNote = "MEDIA UNAVAILABLE",
  className,
}: CameraTileProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [mediaT, setMediaT] = useState(0);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const phase: CameraPhase = run?.phase ?? "idle";
  const busy = phase === "sampling" || phase === "analyzing";
  const hasSignal = !!src && failedSrc !== src;

  useEffect(() => {
    const v = videoRef.current;
    if (!v || !seek) return;
    // timeupdate fires after the seek and refreshes the overlay timecode
    v.currentTime = seek.t;
    void v.play().catch(() => undefined);
  }, [seek]);

  const frame = run?.samples.length ? frameAt(run.samples, mediaT) : null;

  return (
    <figure
      aria-label={`${camera.id} input camera`}
      data-camera-id={camera.id}
      className={cn(
        "relative min-h-0 min-w-0 overflow-hidden border bg-bg",
        highlighted ? "border-fg/80" : "border-line",
        className,
      )}
    >
      {hasSignal ? (
        <video
          ref={videoRef}
          key={src}
          src={src ?? undefined}
          className="absolute inset-0 h-full w-full object-contain grayscale-[35%]"
          muted
          playsInline
          autoPlay
          loop
          preload="metadata"
          onTimeUpdate={(e) => setMediaT(e.currentTarget.currentTime)}
          onError={() => setFailedSrc(src)}
        />
      ) : (
        <div className="dot-field absolute inset-0 flex flex-col items-center justify-center gap-1.5">
          <span className="text-[11px] tracking-[0.3em] text-fg/70">NO SIGNAL</span>
          <span className="micro">{src && failedSrc === src ? "MEDIA UNREACHABLE" : noSignalNote}</span>
        </div>
      )}

      {/* overlay telemetry */}
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,rgba(5,5,5,0.7)_0%,transparent_22%,transparent_74%,rgba(5,5,5,0.78)_100%)]" />
      {busy ? <span className="scanline" aria-hidden /> : null}
      <CornerTicks size={9} className="m-1.5" />

      <figcaption className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between px-2.5 pt-2">
        <span className="flex flex-col">
          <span className="text-[11px] tracking-[0.18em] text-fg">
            {camera.id.toUpperCase()}
            <span className="ml-2 text-muted">IN/{String(slot).padStart(2, "0")}</span>
          </span>
          {camera.label ? <span className="micro">{camera.label}</span> : null}
        </span>
        <span className="micro flex items-center gap-1.5 text-fg/85" data-phase={phase}>
          <StatusDot tone={busy ? "fg" : phase === "complete" ? "muted" : "dim"} pulse={busy} />
          {hasSignal || busy || phase === "complete" ? PHASE_LABEL[phase] : "NO SIGNAL"}
        </span>
      </figcaption>

      <div className="micro pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between gap-2 px-2.5 pb-2">
        <span className="flex flex-col gap-0.5">
          <span className="text-[11px] tracking-[0.12em] text-fg tabular-nums">T {timecode(mediaT)}</span>
          <span>
            {frame ? `SMP ${String(frame.index).padStart(2, "0")} · F${String(frame.frame_id).padStart(6, "0")}` : "F ------"}
          </span>
        </span>
        <span className="flex flex-col items-end gap-0.5 text-right">
          <span>
            HDG {deg(camera.heading_deg)} · FOV {camera.fov_deg != null ? `${camera.fov_deg}°` : "—"}
          </span>
          <span>
            OBS {run?.observationCount ?? 0}
            {run?.sampleFps ? ` · ${run.sampleFps.toFixed(1)} FPS` : ""}
            {camera.time_offset_s ? ` · Δ${camera.time_offset_s.toFixed(2)}S` : ""}
          </span>
        </span>
      </div>
    </figure>
  );
}
