"use client";

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";

import { Barcode, StatusDot } from "@/components/hud/barcode";
import { FrameCounter } from "@/components/hud/frame-counter";
import type { StreamStatus } from "@/hooks/use-run-stream";
import { API_BASE_URL, apiUrl, APP_VERSION } from "@/lib/config";
import type { JudgeGroundTruth, ModelsHealth, PublicScenario, ScenarioSummary } from "@/lib/contracts";
import { fixed, label, signedCoord, timecode, wallClock } from "@/lib/format";
import { scenarioToMediaTime, timelineItems, type RunView } from "@/lib/run-view";
import { cn } from "@/lib/utils";

import { BlindZonePlan } from "./blind-zone-plan";
import { CameraTile, type SeekRequest } from "./camera-tile";
import { EvidenceTimeline } from "./evidence-timeline";
import { GroundTruthTile } from "./ground-truth-tile";
import { HypothesisPanel } from "./hypothesis-panel";
import { RunControls } from "./run-controls";
import { StackHealthPanel, type ApiStatus, type HealthRow } from "./stack-health-panel";
import { TracePanel } from "./trace-panel";

/** Banner under the control strip: API offline, a rejected run, a resuming stream. */
export interface OpsNotice {
  tone: "danger" | "muted";
  text: string;
}

export interface OpsConsoleProps {
  scenarios: readonly ScenarioSummary[];
  /** Public scenario view (visible cameras only). */
  scenario: PublicScenario | null;
  /** Reduced SSE state (lib/run-view.ts). */
  view: RunView;
  onScenarioChange: (scenarioId: string) => void;
  onRun: () => void;
  /**
   * A run request is in flight: RUN, both selects and REVEAL are locked until it answers, so
   * the run it starts and the ground truth shown belong to the same scenario.
   */
  runPending?: boolean;
  /** Live SSE link state; the mock has none. */
  linkStatus?: StreamStatus | null;
  notice?: OpsNotice | null;
  profiles: readonly string[];
  profile: string;
  onProfileChange?: (profile: string) => void;

  health: ModelsHealth | null;
  apiStatus: ApiStatus;
  /** API row detail, e.g. from GET /healthz: version or failing dependencies. */
  apiDetail?: string | null;
  healthExtra?: readonly HealthRow[];

  /** Judge GT metadata; fetched by the caller (only for the reveal action). */
  judge: JudgeGroundTruth | null;
  groundTruthRevealed: boolean;
  /** The reveal's judge request is in flight / failed. */
  groundTruthPending?: boolean;
  groundTruthError?: string | null;
  onRevealGroundTruth?: () => void;
  onHideGroundTruth?: () => void;

  /** Provenance tag shown in the control strip (e.g. mock data). */
  sourceLabel?: string | null;
  /** Shown on camera tiles with no media URL. */
  noSignalNote?: string;
  /** Optional hook for seek telemetry; seeking itself is handled here. */
  onSeek?: (cameraId: string, scenarioT: number) => void;
  /** Right end of the top bar, e.g. the "Technical details" switch (OpsScreen). */
  headerAction?: ReactNode;
}

/** Camera-grid cell: sized by its own aspect when stacked, by the grid from `sm` up. */
const TILE = "aspect-[16/10] sm:aspect-auto";

