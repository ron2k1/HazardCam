"use client";

import { MotionConfig } from "motion/react";
import type { ReactNode } from "react";

/** App-wide: motion components honour the OS prefers-reduced-motion setting. */
export function MotionProvider({ children }: { children: ReactNode }) {
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}
