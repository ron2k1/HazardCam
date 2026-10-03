"use client";

import { AnimatePresence, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";

import type { AlertDelivery, AlertMessage } from "@/lib/contracts";
import type { SeekTarget } from "@/lib/plain";
import type { RunPhase } from "@/lib/run-view";
import { cn } from "@/lib/utils";

import { AlertCard } from "./alert-card";

export interface MessageFeedProps {
  messages: readonly AlertMessage[];
  deliveries: Readonly<Record<string, AlertDelivery>>;
  phase: RunPhase;
  clean: (text: string) => string;
  targetsFor: (message: AlertMessage) => { targets: SeekTarget[]; firstMediaT: number | null };
  activeId?: string | null;
  onShow?: (message: AlertMessage) => void;
  className?: string;
}

/** Within this many px of the bottom counts as "at the bottom" (keeps following new cards). */
const STICK_PX = 48;

function emptyText(phase: RunPhase): string {
  switch (phase) {
    case "queued":
    case "running":
      return "No alerts yet. Checking the cameras…";
    case "complete":
      return "Check finished, but no message came back. Open Technical details to see the full result.";
    case "failed":
      return "The check stopped before it finished. Press Run to try again.";
    default:
      return "No alerts yet. Press Run to check the cameras.";
  }
}

/**
 * The worker's message feed, oldest first like a chat. It follows new cards while the reader is
 * at the bottom and stops following once they scroll up (a "new message" button brings them back).
 * Only scrolls itself where it is a scroll box (desktop); on a phone the page scrolls.
 */
export function MessageFeed({
  messages,
  deliveries,
  phase,
  clean,
  targetsFor,
  activeId = null,
  onShow,
  className,
}: MessageFeedProps) {
  const boxRef = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const [atBottom, setAtBottom] = useState(true);
  const [seen, setSeen] = useState(0);
  const reduce = useReducedMotion();
  const count = messages.length;
  const running = phase === "running" || phase === "queued";

  const toBottom = (smooth: boolean) => {
    const el = boxRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth && !reduce ? "smooth" : "auto" });
  };

  useEffect(() => {
    if (follow.current) toBottom(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- follow new cards only
  }, [count]);

  const onScroll = () => {
    const el = boxRef.current;
    if (!el) return;
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight <= STICK_PX;
    follow.current = bottom;
    setAtBottom(bottom);
    if (bottom) setSeen(count);
  };

  const unseen = !atBottom && count > seen ? count - seen : 0;
  // once the run's final message is in, the heads-up before it is answered: it goes quiet
  const finalMsg = [...messages].reverse().find((m) => m.kind !== "ping") ?? null;

  return (
    <div className={cn("relative flex min-h-0 flex-col", className)}>
      <div
        ref={boxRef}
        onScroll={onScroll}
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-label="Messages"
        data-testid="message-feed"
        className="thin-scroll flex min-h-0 flex-1 flex-col gap-3 p-3 lg:overflow-y-auto lg:p-4"
      >
        {count === 0 ? (
          <div className="dot-field flex min-h-[180px] flex-1 flex-col items-center justify-center gap-3 border border-dashed border-line-strong px-6 py-10 text-center">
            <span aria-hidden className="relative block size-7 border border-line-strong">
              <span className={cn("absolute inset-[9px] bg-fg/60", running && "blink")} />
            </span>
            <p className="max-w-[34ch] text-[16px] leading-[24px] text-fg/85" data-testid="message-empty">
              {emptyText(phase)}
            </p>
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {messages.map((m) => {
              const { targets, firstMediaT } = targetsFor(m);
              return (
                <AlertCard
                  key={m.id}
                  message={m}
                  delivery={deliveries[m.id] ?? null}
                  clean={clean}
                  targets={targets}
                  firstMediaT={firstMediaT}
                  active={activeId === m.id}
                  resolved={m.kind === "ping" && finalMsg !== null}
                  onShow={() => onShow?.(m)}
                />
              );
            })}
          </AnimatePresence>
        )}
      </div>
      {unseen > 0 ? (
        <button
          type="button"
          onClick={() => toBottom(true)}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 border border-fg bg-bg px-4 py-2 text-[14px] text-fg hover:bg-fg hover:text-bg"
        >
          {unseen === 1 ? "1 new message ↓" : `${unseen} new messages ↓`}
        </button>
      ) : null}
    </div>
  );
}
