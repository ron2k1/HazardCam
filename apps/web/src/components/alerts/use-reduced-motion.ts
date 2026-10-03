"use client";

import { useSyncExternalStore } from "react";

/*
 * Hydration-safe prefers-reduced-motion: the server render and the first client render both see
 * `false`, then React re-renders with the real media query value (no hydration mismatch, unlike
 * reading matchMedia during the first render).
 */
const QUERY = "(prefers-reduced-motion: reduce)";

function subscribe(onChange: () => void) {
  if (typeof window === "undefined" || !window.matchMedia) return () => {};
  const m = window.matchMedia(QUERY);
  m.addEventListener("change", onChange);
  return () => m.removeEventListener("change", onChange);
}

export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => (typeof window !== "undefined" && !!window.matchMedia ? window.matchMedia(QUERY).matches : false),
    () => false,
  );
}
