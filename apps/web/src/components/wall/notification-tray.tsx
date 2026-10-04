"use client";

import Link from "next/link";

import { HazardText } from "@/components/alerts/hazard-terms";
import { Panel } from "@/components/hud/panel";
import { kindWord, timeOfDay, viewHref, type Detection } from "@/lib/wall";
import { cn } from "@/lib/utils";

import { BlindSpotTriangle, DetectionSign, WarningTriangle } from "./blind-spot-sign";
import type { WallNotification, WallToast } from "./use-wall-orchestrator";

const EDGE: Record<string, string> = {
  high: "before:bg-danger",
  medium: "before:bg-warning",
  low: "before:bg-line-strong",
};

function topPriority(list: Detection[]): string {
  const order = ["high", "medium", "low"];
  const keys = list.map((d) => d.priority.toLowerCase());
  return order.find((k) => keys.includes(k)) ?? "low";
}

function NotificationCard({ n }: { n: WallNotification }) {
  const words = kindWord(n.kind);
  const linkCls = "tele inline-flex h-6 items-center border px-2 text-fg/90 hover:bg-fg hover:text-bg";
  return (
    <li
      data-testid="wall-notification"
      data-cam={n.cam}
      className={cn(
        "relative border border-line bg-panel py-2 pr-2.5 pl-3.5 duration-300 animate-in fade-in slide-in-from-right-3",
        "before:absolute before:inset-y-0 before:left-0 before:w-[3px]",
        EDGE[topPriority(n.detections)],
      )}
    >
      <p className="micro flex items-center justify-between gap-2">
        <span className="truncate text-fg/80">
          {words.watch} · CAM {n.cam}
        </span>
        <span className="shrink-0 tabular-nums">{timeOfDay(new Date(n.at))}</span>
      </p>
      <ul className="mt-1.5 flex flex-col gap-1.5">
        {n.detections.map((d) => (
          <li key={d.key} className="flex min-w-0 flex-col gap-0.5">
            <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              <DetectionSign kind={n.kind} sign={d.sign} />
              <span className="text-[11px] font-bold tracking-[0.08em] whitespace-nowrap text-fg">
                CAM {n.cam}
                {d.zoneNames.length ? ` · ${d.zoneNames[0]}` : ""}
              </span>
            </span>
            {d.shortTitle ? (
              <span className="text-[12px] leading-[16px] text-fg/80">
                <HazardText text={d.shortTitle} />
              </span>
            ) : null}
          </li>
        ))}
      </ul>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <Link href={viewHref(n.clipId, n.jobId)} className={cn(linkCls, "border-line-strong")} data-testid="notification-view">
          View
        </Link>
      </div>
    </li>
  );
}

/** 02: the detections the safety agent posted, newest first (right column on desktop). */
export function NotificationTray({ items, watching, className }: { items: WallNotification[]; watching: boolean; className?: string }) {
  return (
    <Panel
      index="02"
      title="Detections"
      className={className}
      bodyClassName="flex flex-col"
      meta={<span className={cn("tabular-nums", items.length && "text-danger")}>{items.length ? `${items.length} NEW` : "NONE"}</span>}
    >
      <div aria-label="Notifications" data-testid="notification-tray" className="flex min-h-0 flex-1 flex-col">
        {items.length ? (
          <ol aria-live="polite" className="thin-scroll flex max-h-[38vh] min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-2 xl:max-h-none">
            {items.map((n) => (
              <NotificationCard key={n.id} n={n} />
            ))}
          </ol>
        ) : (
          <div className="hatch flex flex-1 flex-col items-center justify-center gap-1.5 px-4 py-6 text-center">
            <span className="text-[11px] tracking-[0.3em] text-fg/70">{watching ? "NO DETECTIONS" : "STANDBY"}</span>
            <span className="micro max-w-[22rem] normal-case tracking-[0.04em]">
              {watching
                ? "The safety agent posts here when a camera check finds something."
                : "The safety agent is starting."}
            </span>
          </div>
        )}
      </div>
    </Panel>
  );
}

/** Brief toasts for new notifications (bottom of the screen; static under reduced motion). */
export function Toasts({ items, onDismiss }: { items: WallToast[]; onDismiss: (id: string) => void }) {
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-4 bottom-4 z-50 flex flex-col items-center gap-2 xl:inset-x-auto xl:right-4 xl:items-end"
    >
      {items.map((t) => (
        <button
          key={t.id}
          type="button"
          data-testid="wall-toast"
          onClick={() => onDismiss(t.id)}
          className="pointer-events-auto flex max-w-full items-center gap-2.5 border border-warning/70 bg-bg/95 px-3 py-2 text-left text-[12px] font-bold tracking-[0.06em] text-fg shadow-[0_0_0_1px_rgba(5,5,5,0.8)] duration-300 animate-in fade-in slide-in-from-bottom-2"
        >
          {t.kind === "blindspot" ? (
            <BlindSpotTriangle className="size-5" />
          ) : (
            <WarningTriangle glyph={t.detection?.sign?.glyph} className="size-5" />
          )}
          <span>{t.text}</span>
        </button>
      ))}
    </div>
  );
}
