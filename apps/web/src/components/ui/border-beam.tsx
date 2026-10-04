"use client"

/*
 * Origin: Magic UI "Border Beam" (MIT, (c) Magic UI), listed on 21st.dev as
 * https://21st.dev/r/magicui/border-beam; source pulled from the author's public registry
 * https://magicui.design/r/border-beam.json because the 21st.dev registry requires
 * authentication. Normalized for this project: square path (radius 0), amber/off-white
 * defaults from the project tokens, and no beam at all under prefers-reduced-motion
 * (callers keep a static amber border instead).
 */

import type React from "react"
import { motion, type MotionStyle, type Transition } from "motion/react"

import { usePrefersReducedMotion } from "@/components/alerts/use-reduced-motion"
import { cn } from "@/lib/utils"

interface BorderBeamProps {
  /** Length of the travelling beam in px. */
  size?: number
  /** Seconds per lap. */
  duration?: number
  /** Seconds of phase offset. */
  delay?: number
  colorFrom?: string
  colorTo?: string
  transition?: Transition
  className?: string
  style?: React.CSSProperties
  reverse?: boolean
  /** Initial offset position along the border (0-100). */
  initialOffset?: number
  borderWidth?: number
}

export const BorderBeam = ({
  className,
  size = 80,
  delay = 0,
  duration = 4,
  colorFrom = "var(--warning, #ffb340)",
  colorTo = "#fff4dc",
  transition,
  style,
  reverse = false,
  initialOffset = 0,
  borderWidth = 2,
}: BorderBeamProps) => {
  const reduce = usePrefersReducedMotion()
  if (reduce) return null
  return (
    <div
      aria-hidden
      // overflow-clip (edge pushed out to the border box) keeps the travelling square's layout box
      // from adding page scroll when the frame sits at the viewport edge; the mask still draws it
      className="pointer-events-none absolute inset-0 overflow-clip border-(length:--border-beam-width) border-transparent [overflow-clip-margin:var(--border-beam-width)] mask-[linear-gradient(transparent,transparent),linear-gradient(#000,#000)] mask-intersect [mask-clip:padding-box,border-box]"
      style={{ "--border-beam-width": `${borderWidth}px` } as React.CSSProperties}
    >
      <motion.div
        className={cn(
          "absolute aspect-square",
          "bg-linear-to-l from-(--color-from) via-(--color-to) to-transparent",
          className,
        )}
        style={
          {
            width: size,
            offsetPath: "rect(0 auto auto 0)",
            "--color-from": colorFrom,
            "--color-to": colorTo,
            ...style,
          } as MotionStyle
        }
        initial={{ offsetDistance: `${initialOffset}%` }}
        animate={{
          offsetDistance: reverse
            ? [`${100 - initialOffset}%`, `${-initialOffset}%`]
            : [`${initialOffset}%`, `${100 + initialOffset}%`],
        }}
        transition={{ repeat: Infinity, ease: "linear", duration, delay: -delay, ...transition }}
      />
    </div>
  )
}
