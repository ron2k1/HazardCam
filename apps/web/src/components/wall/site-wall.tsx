"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AlertFrame } from "@/components/alerts/alert-frame";
import { DetectionPopoutStack, type DetectionPopoutItem } from "@/components/alerts/detection-popout";

import { CornerTicks } from "@/components/hud/panel";
import { LIVE } from "@/lib/config";
import {
  fetchRuntime,
  fetchWall,
  configured,
  reasoningHref,
  stackLine,
  viewHref,
  WALL,
  wallCameras,
  type RuntimeStatus,
  type WallCamera,
  type WallConfig,
} from "@/lib/wall";
import { cn } from "@/lib/utils";

import { CctvTile } from "./cctv-tile";
import type { WallNotification } from "./use-wall-orchestrator";
import { NotificationTray, Toasts } from "./notification-tray";
import { useWallOrchestrator } from "./use-wall-orchestrator";
import { WallHeader } from "./wall-header";

// Defaults until GET /api/wall answers; config/wall.yaml holds the same words.
const WALL_TITLE = "Site cameras · Factory floor";
const HAZARD_TITLE = "Hazard watch";
const BLINDSPOT_TITLE = "Blind spot watch · Warehouse";

function RowTitle({ title, cams, className }: { title: string; cams: WallCamera[]; className?: string }) {
  const range = cams.length ? `CAM ${cams[0].cam}${cams.length > 1 ? `–${cams[cams.length - 1].cam}` : ""}` : "";
  return (
    <header className={cn("flex h-7 shrink-0 items-center justify-between gap-3 px-2.5", className)}>
      <h2 className="flex min-w-0 items-center gap-2 text-[10px] tracking-[0.18em] text-fg uppercase">
        <span className="h-px w-3 shrink-0 bg-line-strong" aria-hidden />
        <span className="truncate">{title}</span>
      </h2>
      <span className="micro shrink-0">{range}</span>
    </header>
  );
}

function RowMessage({ text }: { text: string }) {
  return (
    <div className="dot-field relative flex min-h-[180px] flex-1 items-center justify-center border border-line">
      <CornerTicks />
      <p className="tele text-fg/70" data-testid="row-message">
        {text}
      </p>
    </div>
  );
}

const sameConfig = (a: WallConfig | null, b: WallConfig) => !!a && JSON.stringify(a) === JSON.stringify(b);

/**
 * "/" — the site camera wall. Six CCTV feeds play the stored clips' raw footage. The safety agent
 * starts each camera's check by itself; a result appears on a tile only after its check completes,
 * and every word of it comes from that clip's stored run through the API.
 */
