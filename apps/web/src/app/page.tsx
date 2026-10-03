import Link from "next/link";

import { Barcode, StatusDot } from "@/components/hud/barcode";
import { FrameCounter } from "@/components/hud/frame-counter";
import { IntersectionWireframe } from "@/components/landing/intersection-wireframe";
import { buttonVariants } from "@/components/ui/button";
import { FlickeringGrid } from "@/components/ui/flickering-grid";
import { APP_VERSION } from "@/lib/config";
import { cn } from "@/lib/utils";

export default function LandingPage() {
  return (
    <main className="relative flex h-dvh min-h-[640px] flex-col overflow-hidden bg-bg">
      <FlickeringGrid className="absolute inset-0 z-0" squareSize={2} gridGap={11} maxOpacity={0.34} />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 z-0 bg-[radial-gradient(ellipse_at_30%_50%,transparent_0%,rgba(5,5,5,0.55)_70%)]"
      />

      {/* top bar */}
      <header className="relative z-10 flex h-14 shrink-0 items-center justify-between border-b border-line px-6 lg:px-10">
        <div className="flex items-center gap-4">
          <span className="text-[17px] font-extrabold tracking-[0.06em] text-fg italic">CameraVision</span>
          <span className="h-4 w-px bg-line-strong" aria-hidden />
          <span className="tele">EST. 2026</span>
        </div>
        <div className="tele hidden items-center gap-3 sm:flex">
          <span>FRAME: LOCAL METRIC</span>
          <StatusDot tone="muted" />
          <span>N 000° · E 090°</span>
        </div>
      </header>

      {/* hero */}
      <section className="relative z-10 grid min-h-0 flex-1 grid-cols-1 items-center gap-8 px-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] lg:px-[7vw]">
        <div className="flex max-w-[640px] flex-col">
          <div className="flex items-center gap-3">
            <span className="h-px w-8 bg-line-strong" aria-hidden />
            <span className="micro">001</span>
            <span className="h-px flex-1 bg-line-strong" aria-hidden />
          </div>

          <div className="mt-5 flex gap-5">
            <span className="rule-dotted-v shrink-0" aria-hidden />
            {/* 10 mono glyphs x (0.6em advance + 0.11em tracking) = 7.1em per line; the clamp keeps
                "THE UNSEEN" inside the hero column from 1280px up */}
            <h1 className="text-[clamp(40px,5.4vw,82px)] leading-[1.06] font-extrabold tracking-[0.11em] text-fg">
              <span className="block whitespace-nowrap">
                INFER <span className="text-dim">/</span>
              </span>
              <span className="block whitespace-nowrap">THE UNSEEN</span>
            </h1>
          </div>

          <div className="rule-dotted mt-6 w-[56%]" aria-hidden />

          <p className="mt-5 max-w-[460px] text-[14px] leading-[1.7] text-fg/80">
            Causal intelligence from distributed visual evidence.
          </p>

          <dl className="micro mt-5 grid max-w-[460px] grid-cols-3 gap-px border border-line bg-line">
            {[
              ["INPUT", "3 CAMERAS"],
              ["WITHHELD", "1 GT CAMERA"],
              ["INFERENCE", "LOCAL"],
            ].map(([k, v]) => (
              <div key={k} className="bg-bg/90 px-3 py-2">
                <dt>{k}</dt>
                <dd className="mt-0.5 text-fg">{v}</dd>
              </div>
            ))}
          </dl>

          <div className="mt-8 flex items-center gap-4">
            <Link href="/ops" className={cn(buttonVariants({ size: "lg" }), "bg-bg/80")}>
              ENTER SYSTEM
            </Link>
            <span className="micro hidden sm:inline">/OPS · RUN CONSOLE</span>
          </div>

          <div className="mt-10 flex items-center gap-3">
            <span className="micro">◂</span>
            <span className="h-px flex-1 bg-line-strong" aria-hidden />
            <span className="micro">INTERSECTION/01</span>
          </div>
        </div>

        <div className="relative hidden h-full max-h-[min(78vh,720px)] items-center justify-center lg:flex">
          <IntersectionWireframe className="h-full max-h-[680px] w-full max-w-[680px]" />
        </div>
      </section>

      {/* bottom bar */}
      <footer className="relative z-10 flex h-11 shrink-0 items-center justify-between border-t border-line px-6 lg:px-10">
        <div className="tele flex items-center gap-5">
          <span>SYSTEM.ACTIVE</span>
          <Barcode seed="ambient-mirror" />
          <span>{APP_VERSION.toUpperCase()}</span>
        </div>
        <div className="tele flex items-center gap-4">
          <span className="flex items-center gap-2">
            <StatusDot pulse />
            RENDERING
          </span>
          <span className="hidden text-dim sm:inline">●●●</span>
          <FrameCounter />
        </div>
      </footer>
    </main>
  );
}
