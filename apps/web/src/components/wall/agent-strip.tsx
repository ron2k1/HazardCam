"use client";

import type { CSSProperties } from "react";

import { StatusDot } from "@/components/hud/barcode";
import { CornerTicks } from "@/components/hud/panel";
import { kindWord, type WallCamera } from "@/lib/wall";
import { cn } from "@/lib/utils";

import type { CheckerState, SiteState, TileRun } from "./use-wall-orchestrator";

// The lead's OpenClaw agent id (apps/api/services/site_runs.py; lead_turn.agent in every stored run).
const LEAD_AGENT_ID = "site-lead";
/** Seconds the bus packet takes from the lead to the last tap (globals.css `bus-run`, 0.9 s). */
const PACKET_S = 0.9;

const DOT: Record<CheckerState, { tone: "fg" | "muted" | "dim" | "danger"; pulse: boolean }> = {
  queued: { tone: "dim", pulse: false },
  running: { tone: "fg", pulse: true },
  done: { tone: "muted", pulse: false },
  failed: { tone: "danger", pulse: false },
};

const fromPhase = (phase: TileRun["phase"]): CheckerState =>
  phase === "checking" ? "running" : phase === "done" ? "done" : phase === "failed" ? "failed" : "queued";

/** Where a checker's centre sits along the bus: n equal columns. */
const centre = (i: number, n: number) => (i + 0.5) / n;

function Checker({
  cam,
  run,
  state,
  outside,
  focused,
  onPick,
}: {
  cam: WallCamera;
  run: TileRun;
  state: CheckerState;
  /** On the wall but not one of the cameras this site run follows. */
  outside: boolean;
  focused: boolean;
  onPick: (clipId: string) => void;
}) {
  const words = kindWord(cam.kind);
  const found = run.phase === "done" ? (run.result?.detections.length ?? 0) : 0;
  let outcome: string;
  let tone = "text-fg/70";
  let progress = 0;
  if (outside) {
    outcome = "Not in this run";
    tone = "text-fg/40";
  } else if (state === "failed" && run.phase !== "failed") {
    // the lead's checker failed before a check job existed, so the tile has nothing to show
    outcome = "Check could not start";
    tone = "text-danger";
  } else if (run.phase === "checking") {
    outcome = `${run.stepWord ?? "Checking"}${run.step > 0 ? ` · ${run.step}/${run.total}` : ""}`;
    progress = run.total > 0 ? run.step / run.total : 0;
  } else if (run.phase === "done") {
    outcome = found ? `${found} ${found === 1 ? words.one : words.many} found` : words.none;
    tone = found ? "text-warning" : "text-fg/55";
    progress = 1;
  } else if (run.phase === "failed") {
    outcome = run.error ?? "Check stopped";
    tone = "text-danger";
  } else {
    outcome = state === "queued" ? "Waiting for the lead" : "Starting";
    tone = "text-fg/45";
  }
  const dot = outside ? DOT.queued : DOT[state];

  return (
    <button
      type="button"
      aria-pressed={focused}
      aria-label={`CAM ${cam.cam} checker, ${outside ? "not in this run" : state}: ${outcome}. Show its plan.`}
      onClick={() => onPick(cam.clip_id)}
      data-testid="agent-checker"
      data-cam={cam.cam}
      data-state={outside ? "outside" : state}
      className={cn(
        "flex h-full w-full min-w-0 flex-col justify-between border bg-bg/70 px-2 pt-1 pb-1.5 text-left transition-colors focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-1 focus-visible:outline-fg",
        focused ? "border-fg/60" : found ? "border-warning/45 hover:border-warning" : "border-line hover:border-fg/40",
      )}
    >
      <span className="flex items-center gap-1.5 leading-none">
        <StatusDot tone={dot.tone} pulse={dot.pulse} />
        <span className="text-[11px] font-extrabold tracking-[0.1em] text-fg">CAM {cam.cam}</span>
        <span className="micro text-fg/45">CHECKER</span>
        <span className={cn("micro ml-auto", state === "failed" && !outside ? "text-danger" : "text-fg/60")}>
          {outside ? "—" : state}
        </span>
      </span>
      <span className={cn("truncate text-[10.5px] leading-[13px]", tone)}>{outcome}</span>
      <span className="relative h-[2px] w-full bg-fg/10" aria-hidden>
        <span
          className={cn(
            "absolute inset-y-0 left-0 transition-[width] duration-500",
            found ? "bg-warning" : run.phase === "done" ? "bg-fg/45" : "bg-fg",
          )}
          style={{ width: `${Math.round(progress * 100)}%` }}
        />
      </span>
    </button>
  );
}

/**
 * 00: the agent team over the feeds. The lead (one OpenClaw agent) on the left with its latest
 * trace line, verbatim from the site run; a bus out to one checker per wall camera, each showing
 * its own check the way its tile does. A packet runs down the bus only when the lead makes a real
 * tool call (a `tool` or `alerts` line in its trace). With no site run the strip says so instead.
 */
