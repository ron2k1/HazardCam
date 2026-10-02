import { cn } from "@/lib/utils";

/** Deterministic bar glyph from a seed string (the reference footer's barcode mark). */
export function Barcode({ seed, bars = 14, className }: { seed: string; bars?: number; className?: string }) {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  const heights: number[] = [];
  for (let i = 0; i < bars; i++) {
    h ^= h << 13;
    h ^= h >>> 17;
    h ^= h << 5;
    heights.push(4 + (Math.abs(h) % 8));
  }
  return (
    <span aria-hidden className={cn("inline-flex h-3 items-end gap-[2px]", className)}>
      {heights.map((v, i) => (
        <span key={i} className="w-[2px] bg-fg/70" style={{ height: `${v}px` }} />
      ))}
    </span>
  );
}

export function StatusDot({
  tone = "fg",
  pulse = false,
  className,
}: {
  tone?: "fg" | "muted" | "dim" | "danger";
  pulse?: boolean;
  className?: string;
}) {
  const color = {
    fg: "bg-fg",
    muted: "bg-muted",
    dim: "bg-dim",
    danger: "bg-danger",
  }[tone];
  return <span aria-hidden className={cn("inline-block size-1.5", color, pulse && "blink", className)} />;
}
