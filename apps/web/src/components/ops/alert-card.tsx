"use client";

import { motion } from "motion/react";
import type { ReactNode } from "react";

import { CornerTicks } from "@/components/hud/panel";
import { useMounted } from "@/hooks/use-animate";
import type { AlertDelivery, AlertLevel, AlertLine, AlertMessage } from "@/lib/contracts";
import { DELIVERY_WORD, LEVEL_WORD, SHOWN_DELIVERY, URGENT_KINDS, kindWord, plainOr, type SeekTarget } from "@/lib/plain";
import { cn } from "@/lib/utils";

export interface AlertCardProps {
  message: AlertMessage;
  /** Latest alert.delivery; shown only for a real send or a failed one (SHOWN_DELIVERY). */
  delivery: AlertDelivery | null;
  /** Leak check for every string shown: returns what may be shown, "" to hide (the server already writes plain text). */
  clean: (text: string) => string;
  /** Where "Show on video" jumps; empty hides the button. */
  targets: readonly SeekTarget[];
  /** Media seconds of the first target, for tests and tooling (not shown). */
  firstMediaT?: number | null;
  onShow?: () => void;
  /** This message is the one on the videos right now. */
  active?: boolean;
  /** A heads-up the run's final message has since answered: shown quiet and folded, never amber. */
  resolved?: boolean;
}

const LEVEL: Record<AlertLevel, { edge: string; text: string; border: string; dot: string }> = {
  danger: { edge: "bg-danger", text: "text-danger", border: "border-danger/80", dot: "bg-danger" },
  warning: { edge: "bg-warning", text: "text-warning", border: "border-warning/80", dot: "bg-warning" },
  info: { edge: "bg-fg/45", text: "text-fg/90", border: "border-line-strong", dot: "bg-fg/60" },
};

/** Rows under the action callout, most useful first; the server's line order is left alone. */
const ROW_ORDER: readonly AlertLine["key"][] = ["how_sure", "where", "when", "seen_on", "what"];

const DELIVERY_DOT: Record<AlertDelivery["status"], string> = {
  sent: "bg-fg",
  not_connected: "bg-muted",
  skipped: "bg-muted",
  failed: "bg-danger",
};

