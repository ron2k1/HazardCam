"use client";

import { useEffect, useState } from "react";

import { StatusDot } from "@/components/hud/barcode";
import { clock, STEP_WORDS, type AgentLine, type HazardProgress } from "@/lib/hazards";
import { cn } from "@/lib/utils";

export type CheckPhase = "idle" | "waiting" | "starting" | "running" | "done" | "failed" | "lost";

export interface CheckState {
  phase: CheckPhase;
  clipId: string;
  jobId: string | null;
  /** Latest numbered step. */
  progress: HazardProgress | null;
  /** When each step started (client ms), by step number. */
  stepStarted: Record<number, number>;
  agent: AgentLine[];
  message: string | null;
}

export function initialCheck(clipId: string, phase: CheckPhase = "waiting"): CheckState {
  return { phase, clipId, jobId: null, progress: null, stepStarted: {}, agent: [], message: null };
}

/** The step where the model works: its elapsed time is shown so it never looks frozen. */
const MODEL_STEP = 5;

function useTicker(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active]);
  return now;
}

export interface CheckStatusProps {
  check: CheckState;
  /** worker.headline once the result is in. */
  headline?: string | null;
  reasoningHref: string | null;
  onCheckAgain: () => void;
  disabled?: boolean;
  className?: string;
}

/** The slim bar under the feed: plain steps, the safety agent's narration, then the outcome. */
export function CheckStatus({ check, headline, reasoningHref, onCheckAgain, disabled = false, className }: CheckStatusProps) {
  const running = check.phase === "starting" || check.phase === "running";
  const now = useTicker(running && (check.progress?.step ?? 0) === MODEL_STEP);
  const total = check.progress?.total || STEP_WORDS.length;
  const step = check.progress ? Math.min(Math.max(check.progress.step, 0), total) : 0;
  const stepText = check.progress?.plain_message || STEP_WORDS[step - 1] || "Starting the safety check";
  const modelStart = check.stepStarted[MODEL_STEP];
  const elapsed = step === MODEL_STEP && modelStart ? clock((now - modelStart) / 1000) : null;
  const lastAgent = check.agent.length ? check.agent[check.agent.length - 1] : null;

  let line: React.ReactNode;
  if (check.phase === "waiting" || check.phase === "idle") {
    line = "Watching this camera. A safety check starts in a moment.";
  } else if (check.phase === "starting") {
    line = "Starting the safety check…";
  } else if (check.phase === "running") {
    line = (
      <>
        {stepText}…{elapsed ? <span className="ml-1.5 tabular-nums text-fg/80">{elapsed}</span> : null}
        {step > 0 ? <span className="ml-2 text-[13px] text-fg/55">Step {step} of {total}</span> : null}
      </>
    );
  } else if (check.phase === "done") {
    line = <>Check finished · {headline ?? "Report ready"}</>;
  } else if (check.phase === "lost") {
    line = "Lost touch with the check. It may still be running.";
  } else {
    line = check.message ?? "The check stopped before it finished.";
  }

  return (
    <section
      aria-label="Safety check"
      className={cn("flex min-w-0 flex-col gap-2 border border-line bg-panel/80 px-3 py-2.5", className)}
      data-testid="check-status"
      data-phase={check.phase}
      data-step={step || undefined}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
        <span className="flex min-w-0 flex-1 basis-[18rem] items-start gap-2.5">
          {running || check.phase === "waiting" ? (
            <StatusDot tone="fg" pulse className="mt-[7px] size-2 shrink-0" />
          ) : check.phase === "failed" || check.phase === "lost" ? (
            <StatusDot tone="danger" className="mt-[7px] size-2 shrink-0" />
          ) : (
            <StatusDot tone="fg" className="mt-[7px] size-2 shrink-0" />
          )}
          <span
            role="status"
            className={cn("min-w-0 text-[15px] leading-[22px]", check.phase === "failed" ? "text-danger" : "text-fg")}
            data-testid="check-line"
          >
            {line}
          </span>
        </span>
        <span className="flex max-w-full shrink-0 flex-wrap items-center gap-2">
          {reasoningHref ? (
            <a
              href={reasoningHref}
              target="_blank"
              rel="noopener"
              className="flex min-h-8 items-center border border-line-strong px-2.5 py-1 text-[13px] leading-[18px] text-fg/90 hover:border-fg/70 hover:text-fg"
              data-testid="open-reasoning"
            >
              Open reasoning and process ↗
            </a>
          ) : null}
          {check.phase === "done" || check.phase === "failed" || check.phase === "lost" ? (
            <button
              type="button"
              onClick={onCheckAgain}
              disabled={disabled}
              className="flex h-8 items-center border border-fg/80 px-2.5 text-[13px] text-fg hover:bg-fg hover:text-bg disabled:opacity-40"
              data-testid="check-again"
            >
              {check.phase === "done" ? "Check again" : "Try again"}
            </button>
          ) : null}
        </span>
      </div>

      {running ? (
        <ol className="grid grid-cols-6 gap-[3px]" aria-label="Steps" data-testid="check-steps">
          {Array.from({ length: total }, (_, i) => {
            const n = i + 1;
            const done = n < step;
            const current = n === step || (step === 0 && n === 1);
            return (
              <li key={n} className="flex min-w-0 flex-col gap-1">
                <span
                  aria-hidden
                  className={cn("h-1.5 border", done ? "border-fg bg-fg" : current ? "blink border-fg/70 bg-fg/40" : "border-line-strong")}
                />
                <span className={cn("hidden truncate text-[11px] leading-4 lg:block", done ? "text-fg/70" : current ? "text-fg" : "text-fg/40")}>
                  {STEP_WORDS[i]}
                </span>
              </li>
            );
          })}
        </ol>
      ) : null}

      {lastAgent && running ? (
        <p className="flex min-w-0 items-start gap-2 border-t border-line pt-2 text-[13px] leading-5" data-testid="agent-line">
          <span className="shrink-0 border border-fg/50 px-1.5 text-[10px] leading-[18px] tracking-[0.12em] text-fg/85 uppercase">Safety agent</span>
          <span className="min-w-0 text-fg/90">{lastAgent.text}</span>
        </p>
      ) : null}
    </section>
  );
}
