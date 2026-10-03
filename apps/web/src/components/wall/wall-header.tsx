"use client";

import Link from "next/link";

import { StatusDot } from "@/components/hud/barcode";
import type { StackLine } from "@/lib/wall";
import { cn } from "@/lib/utils";

import { useNow } from "./use-now";

const NAV = [
  { href: "/", label: "Cameras" },
  { href: "/hazards", label: "Safety hazards" },
] as const;

function Clock() {
  const now = useNow(1000);
  return (
    <span className="shrink-0 text-[13px] text-fg/75 tabular-nums" data-testid="wall-clock">
      {now ? now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "--:--:--"}
    </span>
  );
}

export interface WallHeaderProps {
  /** "Site cameras · Factory floor" (config/wall.yaml `title`). */
  title: string;
  /** "Safety agent watching 6 cameras", or the starting line. */
  agentLine: string;
  agentActive: boolean;
  stack: StackLine | null;
  checked: number;
  total: number;
  /** The site run's six checkers, CAM 1-6 (lead agent row); null when the wall checks directly. */
  site?: { id: string; state: string; checkers: Record<number, string> } | null;
}

/**
 * CameraVision header, the same layout as the /hazards screens: brand, page name, the two product
 * links, the one-line stack status and a clock; under it the safety agent's own status line.
 */
export function WallHeader({ title, agentLine, agentActive, stack, checked, total, site }: WallHeaderProps) {
  return (
    <header className="shrink-0 border-b border-line" data-testid="wall-header">
      <div className="flex min-h-12 flex-wrap items-center justify-between gap-x-5 gap-y-2 px-4 py-2 lg:px-6">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
          <Link href="/" prefetch={false} className="shrink-0 text-[17px] font-extrabold tracking-[0.06em] text-fg italic hover:text-fg/80">
            CameraVision
          </Link>
          <span className="hidden h-4 w-px bg-line-strong sm:block" aria-hidden />
          <h1 className="text-[14px] text-fg/80">{title}</h1>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-x-5 gap-y-2">
          <nav aria-label="Main" className="flex items-center border border-line-strong">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                prefetch={n.href === "/" ? false : undefined}
                aria-current={n.href === "/" ? "page" : undefined}
                className={cn(
                  "flex h-8 items-center px-3 text-[13px] transition-colors",
                  n.href === "/" ? "bg-fg text-bg" : "text-fg/80 hover:bg-fg/10 hover:text-fg",
                )}
              >
                {n.label}
              </Link>
            ))}
          </nav>
          <p className="flex min-w-0 items-center gap-2 text-[12px] text-fg/75" data-testid="wall-stack-line">
            {stack ? (
              <>
                <StatusDot tone={stack.tone === "ok" ? "fg" : stack.tone === "warn" ? "danger" : "muted"} />
                <span>{stack.parts.join(" · ")}</span>
              </>
            ) : (
              <span className="text-muted">Checking the safety system…</span>
            )}
          </p>
          <Clock />
        </div>
      </div>
      <div className="flex min-h-8 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-line px-4 py-1 lg:px-6">
        <p className="flex items-center gap-2 text-[12px] text-fg/85" data-testid="wall-agent-line">
          <StatusDot tone={agentActive ? "fg" : "muted"} pulse={agentActive} />
          {agentLine}
        </p>
        {site ? (
          <span className="tele flex items-center gap-2" data-testid="wall-lead-row">
            <span>LEAD AGENT · {total || 6} CHECKERS</span>
            {Array.from({ length: total || 6 }, (_, i) => i + 1).map((n) => {
              const st = site.checkers[n] ?? "queued";
              return (
                <span
                  key={n}
                  title={`CAM ${n}: ${st}`}
                  aria-label={`CAM ${n} ${st}`}
                  className={cn(
                    "inline-block size-2 border border-fg/60",
                    st === "done" && "bg-fg",
                    st === "running" && "bg-fg/40 motion-safe:animate-pulse",
                    st === "failed" && "border-danger bg-danger",
                  )}
                />
              );
            })}
          </span>
        ) : null}
        {total ? (
          <span className="tele tabular-nums" data-testid="wall-checked">
            Checked {checked} of {total}
          </span>
        ) : null}
      </div>
    </header>
  );
}
