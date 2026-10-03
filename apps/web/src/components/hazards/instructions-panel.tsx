import type { PlainInstructions } from "@/lib/hazards";
import { cn } from "@/lib/utils";

export interface InstructionsPanelProps {
  instructions: PlainInstructions;
  /** Before a check: "will be asked". */
  future?: boolean;
  className?: string;
}

/** "What the AI was asked to check": the plain checklist and answer rules from config/hazards.yaml. */
export function InstructionsPanel({ instructions, future = false, className }: InstructionsPanelProps) {
  return (
    <section aria-labelledby="hz-instructions" className={cn("border border-line bg-panel/60", className)} data-testid="instructions">
      <header className="flex min-h-11 items-center border-b border-line px-4">
        <h2 id="hz-instructions" className="text-[15px] font-bold tracking-[0.12em] text-fg uppercase">
          What the AI {future ? "will be" : "was"} asked to check
        </h2>
      </header>
      <div className="grid gap-x-8 gap-y-5 p-4 md:grid-cols-2">
        <div>
          <h3 className="mb-2 text-[13px] text-fg/60">Checks</h3>
          <ul className="flex flex-col gap-2" data-testid="instruction-checks">
            {instructions.checks.map((c, i) => (
              <li key={i} className="grid grid-cols-[1.5rem_minmax(0,1fr)] text-[14px] leading-[21px] text-fg/95">
                <span aria-hidden className="mt-[4px] size-3 border border-fg/60" />
                <span>{c}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="mb-2 text-[13px] text-fg/60">How the AI must answer</h3>
          <ul className="flex flex-col gap-2" data-testid="instruction-rules">
            {instructions.rules.map((r, i) => (
              <li key={i} className="grid grid-cols-[1.5rem_minmax(0,1fr)] text-[14px] leading-[21px] text-fg/85">
                <span aria-hidden className="text-fg/40">—</span>
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
