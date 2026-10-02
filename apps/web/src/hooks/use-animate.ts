"use client";

import { useReducedMotion } from "motion/react";
import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/** True only on the client after hydration. Avoids server/client markup drift. */
export function useMounted(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}

/**
 * Whether continuous/ambient animation should run: client-only (so SSR markup matches)
 * and never under prefers-reduced-motion.
 */
export function useAmbientMotion(): boolean {
  const mounted = useMounted();
  const reduce = useReducedMotion();
  return mounted && !reduce;
}
