"use client";

import type { ViewMode } from "@/hooks/use-view-mode";
import { cn } from "@/lib/utils";

export interface ViewToggleProps {
  mode: ViewMode;
  onChange: (mode: ViewMode) => void;
  /** compact: the technical console's 36px top bar. */
  size?: "default" | "compact";
  className?: string;
}

/** "Technical details" on/off: the judge/engineer console vs the plain worker view. */
export function ViewToggle({ mode, onChange, size = "default", className }: ViewToggleProps) {
  const on = mode === "technical";
  const compact = size === "compact";
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label="Technical details"
      data-testid="view-toggle"
      data-view={mode}
      onClick={() => onChange(on ? "worker" : "technical")}
      className={cn(
        "group flex shrink-0 items-center gap-2.5 border border-line-strong text-fg/90 transition-colors hover:border-fg/70 hover:text-fg",
        compact ? "h-6 px-2 text-[10px] tracking-[0.14em] uppercase" : "h-10 px-3 text-[14px]",
        className,
      )}
    >
      <span>Technical details</span>
      {/* square track + thumb; the state is also spelled out */}
      <span
        aria-hidden
        className={cn(
          "relative inline-flex shrink-0 items-center border",
          compact ? "h-3 w-6" : "h-4 w-8",
          on ? "border-fg bg-fg/15" : "border-line-strong",
        )}
      >
        <span
          className={cn(
            "absolute transition-[left] duration-150",
            compact ? "top-[1px] size-2" : "top-[2px] size-2.5",
            on ? "bg-fg" : "bg-muted",
          )}
          style={{ left: on ? (compact ? 13 : 17) : 2 }}
        />
      </span>
      <span className={cn("tabular-nums", compact ? "w-[3ch]" : "w-[3ch] text-[12px] tracking-[0.12em] uppercase", on ? "text-fg" : "text-muted")}>
        {on ? "On" : "Off"}
      </span>
    </button>
  );
}
