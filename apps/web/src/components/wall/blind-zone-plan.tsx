"use client";

import dynamic from "next/dynamic";
import { Component, useEffect, useRef, useState, type ReactNode } from "react";

import { Panel } from "@/components/hud/panel";
import { apiUrl } from "@/lib/config";
import { motionPath, type CvMapping, type CvZone, type MotionSeries } from "@/lib/cv-map";
import type { DepthRelief } from "@/lib/depth-relief";
import { fetchDepth, fetchMotion, sourcePath, type WallCamera } from "@/lib/wall";
import { cn } from "@/lib/utils";

import type { TileRun } from "./use-wall-orchestrator";

/** Drawing frame when a run has no video record (boxes are normalized, so only the grid uses it);
 * the size label is then hidden rather than claimed. */
const FRAME: [number, number] = [1920, 1080];
const STRIP_W = 1000;
const STRIP_H = 100;
/** A camera with no depth grid yet (API restarting, file not there) is asked again this often while shown in 3D. */
const DEPTH_RETRY_MS = 6000;

const STAGE: Record<CvZone["stage"], { stroke: string; fill: string; dash?: string; width: number; tag: string }> = {
  marked: { stroke: "rgba(241,241,239,0.5)", fill: "rgba(241,241,239,0.03)", dash: "6 5", width: 1, tag: "text-fg/70" },
  flagged: { stroke: "var(--warning)", fill: "rgba(255,179,64,0.07)", width: 1.25, tag: "text-warning" },
  confirmed: { stroke: "var(--danger)", fill: "rgba(255,69,58,0.18)", width: 2, tag: "text-danger" },
};

