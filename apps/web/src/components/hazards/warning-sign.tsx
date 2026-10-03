import { cn } from "@/lib/utils";

/**
 * The hazard sign a worker sees wherever a hazard is named (wall tiles, notifications, toasts,
 * the /hazards cards): an ISO 7010-style warning triangle plus a short UPPERCASE label.
 *
 * The label and glyph come from configuration (config/hazards.yaml `signs`, served in each
 * HazardView card as `sign {label, glyph}`); this component never decides what a hazard is.
 * Inline SVG only, no external assets.
 */

export type HazardGlyph = "warning" | "trip" | "forklift" | "machine" | "eye" | "exit" | "eye-off";

export const HAZARD_GLYPHS: readonly HazardGlyph[] = ["warning", "trip", "forklift", "machine", "eye", "exit", "eye-off"];

export interface HazardSignData {
  label: string;
  glyph: HazardGlyph | string;
}

/** Sign labels stay short: at most 16 characters, uppercase. */
export const SIGN_LABEL_MAX = 16;

export function signLabel(label: string | null | undefined): string {
  const s = (label ?? "").trim().toUpperCase();
  if (!s) return "HAZARD";
  return s.length > SIGN_LABEL_MAX ? `${s.slice(0, SIGN_LABEL_MAX - 1).trimEnd()}…` : s;
}

function isGlyph(g: string | null | undefined): g is HazardGlyph {
  return !!g && (HAZARD_GLYPHS as readonly string[]).includes(g);
}

/* Black glyphs drawn inside the triangle (viewBox 0 0 24 24, usable area roughly x 7-17, y 9-19). */
function Glyph({ glyph }: { glyph: HazardGlyph }) {
  const ink = "#050505";
  switch (glyph) {
    case "trip":
      // a figure tripping over a step
      return (
        <g fill={ink} stroke={ink} strokeLinecap="square">
          <circle cx="13.6" cy="9.6" r="1.25" stroke="none" />
          <path d="M13.2 11.4 L11.2 14.6 M12.4 12.6 L15.4 13.6 M11.2 14.6 L13.4 17.2 M11.2 14.6 L8.6 15.8" strokeWidth="1.3" fill="none" />
          <rect x="14.2" y="17" width="3.2" height="2" stroke="none" />
          <rect x="6.8" y="18.6" width="10.6" height="0.9" stroke="none" />
        </g>
      );
    case "forklift":
      // a forklift side view: body, mast, forks, wheels
      return (
        <g fill={ink}>
          <rect x="7.2" y="13" width="5.6" height="3.8" />
          <rect x="8.2" y="10.6" width="2.6" height="2.6" fill="none" stroke={ink} strokeWidth="0.9" />
          <rect x="13.4" y="9.8" width="1.1" height="7.4" />
          <rect x="14.5" y="16.2" width="3" height="1" />
          <circle cx="8.6" cy="17.6" r="1.25" />
          <circle cx="12" cy="17.6" r="1.25" />
        </g>
      );
    case "machine":
      // two meshing rollers (entanglement / moving parts)
      return (
        <g fill="none" stroke={ink} strokeWidth="1.3">
          <circle cx="9.8" cy="15.2" r="2.6" />
          <circle cx="14.6" cy="15.2" r="2.6" />
          <circle cx="9.8" cy="15.2" r="0.6" fill={ink} stroke="none" />
          <circle cx="14.6" cy="15.2" r="0.6" fill={ink} stroke="none" />
          <path d="M12.2 9.8 L12.2 12" strokeLinecap="square" />
        </g>
      );
    case "eye":
      return (
        <g>
          <path d="M6.8 15.4 Q12 10.4 17.2 15.4 Q12 20.4 6.8 15.4 Z" fill="none" stroke={ink} strokeWidth="1.3" />
          <circle cx="12" cy="15.4" r="1.7" fill={ink} />
        </g>
      );
    case "eye-off":
      // an eye struck through (a view that is blocked: blind spot)
      return (
        <g>
          <path d="M6.8 15.4 Q12 10.4 17.2 15.4 Q12 20.4 6.8 15.4 Z" fill="none" stroke={ink} strokeWidth="1.3" />
          <circle cx="12" cy="15.4" r="1.7" fill={ink} />
          <path d="M7.6 19.4 L16.4 11" stroke={ink} strokeWidth="1.5" strokeLinecap="square" />
        </g>
      );
    case "exit":
      // a doorway with an arrow through it
      return (
        <g fill="none" stroke={ink} strokeWidth="1.2" strokeLinecap="square">
          <rect x="7.6" y="10.6" width="5" height="8.2" />
          <path d="M10 14.7 L16.6 14.7 M14.6 12.8 L16.6 14.7 L14.6 16.6" />
        </g>
      );
    case "warning":
    default:
      return (
        <g fill={ink}>
          <rect x="11" y="9" width="2" height="6.4" />
          <rect x="11" y="16.6" width="2" height="2" />
        </g>
      );
  }
}

/** The bare triangle (no label), for tight spots such as a tile corner. */
export function WarningTriangle({
  glyph,
  className,
  title,
}: {
  glyph?: HazardGlyph | string | null;
  className?: string;
  title?: string;
}) {
  const g: HazardGlyph = isGlyph(glyph) ? glyph : "warning";
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn("shrink-0", className)}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      data-glyph={g}
    >
      {/* ISO 7010 W001 shape: amber field, black border; square joins keep the HUD feel */}
      <path d="M12 1.8 L23 21.4 L1 21.4 Z" fill="var(--warning, #ffb340)" stroke="#050505" strokeWidth="1.4" strokeLinejoin="miter" />
      <path d="M12 4.6 L20.6 19.9 L3.4 19.9 Z" fill="none" stroke="#050505" strokeWidth="0.9" strokeLinejoin="miter" />
      <Glyph glyph={g} />
    </svg>
  );
}

export interface WarningSignProps {
  /** Short label from configuration, e.g. "BLOCKED AISLE"; uppercased and capped at 16 chars. */
  label: string;
  /** One of warning|trip|forklift|machine|eye|exit|eye-off; anything else draws "!". */
  glyph?: HazardGlyph | string | null;
  size?: "sm" | "md";
  className?: string;
}

/** A compact square-cornered sign: amber triangle + short uppercase label. */
export function WarningSign({ label, glyph, size = "sm", className }: WarningSignProps) {
  const text = signLabel(label);
  const md = size === "md";
  return (
    <span
      className={cn(
        "inline-flex max-w-full shrink-0 items-center border border-warning/80 bg-warning/[0.08] font-bold whitespace-nowrap text-warning uppercase",
        md ? "h-8 gap-2 pr-2.5 pl-1.5 text-[13px] tracking-[0.12em]" : "h-6 gap-1.5 pr-2 pl-1 text-[11px] tracking-[0.1em]",
        className,
      )}
      data-testid="warning-sign"
      data-sign-label={text}
      title={text}
    >
      <WarningTriangle glyph={glyph} className={md ? "size-6" : "size-[18px]"} />
      <span className="truncate leading-none">{text}</span>
    </span>
  );
}