export function OpsConsole(props: OpsConsoleProps) {
  const { scenario, view } = props;
  const cameras = useMemo(() => scenario?.cameras ?? [], [scenario]);
  const [seek, setSeek] = useState<{ cameraId: string; req: SeekRequest } | null>(null);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);

  const items = useMemo(() => timelineItems(view, cameras), [view, cameras]);
  const duration = Math.max(
    scenario?.duration_seconds ?? 0,
    ...items.map((i) => i.tEnd),
    5,
  );
  const samples = useMemo(
    () => Object.fromEntries(Object.entries(view.cameras).map(([id, c]) => [id, c.samples])),
    [view.cameras],
  );

  const handleSeek = (cameraId: string, t: number) => {
    const cam = cameras.find((c) => c.id === cameraId);
    if (!cam) return;
    setSeek((prev) => ({ cameraId, req: { t: scenarioToMediaTime(cam, t), nonce: (prev?.req.nonce ?? 0) + 1 } }));
    props.onSeek?.(cameraId, t);
  };

  const selectEvidence = (id: string | null) => {
    setSelectedEvidenceId(id);
    if (!id) return;
    const it = items.find((i) => i.id === id);
    if (it) handleSeek(it.cameraId, it.tStart);
  };

  const selected = items.find((i) => i.id === selectedEvidenceId) ?? null;
  const activeEvidence = useMemo(
    () => new Set(selectedEvidenceId ? [selectedEvidenceId] : (view.hypothesis?.evidence_ids ?? [])),
    [selectedEvidenceId, view.hypothesis],
  );
  const regionLabel = useMemo(() => {
    const r = view.hypothesis?.region;
    if (!r) return null;
    const cand = view.candidates.find((c) => c.id === r);
    const zone = scenario?.zones.find((z) => z.id === r);
    const named = cand?.label ?? zone?.label;
    if (named) return named.toUpperCase();
    // an unnamed triangulated candidate: say where it is instead
    const c = cand?.center;
    if (!c || c.length < 2) return null;
    return `X ${signedCoord(c[0])} Y ${signedCoord(c[1])}${cand.radius_m != null ? ` · R ${fixed(cand.radius_m, 1)}M` : ""}`;
  }, [view.hypothesis, view.candidates, scenario]);

  // only request media the API reports present; a missing file stays NO SIGNAL, not a 404
  const media = (url: string | null, available: boolean) => (url && available ? apiUrl(url) : null);
  const gtCam = props.judge?.ground_truth_camera ?? null;
  const running = view.phase === "running" || view.phase === "queued";
  // Reveal only a finished run of the scenario on screen, never while the next one is posting.
  const canReveal =
    view.phase === "complete" && view.scenarioId === scenario?.id && !props.runPending && !!props.onRevealGroundTruth;

  return (
    // Below the `ops` breakpoint (1240px) the three columns stack and the page scrolls.
    <div className="flex min-h-dvh flex-col bg-bg ops:h-dvh ops:min-h-[760px]">
      {/* top bar */}
      <header className="flex h-9 shrink-0 items-center justify-between gap-3 border-b border-line px-3">
        <div className="flex min-w-0 items-center gap-3">
          <Link href="/" className="shrink-0 text-[13px] font-extrabold tracking-[0.06em] text-fg italic hover:text-fg/80">
            CameraVision
          </Link>
          <span className="h-3.5 w-px shrink-0 bg-line-strong" aria-hidden />
          <span className="tele shrink-0 text-fg/85">OPS</span>
          <span className="tele truncate">{scenario ? `${scenario.id.toUpperCase()} · ${(scenario.title ?? "").toUpperCase()}` : "NO SCENARIO"}</span>
        </div>
        <div className="flex shrink-0 items-center gap-4">
          <div className="tele hidden shrink-0 items-center gap-4 md:flex">
            <span>{scenario?.cameras.length ?? 0} INPUT CAM · 1 WITHHELD</span>
            <span>RUN Δ {timecode(view.durationMs != null ? view.durationMs / 1000 : null)}</span>
            <span>{wallClock(view.lastTs)} UTC</span>
          </div>
          {props.headerAction}
        </div>
      </header>

      <RunControls
        scenarios={props.scenarios}
        scenarioId={scenario?.id ?? null}
        onScenarioChange={props.onScenarioChange}
        profiles={props.profiles}
        profile={props.profile}
        onProfileChange={props.onProfileChange}
        onRun={props.onRun}
        phase={view.phase}
        runId={view.runId}
        lastSeq={view.lastSeq}
        disabled={props.apiStatus === "offline" || !!props.runPending}
        locked={!!props.runPending}
        link={props.linkStatus}
        sourceLabel={props.sourceLabel}
      />

      {props.notice ? (
        <div
          role={props.notice.tone === "danger" ? "alert" : "status"}
          data-testid="ops-notice"
          className={cn(
            "flex min-h-7 shrink-0 items-center gap-3 border-b px-3 py-1 text-[10px] tracking-[0.14em]",
            props.notice.tone === "danger" ? "border-danger/50 bg-danger/10 text-danger" : "border-line text-fg/80",
          )}
        >
          {props.notice.text}
        </div>
      ) : null}

      {view.failure ? (
        <div
          role="alert"
          data-testid="run-failure"
          className="flex min-h-7 shrink-0 items-center gap-3 border-b border-danger/50 bg-danger/10 px-3 py-1 text-[10px] tracking-[0.14em] text-danger"
        >
          RUN FAILED · STAGE {label(view.failure.stage)} · {view.failure.error}
        </div>
      ) : null}

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-2 p-2 ops:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)_minmax(296px,0.92fr)]">
        {/* col 1: cameras + timeline */}
        <div className="grid min-h-0 gap-2 ops:grid-rows-[minmax(0,1fr)_auto]">
          {/* phone width: one 16:10 tile per row; from `sm`: a 2x2 block */}
          <section
            aria-label="Cameras"
            className="grid min-h-0 grid-cols-1 gap-2 sm:aspect-[16/10] sm:grid-cols-2 sm:grid-rows-2 ops:aspect-auto"
            data-testid="camera-grid"
          >
            {cameras.slice(0, 3).map((cam, i) => (
              <CameraTile
                key={cam.id}
                camera={cam}
                slot={i + 1}
                src={media(cam.media_url, cam.media_available)}
                run={view.cameras[cam.id] ?? null}
                seek={seek?.cameraId === cam.id ? seek.req : null}
                highlighted={seek?.cameraId === cam.id || selected?.cameraId === cam.id}
                noSignalNote={props.noSignalNote}
                className={TILE}
              />
            ))}
            {/* keep the GT tile in slot 4 when there is no scenario (e.g. API offline) */}
            {Array.from({ length: 3 - Math.min(cameras.length, 3) }, (_, i) => (
              <div
                key={`empty-${i}`}
                className={cn(TILE, "dot-field flex min-h-0 min-w-0 items-center justify-center border border-line")}
              >
                <span className="micro">{scenario ? "NO INPUT CAMERA" : "NO SCENARIO"}</span>
              </div>
            ))}
            <GroundTruthTile
              className={TILE}
              judge={props.judge}
              src={props.groundTruthRevealed && gtCam ? media(gtCam.video_url, gtCam.video_available) : null}
              revealed={props.groundTruthRevealed}
              pending={props.groundTruthPending}
              error={props.groundTruthError}
              canReveal={canReveal}
              onReveal={props.onRevealGroundTruth}
              onHide={props.onHideGroundTruth}
            />
          </section>
          <EvidenceTimeline
            cameras={cameras}
            items={items}
            clusters={view.clusters}
            duration={duration}
            samples={samples}
            selectedId={selectedEvidenceId}
            onSeek={handleSeek}
            onSelect={setSelectedEvidenceId}
          />
        </div>

        {/* col 2: plan + hypothesis */}
        <div className="grid min-h-0 grid-rows-[380px_auto] gap-2 ops:grid-rows-[minmax(0,1.05fr)_minmax(0,1fr)]">
          <BlindZonePlan
            cameras={cameras}
            zones={scenario?.zones ?? []}
            candidates={view.candidates}
            rays={view.rays}
            groundTruth={props.groundTruthRevealed ? gtCam : null}
            activeEvidenceIds={activeEvidence}
            highlightCameraId={selected?.cameraId ?? seek?.cameraId ?? null}
          />
          <HypothesisPanel
            hypothesis={view.hypothesis}
            final={view.hypothesisFinal}
            phase={view.phase}
            regionLabel={regionLabel}
            selectedEvidenceId={selectedEvidenceId}
            onSelectEvidence={selectEvidence}
          />
        </div>

        {/* col 3: trace + health */}
        <div className="grid min-h-0 grid-rows-[420px_auto] gap-2 ops:grid-rows-[minmax(0,1fr)_auto]">
          <TracePanel
            rows={view.trace}
            harness={view.harness}
            phase={view.phase}
            lastSeq={view.lastSeq}
            startedAt={view.startedAt}
          />
          <StackHealthPanel
            health={props.health}
            api={{ status: props.apiStatus, baseUrl: API_BASE_URL, detail: props.apiDetail }}
            extra={props.healthExtra}
          />
        </div>
      </main>

      {/* bottom bar */}
      <footer className="flex h-7 shrink-0 items-center justify-between border-t border-line px-3">
        <div className="micro flex items-center gap-4">
          <span>SYSTEM.ACTIVE</span>
          <Barcode seed={view.runId ?? "idle"} />
          <span className="hidden sm:inline">{APP_VERSION.toUpperCase()}</span>
          <span className="hidden md:inline">FRAME LOCAL METRIC · X_EAST · Y_NORTH</span>
        </div>
        <div className="micro flex items-center gap-4">
          <span className="flex items-center gap-1.5">
            <StatusDot tone={running ? "fg" : "dim"} pulse={running} />
            {running ? "STREAMING" : "IDLE"}
          </span>
          <FrameCounter />
        </div>
      </footer>
    </div>
  );
}
