import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Four L-shaped corner ticks; targeting-frame motif from the reference. */
export function CornerTicks({ className, size = 7 }: { className?: string; size?: number }) {
  const s = `${size}px`;
  const base = "pointer-events-none absolute border-fg/55";
  return (
    <span aria-hidden className={cn("pointer-events-none absolute inset-0", className)}>
      <span className={cn(base, "-top-px -left-px border-t border-l")} style={{ width: s, height: s }} />
      <span className={cn(base, "-top-px -right-px border-t border-r")} style={{ width: s, height: s }} />
      <span className={cn(base, "-bottom-px -left-px border-b border-l")} style={{ width: s, height: s }} />
      <span className={cn(base, "-right-px -bottom-px border-r border-b")} style={{ width: s, height: s }} />
    </span>
  );
}

export interface PanelProps {
  /** Two/three digit panel index shown before the title, e.g. "03". */
  index: string;
  title: string;
  /** Right-aligned telemetry in the header strip. */
  meta?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  id?: string;
}

/** Square 1px panel with a telemetry header strip. */
export function Panel({ index, title, meta, children, className, bodyClassName, id }: PanelProps) {
  return (
    <section
      id={id}
      aria-label={title}
      className={cn("@container relative flex min-h-0 min-w-0 flex-col border border-line bg-panel/80", className)}
    >
      <CornerTicks />
      <header className="flex h-7 shrink-0 items-center justify-between gap-3 border-b border-line px-2.5">
        <h2 className="flex min-w-0 items-center gap-2 text-[10px] tracking-[0.18em] text-fg uppercase">
          <span className="text-muted">{index}</span>
          <span className="h-px w-3 bg-line-strong" aria-hidden />
          <span className="truncate">{title}</span>
        </h2>
        {meta ? <div className="micro flex shrink-0 items-center gap-3">{meta}</div> : null}
      </header>
      <div className={cn("relative min-h-0 flex-1", bodyClassName)}>{children}</div>
    </section>
  );
}