function localTime(iso: string): string {
  const d = new Date(iso);
  if (!iso || Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/**
 * One plain-language message: kind and urgency in words, headline, then "What to do" straight
 * under it, then the other rows. A resolved heads-up folds its rows away behind "Earlier heads-up".
 */
export function AlertCard({
  message,
  delivery,
  clean,
  targets,
  firstMediaT = null,
  onShow,
  active = false,
  resolved = false,
}: AlertCardProps) {
  // local time only after hydration: the server's clock zone is not the viewer's
  const mounted = useMounted();
  const quiet = resolved && message.kind === "ping";
  const tone = LEVEL[quiet ? "info" : message.level];
  const kind = kindWord(message);
  const lines = message.lines
    .map((l) => ({ ...l, label: plainOr(l.label, ""), value: clean(l.value) }))
    .filter((l) => l.label && l.value);
  const todo = lines.find((l) => l.key === "what_to_do") ?? null;
  const rows = ROW_ORDER.flatMap((key) => lines.filter((l) => l.key === key));
  const headline = plainOr(message.headline, kind);
  const sent = mounted ? localTime(message.created_at) : "";
  const showDelivery = !!delivery && SHOWN_DELIVERY.has(delivery.status);
  const hasFooter = showDelivery || targets.length > 0;

  const body: ReactNode = (
    <>
      {todo ? (
        <dl className="mt-2.5 mr-4">
          <div data-line="what_to_do" className="border-l-2 border-fg py-0.5 pl-3">
            <dt className="text-[14px] leading-[20px] text-fg/70">{todo.label}</dt>
            <dd className="text-[17px] leading-[24px] font-semibold break-words text-fg">{todo.value}</dd>
          </div>
        </dl>
      ) : null}
      {rows.length ? (
        <>
          <div className="rule-dotted mt-3 mr-4" aria-hidden />
          <dl className="pt-1 pr-4 pb-1">
            {rows.map((l, i) => (
              <div
                key={`${l.key}-${i}`}
                data-line={l.key}
                className={cn(
                  "grid grid-cols-1 gap-x-4 gap-y-0.5 py-2 sm:grid-cols-[9.5rem_minmax(0,1fr)]",
                  i > 0 && "border-t border-line",
                )}
              >
                <dt className="text-[14px] leading-[22px] text-fg/65">{l.label}</dt>
                <dd className="min-w-0 text-[15px] leading-[22px] break-words text-fg/95">{l.value}</dd>
              </div>
            ))}
          </dl>
        </>
      ) : null}
    </>
  );

  const footer: ReactNode = hasFooter ? (
    <footer className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line py-3 pr-4">
      {showDelivery && delivery ? (
        <span
          className={cn("flex items-center gap-1.5 text-[14px]", delivery.status === "failed" ? "text-danger" : "text-fg/85")}
          data-testid="alert-delivery"
          data-status={delivery.status}
        >
          <span aria-hidden className={cn("inline-block size-2", DELIVERY_DOT[delivery.status])} />
          {DELIVERY_WORD[delivery.status]}
        </span>
      ) : null}
      {targets.length ? (
        <button
          type="button"
          onClick={onShow}
          data-testid="show-on-video"
          data-seek-camera={targets[0].cameraId}
          data-seek-t={firstMediaT ?? undefined}
          aria-pressed={active}
          className={cn(
            "ml-auto flex h-10 items-center gap-2 border px-4 text-[14px] transition-colors",
            active ? "border-fg bg-fg text-bg" : "border-fg/80 text-fg hover:bg-fg hover:text-bg",
          )}
        >
          <span aria-hidden className="text-[11px]">▶</span>
          Show on video
        </button>
      ) : null}
    </footer>
  ) : null;

  return (
    <motion.article
      layout="position"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.2, 0.7, 0.2, 1] }}
      aria-label={`${kind}: ${headline}`}
      data-testid="alert-card"
      data-message-id={message.id}
      data-kind={message.kind}
      data-level={message.level}
      data-delivery={delivery?.status}
      data-resolved={quiet ? "true" : undefined}
      className={cn(
        "relative min-w-0 border bg-panel pl-4 sm:pl-5",
        active ? "border-fg/70" : "border-line-strong",
        !hasFooter && !quiet && "pb-2",
      )}
    >
      <span aria-hidden className={cn("absolute inset-y-0 left-0 w-[3px]", tone.edge)} />
      <CornerTicks size={8} />

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 pt-3.5 pr-4">
        <span
          className={cn("border px-2 py-0.5 text-[14px] leading-[20px] font-bold tracking-[0.12em]", tone.border, tone.text)}
          data-testid="alert-kind"
        >
          {kind}
        </span>
        {quiet ? (
          <span data-testid="alert-resolved" className="text-[14px] text-fg/70">
            Checked. See the result below.
          </span>
        ) : URGENT_KINDS.has(message.kind) ? (
          <span className="flex items-center gap-1.5 text-[14px] font-semibold text-fg/90" data-testid="alert-level">
            <span aria-hidden className={cn("inline-block size-2", tone.dot)} />
            {LEVEL_WORD[message.level]}
          </span>
        ) : null}
        <time dateTime={message.created_at} className="ml-auto text-[14px] text-fg/70 tabular-nums">
          {sent ? `Sent ${sent}` : ""}
        </time>
      </div>

      <h3
        className={cn(
          "pt-2.5 pr-4 font-bold",
          quiet ? "text-[17px] leading-[1.3] text-fg/70" : "text-[20px] leading-[1.25] text-fg sm:text-[22px]",
        )}
        data-testid="alert-headline"
      >
        {headline}
      </h3>

      {quiet ? (
        <details className="group pr-4 pt-1.5 pb-3">
          <summary className="cursor-pointer text-[14px] text-fg/70 hover:text-fg">Earlier heads-up</summary>
          {body}
          {footer}
        </details>
      ) : (
        <>
          {body}
          {footer}
        </>
      )}
    </motion.article>
  );
}
