"use client";

import { StatusDot } from "@/components/hud/barcode";
import type { ClipSummary, WallTiles } from "@/lib/hazards";
import { cn } from "@/lib/utils";

import { isBlindspot } from "./derive";

/** What this browser session knows about a camera (never a stored result). */
export interface CameraState {
  text: string;
  tone: "fg" | "warning" | "danger" | "muted";
  busy?: boolean;
}

export interface CameraSwitcherProps {
  clips: readonly ClipSummary[];
  selectedId: string | null;
  onSelect: (clipId: string) => void;
  states: Record<string, CameraState | undefined>;
  cams: Record<string, number>;
}

export const camLabel = (n: number | undefined) => (n ? `CAM ${n}` : "CAM");

/**
 * Camera numbers matching the home wall: the wall's own CAM numbers when it answers, otherwise
 * its defaults (the first three hazard clips by id are CAM 1-3, blind-spot clips CAM 4-6); any
 * other clip comes after. Returns the clips in camera order and the numbers by clip id.
 */
export function cameraOrder(clips: readonly ClipSummary[], wall: WallTiles | null): { ordered: ClipSummary[]; cams: Record<string, number> } {
  const cams: Record<string, number> = {};
  const tiles = [...(wall?.hazard_tiles ?? []), ...(wall?.blindspot_tiles ?? [])];
  if (tiles.length) {
    for (const t of tiles) if (clips.some((c) => c.clip_id === t.clip_id)) cams[t.clip_id] = t.cam;
  } else {
    const byId = [...clips].sort((a, b) => a.clip_id.localeCompare(b.clip_id, undefined, { numeric: true }));
    byId.filter((c) => !isBlindspot(c.kind)).slice(0, 3).forEach((c, i) => (cams[c.clip_id] = i + 1));
    byId.filter((c) => isBlindspot(c.kind)).slice(0, 3).forEach((c, i) => (cams[c.clip_id] = i + 4));
  }
  let next = Math.max(6, ...Object.values(cams)) + 1;
  const rest = clips.filter((c) => !(c.clip_id in cams));
  for (const c of [...rest.filter((c) => !isBlindspot(c.kind)), ...rest.filter((c) => isBlindspot(c.kind))]) cams[c.clip_id] = next++;
  // When the wall answers, the rail shows only its cameras, so both screens count the same six.
  const shown = tiles.length ? clips.filter((c) => tiles.some((t) => t.clip_id === c.clip_id)) : [...clips];
  const ordered = shown.sort((a, b) => cams[a.clip_id] - cams[b.clip_id]);
  return { ordered, cams };
}

const TONE: Record<CameraState["tone"], string> = {
  fg: "text-fg",
  warning: "text-warning",
  danger: "text-danger",
  muted: "text-fg/55",
};

/** Desktop: the cameras as a strip of tabs. Picking one resets the screen to its live feed. */
export function CameraStrip({ clips, selectedId, onSelect, states, cams }: CameraSwitcherProps) {
  return (
    <nav aria-label="Cameras" className="thin-scroll flex min-w-0 overflow-x-auto border-b border-line" data-testid="camera-strip">
      {clips.map((c) => {
        const selected = c.clip_id === selectedId;
        const st = states[c.clip_id];
        return (
          <button
            key={c.clip_id}
            type="button"
            onClick={() => onSelect(c.clip_id)}
            aria-current={selected ? "true" : undefined}
            data-testid="clip-item"
            data-clip-id={c.clip_id}
            className={cn(
              "relative flex min-w-[11.5rem] shrink-0 flex-col gap-0.5 border-r border-line px-4 py-2 text-left transition-colors",
              selected ? "bg-fg/[0.07]" : "hover:bg-fg/[0.04]",
            )}
          >
            {selected ? <span aria-hidden className="absolute inset-x-0 bottom-0 h-[2px] bg-fg" /> : null}
            <span className="flex items-center gap-2">
              <span className="text-[11px] font-bold tracking-[0.16em] text-fg/70">{camLabel(cams[c.clip_id])}</span>
              {isBlindspot(c.kind) ? <span className="border border-line-strong px-1 text-[10px] leading-[14px] tracking-[0.1em] text-fg/70 uppercase">Blind spot</span> : null}
            </span>
            <span className="truncate text-[14px] leading-[19px] font-bold text-fg">{c.title}</span>
            <span className={cn("flex h-4 items-center gap-1.5 text-[12px]", st ? TONE[st.tone] : "text-transparent")}>
              {st?.busy ? <StatusDot tone="fg" pulse /> : null}
              {st?.text ?? "·"}
            </span>
          </button>
        );
      })}
    </nav>
  );
}

/** Narrow screens: the same cameras as a select. */
export function CameraSelect({ clips, selectedId, onSelect, states, cams }: CameraSwitcherProps) {
  return (
    <label htmlFor="hazard-camera" className="flex w-full min-w-0 flex-col gap-1.5">
      <span className="text-[13px] text-fg/65">Camera</span>
      <select
        id="hazard-camera"
        data-testid="clip-select"
        className="hud-select h-11 w-full min-w-0 border border-line-strong bg-bg pr-8 pl-2.5 text-[14px] text-fg outline-none hover:border-fg/70 focus-visible:border-fg"
        value={selectedId ?? ""}
        onChange={(e) => onSelect(e.target.value)}
      >
        {clips.map((c) => {
          const st = states[c.clip_id];
          return (
            <option key={c.clip_id} value={c.clip_id}>
              {camLabel(cams[c.clip_id])} · {c.title}
              {st ? ` — ${st.text}` : ""}
            </option>
          );
        })}
      </select>
    </label>
  );
}
