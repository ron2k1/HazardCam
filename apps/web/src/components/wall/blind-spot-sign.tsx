import { signLabel, WarningSign } from "@/components/hazards/warning-sign";
import type { SignData, WatchKind } from "@/lib/wall";
import { cn } from "@/lib/utils";

/**
 * The blind-spot sign: the same ISO 7010-style amber triangle as the hazard sign, with an eye
 * struck through (a view that is blocked). Inline SVG, no external assets. The label comes from
 * the API (config/hazards.yaml `signs`); this component never decides what was found.
 */
export function BlindSpotTriangle({ className, title }: { className?: string; title?: string }) {
  const ink = "#050505";
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn("shrink-0", className)}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      data-glyph="eye-off"
    >
      <path d="M12 1.8 L23 21.4 L1 21.4 Z" fill="var(--warning, #ffb340)" stroke={ink} strokeWidth="1.4" strokeLinejoin="miter" />
      {/* a solid eye with a bold strike: the inner outline is left off so the eye still reads at 18px */}
      <path d="M5.2 15.6 Q12 9 18.8 15.6 Q12 22.2 5.2 15.6 Z" fill={ink} />
      <circle cx="12" cy="15.6" r="2.6" fill="var(--warning, #ffb340)" />
      <circle cx="12" cy="15.6" r="1.1" fill={ink} />
      <path d="M6.6 20.2 L17 10.6" stroke="var(--warning, #ffb340)" strokeWidth="2.4" strokeLinecap="butt" />
      <path d="M6.6 20.2 L17 10.6" stroke={ink} strokeWidth="1.2" strokeLinecap="butt" />
    </svg>
  );
}

export function BlindSpotSign({
  label,
  size = "sm",
  className,
}: {
  label: string;
  size?: "sm" | "md";
  className?: string;
}) {
  const text = signLabel(label);
  const md = size === "md";
  return (
    <span
      className={cn(
        "inline-flex max-w-full shrink-0 items-center border border-warning/80 bg-warning/[0.08] font-bold whitespace-nowrap text-warning uppercase",
        md ? "h-8 gap-2 pr-2.5 pl-1.5 text-[13px] tracking-[0.12em]" : "h-6 gap-1.5 pr-2 pl-1 text-[11px] tracking-[0.1em]",
        className,
      )}
      data-testid="blind-spot-sign"
      data-sign-label={text}
      title={text}
    >
      <BlindSpotTriangle className={md ? "size-6" : "size-[18px]"} />
      <span className="truncate leading-none">{text}</span>
    </span>
  );
}

/** Blind-spot clips, or a sign whose glyph says so, draw the eye-off sign; hazards the triangle. */
function isBlindspot(kind: WatchKind, sign: SignData | null): boolean {
  return kind === "blindspot" || sign?.glyph === "eye-off";
}

/** The sign for one detection, with the label exactly as the API configured it. */
export function DetectionSign({
  kind,
  sign,
  size = "sm",
  className,
}: {
  kind: WatchKind;
  sign: SignData | null;
  size?: "sm" | "md";
  className?: string;
}) {
  // An API that sends no sign gets the sign's own fallback word for hazards; the watch type for blind spots.
  if (isBlindspot(kind, sign)) return <BlindSpotSign label={sign?.label || "BLIND SPOT"} size={size} className={className} />;
  return <WarningSign label={sign?.label ?? ""} glyph={sign?.glyph} size={size} className={className} />;
}

/** The bare triangle for a zone tag. */
export { WarningTriangle } from "@/components/hazards/warning-sign";
export { isBlindspot as isBlindspotSign };
