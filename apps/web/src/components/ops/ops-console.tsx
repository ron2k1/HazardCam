"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { Barcode, StatusDot } from "@/components/hud/barcode";
import { FrameCounter } from "@/components/hud/frame-counter";
import { API_BASE_URL, apiUrl, APP_VERSION } from "@/lib/config";
import type { JudgeGroundTruth, ModelsHealth, PublicScenario, ScenarioSummary } from "@/lib/contracts";
import { label, timecode, wallClock } from "@/lib/format";
import { scenarioToMediaTime, timelineItems, type RunView } from "@/lib/run-view";

import { BlindZonePlan } from "./blind-zone-plan";
import { CameraTile, type SeekRequest } from "./camera-tile";
import { EvidenceTimeline } from "./evidence-timeline";
import { GroundTruthTile } from "./ground-truth-tile";
import { HypothesisPanel } from "./hypothesis-panel";
import { RunControls } from "./run-controls";
import { StackHealthPanel, type ApiStatus, type HealthRow } from "./stack-health-panel";
import { TracePanel } from "./trace-panel";

export interface OpsConsoleProps {
  scenarios: readonly ScenarioSummary[];
  /** Public scenario view (visible cameras only). */
  scenario: PublicScenario | null;
  /** Reduced SSE state (lib/run-view.ts). */
  view: RunView;
  onScenarioChange: (scenarioId: string) => void;
  onRun: () => void;
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
  onRevealGroundTruth?: () => void;
  onHideGroundTruth?: () => void;

  /** Provenance tag shown in the control strip (e.g. mock data). */
  sourceLabel?: string | null;
  /** Shown on camera tiles with no media URL. */
  noSignalNote?: string;
  /** Optional hook for seek telemetry; seeking itself is handled here. */
  onSeek?: (cameraId: string, scenarioT: number) => void;
}

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
    return (cand?.label ?? zone?.label ?? null)?.toUpperCase() ?? null;
  }, [view.hypothesis, view.candidates, scenario]);

  // only request media the API reports present; a missing file stays NO SIGNAL, not a 404
  const media = (url: string | null, available: boolean) => (url && available ? apiUrl(url) : null);
  const gtCam = props.judge?.ground_truth_camera ?? null;
  const running = view.phase === "running" || view.phase === "queued";

  return (
    <div className="flex h-dvh min-h-[760px] min-w-[1240px] flex-col bg-bg">
      {/* top bar */}
      <header className="flex h-9 shrink-0 items-center justify-between border-b border-line px-3">
        <div className="flex items-center gap-3">
          <Link href="/" className="text-[13px] font-extrabold tracking-[0.06em] text-fg italic hover:text-fg/80">
            AMBIENT/MIRROR
          </Link>
          <span className="h-3.5 w-px bg-line-strong" aria-hidden />
          <span className="tele text-fg/85">OPS</span>
          <span className="tele">{scenario ? `${scenario.id.toUpperCase()} · ${(scenario.title ?? "").toUpperCase()}` : "NO SCENARIO"}</span>
        </div>
        <div className="tele flex items-center gap-4">
          <span>{scenario?.cameras.length ?? 0} INPUT CAM · 1 WITHHELD</span>
          <span>RUN Δ {timecode(view.durationMs != null ? view.durationMs / 1000 : null)}</span>
          <span>{wallClock(view.lastTs)} UTC</span>
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
        disabled={props.apiStatus === "offline"}
        sourceLabel={props.sourceLabel}
      />

      {view.failure ? (
        <div role="alert" className="flex h-7 shrink-0 items-center gap-3 border-b border-danger/50 bg-danger/10 px-3 text-[10px] tracking-[0.14em] text-danger">
          RUN FAILED · STAGE {label(view.failure.stage)} · {view.failure.error}
        </div>
      ) : null}

      <main className="grid min-h-0 flex-1 grid-cols-[minmax(0,2fr)_minmax(300px,1fr)_minmax(296px,0.92fr)] gap-2 p-2">
        {/* col 1: cameras + timeline */}
        <div className="grid min-h-0 grid-rows-[minmax(0,1fr)_auto] gap-2">
          <section aria-label="Cameras" className="grid min-h-0 grid-cols-2 grid-rows-2 gap-2" data-testid="camera-grid">
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
              />
            ))}
            <GroundTruthTile
              judge={props.judge}
              src={props.groundTruthRevealed && gtCam ? media(gtCam.video_url, gtCam.video_available) : null}
              revealed={props.groundTruthRevealed}
              canReveal={view.phase === "complete" && !!props.onRevealGroundTruth}
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
        <div className="grid min-h-0 grid-rows-[minmax(0,1.05fr)_minmax(0,1fr)] gap-2">
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
        <div className="grid min-h-0 grid-rows-[minmax(0,1fr)_auto] gap-2">
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
          <span>{APP_VERSION.toUpperCase()}</span>
          <span>FRAME LOCAL METRIC · X_EAST · Y_NORTH</span>
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
