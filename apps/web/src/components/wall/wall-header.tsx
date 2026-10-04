"use client";

import Link from "next/link";

import { Barcode, StatusDot } from "@/components/hud/barcode";
import { AnimatedText } from "@/components/ui/animated-text";
import { cn } from "@/lib/utils";

import { ResetDemoButton } from "./reset-demo-button";
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
  /** "Safety agent watching 4 cameras", or the starting line. */
  agentLine: string;
  agentActive: boolean;
  checked: number;
  total: number;
}

// Recording build: the stack line is fixed "on". The replayed checks are stored runs from the
// GB10, where the safety agent and its sandbox were up; this screen does not poll for them.
const STACK_PARTS = ["Safety agent on this computer", "secure sandbox on", "no internet needed"] as const;

/**
 * CameraVision header, the same layout as the /hazards screens: brand, page name, the two product
 * links, the one-line stack status and a clock; under it the safety agent's own status line.
 */
export function WallHeader({ title, agentLine, agentActive, checked, total }: WallHeaderProps) {
  return (
    <header className="shrink-0 border-b border-line" data-testid="wall-header">
      <div className="flex min-h-12 flex-wrap items-center justify-between gap-x-5 gap-y-2 px-4 py-2 lg:px-6">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
          <Link href="/" prefetch={false} className="shrink-0 tracking-[0.04em] text-fg italic hover:text-fg/80">
            <AnimatedText text="CameraVision" fontSize={19} minWeight={250} maxWeight={800} animationDuration={1.6} delayMultiplier={0.12} />
          </Link>
          <span className="hidden h-4 w-px bg-line-strong sm:block" aria-hidden />
          <h1 className="text-[11px] tracking-[0.2em] text-fg/85 uppercase">{title}</h1>
          <Barcode seed={title} className="hidden lg:inline-flex" />
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
          <ResetDemoButton />
          <p className="flex min-w-0 items-center gap-2 text-[12px] text-fg/80" data-testid="wall-stack-line">
            <StatusDot tone="fg" />
            <span>{STACK_PARTS.join(" · ")}</span>
          </p>
          <Clock />
        </div>
      </div>
      <div className="flex min-h-8 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-line px-4 py-1 lg:px-6">
        <p className="flex items-center gap-2 text-[12px] text-fg/85" data-testid="wall-agent-line">
          <StatusDot tone={agentActive ? "fg" : "muted"} pulse={agentActive} />
          {agentLine}
        </p>
        {total ? (
          <span className="tele tabular-nums" data-testid="wall-checked">
            Checked {checked} of {total}
          </span>
        ) : null}
      </div>
    </header>
  );
}
