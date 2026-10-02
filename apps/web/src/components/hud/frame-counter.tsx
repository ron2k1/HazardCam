"use client";

import { useEffect, useState } from "react";

import { useAmbientMotion } from "@/hooks/use-animate";

/** Incrementing frame id for telemetry chrome. Static under reduced motion. */
export function FrameCounter({ fps = 30, prefix = "FRAME" }: { fps?: number; prefix?: string }) {
  const animate = useAmbientMotion();
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    if (!animate) return;
    const start = performance.now();
    const id = window.setInterval(() => {
      setFrame(Math.floor(((performance.now() - start) / 1000) * fps));
    }, 100);
    return () => window.clearInterval(id);
  }, [animate, fps]);

  return (
    <span className="tabular-nums">
      {prefix} {String(frame).padStart(6, "0")}
    </span>
  );
}
