"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AlertFrame } from "@/components/alerts/alert-frame";
import { DetectionPopoutStack, type DetectionPopoutItem } from "@/components/alerts/detection-popout";

import { CornerTicks, Panel } from "@/components/hud/panel";
import { LIVE } from "@/lib/config";
import { configured, fetchWall, viewHref, WALL, wallCameras, type WallConfig } from "@/lib/wall";
import { cn } from "@/lib/utils";

import { AgentStrip } from "./agent-strip";
import { CctvTile } from "./cctv-tile";
import { NotificationTray, Toasts } from "./notification-tray";
import { useAgentLog } from "./use-agent-log";
import type { WallNotification } from "./use-wall-orchestrator";
import { useWallOrchestrator } from "./use-wall-orchestrator";
import { BlindZonePlanPanel } from "./blind-zone-plan";
import { AgentLogPanel, CheckTimelinePanel } from "./wall-panels";
import { WallHeader } from "./wall-header";

// Default until GET /api/wall answers; config/wall.yaml holds the same words.
const WALL_TITLE = "Site cameras · Factory floor";

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
 * "/" — the site camera wall. The CCTV feeds play the stored clips' raw footage. The safety agent
 * starts each camera's check by itself; a result appears on a tile only after its check completes,
 * and every word of it comes from that clip's stored run through the API.
 *
 * Layout (desktop): 00 the agent team (the lead and one checker per camera) over 01 the live
 * feeds in one grid; a right rail with 02 detections, 03 the blind-zone plan of one camera (the
 * latest alert, or the tile or checker last clicked), 04 the agent log of every check event, 05 a
 * timeline of the checks against wall time.
 */
