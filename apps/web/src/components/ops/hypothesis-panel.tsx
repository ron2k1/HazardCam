"use client";

import { AnimatePresence, motion } from "motion/react";

import { StatusDot } from "@/components/hud/barcode";
import { Panel } from "@/components/hud/panel";
import { NumberTicker } from "@/components/ui/number-ticker";
import { isAbstain, type Hypothesis } from "@/lib/contracts";
import { fixed, label } from "@/lib/format";
import type { RunPhase } from "@/lib/run-view";
import { cn } from "@/lib/utils";

export interface HypothesisPanelProps {
  hypothesis: Hypothesis | null;
  /** hypothesis.updated final flag / run.complete. */
  final: boolean;
  phase: RunPhase;
  /** Human label for hypothesis.region (zone or candidate label), if known. */
  regionLabel?: string | null;
  selectedEvidenceId?: string | null;
  onSelectEvidence?: (evidenceId: string) => void;
  className?: string;
}

function ConfidenceBar({ value, className }: { value: number; className?: string }) {
  const v = Math.min(Math.max(value, 0), 1);
  return (
    <div className={cn("relative h-2.5 border border-line-strong", className)} role="meter" aria-valuemin={0} aria-valuemax={1} aria-valuenow={v} aria-label="confidence">
      <motion.div
        className="absolute inset-0 bg-fg"
        style={{ originX: 0 }}
        initial={{ scaleX: 0 }}
        animate={{ scaleX: v }}
        transition={{ duration: 0.8, ease: [0.2, 0.7, 0.2, 1] }}
      />
      {Array.from({ length: 9 }, (_, i) => (
        <span key={i} aria-hidden className="absolute inset-y-0 w-px bg-bg/70" style={{ left: `${(i + 1) * 10}%` }} />
      ))}
    </div>
  );
}

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[84px_minmax(0,1fr)] gap-x-3 border-b border-line/70 py-2 last:border-b-0">
      <span className="micro pt-px">{k}</span>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function HypothesisPanel({
  hypothesis,
  final,
  phase,
  regionLabel,
  selectedEvidenceId,
  onSelectEvidence,
  className,
}: HypothesisPanelProps) {
  const abstain = isAbstain(hypothesis);
  const stateLabel = !hypothesis
    ? phase === "running"
      ? "RESOLVING"
      : phase === "failed"
        ? "NO RESULT"
        : "AWAITING RUN"
    : abstain
      ? final
        ? "ABSTAIN · FINAL"
        : "ABSTAIN · PROVISIONAL"
      : final
        ? "FINAL"
        : "PROVISIONAL";

  return (
    <Panel
      index="04"
      title="Hypothesis"
      className={className}
      bodyClassName="thin-scroll overflow-y-auto [mask-image:linear-gradient(to_bottom,#000_calc(100%-16px),transparent_100%)]"
      meta={
        <span className="flex items-center gap-1.5 text-fg/85" data-hypothesis-state={stateLabel}>
          <StatusDot tone={hypothesis ? (final ? "fg" : "muted") : "dim"} pulse={!final && phase === "running"} />
          {stateLabel}
        </span>
      }
    >
      <div className="px-2.5 pt-2 pb-1">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={hypothesis ? `${hypothesis.event_type}|${hypothesis.region}` : "unknown"}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.25 }}
          >
            <span className="micro">EVENT TYPE</span>
            <p
              className={cn(
                "mt-0.5 text-[17px] leading-tight font-bold tracking-[0.08em] break-words",
                !hypothesis || abstain ? "text-fg/45" : "text-fg",
              )}
            >
              {!hypothesis ? "UNKNOWN" : abstain ? "ABSTAIN — UNKNOWN" : label(hypothesis.event_type)}
            </p>
            {abstain ? <p className="micro mt-1 text-fg/80">INSUFFICIENT CORROBORATING EVIDENCE · NO CLAIM MADE</p> : null}
          </motion.div>
        </AnimatePresence>

        <div className="mt-3 flex items-end justify-between gap-3">
          <span className="micro">CONFIDENCE</span>
          <span className="text-[20px] leading-none font-bold">
            {hypothesis ? <NumberTicker value={hypothesis.confidence} decimalPlaces={2} /> : <span className="text-dim">—.——</span>}
          </span>
        </div>
        <ConfidenceBar value={hypothesis?.confidence ?? 0} className="mt-1.5" />
      </div>

      {hypothesis ? (
        <div className="px-2.5 pb-4">
          <Row k="REGION">
            <span className="text-[11px] text-fg">{hypothesis.region.toUpperCase()}</span>
            {regionLabel ? <span className="micro ml-2">{regionLabel}</span> : null}
          </Row>
          <Row k="REASON">
            <p className="text-[11px] leading-[1.5] text-fg/85">{hypothesis.reason}</p>
          </Row>
          <Row k="EVIDENCE">
            {hypothesis.evidence_ids.length ? (
              <span className="flex flex-wrap gap-1">
                {hypothesis.evidence_ids.map((id) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => onSelectEvidence?.(id)}
                    className={cn(
                      "border px-1.5 py-px text-[10px] tracking-[0.06em] transition-colors",
                      id === selectedEvidenceId ? "border-fg bg-fg text-bg" : "border-line-strong text-fg/85 hover:border-fg",
                    )}
                  >
                    {id}
                  </button>
                ))}
              </span>
            ) : (
              <span className="micro">NONE CITED</span>
            )}
          </Row>
          <Row k="ALTERNATIVES">
            {hypothesis.alternatives.length ? (
              <ul className="flex flex-col gap-1">
                {hypothesis.alternatives.map((a) => (
                  <li key={a.event_type} className="grid grid-cols-[minmax(0,1fr)_64px_32px] items-center gap-2">
                    <span className="truncate text-[10px] tracking-[0.06em] text-fg/80">{label(a.event_type)}</span>
                    <span className="relative h-1.5 border border-line">
                      <span className="absolute inset-y-0 left-0 bg-fg/60" style={{ width: `${Math.min(Math.max(a.confidence, 0), 1) * 100}%` }} />
                    </span>
                    <span className="micro text-right text-fg/70">{fixed(a.confidence)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <span className="micro">NONE</span>
            )}
          </Row>
          <Row k="LIMITATIONS">
            {hypothesis.limitations.length ? (
              <ul className="flex flex-col gap-0.5">
                {hypothesis.limitations.map((l) => (
                  <li key={l} className="text-[11px] leading-snug text-fg/75">
                    <span className="mr-1.5 text-dim">—</span>
                    {l}
                  </li>
                ))}
              </ul>
            ) : (
              <span className="micro">NONE STATED</span>
            )}
          </Row>
        </div>
      ) : (
        <p className="micro px-2.5 pb-3">
          {phase === "running" ? "AWAITING REASONING STAGE" : "IDLE · NO HYPOTHESIS"}
        </p>
      )}
    </Panel>
  );
}
