import type { ToolSummary } from "./contracts";

const pad = (n: number, w = 2) => String(Math.floor(Math.abs(n))).padStart(w, "0");

/** Seconds -> "MM:SS.ss" timecode. */
export function timecode(seconds: number | null | undefined, decimals = 2): string {
  if (seconds == null || !Number.isFinite(seconds)) return "--:--.--";
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  const rest = s - m * 60;
  const whole = Math.floor(rest);
  const frac = decimals > 0 ? `.${pad(Math.round((rest - whole) * 10 ** decimals), decimals)}` : "";
  return `${pad(m)}:${pad(whole)}${frac}`;
}

/** ISO timestamp -> "HH:MM:SS.mmm" (UTC, wall clock). */
export function wallClock(iso: string | null | undefined): string {
  if (!iso) return "--:--:--.---";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "--:--:--.---";
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}.${pad(d.getUTCMilliseconds(), 3)}`;
}

/** snake_case / dotted identifiers -> spaced uppercase label. */
export function label(id: string | null | undefined): string {
  if (!id) return "—";
  return id.replace(/[_.]+/g, " ").trim().toUpperCase();
}

export function pct(x: number | null | undefined, digits = 0): string {
  if (x == null || !Number.isFinite(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

export function fixed(x: number | null | undefined, digits = 2): string {
  if (x == null || !Number.isFinite(x)) return "—";
  return x.toFixed(digits);
}

export function signedCoord(x: number | null | undefined, digits = 1): string {
  if (x == null || !Number.isFinite(x)) return "—";
  return `${x >= 0 ? "+" : "-"}${Math.abs(x).toFixed(digits)}`;
}

export function deg(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return "---°";
  return `${pad(((x % 360) + 360) % 360, 3)}°`;
}

export function ms(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return "—";
  return x >= 1000 ? `${(x / 1000).toFixed(2)}s` : `${Math.round(x)}ms`;
}

/** Tool args/result summaries: strings verbatim, objects as compact k=v pairs. */
export function summary(s: ToolSummary | undefined): string {
  if (s == null) return "";
  if (typeof s === "string") return s;
  return Object.entries(s)
    .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(" ");
}

/** Seconds since `startIso` at `iso`: "+1.98S", or "+1:02.4" past a minute. */
export function elapsed(iso: string | null | undefined, startIso: string | null | undefined): string {
  if (!iso || !startIso) return "+—";
  const s = (Date.parse(iso) - Date.parse(startIso)) / 1000;
  if (!Number.isFinite(s)) return "+—";
  const t = Math.max(0, s);
  if (t < 60) return `+${t.toFixed(2)}S`;
  const m = Math.floor(t / 60);
  return `+${m}:${(t - m * 60).toFixed(1).padStart(4, "0")}`;
}

/** Hard clip with an ellipsis, for controls that cannot ellipsize (native <select>). */
export function clip(s: string, max: number): string {
  return s.length <= max ? s : `${s.slice(0, Math.max(max - 1, 0)).trimEnd()}…`;
}

export function seqId(n: number, width = 4): string {
  return pad(n, width);
}
