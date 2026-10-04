"use client";

import { cn } from "@/lib/utils";

// What this tab remembers about the wall: the checks' results (use-wall-orchestrator.ts SAVE_KEY)
// and which pop-outs already showed (site-wall.tsx POPPED_KEY).
const WALL_KEYS = ["cv-wall-checks-v3", "cv-wall-popped-v1"];

/** Forget this tab's wall results and pop-outs, then load the wall fresh so every check runs again. */
export function resetDemo() {
  for (const key of WALL_KEYS) {
    try {
      window.sessionStorage.removeItem(key);
    } catch {
      /* storage blocked: nothing was saved, the reload alone starts over */
    }
  }
  window.location.assign("/");
}

export function ResetDemoButton({ className }: { className?: string }) {
  return (
    <button
      type="button"
      onClick={resetDemo}
      title="Start the camera checks again from the beginning"
      className={cn(
        "flex h-8 shrink-0 items-center gap-2 border border-line-strong px-3 text-[13px] text-fg/80 transition-colors hover:bg-fg/10 hover:text-fg",
        className,
      )}
      data-testid="demo-reset"
    >
      <span aria-hidden>↺</span>
      Reset demo
    </button>
  );
}
