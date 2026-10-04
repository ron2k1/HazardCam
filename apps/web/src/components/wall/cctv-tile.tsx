"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { HazardText } from "@/components/alerts/hazard-terms";
import { StatusDot } from "@/components/hud/barcode";
import { useMounted } from "@/hooks/use-animate";
import { apiUrl } from "@/lib/config";
import {
  configured,
  elapsedClock,
  kindWord,
  timeOfDay,
  viewHref,
  type Detection,
  type WallCamera,
  type ZoneMark,
} from "@/lib/wall";
import { cn } from "@/lib/utils";

import { BlindSpotTriangle, DetectionSign, isBlindspotSign, WarningTriangle } from "./blind-spot-sign";
import { Brackets, FeedTelemetry, Reticle, Stamp } from "./tile-hud";
import type { TileRun } from "./use-wall-orchestrator";
import { useNow } from "./use-now";

type Signal = "connecting" | "live" | "nosignal";

function Elapsed({ since }: { since: number }) {
  const now = useNow(1000);
  return <span className="tabular-nums">{elapsedClock((now?.getTime() ?? since) - since)}</span>;
}

/** Where the video's picture actually sits inside its box (object-contain maths: never cropped). */
function pictureRect(box: { w: number; h: number } | null, video: { w: number; h: number } | null) {
  if (!box || !video || !box.w || !box.h || !video.w || !video.h) return null;
  const scale = Math.min(box.w / video.w, box.h / video.h);
  const w = video.w * scale;
  const h = video.h * scale;
  return { left: (box.w - w) / 2, top: (box.h - h) / 2, width: w, height: h };
}

function ZoneOutlines({ zones, blindspot }: { zones: ZoneMark[]; blindspot: boolean }) {
  return (
    <>
      {zones.map((z) => {
        const [x0, y0, x1, y1] = z.box;
        const tagInside = y0 < 0.09;
        // keep the tag on the picture: zones near the right edge carry it on their right side
        const tagRight = x0 > 0.78;
        const eye = blindspot || isBlindspotSign(blindspot ? "blindspot" : "hazard", z.sign);
        return (
          <div
            key={z.number}
            data-testid="tile-zone"
            className="absolute border border-warning shadow-[0_0_0_1px_rgba(5,5,5,0.55)] duration-500 animate-in fade-in"
            style={{
              left: `${x0 * 100}%`,
              top: `${y0 * 100}%`,
              width: `${(x1 - x0) * 100}%`,
              height: `${(y1 - y0) * 100}%`,
            }}
          >
            <span
              className={cn(
                "absolute flex h-4 items-center gap-1 bg-bg/85 pr-1.5 pl-0.5 text-[9px] leading-none font-bold tracking-[0.14em] whitespace-nowrap text-warning",
                tagInside ? "top-0" : "bottom-full",
                tagRight ? "-right-px" : "-left-px",
              )}
            >
              {eye ? <BlindSpotTriangle className="size-3" /> : <WarningTriangle glyph={z.sign?.glyph} className="size-3" />}
              {z.name.toUpperCase()}
            </span>
          </div>
        );
      })}
    </>
  );
}

