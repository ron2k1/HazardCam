"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import type { RuntimeStatus } from "@/lib/hazards";
import { cn } from "@/lib/utils";

import { RuntimeLine } from "./runtime-strip";

const NAV = [
  { href: "/", label: "Cameras" },
  { href: "/hazards", label: "Safety hazards" },
] as const;

/** A wall clock that renders only after mount (no hydration mismatch). */
export function useClock(intervalMs = 1000): Date | null {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    const tick = () => setNow(new Date());
    const first = window.setTimeout(tick, 0);
    const id = window.setInterval(tick, intervalMs);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(id);
    };
  }, [intervalMs]);
  return now;
}

export function HeaderClock() {
  const now = useClock();
  return (
    <span className="shrink-0 text-[13px] text-fg/75 tabular-nums" data-testid="header-clock" suppressHydrationWarning>
      {now ? now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "--:--:--"}
    </span>
  );
}

export interface HazardsHeaderProps {
  /** Which nav entry is current. */
  current: "/" | "/hazards" | null;
  /** The page's own name after the brand, e.g. "Safety hazards" or "Reasoning and process". */
  title: string;
  runtime: RuntimeStatus | null;
  /** Extra right-side controls. */
  right?: ReactNode;
  badge?: ReactNode;
}

/** CameraVision header: brand, page name, Cameras / Safety hazards, the stack line and a clock. */
export function HazardsHeader({ current, title, runtime, right, badge }: HazardsHeaderProps) {
  return (
    <header className="flex min-h-12 shrink-0 flex-wrap items-center justify-between gap-x-5 gap-y-2 border-b border-line px-4 py-2 lg:px-6" data-testid="hazards-header">
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
        <Link href="/" className="shrink-0 text-[17px] font-extrabold tracking-[0.06em] text-fg italic hover:text-fg/80">
          CameraVision
        </Link>
        <span className="h-4 w-px bg-line-strong" aria-hidden />
        <span className="text-[14px] text-fg/80">{title}</span>
        {badge}
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-x-5 gap-y-2">
        <nav aria-label="Main" className="flex items-center border border-line-strong">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              aria-current={current === n.href ? "page" : undefined}
              className={cn(
                "flex h-8 items-center px-3 text-[13px] transition-colors",
                current === n.href ? "bg-fg text-bg" : "text-fg/80 hover:bg-fg/10 hover:text-fg",
              )}
            >
              {n.label}
            </Link>
          ))}
        </nav>
        <RuntimeLine status={runtime} lead="watching" className="hidden max-w-[36rem] md:flex" />
        {right}
        <HeaderClock />
      </div>
    </header>
  );
}