export function SiteWall() {
  const [config, setConfig] = useState<WallConfig | null>(null);
  const [offline, setOffline] = useState(false);
  const [loadedAt, setLoadedAt] = useState<number | null>(null);
  const [watching, setWatching] = useState(false);

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

  useEffect(() => {
    if (loadedAt === null) return;
    const t = setTimeout(() => setWatching(true), Math.max(0, loadedAt + WALL.watchingAfterS * 1000 - Date.now()));
    return () => clearTimeout(t);
  }, [loadedAt]);

  const cameras = useMemo(() => (config ? wallCameras(config) : []), [config]);
  const { runs, notifications, toasts, dismissToast, retry, idle, site, direct, origin } = useWallOrchestrator(cameras, loadedAt);
  const log = useAgentLog(cameras, runs, site);

  // Pop-outs: every new notification fires one, once (remembered in this tab, so coming back to
  // the wall does not fire them again); its tile keeps an amber frame until acknowledged.
  const seen = useRef<Set<string>>(readPopped());
  const [popouts, setPopouts] = useState<DetectionPopoutItem[]>([]);
  const [unacked, setUnacked] = useState<Record<string, WallNotification>>({});
  useEffect(() => {
    const fresh = notifications.filter((n) => !seen.current.has(n.id) && n.detections.length > 0);
    if (!fresh.length) return;
    fresh.forEach((n) => seen.current.add(n.id));
    writePopped(seen.current);
    setPopouts((prev) => [...fresh.map(popoutItem).reverse(), ...prev].slice(0, 6));
    setUnacked((prev) => ({ ...prev, ...Object.fromEntries(fresh.map((n) => [n.clipId, n])) }));
  }, [notifications]);
  const ack = (clipId: string) => setUnacked((prev) => { const next = { ...prev }; delete next[clipId]; return next; });

  // 03 follows a clicked tile; until then the newest alert, else the camera that finished last.
  const [picked, setPicked] = useState<string | null>(null);
  const newestAlert = notifications.reduce<WallNotification | null>((a, n) => (!a || n.at > a.at ? n : a), null);
  const lastDone = cameras
    .filter((c) => runs[c.clip_id]?.phase === "done")
    .sort((a, b) => (runs[b.clip_id]?.finishedAt ?? 0) - (runs[a.clip_id]?.finishedAt ?? 0))[0];
  const planClip = picked ?? newestAlert?.clipId ?? lastDone?.clip_id ?? null;
  const planCam = cameras.find((c) => c.clip_id === planClip) ?? null;
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
        <div
          className={cn("relative grid min-h-0 min-w-0", planCam?.clip_id === cam.clip_id && "outline outline-1 -outline-offset-1 outline-fg/40")}
          onPointerDown={() => {
            ack(cam.clip_id);
            setPicked(cam.clip_id);
          }}
        >
          {tile}
        </div>
      </AlertFrame>
    );
  };

  const checked = cameras.filter((c) => runs[c.clip_id]?.phase === "done").length;
  const agentLine = watching && cameras.length
    ? `Safety agent watching ${cameras.length} camera${cameras.length === 1 ? "" : "s"}`
    : "Safety agent starting…";
  const wallTitle = configured(config?.title, WALL_TITLE);
  const alerts = notifications.length;

  return (
    <div className="grid-field flex min-h-dvh flex-col bg-bg xl:h-dvh xl:min-h-[700px]">
      <WallHeader
        title={wallTitle}
        agentLine={agentLine}
        agentActive={watching && cameras.length > 0}
        checked={checked}
        total={cameras.length}
      />

      <main className="flex min-h-0 flex-1 flex-col gap-3 px-4 py-3 lg:px-5 xl:flex-row">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
          <AgentStrip
            cameras={cameras}
            runs={runs}
            idle={idle}
            site={site}
            direct={direct}
            focusClip={planCam?.clip_id ?? null}
            onPick={setPicked}
          />
        <Panel
          index="01"
          title="Live feeds"
          className="min-h-0 flex-1 bg-panel/60"
          bodyClassName="flex flex-col"
          meta={
            <>
              <span className="tabular-nums">{cameras.length} FEEDS</span>
              <span className="tabular-nums">
                {checked}/{cameras.length} CHECKED
              </span>
              <span className={cn("tabular-nums", alerts ? "text-danger" : "")}>{alerts} ALERT</span>
            </>
          }
        >
          <div className="flex min-h-0 flex-1 flex-col p-2" data-testid="camera-wall">
            {config === null ? (
              <RowMessage text={offline ? "Can't reach the camera system. Trying again…" : "Connecting to the cameras…"} />
            ) : cameras.length ? (
              <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 md:grid-cols-2 xl:grid-rows-2" data-testid="hazard-row">
                {cameras.map((cam) =>
                  framed(cam, <CctvTile cam={cam} run={runs[cam.clip_id] ?? idle} onRetry={() => retry(cam)} />),
                )}
              </div>
            ) : (
              <RowMessage text="No camera clips are ready yet" />
            )}
          </div>
        </Panel>
        </div>

        <div className="flex min-h-0 shrink-0 flex-col gap-3 xl:w-[400px] 2xl:w-[440px]">
          <NotificationTray items={notifications} watching={watching} className="min-h-[150px] xl:flex-[1_1_0%]" />
          <BlindZonePlanPanel
            cameras={cameras}
            cam={planCam}
            run={planCam ? (runs[planCam.clip_id] ?? null) : null}
            onPick={setPicked}
            className="shrink-0"
          />
          <AgentLogPanel
            rows={log}
            origin={origin}
            emptyText={checked ? "Checks ran before this visit" : "Awaiting first check"}
            className="min-h-[200px] xl:flex-[1_1_0%]"
          />
          <CheckTimelinePanel cameras={cameras} runs={runs} origin={origin} className="shrink-0" />
        </div>
      </main>

      {/* Detections already pop out once; toasts only carry the rest (errors, retries). */}
      <Toasts items={toasts.filter((t) => !t.detection)} onDismiss={dismissToast} />
      <DetectionPopoutStack
        items={popouts}
        onCollapse={(id) => setPopouts((prev) => prev.filter((p) => p.id !== id))}
        autoCollapseMs={6000}
        maxVisible={1}
      />
    </div>
  );
}

const POPPED_KEY = "cv-wall-popped-v1";

function readPopped(): Set<string> {
  try {
    const raw = typeof window === "undefined" ? null : window.sessionStorage.getItem(POPPED_KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

function writePopped(ids: Set<string>) {
  try {
    window.sessionStorage.setItem(POPPED_KEY, JSON.stringify([...ids]));
  } catch {
    /* storage blocked: pop-outs may show again after a reload */
  }
}

/** One pop-out per notification: sign, camera, zone and one short paragraph. */
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
    detail: d?.explain || undefined,
    timestamp: new Date(n.at).toLocaleTimeString([], { hour12: false }),
    viewHref: viewHref(n.clipId, n.jobId),
  };
}
