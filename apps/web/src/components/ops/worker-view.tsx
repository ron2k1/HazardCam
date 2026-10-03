"use client";

import { useReducedMotion } from "motion/react";
import Link from "next/link";
import { useMemo, useRef, useState } from "react";

import { StatusDot } from "@/components/hud/barcode";
import type { ViewMode } from "@/hooks/use-view-mode";
import { apiUrl } from "@/lib/config";
import type { AlertMessage } from "@/lib/contracts";
import { clip } from "@/lib/format";
import {
  cameraNames,
  plainText,
  recordingName,
  seekTargets,
  workerProgress,
  type ProgressTone,
} from "@/lib/plain";
import { scenarioToMediaTime } from "@/lib/run-view";
import { cn } from "@/lib/utils";

import type { SeekRequest } from "./camera-tile";
import { MessageFeed } from "./message-feed";
import type { OpsConsoleProps } from "./ops-console";
import { ViewToggle } from "./view-toggle";
import { WorkerCamera } from "./worker-camera";

export interface WorkerViewProps extends OpsConsoleProps {
  onViewChange: (mode: ViewMode) => void;
}

const PROGRESS_TEXT: Record<ProgressTone, string> = {
  idle: "text-fg/80",
  busy: "text-fg",
  done: "text-fg",
  failed: "text-danger",
};

/**
 * The default /ops view for a frontline worker: plain-language message cards first, the camera
 * videos, one big Run button and a one-line progress readout. No ids, coordinates, scores or
 * model prose; everything technical stays behind the "Technical details" switch.
 */