function Feed({
  src,
  zones,
  blindspot,
  onVideo,
}: {
  src: string;
  zones: ZoneMark[];
  blindspot: boolean;
  /** Hands the tile the playing element, for the HUD telemetry. */
  onVideo: (el: HTMLVideoElement | null) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement | null>(null);
  const attach = useCallback(
    (el: HTMLVideoElement | null) => {
      video.current = el;
      onVideo(el);
    },
    [onVideo],
  );
  const [signal, setSignal] = useState<Signal>("connecting");
  const [box, setBox] = useState<{ w: number; h: number } | null>(null);
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null);

  useEffect(() => {
    const v = video.current;
    if (!v) return;
    // muted must be a property before play() for autoplay to be allowed
    v.muted = true;
    v.play().catch(() => {});
  }, [src]);

  useEffect(() => {
    const el = wrap.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => {
      const r = entry.contentRect;
      setBox({ w: r.width, h: r.height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const rect = pictureRect(box, dims);

  return (
    <div ref={wrap} className="dot-field absolute inset-0 overflow-hidden bg-[#020202]">
      <video
        ref={attach}
        src={src}
        autoPlay
        muted
        loop
        playsInline
        preload="auto"
        aria-hidden
        tabIndex={-1}
        data-testid="tile-video"
        className="absolute inset-0 size-full object-contain grayscale-[35%] contrast-[1.05]"
        onLoadedMetadata={(e) => setDims({ w: e.currentTarget.videoWidth, h: e.currentTarget.videoHeight })}
        onPlaying={() => setSignal("live")}
        onError={() => setSignal("nosignal")}
      />
      {zones.length ? (
        <div
          className="pointer-events-none absolute"
          style={rect ?? { left: 0, top: 0, width: "100%", height: "100%" }}
          data-testid="tile-zones"
        >
          <ZoneOutlines zones={zones} blindspot={blindspot} />
        </div>
      ) : null}
      {signal !== "live" ? (
        <div className="dot-field absolute inset-0 flex items-center justify-center bg-[#020202]/80">
          <span className="tele text-fg/70">{signal === "nosignal" ? "NO SIGNAL" : "CONNECTING…"}</span>
        </div>
      ) : null}
    </div>
  );
}

/** Detection rows a tile lists; the rest are one click away in View. */
const ROWS_SHOWN = 3;

/** One sign per distinct label, in the API's order (highest priority first). */
function distinctSigns(list: Detection[]): Detection[] {
  const seen = new Set<string>();
  return list.filter((d) => {
    const k = d.sign?.label ?? "";
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

const PRIORITY_TONE: Record<string, string> = {
  high: "border-danger/70 text-danger",
  medium: "border-warning/70 text-warning",
  low: "border-line-strong text-fg/75",
};

function PriorityTag({ priority }: { priority: string }) {
  const key = priority.toLowerCase();
  if (!PRIORITY_TONE[key]) return null;
  return (
    <span className={cn("shrink-0 border px-1 text-[9px] leading-[14px] font-bold tracking-[0.14em] uppercase", PRIORITY_TONE[key])}>
      {priority}
    </span>
  );
}

function StepTrack({ step, total }: { step: number; total: number }) {
  return (
    <span className="flex gap-[3px]" aria-hidden>
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          className={cn(
            "h-[3px] flex-1",
            i + 1 < step ? "bg-fg/80" : i + 1 === step ? "bg-fg blink" : "bg-line-strong/60",
          )}
        />
      ))}
    </span>
  );
}

function Readout({ cam, run, onRetry }: { cam: WallCamera; run: TileRun; onRetry: () => void }) {
  const words = kindWord(cam.kind);
  const linkCls = "tele inline-flex h-6 items-center border px-2 text-fg/90 hover:bg-fg hover:text-bg";

  if (run.phase === "watching") {
    return (
      <div className="flex flex-col gap-2" data-testid="tile-readout" data-phase="watching">
        <p className="flex items-center gap-2 text-[11px] text-fg/80">
          <StatusDot tone="muted" />
          Watching
        </p>
        <p className="micro">Safety check starts on its own</p>
      </div>
    );
  }

  if (run.phase === "checking") {
    return (
      <div className="flex flex-col gap-1.5" data-testid="tile-readout" data-phase="checking">
        <p className="flex items-center justify-between gap-2 text-[11px] font-bold tracking-[0.08em] text-fg">
          <span className="flex items-center gap-2">
            <StatusDot tone="fg" pulse />
            Checking…
          </span>
          {run.startedAt ? (
            <span className="micro text-fg/70">
              <Elapsed since={run.startedAt} />
            </span>
          ) : null}
        </p>
        <StepTrack step={run.step} total={run.total} />
        <p className="truncate text-[11px] text-fg/75">
          {run.stepWord ? `${run.stepWord}…` : "Starting the check…"}
          {run.step > 0 ? <span className="text-muted"> · step {run.step} of {run.total}</span> : null}
        </p>
        {/* Agent narration lives in the agent log panel and the reasoning tab, not on the tile. */}
      </div>
    );
  }

  if (run.phase === "failed") {
    return (
      <div className="flex flex-col gap-2" data-testid="tile-readout" data-phase="failed">
        <p className="text-[11px] font-bold text-fg">Check didn&apos;t finish</p>
        <p className="line-clamp-2 text-[11px] text-fg/70">{run.error}</p>
        <button type="button" onClick={onRetry} className={cn(linkCls, "self-start border-line-strong")}>
          Try again
        </button>
      </div>
    );
  }

  const result = run.result;
  const detections = result?.detections ?? [];
  const smallLink = "micro inline-flex h-5 items-center border px-1.5 text-fg/90 hover:bg-fg hover:text-bg";
  const links =
    run.jobId !== null ? (
      <span className="flex shrink-0 gap-1">
        <Link href={viewHref(cam.clip_id, run.jobId)} className={cn(smallLink, "border-line-strong")} data-testid="tile-view">
          View
        </Link>
      </span>
    ) : null;

  if (!detections.length) {
    return (
      <div className="flex flex-col gap-1.5" data-testid="tile-readout" data-phase="clear">
        <p className="flex flex-wrap items-center justify-between gap-2 text-[12px] text-fg/85">
          <span className="flex items-center gap-2">
            <StatusDot tone="muted" />
            {words.none}
          </span>
          {links}
        </p>
        {run.finishedAt ? <p className="micro">Checked at {timeOfDay(new Date(run.finishedAt))}</p> : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5" data-testid="tile-readout" data-phase="found">
      <p className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 text-[11px] font-bold tracking-[0.06em] text-warning">
        <span>
          {detections.length} {detections.length === 1 ? words.one : words.many} found
        </span>
        {links}
      </p>
      <ul className="flex flex-col gap-1">
        {detections.slice(0, ROWS_SHOWN).map((d) => {
          const line = `${d.zoneNames.length ? `${d.zoneNames.join(", ")} · ` : ""}${d.shortTitle}`;
          return (
            <li key={d.key} className="flex min-w-0 items-center gap-1.5 text-[12px] leading-[16px]" data-testid="tile-detection">
              {cam.kind === "blindspot" || isBlindspotSign(cam.kind, d.sign) ? (
                <BlindSpotTriangle className="size-3.5" />
              ) : (
                <WarningTriangle glyph={d.sign?.glyph} className="size-3.5" />
              )}
              <span className="min-w-0 flex-1 truncate" title={line}>
                {d.zoneNames.length ? <span className="font-bold text-fg">{d.zoneNames[0]} · </span> : null}
                <span className="text-fg/85">
                  <HazardText text={d.shortTitle} />
                </span>
              </span>
              <PriorityTag priority={d.priority} />
            </li>
          );
        })}
      </ul>
      {detections.length > ROWS_SHOWN ? (
        <p className="micro text-fg/60">
          {detections.length - ROWS_SHOWN} more in View
        </p>
      ) : null}
    </div>
  );
}

export interface CctvTileProps {
  cam: WallCamera;
  run: TileRun;
  onRetry: () => void;
  /** Part of a joined strip: no own outer border. */
  joined?: boolean;
}

const PHASE: Record<TileRun["phase"], { label: string; tone: "fg" | "muted" | "dim" | "danger"; pulse: boolean }> = {
  watching: { label: "STANDBY", tone: "dim", pulse: false },
  checking: { label: "ANALYZING", tone: "fg", pulse: true },
  done: { label: "CLEAR", tone: "muted", pulse: false },
  failed: { label: "FAULT", tone: "danger", pulse: false },
};
const ALERT = { label: "ALERT", tone: "danger", pulse: true } as const;

/** A CCTV tile: the raw feed (no AI markings) with HUD telemetry, then its check readout. */
export function CctvTile({ cam, run, onRetry, joined = false }: CctvTileProps) {
  const mounted = useMounted();
  const [videoEl, setVideoEl] = useState<HTMLVideoElement | null>(null);
  const words = kindWord(cam.kind);
  const src = cam.source_url.startsWith("/api/") ? apiUrl(cam.source_url) : cam.source_url;
  const detections = run.phase === "done" ? (run.result?.detections ?? []) : [];
  const zones = run.phase === "done" ? (run.result?.zones ?? []) : [];
  const found = detections.length > 0;
  const blindspot = cam.kind === "blindspot";
  const phase = found ? ALERT : PHASE[run.phase];
  const fps = typeof cam.fps === "number" && cam.fps > 0 ? cam.fps : null;

  return (
    <article
      aria-label={`CAM ${cam.cam} · ${cam.title}`}
      data-testid="cctv-tile"
      data-cam={cam.cam}
      data-kind={cam.kind}
      data-phase={run.phase}
      className={cn("@container relative flex min-h-0 min-w-0 flex-col bg-panel/80 xl:h-full", !joined && "border border-line")}
    >
      {/* 16:9 when the page scrolls; on the desktop wall the monitor fills its grid cell (the picture is never cropped) */}
      <div className="relative aspect-video w-full shrink-0 overflow-hidden xl:aspect-auto xl:min-h-0 xl:flex-1">
        {mounted ? <Feed src={src} zones={zones} blindspot={blindspot} onVideo={setVideoEl} /> : <div className="absolute inset-0 bg-[#020202]" />}
        {run.phase === "checking" ? (
          <>
            <span className="scanline" aria-hidden />
            <Reticle />
          </>
        ) : null}
        {/* legibility gradients for the overlay text */}
        <span aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-14 bg-linear-to-b from-black/75 to-transparent" />
        <span aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 h-14 bg-linear-to-t from-black/70 to-transparent" />
        <Brackets />
        <div className="pointer-events-none absolute top-3 left-4 flex flex-col items-start gap-1 leading-none">
          <span className="flex items-baseline gap-2 bg-black/75 px-1 py-0.5">
            <span className="text-[13px] font-extrabold tracking-[0.1em] text-fg">CAM {cam.cam}</span>
            <span className="micro text-fg/55">IN/{String(cam.cam).padStart(2, "0")}</span>
          </span>
          <span className="micro max-w-[60cqw] truncate bg-black/75 px-1 text-fg/85">
            {configured(cam.watch, words.watch)} · {cam.title}
          </span>
        </div>
        <div className="pointer-events-none absolute top-3 right-4 flex flex-col items-end gap-1 leading-none">
          <span className="micro flex items-center gap-1.5 bg-black/75 px-1 text-fg/90">
            <StatusDot tone="danger" pulse />
            REC
            <span className="text-fg/70">
              <Stamp />
            </span>
          </span>
          <span
            className={cn("micro flex items-center gap-1.5 bg-black/75 px-1", found ? "text-danger" : "text-fg/90")}
            data-testid="tile-phase"
          >
            <StatusDot tone={phase.tone} pulse={phase.pulse} />
            {phase.label}
          </span>
        </div>
        {mounted ? <FeedTelemetry video={videoEl} fps={fps} /> : null}
        {found ? (
          <div className="pointer-events-none absolute bottom-12 left-4 flex max-w-[calc(100%-2rem)] flex-wrap gap-1 duration-500 animate-in fade-in">
            {distinctSigns(detections).map((d) => (
              <span key={d.key} className="bg-bg/85">
                <DetectionSign kind={cam.kind} sign={d.sign} />
              </span>
            ))}
          </div>
        ) : null}
      </div>
      <div className="thin-scroll min-h-[76px] shrink-0 overflow-y-auto border-t border-line px-3 py-2 xl:h-[78px]">
        <Readout cam={cam} run={run} onRetry={onRetry} />
      </div>
      {found ? (
        <span aria-hidden data-testid="tile-alert-frame" className="pointer-events-none absolute inset-0 border border-warning duration-500 animate-in fade-in" />
      ) : null}
    </article>
  );
}
