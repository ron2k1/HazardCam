/** /ops view. worker: the plain-language default; technical: the full judge/engineer console. */
export type ViewMode = "worker" | "technical";

/** The query parameter that carries the view: ?view=technical. */
export const VIEW_PARAM = "view";

export function parseViewMode(v: string | null | undefined): ViewMode | null {
  return v === "technical" || v === "worker" ? v : null;
}
