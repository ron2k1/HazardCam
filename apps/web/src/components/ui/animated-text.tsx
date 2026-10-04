import type { CSSProperties } from "react";

import { cn } from "@/lib/utils";

interface AnimatedTextProps {
  text: string;
  /** px */
  fontSize?: number;
  /** Variable-font weight range; JetBrains Mono's axis is 100-800. */
  minWeight?: number;
  maxWeight?: number;
  /** Seconds for one light-to-heavy sweep (it then sweeps back). */
  animationDuration?: number;
  /** Seconds of offset between neighbouring letters, centred on the middle letter. */
  delayMultiplier?: number;
  className?: string;
}

/**
 * Text whose letters "breathe" between two weights in a wave across the word. The keyframes and
 * the `.breath-letter` animation live in globals.css and read CSS variables set here, so this
 * stays a plain server-renderable component (no styled-jsx). Under reduced motion the letters
 * hold the heavy weight with no wave. Screen readers get the word once, not letter by letter.
 */
export function AnimatedText({
  text,
  fontSize = 150,
  minWeight = 100,
  maxWeight = 800,
  animationDuration = 1.5,
  delayMultiplier = 0.25,
  className,
}: AnimatedTextProps) {
  const letters = text.split("");
  const style = {
    fontSize: `${fontSize}px`,
    "--breath-min": minWeight,
    "--breath-max": maxWeight,
    "--breath-s": `${animationDuration}s`,
  } as CSSProperties;

  return (
    <span className={cn("m-0 inline-block whitespace-pre", className)} style={style}>
      <span className="sr-only">{text}</span>
      {letters.map((char, i) => (
        <span
          key={i}
          aria-hidden
          className="breath-letter"
          style={{ "--breath-delay": `${(i - letters.length / 2) * delayMultiplier}s` } as CSSProperties}
        >
          {char}
        </span>
      ))}
    </span>
  );
}
