"use client";

import { useEffect, useState } from "react";

/**
 * Current time, refreshed every `everyMs` while `active`. Null until mounted, so server and
 * client markup match (the wall never renders a clock on the server).
 */
export function useNow(everyMs = 1000, active = true): Date | null {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    if (!active) return;
    const tick = () => setNow(new Date());
    const first = setTimeout(tick, 0);
    const id = setInterval(tick, everyMs);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [everyMs, active]);
  return now;
}
