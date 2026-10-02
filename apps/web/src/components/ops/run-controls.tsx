"use client";

import { StatusDot } from "@/components/hud/barcode";
import { Button } from "@/components/ui/button";
import type { ScenarioSummary } from "@/lib/contracts";
import { clip, seqId } from "@/lib/format";
import type { RunPhase } from "@/lib/run-view";
import { cn } from "@/lib/utils";

export interface RunControlsProps {
  scenarios: readonly ScenarioSummary[];
  scenarioId: string | null;
  onScenarioChange: (scenarioId: string) => void;
  profiles: readonly string[];
  profile: string;
  onProfileChange?: (profile: string) => void;
  onRun: () => void;
  phase: RunPhase;
  runId: string | null;
  lastSeq: number;
  /** Disable RUN independently of phase (e.g. API offline). */
  disabled?: boolean;
  /** Data provenance tag, e.g. "MOCK · contracts/examples". */
  sourceLabel?: string | null;
  className?: string;
}

function Field({ id, k, children }: { id: string; k: string; children: React.ReactNode }) {
  return (
    <label htmlFor={id} className="flex h-full items-center gap-2 border-r border-line pr-3">
      <span className="micro">{k}</span>
      {children}
    </label>
  );
}

// 280px select minus padding/chevron at 11px mono + 0.06em tracking ≈ 33 glyphs
const SCENARIO_OPTION_CHARS = 33;

const selectCls =
  "hud-select h-7 min-w-0 border border-line-strong bg-bg pr-7 pl-2 text-[11px] tracking-[0.06em] text-fg outline-none hover:border-fg/70 focus-visible:border-fg disabled:opacity-40";

export function RunControls({
  scenarios,
  scenarioId,
  onScenarioChange,
  profiles,
  profile,
  onProfileChange,
  onRun,
  phase,
  runId,
  lastSeq,
  disabled = false,
  sourceLabel,
  className,
}: RunControlsProps) {
  const running = phase === "running" || phase === "queued";
  return (
    <div className={cn("flex h-11 shrink-0 items-center gap-3 border-b border-line px-3", className)}>
      <Field id="scenario-select" k="SCENARIO">
        <select
          id="scenario-select"
          className={cn(selectCls, "w-[280px]")}
          value={scenarioId ?? ""}
          disabled={running || scenarios.length === 0}
          onChange={(e) => onScenarioChange(e.target.value)}
          title={scenarios.find((s) => s.id === scenarioId)?.title ?? undefined}
        >
          {scenarios.length === 0 ? <option value="">NO SCENARIOS</option> : null}
          {scenarios.map((s) => (
            <option key={s.id} value={s.id} title={s.title ?? undefined}>
              {clip(s.title ? `${s.id} · ${s.title}` : s.id, SCENARIO_OPTION_CHARS)}
            </option>
          ))}
        </select>
      </Field>
      <Field id="profile-select" k="PROFILE">
        <select
          id="profile-select"
          className={cn(selectCls, "w-[112px]")}
          value={profile}
          disabled={running || !onProfileChange}
          onChange={(e) => onProfileChange?.(e.target.value)}
        >
          {profiles.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </Field>
      <Button
        size="sm"
        variant={running ? "ghost" : "solid"}
        disabled={disabled || running || !scenarioId}
        onClick={onRun}
        className="min-w-[92px]"
        data-testid="run-button"
      >
        {running ? "RUNNING" : phase === "idle" ? "▶ RUN" : "▶ RE-RUN"}
      </Button>

      <div className="micro ml-1 flex items-center gap-2 text-fg/85" data-run-phase={phase}>
        <StatusDot tone={phase === "failed" ? "danger" : running ? "fg" : phase === "complete" ? "muted" : "dim"} pulse={running} />
        <span className={phase === "failed" ? "text-danger" : undefined}>{phase.toUpperCase()}</span>
      </div>
      <span className="micro hidden xl:inline">RUN {runId ?? "—"}</span>
      <span className="micro">SEQ {seqId(lastSeq)}</span>

      {sourceLabel ? (
        <span className="micro ml-auto border border-line-strong px-1.5 py-0.5 text-fg/80" data-testid="source-label">
          {sourceLabel}
        </span>
      ) : null}
    </div>
  );
}
