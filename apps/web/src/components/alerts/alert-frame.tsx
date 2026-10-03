"use client";

/*
 * AlertFrame: wraps a camera tile. Inactive, it renders the children unchanged (the wrapper div is
 * kept so a playing <video> never remounts). Active, it overlays a pulsing amber outline with a
 * travelling border beam (components/ui/border-beam.tsx, Magic UI via 21st.dev), corner brackets,
 * a top-left stamp (warning triangle + short label) and an optional spotlight vignette.
 * Reduced motion: static amber outline, no beam, no pulse, no flash.
 */

import type { ReactNode } from "react";
import { motion } from "motion/react";

import { WarningTriangle, type AlertTone } from "@/components/alerts/warning-triangle";
import { BorderBeam } from "@/components/ui/border-beam";
import { usePrefersReducedMotion } from "@/components/alerts/use-reduced-motion";
import { cn } from "@/lib/utils";

export interface AlertFrameProps {
  active: boolean;
  /** Short stamp label, e.g. "BLOCKED AISLE". */
  label?: string;
  /** Optional micro prefix in the stamp, e.g. "CAM 2". */
  kicker?: string;
  glyph?: string;
  tone?: AlertTone;
  /** Darken the tile edges and glow amber inside, to pull the eye to this tile. */
  spotlight?: boolean;
  className?: string;
  children: ReactNode;
}

const BRACKET = "pointer-events-none absolute size-5 border-warning";

export function AlertFrame({ active, label, kicker, glyph, tone = "hazard", spotlight = false, className, children }: AlertFrameProps) {
  const reduce = usePrefersReducedMotion();
  return (
    <div className={cn("relative", className)} data-alert-active={active ? "true" : "false"}>
      {children}
      {active ? (
        <div className="pointer-events-none absolute inset-0 z-20" aria-hidden={label ? undefined : true}>
          {spotlight ? (
            <div
              className="absolute inset-0"
              style={{
                background: "radial-gradient(ellipse at center, transparent 45%, rgba(5,5,5,0.55) 100%)",
                boxShadow: "inset 0 0 60px rgba(255,179,64,0.28)",
              }}
            />
          ) : null}
          {!reduce ? (
            <motion.div
              className="absolute inset-0 bg-warning"
              initial={{ opacity: 0.45 }}
              animate={{ opacity: 0 }}
              transition={{ duration: 0.7, ease: "easeOut" }}
            />
          ) : null}
          {/* outline: pulses unless reduced motion */}
          <motion.div
            className="absolute inset-0 border-2 border-warning"
            style={{ boxShadow: "0 0 0 1px #050505, 0 0 22px rgba(255,179,64,0.55), inset 0 0 18px rgba(255,179,64,0.25)" }}
            initial={false}
            animate={reduce ? { opacity: 1 } : { opacity: [1, 0.35, 1] }}
            transition={reduce ? { duration: 0 } : { duration: 1.2, ease: "easeInOut", repeat: Infinity }}
          />
          <BorderBeam size={140} duration={3.2} borderWidth={3} />
          <BorderBeam size={140} duration={3.2} borderWidth={3} initialOffset={50} />
          <span className={cn(BRACKET, "-top-1.5 -left-1.5 border-t-[3px] border-l-[3px]")} />
          <span className={cn(BRACKET, "-top-1.5 -right-1.5 border-t-[3px] border-r-[3px]")} />
          <span className={cn(BRACKET, "-bottom-1.5 -left-1.5 border-b-[3px] border-l-[3px]")} />
          <span className={cn(BRACKET, "-right-1.5 -bottom-1.5 border-r-[3px] border-b-[3px]")} />
          {label ? (
            <motion.div
              className="absolute top-2 left-2 flex h-7 max-w-[calc(100%-16px)] items-center gap-1.5 border border-[#050505] bg-warning pr-2.5 pl-1 text-[12px] leading-none font-bold tracking-[0.12em] whitespace-nowrap text-[#050505] uppercase shadow-[0_4px_16px_rgba(0,0,0,0.6)]"
              initial={reduce ? false : { x: -16, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              transition={{ type: "spring", stiffness: 420, damping: 28 }}
              data-testid="alert-frame-stamp"
            >
              <WarningTriangle glyph={glyph} tone={tone} size={20} />
              {kicker ? <span className="text-[9px] tracking-[0.18em] opacity-70">{kicker}</span> : null}
              <span className="truncate">{label}</span>
            </motion.div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