export function AgentStrip({
  cameras,
  runs,
  idle,
  site,
  direct,
  focusClip,
  onPick,
  className,
}: {
  cameras: WallCamera[];
  runs: Record<string, TileRun>;
  idle: TileRun;
  site: SiteState | null;
  direct: boolean;
  focusClip: string | null;
  onPick: (clipId: string) => void;
  className?: string;
}) {
  const lead = site?.lead ?? [];
  const calls = site?.toolCalls ?? 0;
  const lastCallKind = site?.lastCallKind ?? null;
  const allDone = cameras.length > 0 && cameras.every((c) => runs[c.clip_id]?.phase === "done");
  const n = Math.max(cameras.length, 1);
  const runCams = site?.runCams ?? null;
  const followed = site?.followed ?? null;
  const following = followed ? cameras.filter((c) => followed.includes(c.clip_id)).length : cameras.length;

  let status: string;
  let line: string;
  let active = false;
  if (site) {
    active = site.state === "running";
    status = active ? "RUNNING" : "DONE";
    line = lead.at(-1)?.text ?? "Lead agent starting";
  } else if (direct) {
    status = "OFF";
    line = "No lead run: each camera is checked directly";
  } else if (allDone) {
    status = "IDLE";
    line = "Checks ran before this visit";
  } else {
    status = "STARTING";
    line = "Starting the lead agent";
  }

  return (
    <section
      aria-label="Agent team"
      data-testid="agent-strip"
      data-lead={status.toLowerCase()}
      data-calls={calls}
      className={cn("relative flex h-[76px] shrink-0 items-stretch border border-line bg-panel/80", className)}
    >
      <CornerTicks />
      <div className="flex w-[400px] shrink-0 flex-col justify-center gap-[3px] border-r border-line bg-fg/[0.025] px-3" data-testid="lead-agent">
        <div className="flex items-center gap-2 leading-none">
          <span className="text-[10px] tracking-[0.18em] text-muted">00</span>
          <span className="h-px w-3 bg-line-strong" aria-hidden />
          <StatusDot tone={site ? "fg" : "dim"} pulse={active} />
          <span className="text-[12.5px] font-extrabold tracking-[0.16em] text-fg">LEAD AGENT</span>
          <span className="micro truncate text-fg/50">OPENCLAW · {LEAD_AGENT_ID}</span>
          <span className={cn("micro ml-auto", active ? "text-fg" : "text-fg/55")} data-testid="lead-status">
            {status}
          </span>
        </div>
        <p
          key={site?.leadTotal ?? 0}
          className="truncate text-[11.5px] leading-[15px] text-fg/90 duration-300 animate-in fade-in"
          title={line}
          data-testid="lead-line"
        >
          {line}
        </p>
        <div className="micro flex items-center gap-3 text-fg/50 tabular-nums">
          {site ? (
            <>
              <span>
                TOOL CALLS <b className="text-fg/85">{calls}</b>
              </span>
              <span>{site.mode === "replay" ? "REPLAY · RECORDED RUN" : "LIVE RUN"}</span>
              <span className="truncate">RUN {site.id.slice(-8).toUpperCase()}</span>
            </>
          ) : (
            <span>{cameras.length} CAMERAS</span>
          )}
        </div>
      </div>

      <div className="relative min-w-0 flex-1" data-testid="agent-bus">
        {/* the bus: out of the lead along the top, one tap down into each checker */}
        <span className="absolute top-[9px] left-0 size-[5px] -translate-x-1/2 -translate-y-1/2 border border-fg/70 bg-bg" aria-hidden />
        <span className="absolute top-[9px] left-0 h-px bg-line-strong" style={{ right: `${(1 - centre(n - 1, n)) * 100}%` }} aria-hidden>
          {calls > 0 ? <span key={calls} className="bus-packet" data-kind={lastCallKind ?? "tool"} /> : null}
        </span>
        <span className="micro absolute top-[3px] left-2.5 bg-panel px-1 text-fg/45 tabular-nums" data-testid="agent-bus-count">
          {runCams && runCams !== following ? `${following} OF ${runCams} ON THIS WALL` : `${following} CHECKERS`}
        </span>
        {cameras.map((c, i) => (
          <span key={c.clip_id} className="absolute top-[9px] h-[9px] w-px" style={{ left: `${centre(i, n) * 100}%` }} aria-hidden>
            <span
              key={lastCallKind === "tool" ? calls : 0}
              className={cn("absolute inset-0 bg-line-strong", lastCallKind === "tool" && "bus-tap")}
              style={{ "--tap-delay": `${((centre(i, n) / centre(n - 1, n)) * PACKET_S * 0.8).toFixed(2)}s` } as CSSProperties}
            />
          </span>
        ))}
        <div className="absolute inset-x-0 top-[18px] bottom-0 grid" style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` }}>
          {cameras.map((c) => {
            const run = runs[c.clip_id] ?? idle;
            const state = site ? (site.checkers[c.cam] ?? "queued") : fromPhase(run.phase);
            const outside = !!followed && !followed.includes(c.clip_id);
            return (
              <div key={c.clip_id} className="min-w-0 px-1 pb-1.5">
                <Checker cam={c} run={run} state={state} outside={outside} focused={c.clip_id === focusClip} onPick={onPick} />
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
