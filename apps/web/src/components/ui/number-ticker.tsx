"use client"

/*
 * Origin: Magic UI "Number Ticker" (MIT, (c) Magic UI), listed on 21st.dev as
 * /@dillionverma/components/number-ticker; source pulled from the author's public
 * registry https://magicui.design/r/number-ticker.json because the 21st.dev registry
 * requires authentication. Normalized: project text color, re-animates when `value`
 * changes, faster near-critical spring, jumps straight to the value under
 * prefers-reduced-motion.
 */

import { useEffect, useRef, type ComponentPropsWithoutRef } from "react"
import { useInView, useMotionValue, useReducedMotion, useSpring } from "motion/react"

import { cn } from "@/lib/utils"

interface NumberTickerProps extends ComponentPropsWithoutRef<"span"> {
  value: number
  startValue?: number
  direction?: "up" | "down"
  delay?: number
  decimalPlaces?: number
}

function format(n: number, decimalPlaces: number): string {
  return Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimalPlaces,
    maximumFractionDigits: decimalPlaces,
  }).format(Number(n.toFixed(decimalPlaces)))
}

export function NumberTicker({
  value,
  startValue = 0,
  direction = "up",
  delay = 0,
  className,
  decimalPlaces = 0,
  ...props
}: NumberTickerProps) {
  const ref = useRef<HTMLSpanElement>(null)
  const reduceMotion = useReducedMotion()
  const motionValue = useMotionValue(direction === "down" ? value : startValue)
  // upstream: damping 60 / stiffness 100 (overdamped, ~3s to settle); near-critical here so a
  // telemetry readout lands on its true value in ~0.5s
  const springValue = useSpring(motionValue, {
    damping: 34,
    stiffness: 260,
    restDelta: 0.0005,
  })
  const isInView = useInView(ref, { once: true, margin: "0px" })

  useEffect(() => {
    if (reduceMotion) {
      if (ref.current) ref.current.textContent = format(value, decimalPlaces)
      return
    }
    let timer: ReturnType<typeof setTimeout> | null = null

    if (isInView) {
      timer = setTimeout(() => {
        motionValue.set(direction === "down" ? startValue : value)
      }, delay * 1000)
    }

    return () => {
      if (timer !== null) {
        clearTimeout(timer)
      }
    }
  }, [motionValue, isInView, delay, value, direction, startValue, reduceMotion, decimalPlaces])

  useEffect(
    () =>
      springValue.on("change", (latest) => {
        if (ref.current && !reduceMotion) {
          ref.current.textContent = format(latest, decimalPlaces)
        }
      }),
    [springValue, decimalPlaces, reduceMotion]
  )

  return (
    <span
      ref={ref}
      className={cn("inline-block tabular-nums text-fg", className)}
      {...props}
    >
      {format(startValue, decimalPlaces)}
    </span>
  )
}
