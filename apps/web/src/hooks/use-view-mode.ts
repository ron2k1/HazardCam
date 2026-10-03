"use client";

import { useCallback, useSyncExternalStore } from "react";

import { parseViewMode, VIEW_PARAM, type ViewMode } from "@/lib/view-mode";

export type { ViewMode } from "@/lib/view-mode";

const STORAGE_KEY = "cameravision.ops.view";
const CHANGE_EVENT = "cameravision:view-change";

function readStored(): ViewMode | null {
  try {
    return parseViewMode(window.localStorage.getItem(STORAGE_KEY));
  } catch {
    return null;
  }
}

function writeStored(mode: ViewMode): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // private window / blocked storage: the URL still carries the choice
  }
}

/** ?view= wins; without it the last choice on this browser; otherwise the worker view. */
function currentMode(): ViewMode {
  const fromUrl = parseViewMode(new URLSearchParams(window.location.search).get(VIEW_PARAM));
  return fromUrl ?? readStored() ?? "worker";
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, onChange);
  window.addEventListener("popstate", onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange);
    window.removeEventListener("popstate", onChange);
    window.removeEventListener("storage", onChange);
  };
}

/**
 * The /ops view, persisted in the URL (?view=technical; the worker view drops the param) and,
 * best effort, in localStorage. `initial` is what the server rendered from ?view=, so hydration
 * matches; a stored choice without a URL param applies right after hydration.
 */
export function useViewMode(initial: ViewMode | null): [ViewMode, (mode: ViewMode) => void] {
  const mode = useSyncExternalStore(subscribe, currentMode, () => initial ?? "worker");
  const setMode = useCallback((next: ViewMode) => {
    const url = new URL(window.location.href);
    if (next === "technical") url.searchParams.set(VIEW_PARAM, "technical");
    else url.searchParams.delete(VIEW_PARAM);
    window.history.replaceState(null, "", url);
    writeStored(next);
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, []);
  return [mode, setMode];
}
