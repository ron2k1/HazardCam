"use client";

import { useEffect, useState } from "react";

import { StatusDot } from "@/components/hud/barcode";
import { hazardsApi, type RuntimeRow, type RuntimeStatus } from "@/lib/hazards";
import { cn } from "@/lib/utils";

const POLL_MS = 15_000;

/** GET /api/runtime/status every 15 s; null until it answers (or while it does not). */
export function useRuntimeStatus(enabled = true): RuntimeStatus | null {
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    let ctl: AbortController | null = null;
    const load = () => {
      ctl?.abort();
      ctl = new AbortController();
      hazardsApi.runtimeStatus(ctl.signal).then(
        (s) => {
          if (alive && s && Array.isArray(s.rows)) setStatus(s);
        },
        () => {
          if (alive) setStatus(null);
        },
      );
    };
    load();
    const id = window.setInterval(load, POLL_MS);
    return () => {
      alive = false;
      ctl?.abort();
      window.clearInterval(id);
    };
  }, [enabled]);
  return status;
}

function row(status: RuntimeStatus, ...keys: string[]): RuntimeRow | undefined {
  return status.rows.find((r) => keys.some((k) => r.key === k || r.key.includes(k)));
}

/**
 * One plain line for a worker, built only from rows that are up:
 * "Checked on this computer by the safety agent · secure sandbox on · no internet needed".
 */
export function plainStackLine(status: RuntimeStatus, lead: "checked" | "watching" = "checked"): { text: string; ok: boolean } {
  const agent = row(status, "openclaw");
  const sandbox = row(status, "nemoclaw");
  const network = row(status, "network");
  const qwen = row(status, "qwen");
  const agentOn = agent?.status === "ok" && /agent/i.test(agent.value ?? "agent");
  const head =
    lead === "checked"
      ? agentOn
        ? "Checked on this computer by the safety agent"
        : "Checked on this computer"
      : agentOn
        ? "Safety agent on this computer"
        : "Running on this computer";
  const parts = [head];
  if (sandbox?.status === "ok") parts.push("secure sandbox on");
  if (network?.status === "ok" || status.local_only) parts.push("no internet needed");
  const ok = (qwen ? qwen.status === "ok" : true) && (agent ? agent.status === "ok" : true);
  return { text: parts.join(" · "), ok };
}

/** Worker screens: the plain stack line with a status dot (nothing until the API answers). */
export function RuntimeLine({
  status,
  lead = "checked",
  wrap = false,
  className,
}: {
  status: RuntimeStatus | null;
  lead?: "checked" | "watching";
  /** Let the line wrap (narrow screens) instead of truncating it. */
  wrap?: boolean;
  className?: string;
}) {
  if (!status) return null;
  const { text, ok } = plainStackLine(status, lead);
  return (
    <span className={cn("flex min-w-0 gap-2 text-[12px] text-fg/75", wrap ? "items-start leading-[18px]" : "items-center", className)} data-testid="runtime-line">
      <StatusDot tone={ok ? "fg" : "dim"} className={cn(ok ? "" : "opacity-60", wrap && "mt-[5px]")} />
      <span className={wrap ? "min-w-0" : "truncate"} title={text}>
        {text}
      </span>
    </span>
  );
}

const TONE: Record<RuntimeRow["status"], string> = {
  ok: "border-fg/70 text-fg",
  down: "border-danger/70 text-danger",
  unknown: "border-line-strong text-fg/55",
};

/** Process page: every stack row with its status. */
export function RuntimeRows({ status }: { status: RuntimeStatus | null }) {
  if (!status) {
    return <p className="px-3 py-2 text-[11px] text-fg/60">The runtime status endpoint is not answering.</p>;
  }
  return (
    <div className="flex flex-col" data-testid="runtime-rows">
      <ul className="divide-y divide-line">
        {status.rows.map((r) => (
          <li key={r.key} className="grid grid-cols-[minmax(8rem,30%)_4.5rem_minmax(0,1fr)] items-start gap-3 px-3 py-1.5 text-[11px] leading-4">
            <span className="font-bold text-fg">{r.label}</span>
            <span className={cn("justify-self-start border px-1.5 text-[10px] leading-[16px] tracking-[0.1em] uppercase", TONE[r.status] ?? TONE.unknown)}>
              {r.status}
            </span>
            <span className="min-w-0 break-words text-fg/85">
              {r.value ?? "—"}
              {r.detail ? <span className="text-fg/55"> · {r.detail}</span> : null}
            </span>
          </li>
        ))}
      </ul>
      <p className="micro border-t border-line px-3 py-1.5 normal-case tracking-[0.06em]">
        checked {status.checked_at} · local only: {status.local_only ? "yes" : "no"}
      </p>
    </div>
  );
}