export function WorkerView(props: WorkerViewProps) {
  const { scenario, view } = props;
  const cameras = useMemo(() => scenario?.cameras ?? [], [scenario]);
  const names = useMemo(() => cameraNames(cameras), [cameras]);
  const [seeks, setSeeks] = useState<Record<string, SeekRequest>>({});
  const [activeId, setActiveId] = useState<string | null>(null);
  const camerasRef = useRef<HTMLElement>(null);
  const reduce = useReducedMotion();

  // the server writes plain text; the card only hides a sentence that still leaks
  const clean = plainText;
  const progress = workerProgress(view, names);

  const targetsFor = (m: AlertMessage) => {
    const targets = seekTargets(m, view, cameras);
    const cam = targets[0] ? cameras.find((c) => c.id === targets[0].cameraId) : undefined;
    return { targets, firstMediaT: cam && targets[0] ? scenarioToMediaTime(cam, targets[0].t) : null };
  };

  const shown = view.messages.find((m) => m.id === activeId) ?? null;
  const highlighted = useMemo(
    () => new Set(shown ? seekTargets(shown, view, cameras).map((t) => t.cameraId) : []),
    [shown, view, cameras],
  );

  const showOnVideo = (m: AlertMessage) => {
    const targets = seekTargets(m, view, cameras);
    if (!targets.length) return;
    setActiveId(m.id);
    setSeeks((prev) => {
      const next = { ...prev };
      for (const t of targets) {
        const cam = cameras.find((c) => c.id === t.cameraId);
        if (cam) next[t.cameraId] = { t: scenarioToMediaTime(cam, t.t), nonce: (prev[t.cameraId]?.nonce ?? 0) + 1 };
      }
      return next;
    });
    for (const t of targets) props.onSeek?.(t.cameraId, t.t);
    // on a phone the videos are below the feed: bring the first one into view
    const first = camerasRef.current?.querySelector(`[data-camera-id="${CSS.escape(targets[0].cameraId)}"]`);
    first?.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
  };

  const media = (url: string | null, available: boolean) => (url && available ? apiUrl(url) : null);
  const running = view.phase === "running" || view.phase === "queued";
  const runDisabled = props.apiStatus === "offline" || !!props.runPending || running || !scenario;

  // plain-language banner; the technical wording stays in the technical view
  let banner: { tone: "danger" | "muted"; text: string } | null = null;
  if (props.apiStatus === "offline") banner = { tone: "danger", text: "Can't reach the camera system. Trying again on its own…" };
  else if (props.notice?.tone === "danger") banner = { tone: "danger", text: "Something went wrong. Press Run to try again, or open Technical details." };
  else if (props.linkStatus === "reconnecting") banner = { tone: "muted", text: "Connection dropped. Reconnecting…" };

  const tag = props.apiStatus === "mock" ? "Demo data" : view.profile === "fixture" ? "Recorded results" : null;
  const count = view.messages.length;

  return (
    <div className="flex min-h-dvh flex-col bg-bg lg:h-dvh lg:min-h-[720px]" data-testid="worker-view">
      <header className="flex min-h-14 shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-line px-4 py-2 lg:px-6">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
          <Link href="/" className="shrink-0 text-[17px] font-extrabold tracking-[0.06em] text-fg italic hover:text-fg/80">
            CameraVision
          </Link>
          <span className="hidden h-4 w-px bg-line-strong sm:block" aria-hidden />
          <span className="hidden text-[14px] text-fg/70 sm:inline">Camera alerts</span>
          {tag ? (
            <span className="border border-line-strong px-2 py-0.5 text-[12px] tracking-[0.12em] text-fg/75 uppercase" data-testid="worker-source">
              {tag}
            </span>
          ) : null}
        </div>
        <ViewToggle mode="worker" onChange={props.onViewChange} />
      </header>

      {banner ? (
        <div
          role={banner.tone === "danger" ? "alert" : "status"}
          data-testid="worker-notice"
          className={cn(
            "shrink-0 border-b px-4 py-2.5 text-[15px] lg:px-6",
            banner.tone === "danger" ? "border-danger/50 bg-danger/10 text-danger" : "border-line text-fg/85",
          )}
        >
          {banner.text}
        </div>
      ) : null}

      <section
        aria-label="Run"
        className="flex shrink-0 flex-wrap items-center gap-x-5 gap-y-3 border-b border-line px-4 py-3 lg:px-6"
      >
        <button
          type="button"
          onClick={props.onRun}
          disabled={runDisabled}
          data-testid="run-button"
          className={cn(
            "flex h-14 w-full shrink-0 items-center justify-center gap-3 border text-[18px] font-bold tracking-[0.16em] transition-colors sm:w-auto sm:min-w-[220px] sm:px-8",
            running
              ? "border-line-strong text-fg/70"
              : "border-fg bg-fg text-bg hover:bg-transparent hover:text-fg disabled:border-line-strong disabled:bg-transparent disabled:text-fg/40",
          )}
        >
          {running ? (
            <>
              <StatusDot tone="fg" pulse className="size-2.5" />
              RUNNING…
            </>
          ) : (
            <>
              <span aria-hidden className="text-[14px]">▶</span>
              {view.phase === "idle" ? "RUN" : "RUN AGAIN"}
            </>
          )}
        </button>

        <div
          className="flex min-w-0 flex-1 basis-[16rem] flex-col gap-2"
          data-run-phase={view.phase}
          data-run-id={view.runId ?? undefined}
          data-testid="worker-progress"
        >
          <p role="status" className={cn("text-[16px] leading-[24px]", PROGRESS_TEXT[progress.tone])}>
            {progress.text}
          </p>
          <div className="flex h-2 gap-[3px]" aria-hidden>
            {Array.from({ length: progress.total }, (_, i) => (
              <span
                key={i}
                className={cn(
                  "h-full flex-1 border",
                  i < progress.done
                    ? progress.tone === "failed"
                      ? "border-danger/60 bg-danger/60"
                      : "border-fg bg-fg"
                    : i === progress.done && progress.tone === "busy"
                      ? "blink border-fg/60 bg-fg/40"
                      : "border-line-strong",
                )}
              />
            ))}
          </div>
        </div>

        {props.scenarios.length > 1 ? (
          <label htmlFor="worker-recording" className="flex w-full min-w-0 items-center gap-2 sm:w-auto">
            <span className="shrink-0 text-[14px] text-fg/70">Recording</span>
            <select
              id="worker-recording"
              data-testid="worker-recording"
              className="hud-select h-10 w-full min-w-0 border border-line-strong bg-bg pr-8 pl-2.5 text-[14px] text-fg outline-none hover:border-fg/70 focus-visible:border-fg disabled:opacity-40 sm:w-[min(320px,40vw)]"
              value={scenario?.id ?? ""}
              disabled={running || !!props.runPending}
              onChange={(e) => props.onScenarioChange(e.target.value)}
            >
              {props.scenarios.map((s, i) => (
                <option key={s.id} value={s.id}>
                  {clip(recordingName(s.title, i), 44)}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </section>

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-3 p-3 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] lg:gap-4 lg:p-4">
        <section aria-label="Alerts" className="flex min-h-0 flex-col border border-line bg-panel/60">
          <header className="flex h-11 shrink-0 items-center justify-between gap-3 border-b border-line px-3 lg:px-4">
            <h2 className="text-[15px] font-bold tracking-[0.14em] text-fg uppercase">Messages</h2>
            <span className="text-[14px] text-fg/65 tabular-nums">
              {count === 0 ? "None yet" : count === 1 ? "1 message" : `${count} messages`}
            </span>
          </header>
          <MessageFeed
            className="flex-1"
            messages={view.messages}
            deliveries={view.deliveries}
            phase={view.phase}
            clean={clean}
            targetsFor={targetsFor}
            activeId={shown?.id ?? null}
            onShow={showOnVideo}
          />
        </section>

        <section
          ref={camerasRef}
          aria-label="Cameras"
          className="thin-scroll grid min-h-0 grid-cols-1 content-start gap-3 sm:grid-cols-2 lg:overflow-y-auto"
          data-testid="worker-cameras"
        >
          {cameras.map((cam, i) => (
            <WorkerCamera
              key={cam.id}
              camera={cam}
              name={names.get(cam.id) ?? `Camera ${i + 1}`}
              src={media(cam.media_url, cam.media_available)}
              run={view.cameras[cam.id] ?? null}
              seek={seeks[cam.id] ?? null}
              highlighted={highlighted.has(cam.id)}
              className={cn("aspect-[16/10]", i === 0 && cameras.length % 2 === 1 && "sm:col-span-2")}
            />
          ))}
          {cameras.length === 0 ? (
            <div className="dot-field flex aspect-[16/10] items-center justify-center border border-line sm:col-span-2">
              <span className="text-[15px] text-fg/70">{scenario ? "No cameras" : "Waiting for the camera system…"}</span>
            </div>
          ) : null}
        </section>
      </main>

      <footer className="flex min-h-8 shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-line px-4 py-1.5 lg:px-6">
        <span className="text-[12px] text-fg/60">Runs on this computer. Video never leaves it.</span>
        <span className="flex items-center gap-1.5 text-[12px] text-fg/60">
          <StatusDot tone={running ? "fg" : "dim"} pulse={running} />
          {running ? "Checking" : "Ready"}
        </span>
      </footer>
    </div>
  );
}
