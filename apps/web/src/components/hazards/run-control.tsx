"use client";

import { StatusDot } from "@/components/hud/barcode";
import { STEP_WORDS, type HazardClipStatus, type HazardProgress } from "@/lib/hazards-v1";
import { cn } from "@/lib/utils";

export type JobState =
  | { phase: "starting"; clipId: string }
  | { phase: "running"; clipId: string; jobId: string; progress: HazardProgress | null }
  /** Someone else's job (status "reviewing" without a stream here): poll until it ends. */
  | { phase: "watching"; clipId: string }
  | { phase: "failed"; clipId: string; message: string };

export interface RunControlProps {
  status: HazardClipStatus;
  job: JobState | null;
  /** Another clip is being checked from this screen. */
  busyElsewhere: boolean;
  offline: boolean;
  onCheck: () => void;
  technical: boolean;
  refresh: boolean;
  onRefreshChange: (v: boolean) => void;
}

/** "Check this clip" plus the live progress in plain words (six steps). */
export function RunControl({ status, job, busyElsewhere, offline, onCheck, technical, refresh, onRefreshChange }: RunControlProps) {
  const running = job?.phase === "starting" || job?.phase === "running" || job?.phase === "watching" || status === "reviewing";
  const failed = job?.phase === "failed" ? job.message : status === "failed" ? "The last check didn't finish." : null;
  const progress = job?.phase === "running" ? job.progress : null;
  const total = progress?.total || STEP_WORDS.length;
  const step = progress ? Math.min(Math.max(progress.step, 1), total) : 0;
  const stepText = progress
    ? progress.plain_message || STEP_WORDS[step - 1] || "Working"
    : job?.phase === "starting"
      ? "Starting"
      : "Being checked";

  const label = running ? "Checking…" : status === "reviewed" ? "Check again" : failed ? "Try again" : "Check this clip";
  const disabled = running || busyElsewhere || offline;

  return (
    <section aria-label="Check this clip" className="flex flex-wrap items-center gap-x-5 gap-y-3" data-testid="run-control">
      <button
        type="button"
        onClick={onCheck}
        disabled={disabled}
        data-testid="check-button"
        className={cn(
          "flex h-12 w-full shrink-0 items-center justify-center gap-3 border text-[16px] font-bold tracking-[0.12em] uppercase transition-colors sm:w-auto sm:min-w-[210px] sm:px-6",
          running
            ? "border-line-strong text-fg/70"
            : "border-fg bg-fg text-bg hover:bg-transparent hover:text-fg disabled:border-line-strong disabled:bg-transparent disabled:text-fg/40",
        )}
      >
        {running ? <StatusDot tone="fg" pulse className="size-2.5" /> : <span aria-hidden className="text-[13px]">▶</span>}
        {label}
      </button>

      <div className="flex min-w-0 flex-1 basis-[16rem] flex-col gap-2" data-testid="check-progress" data-step={step || undefined}>
        <p role="status" className={cn("text-[15px] leading-[22px]", failed && !running ? "text-danger" : "text-fg")}>
          {running
            ? `${stepText}…${progress ? ` Step ${step} of ${total}.` : ""}`
            : failed
              ? failed
              : offline
                ? "Can't reach the camera system right now."
                : busyElsewhere
                  ? "Another clip is being checked. One at a time."
                  : status === "reviewed"
                    ? "Checked. You can check it again at any time."
                    : "This clip hasn't been checked yet."}
        </p>
        {running ? (
          <div className="flex h-2 gap-[3px]" aria-hidden>
            {Array.from({ length: total }, (_, i) => (
              <span
                key={i}
                className={cn(
                  "h-full flex-1 border",
                  i < step - 1 ? "border-fg bg-fg" : i === step - 1 || (!progress && i === 0) ? "blink border-fg/60 bg-fg/40" : "border-line-strong",
                )}
              />
            ))}
          </div>
        ) : null}
        {technical && progress?.message ? <p className="micro normal-case tracking-[0.06em]">{progress.message}</p> : null}
      </div>

      {technical ? (
        <label className="flex items-center gap-2 text-[11px] tracking-[0.12em] text-fg/70 uppercase">
          <input
            type="checkbox"
            checked={refresh}
            onChange={(e) => onRefreshChange(e.target.checked)}
            className="size-3.5 appearance-none border border-line-strong checked:border-fg checked:bg-fg"
          />
          Refresh (skip cached model answer)
        </label>
      ) : null}
    </section>
  );
}