export function SiteWall() {
  const [config, setConfig] = useState<WallConfig | null>(null);
  const [offline, setOffline] = useState(false);
  const [loadedAt, setLoadedAt] = useState<number | null>(null);
  const [watching, setWatching] = useState(false);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);

  // Wall config: GET /api/wall (or the clip list until that route exists). Re-read while the
  // blind-spot row is still empty, so its cameras join as soon as they are prepared.
  useEffect(() => {
    const ctrl = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;
    const load = async () => {
      try {
        const { config: next } = await fetchWall(ctrl.signal);
        if (ctrl.signal.aborted) return;
        setConfig((prev) => (sameConfig(prev, next) ? prev : next));
        setOffline(false);
        setLoadedAt((prev) => prev ?? Date.now());
        if (!next.blindspot_tiles?.length) timer = setTimeout(load, WALL.configRetryMs);
      } catch {
        if (ctrl.signal.aborted) return;
        setOffline(true);
        timer = setTimeout(load, LIVE.offlinePollMs);
      }
    };
    timer = setTimeout(load, 0);
    return () => {
      ctrl.abort();
      if (timer !== null) clearTimeout(timer);
    };
  }, []);

  // GET /api/runtime/status every 15 s for the one-line stack status.
  useEffect(() => {
    const ctrl = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;
    const poll = async () => {
      try {
        const rt = await fetchRuntime(ctrl.signal);
        if (!ctrl.signal.aborted) setRuntime(rt);
      } catch {
        if (!ctrl.signal.aborted) setRuntime(null);
      }
      if (!ctrl.signal.aborted) timer = setTimeout(poll, WALL.runtimePollMs);
    };
    timer = setTimeout(poll, 0);
    return () => {
      ctrl.abort();
      if (timer !== null) clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    if (loadedAt === null) return;
    const t = setTimeout(() => setWatching(true), Math.max(0, loadedAt + WALL.watchingAfterS * 1000 - Date.now()));
    return () => clearTimeout(t);
  }, [loadedAt]);

  const cameras = useMemo(() => (config ? wallCameras(config) : []), [config]);
  const hazardCams = cameras.filter((c) => c.kind === "hazard");
  const blindCams = cameras.filter((c) => c.kind === "blindspot");
  const { runs, notifications, toasts, dismissToast, retry, idle, site } = useWallOrchestrator(cameras, loadedAt);

  // Pop-outs: every new notification fires one; its tile keeps an amber frame until acknowledged.
  const seen = useRef<Set<string>>(new Set());
  const [popouts, setPopouts] = useState<DetectionPopoutItem[]>([]);
  const [unacked, setUnacked] = useState<Record<string, WallNotification>>({});
  useEffect(() => {
    const fresh = notifications.filter((n) => !seen.current.has(n.id) && n.detections.length > 0);
    if (!fresh.length) return;
    fresh.forEach((n) => seen.current.add(n.id));
    setPopouts((prev) => [...fresh.map(popoutItem).reverse(), ...prev].slice(0, 6));
    setUnacked((prev) => ({ ...prev, ...Object.fromEntries(fresh.map((n) => [n.clipId, n])) }));
  }, [notifications]);
  const ack = (clipId: string) => setUnacked((prev) => { const next = { ...prev }; delete next[clipId]; return next; });
  const framed = (cam: (typeof cameras)[number], tile: ReactNode) => {
    const n = unacked[cam.clip_id];
    const d = n?.detections[0];
    return (
      <AlertFrame
        key={cam.clip_id}
        active={Boolean(n)}
        label={d?.sign?.label}
        glyph={d?.sign?.glyph}
        tone={cam.kind === "blindspot" ? "blindspot" : "hazard"}
        className="grid min-h-0 min-w-0"
      >
        <div className="grid min-h-0 min-w-0" onPointerDown={() => ack(cam.clip_id)}>{tile}</div>
      </AlertFrame>
    );
  };

  const checked = cameras.filter((c) => runs[c.clip_id]?.phase === "done").length;
  const agentLine = watching && cameras.length
    ? `Safety agent watching ${cameras.length} camera${cameras.length === 1 ? "" : "s"}`
    : "Safety agent starting…";
  const wallTitle = configured(config?.title, WALL_TITLE);
  const hazardTitle = configured(config?.hazard_title, HAZARD_TITLE);
  const blindTitle = configured(config?.blindspot_title, BLINDSPOT_TITLE);

  return (
    <div className="flex min-h-dvh flex-col bg-bg xl:h-dvh xl:min-h-[700px]">
      <WallHeader
        title={wallTitle}
        agentLine={agentLine}
        agentActive={watching && cameras.length > 0}
        stack={stackLine(runtime)}
        checked={checked}
        total={cameras.length}
        site={site}
      />

      <div className="flex min-h-0 flex-1 flex-col gap-3 px-4 py-3 lg:px-6 xl:flex-row">
        <div className="shrink-0 xl:order-last xl:w-[300px] 2xl:w-[340px]">
          <NotificationTray items={notifications} watching={watching} />
        </div>

        <main className="flex min-h-0 min-w-0 flex-1 flex-col gap-3" data-testid="camera-wall">
          {config === null ? (
            <RowMessage text={offline ? "Can't reach the camera system. Trying again…" : "Connecting to the cameras…"} />
          ) : (
            <>
              <section aria-label={hazardTitle} className="flex min-h-0 flex-1 flex-col" data-testid="hazard-row">
                <RowTitle title={hazardTitle} cams={hazardCams} className="px-0.5" />
                {hazardCams.length ? (
                  <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 md:grid-cols-3">
                    {hazardCams.map((cam) =>
                      framed(cam, <CctvTile cam={cam} run={runs[cam.clip_id] ?? idle} onRetry={() => retry(cam)} />),
                    )}
                  </div>
                ) : (
                  <RowMessage text="No camera clips are ready yet" />
                )}
              </section>

              <section
                aria-label={blindTitle}
                className="relative flex min-h-0 flex-1 flex-col border border-line bg-panel/40"
                data-testid="blindspot-strip"
              >
                <CornerTicks />
                <RowTitle title={blindTitle} cams={blindCams} className="border-b border-line" />
                {blindCams.length ? (
                  <div className="grid min-h-0 flex-1 grid-cols-1 divide-y divide-line md:grid-cols-3 md:divide-x md:divide-y-0">
                    {blindCams.map((cam) =>
                      framed(cam, <CctvTile cam={cam} run={runs[cam.clip_id] ?? idle} onRetry={() => retry(cam)} joined />),
                    )}
                  </div>
                ) : (
                  <div className="dot-field flex min-h-[160px] flex-1 items-center justify-center">
                    <p className="tele text-fg/70" data-testid="row-message">
                      Blind spot watch starting…
                    </p>
                  </div>
                )}
              </section>
            </>
          )}
        </main>
      </div>

      <Toasts items={toasts} onDismiss={dismissToast} />
      <DetectionPopoutStack
        items={popouts}
        onCollapse={(id) => setPopouts((prev) => prev.filter((p) => p.id !== id))}
        autoCollapseMs={5000}
        maxVisible={2}
      />
    </div>
  );
}

/** One pop-out per notification: sign, camera and zone only (no sentences). */
function popoutItem(n: WallNotification): DetectionPopoutItem {
  const d = n.detections[0];
  const blind = n.kind === "blindspot";
  return {
    id: n.id,
    kicker: blind ? "BLIND SPOT FOUND" : "HAZARD DETECTED",
    label: d?.sign?.label ?? (blind ? "BLIND SPOT" : "HAZARD"),
    glyph: d?.sign?.glyph,
    tone: blind ? "blindspot" : "hazard",
    cameraLabel: `CAM ${n.cam}`,
    zoneName: d?.zoneNames?.[0],
    timestamp: new Date(n.at).toLocaleTimeString([], { hour12: false }),
    viewHref: viewHref(n.clipId, n.jobId),
    reasoningHref: reasoningHref(n.clipId, n.jobId),
  };
}