/** Grid lines every 120 source px, majors every 480 (a 16x9 grid on 1920x1080). */
function Grid({ w, h }: { w: number; h: number }) {
  const lines: { x1: number; y1: number; x2: number; y2: number; major: boolean }[] = [];
  for (let x = 120; x < w; x += 120) lines.push({ x1: x, y1: 0, x2: x, y2: h, major: x % 480 === 0 });
  for (let y = 120; y < h; y += 120) lines.push({ x1: 0, y1: y, x2: w, y2: y, major: y % 480 === 0 });
  return (
    <g>
      {lines.map(({ x1, y1, x2, y2, major }) => (
        <line
          key={`${x1}-${y1}-${x2}-${y2}`}
          x1={x1}
          y1={y1}
          x2={x2}
          y2={y2}
          stroke={major ? "rgba(255,255,255,0.13)" : "rgba(255,255,255,0.05)"}
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </g>
  );
}

/** The marked areas in the camera's own frame, exactly where the CV pass put them. */
function FramePlan({ cv }: { cv: CvMapping }) {
  const [w, h] = cv.source ?? FRAME;
  const crops = cv.evidence.filter((e) => e.box);
  // confirmed on top, then flagged, then the rest
  const order = [...cv.zones].sort((a, b) => rank(a.stage) - rank(b.stage) || a.number - b.number);
  return (
    <div className="relative aspect-video w-full border border-line bg-[#030303]" data-testid="plan-frame">
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="absolute inset-0 size-full" aria-hidden>
        <Grid w={w} h={h} />
        {crops.map((e) => {
          const [x0, y0, x1, y1] = e.box!;
          return (
            <rect
              key={e.id}
              x={x0 * w}
              y={y0 * h}
              width={(x1 - x0) * w}
              height={(y1 - y0) * h}
              fill="none"
              stroke="rgba(241,241,239,0.16)"
              strokeDasharray="2 4"
              vectorEffect="non-scaling-stroke"
            />
          );
        })}
        {order.map((z) => {
          const s = STAGE[z.stage];
          const [x0, y0, x1, y1] = z.box;
          return (
            <rect
              key={z.id}
              data-testid="plan-zone"
              data-stage={z.stage}
              x={x0 * w}
              y={y0 * h}
              width={(x1 - x0) * w}
              height={(y1 - y0) * h}
              fill={s.fill}
              stroke={s.stroke}
              strokeWidth={s.width}
              strokeDasharray={s.dash}
              vectorEffect="non-scaling-stroke"
            />
          );
        })}
      </svg>
      {order.map((z) => {
        const [x0, y0] = z.box;
        return (
          <span
            key={z.id}
            className={cn(
              "absolute bg-bg/80 px-[3px] text-[8px] leading-[11px] font-bold tracking-[0.08em] whitespace-nowrap",
              STAGE[z.stage].tag,
            )}
            style={{ left: `${x0 * 100}%`, top: `${y0 * 100}%`, transform: y0 > 0.04 ? "translateY(-100%)" : undefined }}
          >
            {z.id}
            {/* edge contours are the default seed; only a YOLO-seeded area is called out */}
            {z.sourceKind === "yolo" ? <span className="ml-1 font-normal opacity-70">YOLO</span> : null}
          </span>
        );
      })}
      <span className="micro absolute top-0.5 left-1 text-fg/40">0,0</span>
      {cv.source ? (
        <span className="micro absolute right-1 bottom-0.5 text-fg/40 tabular-nums">
          {w},{h}
        </span>
      ) : null}
    </div>
  );
}

const rank = (s: CvZone["stage"]) => (s === "marked" ? 0 : s === "flagged" ? 1 : 2);

function PlanNote({ text }: { text: string }) {
  return (
    <div className="dot-field flex aspect-video w-full items-center justify-center border border-line">
      <span className="tele text-fg/60">{text}</span>
    </div>
  );
}

// three.js only runs in the browser, and only loads once the 3D view is shown
const DepthReliefView = dynamic(() => import("./depth-relief-view").then((m) => m.DepthReliefView), {
  ssr: false,
  loading: () => <PlanNote text="Loading 3D view" />,
});

type View = "3d" | "2d";

/** If the 3D view throws (no WebGL, a lost context), this camera falls back to the flat plan. */
class ReliefBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/** Square header toggle; aria-pressed carries its state for keyboards and screen readers. */
function HeaderButton({
  on,
  label,
  onClick,
  children,
  testId,
  value,
}: {
  on: boolean;
  label: string;
  onClick: () => void;
  children: ReactNode;
  testId: string;
  value: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      aria-label={label}
      onClick={onClick}
      data-testid={testId}
      data-value={value}
      className={cn(
        "h-[17px] min-w-[17px] border px-1 leading-none tabular-nums transition-colors focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-1 focus-visible:outline-fg",
        on ? "border-fg bg-fg text-bg" : "border-line-strong text-fg/60 hover:border-fg/60 hover:text-fg",
      )}
    >
      {children}
    </button>
  );
}

/** Real per-frame motion with a tick per evidence frame and a playhead locked to the tile's video. */
function MotionStrip({ clipId, cv, motion }: { clipId: string; cv: CvMapping; motion: MotionSeries | null | undefined }) {
  const head = useRef<HTMLSpanElement>(null);
  const span = cv.durationS && cv.durationS > 0 ? cv.durationS : motion?.t.at(-1) || 1;

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const v = document.querySelector<HTMLVideoElement>(`[data-testid="cctv-tile"][data-clip="${CSS.escape(clipId)}"] video`);
      if (head.current && v && Number.isFinite(v.currentTime)) {
        head.current.style.left = `${Math.min(100, (v.currentTime / span) * 100)}%`;
        head.current.style.opacity = "1";
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [clipId, span]);

  const path = motion ? motionPath(motion, span, STRIP_W, STRIP_H) : "";
  return (
    <div className="flex flex-col gap-0.5" data-testid="plan-motion">
      <div className="micro flex justify-between text-fg/55">
        <span>MOTION / FRAME · {motion ? `${motion.t.length} FR` : "—"}</span>
        <span className="tabular-nums">PEAK {motion ? `${(motion.peak * 100).toFixed(2)}%` : "—"}</span>
      </div>
      <div className="relative h-10 border border-line bg-fg/[0.015]">
        {path ? (
          <svg viewBox={`0 0 ${STRIP_W} ${STRIP_H}`} preserveAspectRatio="none" className="absolute inset-0 size-full" aria-hidden>
            <path d={`${path}L${STRIP_W} ${STRIP_H}L0 ${STRIP_H}Z`} fill="rgba(241,241,239,0.07)" />
            <path d={path} fill="none" stroke="rgba(241,241,239,0.75)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
          </svg>
        ) : motion === null ? (
          <span className="micro absolute inset-0 flex items-center justify-center text-fg/40">NO MOTION RECORD</span>
        ) : null}
        <span ref={head} aria-hidden className="absolute inset-y-0 w-px bg-danger opacity-0" />
      </div>
      <div className="relative h-2" aria-hidden>
        {cv.evidence.map((e) => (
          <span
            key={e.id}
            className={cn("absolute top-0 w-px", e.kind === "zone crop" ? "h-2 bg-fg/70" : "h-1 bg-fg/35")}
            style={{ left: `${Math.min(100, (e.t / span) * 100)}%` }}
          />
        ))}
      </div>
      <div className="micro flex justify-between text-fg/45 tabular-nums">
        <span>0S</span>
        <span>{cv.imagesSent != null ? `${cv.imagesSent} IMAGES → QWEN` : ""}</span>
        <span>{span.toFixed(1)}S</span>
      </div>
    </div>
  );
}

function Legend() {
  const items: [string, string][] = [
    ["border border-dashed border-fg/50", "MARKED BY CV"],
    ["border border-warning bg-warning/10", "FLAGGED BY QWEN"],
    ["border-2 border-danger bg-danger/20", "CONFIRMED"],
  ];
  return (
    <div className="micro flex flex-wrap gap-x-3 gap-y-0.5 text-fg/55">
      {items.map(([sw, label]) => (
        <span key={label} className="flex items-center gap-1">
          <span className={cn("inline-block size-2", sw)} aria-hidden />
          {label}
        </span>
      ))}
    </div>
  );
}

/**
 * 03: one camera's blind-zone plan. Every area the CV pass marked is drawn where it marked it,
 * styled by how far it got (marked, flagged by Qwen, confirmed after the audit), with the
 * pipeline's own counts, detector and per-frame motion. 3D drapes the clip over a relative depth
 * map precomputed from one real frame (display only: no review reads it); 2D is the flat
 * image-space plan. The wall clips carry no camera calibration, so neither view claims metres, a
 * floor plan or a field of view.
 */
export function BlindZonePlanPanel({
  cameras,
  cam,
  run,
  onPick,
  className,
}: {
  cameras: WallCamera[];
  cam: WallCamera | null;
  run: TileRun | null;
  onPick: (clipId: string) => void;
  className?: string;
}) {
  const cv = run?.phase === "done" ? (run.result?.cv ?? null) : null;
  const clipId = cam?.clip_id ?? null;
  const [view, setView] = useState<View>("3d");
  const [motion, setMotion] = useState<{ clip: string; series: MotionSeries | null } | null>(null);
  const [reliefs, setReliefs] = useState<Record<string, DepthRelief | null>>({});

  useEffect(() => {
    if (!clipId || !cv) return;
    const ctrl = new AbortController();
    fetchMotion(clipId, ctrl.signal)
      .then((series) => setMotion({ clip: clipId, series }))
      .catch(() => {
        if (!ctrl.signal.aborted) setMotion({ clip: clipId, series: null });
      });
    return () => ctrl.abort();
  }, [clipId, cv]);

  // A grid once loaded is kept. A miss is not final: while that camera is shown in 3D it is asked
  // again every DEPTH_RETRY_MS (each answer stores a new object, which re-runs this effect).
  useEffect(() => {
    if (!clipId || view !== "3d" || reliefs[clipId]) return;
    const ctrl = new AbortController();
    const timer = setTimeout(
      () => {
        fetchDepth(clipId, ctrl.signal)
          .then((relief) => setReliefs((prev) => ({ ...prev, [clipId]: relief })))
          .catch(() => {
            if (!ctrl.signal.aborted) setReliefs((prev) => ({ ...prev, [clipId]: null }));
          });
      },
      clipId in reliefs ? DEPTH_RETRY_MS : 0,
    );
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [clipId, view, reliefs]);

  // undefined while this clip's file loads, so a focus change never flashes "no record"
  const series = motion && motion.clip === clipId ? motion.series : undefined;
  const relief = clipId ? reliefs[clipId] : undefined;
  const f = cv?.funnel;

  let frame: ReactNode = null;
  if (cam && cv) {
    if (view === "2d" || relief === null) frame = <FramePlan cv={cv} />;
    else if (relief)
      frame = (
        <ReliefBoundary
          key={cam.clip_id}
          fallback={
            <>
              <FramePlan cv={cv} />
              <span className="micro -mt-1 text-fg/45">3D VIEW UNAVAILABLE HERE · IMAGE SPACE</span>
            </>
          }
        >
          <DepthReliefView clipId={cam.clip_id} videoSrc={apiUrl(sourcePath(cam.clip_id))} relief={relief} zones={cv.zones} />
        </ReliefBoundary>
      );
    else frame = <PlanNote text="Loading depth" />;
  }

  return (
    <Panel
      index="03"
      title="Blind-zone plan"
      className={className}
      meta={
        <>
          <span className="flex items-center gap-[3px]" role="group" aria-label="Camera">
            <span className="mr-0.5 text-fg/50">CAM</span>
            {cameras.map((c) => (
              <HeaderButton
                key={c.clip_id}
                on={c.clip_id === clipId}
                label={`Show camera ${c.cam}`}
                onClick={() => onPick(c.clip_id)}
                testId="plan-cam"
                value={String(c.cam)}
              >
                {c.cam}
              </HeaderButton>
            ))}
          </span>
          <span className="flex items-center" role="group" aria-label="View">
            {(["3d", "2d"] as const).map((v) => (
              <HeaderButton
                key={v}
                on={view === v}
                label={v === "3d" ? "3D depth view" : "2D image-space view"}
                onClick={() => setView(v)}
                testId="plan-view"
                value={v}
              >
                {v.toUpperCase()}
              </HeaderButton>
            ))}
          </span>
        </>
      }
    >
      <div
        className="flex flex-col gap-1.5 px-2.5 pt-2 pb-2"
        data-testid="blind-zone-plan"
        data-clip={clipId ?? ""}
        data-view={view}
      >
        {cam && cv ? (
          <>
            {frame}
            {view === "3d" && relief === null ? (
              <span className="micro -mt-1 text-fg/45">NO DEPTH MAP FOR THIS CAMERA · IMAGE SPACE</span>
            ) : null}
            <Legend />
            <div className="flex items-baseline gap-1.5 text-[10px] tracking-[0.1em] text-fg/80 tabular-nums" data-testid="plan-funnel">
              <span>
                <b className="text-fg">{f?.proposals ?? "—"}</b> PROPOSALS
              </span>
              <span className="text-fg/35">→</span>
              <span>
                <b className="text-fg">{f?.areas}</b> AREAS
              </span>
              <span className="text-fg/35">→</span>
              <span className="text-warning">
                <b>{f?.flagged}</b> FLAGGED
              </span>
              <span className="text-fg/35">→</span>
              <span className={f?.confirmed ? "text-danger" : "text-fg/60"}>
                <b>{f?.confirmed}</b> CONFIRMED
              </span>
            </div>
            <div className="micro truncate text-fg/55 tabular-nums" data-testid="plan-detector">
              {[
                cv.detector ? `${cv.detector.model} · ${cv.detector.device}` : null,
                cv.detector?.ms != null ? `${Math.round(cv.detector.ms)} MS` : null,
                cv.frames != null ? `${cv.frames} FR` : null,
                cv.analysis ? `@ ${cv.analysis[0]}×${cv.analysis[1]}` : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </div>
            <MotionStrip clipId={cam.clip_id} cv={cv} motion={series} />
          </>
        ) : (
          <PlanNote text={cam ? "Plan draws when this camera's check finishes" : "Awaiting first check"} />
        )}
      </div>
    </Panel>
  );
}
