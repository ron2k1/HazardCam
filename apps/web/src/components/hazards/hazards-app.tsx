"use client";

import { useReducedMotion } from "motion/react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DetectionPopoutStack, type DetectionPopoutItem } from "@/components/alerts/detection-popout";
import { StatusDot } from "@/components/hud/barcode";
import { Panel } from "@/components/hud/panel";
import { ViewToggle } from "@/components/ops/view-toggle";
import { useMounted } from "@/hooks/use-animate";
import { useViewMode, type ViewMode } from "@/hooks/use-view-mode";
import { ApiError } from "@/lib/api";
import { API_BASE_URL } from "@/lib/config";
import {
  clock,
  mediaUrl,
  plainError,
  sortHazards,
  sourceVideoPath,
  type ClipSummary,
  type HazardImage,
  type HazardInstructions,
  type HazardView,
  type WorkerHazard,
} from "@/lib/hazards";
import { cn } from "@/lib/utils";
import { MOCK_CLIPS, MOCK_INSTRUCTIONS, MOCK_VIEWS } from "@/mocks/hazards";

import { ClipRail, ClipSelect } from "./clip-rail";
import { EvidencePlayer, type SeekRequest } from "./evidence-player";
import { InstructionsPanel } from "./instructions-panel";
import { PictureGrid } from "./picture-grid";
import { RunControl, type JobState } from "./run-control";
import { liveSource, mockSource, type HazardsSource } from "./sources";
import { TechnicalDetails, TechnicalFindings } from "./technical-report";
import { WorkerReport } from "./worker-report";

export type HazardsMock = "default" | "empty";

export interface HazardsAppProps {
  /** ?mock: replay src/mocks/hazards without the API. */
  mock: HazardsMock | null;
  /** ?view= as the server read it. */
  initialView: ViewMode | null;
  /** ?clip= as the server read it. */
  initialClipId: string | null;
}

const POLL_MS = 3_000;

function localWhen(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/**
 * /hazards: one camera clip at a time, reviewed for safety hazards. The worker view reads like
 * a short message (no ids, scores or model names); "Technical details" shows the raw report.
 */
export function HazardsApp({ mock, initialView, initialClipId }: HazardsAppProps) {
  const [source] = useState<HazardsSource>(() => (mock ? mockSource(mock) : liveSource));
  const [mode, setMode] = useViewMode(initialView);
  const technical = mode === "technical";

  const [clips, setClips] = useState<ClipSummary[] | null>(() => (mock ? (mock === "empty" ? [] : MOCK_CLIPS) : null));
  const [clipsError, setClipsError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(initialClipId);
  const [views, setViews] = useState<Record<string, HazardView>>(() => (mock === "default" ? { ...MOCK_VIEWS } : {}));
  const [viewErrors, setViewErrors] = useState<Record<string, string>>({});
  const [viewNonce, setViewNonce] = useState(0);
  const [job, setJob] = useState<JobState | null>(null);
  const [refresh, setRefresh] = useState(false);
  const [instructions, setInstructions] = useState<HazardInstructions | null>(mock ? MOCK_INSTRUCTIONS : null);
  const closeJob = useRef<(() => void) | null>(null);
  const viewsRef = useRef(views);
  // Event day: a finished check pops its hazards out once (the same pop-out as the wall had).
  const popFor = useRef<string | null>(null);
  const [popouts, setPopouts] = useState<DetectionPopoutItem[]>([]);
  useEffect(() => {
    viewsRef.current = views;
  }, [views]);

  const effectiveId = useMemo(() => {
    if (!clips?.length) return null;
    if (selectedId && clips.some((c) => c.clip_id === selectedId)) return selectedId;
    return (clips.find((c) => c.status === "reviewed") ?? clips[0]).clip_id;
  }, [clips, selectedId]);
  const clip = clips?.find((c) => c.clip_id === effectiveId) ?? null;

  /** Fetch a clip's view and swap it in when it lands (no flash of the loading state). */
  const reloadView = useCallback(
    (clipId: string) => {
      source.view(clipId).then(
        (v) => setViews((p) => ({ ...p, [clipId]: v })),
        () => undefined,
      );
    },
    [source],
  );

  const applyClips = useCallback(
    (list: ClipSummary[]) => {
      setClips(list);
      setClipsError(null);
      setJob((j) => (j?.phase === "watching" && list.find((c) => c.clip_id === j.clipId)?.status !== "reviewing" ? null : j));
      // a cached view whose status or review time moved on is stale
      for (const c of list) {
        const v = viewsRef.current[c.clip_id];
        if (v && (v.status !== c.status || v.reviewed_at !== c.reviewed_at)) reloadView(c.clip_id);
      }
    },
    [reloadView],
  );
  const clipsFailed = useCallback((err: unknown) => setClipsError(plainError(err)), []);
  const refreshClips = useCallback(() => {
    source.clips().then(applyClips, clipsFailed);
  }, [source, applyClips, clipsFailed]);

  // first load (mock data is already in state)
  useEffect(() => {
    if (source.kind === "mock") return;
    const ctl = new AbortController();
    source.clips(ctl.signal).then(applyClips, (err) => {
      if (!ctl.signal.aborted) clipsFailed(err);
    });
    source.instructions(ctl.signal).then(setInstructions, () => undefined);
    return () => ctl.abort();
  }, [source, applyClips, clipsFailed]);

  // poll while offline, or while a clip is being checked by a job this screen does not stream
  const ownStream = job?.phase === "running" || job?.phase === "starting";
  const needPoll =
    (source.kind === "live" && clipsError !== null) ||
    job?.phase === "watching" ||
    (!ownStream && !!clips?.some((c) => c.status === "reviewing"));
  useEffect(() => {
    if (!needPoll) return;
    const id = window.setInterval(refreshClips, POLL_MS);
    return () => window.clearInterval(id);
  }, [needPoll, refreshClips]);

  // the selected clip's view
  const haveView = effectiveId ? effectiveId in views : true;
  useEffect(() => {
    if (!effectiveId || haveView) return;
    const ctl = new AbortController();
    const id = effectiveId;
    source.view(id, ctl.signal).then(
      (v) => {
        setViews((p) => ({ ...p, [id]: v }));
        setViewErrors((p) => {
          const n = { ...p };
          delete n[id];
          return n;
        });
      },
      (err) => {
        if (!ctl.signal.aborted) setViewErrors((p) => ({ ...p, [id]: plainError(err) }));
      },
    );
    return () => ctl.abort();
  }, [effectiveId, haveView, source, viewNonce]);

  useEffect(() => () => closeJob.current?.(), []);

  const selectClip = useCallback((id: string) => {
    setSelectedId(id);
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("clip", id);
      window.history.replaceState(null, "", url);
    } catch {
      // the URL is a convenience only
    }
  }, []);

  const retryView = useCallback((id: string) => {
    setViewErrors((p) => {
      const n = { ...p };
      delete n[id];
      return n;
    });
    setViewNonce((n) => n + 1);
  }, []);

  const onCheck = useCallback(() => {
    if (!effectiveId) return;
    const clipId = effectiveId;
    closeJob.current?.();
    closeJob.current = null;
    setJob({ phase: "starting", clipId });
    source.review(clipId, refresh).then(
      (jobId) => {
        setJob({ phase: "running", clipId, jobId, progress: null });
        setClips((cs) => cs?.map((c) => (c.clip_id === clipId ? { ...c, status: "reviewing" } : c)) ?? cs);
        closeJob.current = source.subscribe(jobId, {
          onProgress: (p) => setJob((j) => (j?.phase === "running" && j.jobId === jobId ? { ...j, progress: p } : j)),
          onDone: () => {
            closeJob.current = null;
            setJob(null);
            popFor.current = clipId;
            reloadView(clipId);
            refreshClips();
          },
          onFailed: (message) => {
            closeJob.current = null;
            setJob({ phase: "failed", clipId, message });
            reloadView(clipId);
            refreshClips();
          },
          onLost: () => {
            closeJob.current = null;
            setJob({ phase: "watching", clipId });
            refreshClips();
          },
        });
      },
      (err) => {
        if (err instanceof ApiError && err.status === 409) {
          setJob({ phase: "watching", clipId });
          refreshClips();
          return;
        }
        setJob({ phase: "failed", clipId, message: plainError(err) });
      },
    );
  }, [effectiveId, refresh, source, refreshClips, reloadView]);

  const offline = source.kind === "live" && clipsError !== null;
  useEffect(() => {
    const id = popFor.current;
    const v = id ? views[id] : undefined;
    if (!id || !v || v.status !== "reviewed") return;
    popFor.current = null;
    const items = (v.worker?.hazards ?? []).map((h, i): DetectionPopoutItem => {
      const img = h.evidence[0]?.image_url;
      return {
        id: `${id}:${v.reviewed_at ?? ""}:${h.id}`,
        kicker: `HAZARD ${i + 1} OF ${v.worker?.hazards.length ?? 1} · ${h.priority.toUpperCase()}`,
        label: h.title,
        cameraLabel: v.clip.title,
        zoneName: h.where,
        detail: [h.what_we_saw, h.what_to_do[0]].filter(Boolean).join(" "),
        timestamp: h.when,
        tone: "hazard",
        imageUrl: img ? (img.startsWith("http") ? img : `${API_BASE_URL}${img}`) : undefined,
        imageAlt: h.title,
      };
    });
    if (items.length) setPopouts(items);
  }, [views]);

  const jobHere = job && job.clipId === effectiveId ? job : null;
  const busyElsewhere = !!job && job.clipId !== effectiveId && (job.phase === "starting" || job.phase === "running");
  const anyRunning = !!job && job.phase !== "failed";

  return (
    <div className="flex min-h-dvh flex-col bg-bg" data-testid="hazards-app" data-view={mode}>
      <header className="flex min-h-14 shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-line px-4 py-2 lg:px-6">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
          <Link href="/" className="shrink-0 text-[17px] font-extrabold tracking-[0.06em] text-fg italic hover:text-fg/80">
            CameraVision
          </Link>
          <span className="h-4 w-px bg-line-strong" aria-hidden />
          <span className="text-[14px] text-fg/75">Safety hazards</span>
          {mock ? (
            <span className="border border-line-strong px-2 py-0.5 text-[12px] tracking-[0.12em] text-fg/75 uppercase" data-testid="hazards-source">
              Demo data
            </span>
          ) : null}
        </div>
        <ViewToggle mode={mode} onChange={setMode} />
      </header>

      {offline && clips ? (
        <div role="alert" className="shrink-0 border-b border-danger/50 bg-danger/10 px-4 py-2.5 text-[15px] text-danger lg:px-6">
          Can&apos;t reach the camera system. Trying again on its own…
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {clips && clips.length > 0 ? (
          <aside className="hidden shrink-0 border-r border-line lg:block lg:w-[272px]">
            <div className="sticky top-0 flex max-h-dvh flex-col">
              <ClipRail clips={clips} selectedId={effectiveId} onSelect={selectClip} technical={technical} />
            </div>
          </aside>
        ) : null}

        <main className="min-w-0 flex-1 px-4 py-4 lg:px-6 lg:py-5">
          {clips === null ? (
            offline ? (
              <StateBox tone="danger" title="Can't reach the camera system" testId="hazards-offline">
                Trying again on its own…
                {technical ? <TechLine>API {API_BASE_URL} · {clipsError}</TechLine> : null}
              </StateBox>
            ) : (
              <StateBox title="Loading camera clips…" testId="hazards-loading" />
            )
          ) : clips.length === 0 ? (
            <StateBox title="No camera clips are ready yet" testId="hazards-empty">
              {technical ? (
                <>
                  Prepare the clips (neutral ids, labels kept judge-only), then reload:
                  <pre className="mt-3 overflow-x-auto border border-line bg-panel px-3 py-2 text-[12px] leading-5 text-fg">
                    {".venv/bin/python scripts/hazards/prepare_clips.py\n.venv/bin/python scripts/hazards/prepare_clips.py --import-example"}
                  </pre>
                </>
              ) : (
                "When camera clips are added, they will show up here."
              )}
            </StateBox>
          ) : clip ? (
            <>
              <div className="mb-4 lg:hidden">
                <ClipSelect clips={clips} selectedId={effectiveId} onSelect={selectClip} />
              </div>
              <ClipPanel
                key={clip.clip_id}
                clip={clip}
                index={clips.indexOf(clip) + 1}
                total={clips.length}
                view={views[clip.clip_id] ?? null}
                viewError={viewErrors[clip.clip_id] ?? null}
                onRetryView={() => retryView(clip.clip_id)}
                technical={technical}
                live={source.kind === "live"}
                instructions={instructions}
                job={jobHere}
                busyElsewhere={busyElsewhere}
                offline={offline}
                onCheck={onCheck}
                refresh={refresh}
                onRefreshChange={setRefresh}
              />
            </>
          ) : null}
        </main>
      </div>

      <footer className="flex min-h-8 shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-line px-4 py-1.5 lg:px-6">
        <span className="text-[12px] text-fg/60">Runs on this computer. Video never leaves it.</span>
        <span className="flex items-center gap-1.5 text-[12px] text-fg/60">
          <StatusDot tone={anyRunning ? "fg" : "dim"} pulse={anyRunning} />
          {anyRunning ? "Checking" : "Ready"}
        </span>
      </footer>
      <DetectionPopoutStack
        items={popouts}
        onCollapse={(pid) => setPopouts((prev) => prev.filter((p) => p.id !== pid))}
        autoCollapseMs={6000}
        maxVisible={1}
      />
    </div>
  );
}

/* --------------------------------------------------------------- the clip */

interface ClipPanelProps {
  clip: ClipSummary;
  index: number;
  total: number;
  view: HazardView | null;
  viewError: string | null;
  onRetryView: () => void;
  technical: boolean;
  live: boolean;
  instructions: HazardInstructions | null;
  job: JobState | null;
  busyElsewhere: boolean;
  offline: boolean;
  onCheck: () => void;
  refresh: boolean;
  onRefreshChange: (v: boolean) => void;
}

function ClipPanel(props: ClipPanelProps) {
  const { clip, view, technical } = props;
  const mounted = useMounted();
  const reduce = useReducedMotion();
  const [seek, setSeek] = useState<SeekRequest | null>(null);
  const [activeHazard, setActiveHazard] = useState<string | null>(null);
  const playerRef = useRef<HTMLElement>(null);

  const worker = view?.worker ?? null;
  const vision = view?.vision ?? null;
  const tech = view?.technical ?? null;
  const hazards = useMemo(() => sortHazards(worker?.hazards ?? []), [worker]);
  const status = view?.status ?? clip.status;
  const reviewedAt = view?.reviewed_at ?? clip.reviewed_at;
  const duration = vision?.duration_s ?? view?.clip.duration_s ?? clip.duration_s;
  const processedUrl = mediaUrl(vision?.processed_video_url);
  const sourceUrl = mediaUrl(vision?.source_video_url ?? (props.live ? sourceVideoPath(clip.clip_id) : null));
  const images = vision?.shown_images ?? [];
  const plainInstructions = vision?.instructions ?? props.instructions;

  const showAt = (t: number, hazardId: string | null) => {
    setSeek((s) => ({ t, nonce: (s?.nonce ?? 0) + 1 }));
    setActiveHazard(hazardId);
    const el = playerRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    if (r.top < 0 || r.top > window.innerHeight * 0.5) el.scrollIntoView({ block: "start", behavior: reduce ? "auto" : "smooth" });
  };
  const onShow = (h: WorkerHazard) => showAt(h.start_s, h.id);
  const onPicture = (im: HazardImage, h?: WorkerHazard) => showAt(im.time_s, h?.id ?? null);

  const meta = [
    technical ? clip.clip_id : `Clip ${props.index} of ${props.total}`,
    `${clock(duration)} long`,
    status === "reviewed" && reviewedAt && mounted ? `Checked ${localWhen(reviewedAt)}` : null,
  ].filter(Boolean);

  const player = (timeline: boolean) => (
    <EvidencePlayer
      processedUrl={processedUrl}
      sourceUrl={sourceUrl}
      duration={duration}
      hazards={hazards}
      images={images}
      seek={seek}
      activeHazardId={activeHazard}
      onSeek={showAt}
      timeline={timeline}
    />
  );

  const evidenceDetails = useMemo(() => {
    if (!tech || tech.evidence.length !== images.length) return undefined;
    return tech.evidence.map((e) => [e.evidence_id, e.kind, e.zone_id, `f${e.frame_index}`].filter(Boolean).join(" · "));
  }, [tech, images.length]);

  let body: React.ReactNode;
  if (!view && !props.viewError) {
    body = <StateBox title="Loading the report…" testId="view-loading" />;
  } else if (!view) {
    body = (
      <StateBox tone="danger" title={props.viewError ?? "Something went wrong."} testId="view-error">
        <button type="button" onClick={props.onRetryView} className="mt-3 h-10 border border-fg/80 px-4 text-[14px] text-fg hover:bg-fg hover:text-bg">
          Try again
        </button>
      </StateBox>
    );
  } else if (!technical && worker) {
    body = (
      <>
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] xl:items-start">
          <WorkerReport
            worker={worker}
            hazards={hazards}
            imagesSent={vision?.images_sent ?? images.length}
            activeHazardId={activeHazard}
            onShow={onShow}
            onPicture={onPicture}
          />
          <section
            ref={playerRef}
            aria-labelledby="hz-cv"
            className="flex min-w-0 scroll-mt-4 flex-col gap-3 xl:sticky xl:top-4"
            data-testid="cv-section"
          >
            <h2 id="hz-cv" className="text-[15px] font-bold tracking-[0.12em] text-fg uppercase">
              What the computer vision saw
            </h2>
            {vision ? (
              <p className="text-[13px] leading-5 text-fg/65">
                Scanned all {vision.frames_scanned} frames · marked {vision.areas_marked} areas to check · sent {vision.images_sent} pictures to the AI
              </p>
            ) : null}
            {player(true)}
            <p className="text-[13px] leading-5 text-fg/60">
              Boxes mark the areas the computer picked for a closer look. A box is not a hazard by itself.
            </p>
          </section>
        </div>

        {images.length ? (
          <section aria-labelledby="hz-pictures" className="mt-8 flex flex-col gap-3" data-testid="pictures-section">
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <h2 id="hz-pictures" className="text-[15px] font-bold tracking-[0.12em] text-fg uppercase">
                Pictures the AI looked at ({images.length})
              </h2>
              <p className="text-[13px] text-fg/60">In the order the AI saw them. Pick one to see that moment.</p>
            </div>
            <PictureGrid images={images} onPicture={(im) => onPicture(im)} />
          </section>
        ) : null}

        {plainInstructions ? <InstructionsPanel instructions={plainInstructions} className="mt-8" /> : null}
      </>
    );
  } else if (technical && tech) {
    body = (
      <div className="flex flex-col gap-3">
        <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] xl:items-start">
          <TechnicalFindings technical={tech} />
          <section ref={playerRef} aria-label="Processed video" className="min-w-0 scroll-mt-4 xl:sticky xl:top-4">
            <Panel
              index="04"
              title="Processed video · zone overlays"
              meta={
                vision ? (
                  <span className="hidden sm:inline">
                    {vision.frames_scanned} frames · {vision.areas_marked} zones · {vision.images_sent} images
                  </span>
                ) : null
              }
              bodyClassName="p-3"
            >
              {player(true)}
            </Panel>
          </section>
        </div>
        {images.length ? (
          <Panel index="05" title="Evidence sent to the model, in order" meta={<span className="hidden sm:inline">{images.length} images</span>} bodyClassName="p-3">
            <PictureGrid images={images} onPicture={(im) => onPicture(im)} details={evidenceDetails} />
          </Panel>
        ) : null}
        <TechnicalDetails technical={tech} />
      </div>
    );
  } else {
    // no report yet (or the technical block is missing): the clip itself, and what will be checked
    const words =
      status === "failed"
        ? { title: "The last check didn't finish", text: "Press Try again to check this clip." }
        : status === "reviewing"
          ? { title: "This clip is being checked", text: "The report will show up here when it's ready." }
          : { title: "Not checked yet", text: "Press Check this clip to look for safety hazards." };
    body = (
      <>
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] xl:items-start">
          <StateBox title={words.title} testId="not-reviewed">
            {words.text}
            {technical && view.technical == null ? <TechLine>No hazard_report.json for {clip.clip_id} yet.</TechLine> : null}
          </StateBox>
          <section ref={playerRef} aria-label="Clip video" className="min-w-0 scroll-mt-4">
            {player(false)}
          </section>
        </div>
        {plainInstructions ? <InstructionsPanel instructions={plainInstructions} future className="mt-8" /> : null}
      </>
    );
  }

  return (
    <article aria-labelledby="hz-clip-title" className="flex min-w-0 flex-col gap-5" data-testid="clip-panel" data-clip-id={clip.clip_id} data-status={status}>
      <header className="flex flex-col gap-4 border-b border-line pb-5">
        <div>
          <p className="text-[12px] tracking-[0.12em] text-fg/55 uppercase tabular-nums">{meta.join(" · ")}</p>
          <h1 id="hz-clip-title" className="mt-1 text-[24px] leading-[1.2] font-extrabold tracking-[0.02em] text-fg sm:text-[28px]">
            {clip.title}
          </h1>
        </div>
        <RunControl
          status={status}
          job={props.job}
          busyElsewhere={props.busyElsewhere}
          offline={props.offline}
          onCheck={props.onCheck}
          technical={technical}
          refresh={props.refresh}
          onRefreshChange={props.onRefreshChange}
        />
      </header>
      {body}
    </article>
  );
}

/* ------------------------------------------------------------------ states */

function StateBox({
  title,
  tone = "muted",
  testId,
  children,
}: {
  title: string;
  tone?: "muted" | "danger";
  testId?: string;
  children?: React.ReactNode;
}) {
  return (
    <div
      className={cn("dot-field border px-5 py-8 sm:px-8", tone === "danger" ? "border-danger/50" : "border-line")}
      data-testid={testId}
      role={tone === "danger" ? "alert" : undefined}
    >
      <p className={cn("text-[20px] leading-[1.3] font-bold", tone === "danger" ? "text-danger" : "text-fg")}>{title}</p>
      {children ? <div className="mt-2 max-w-[64ch] text-[15px] leading-[23px] text-fg/80">{children}</div> : null}
    </div>
  );
}

function TechLine({ children }: { children: React.ReactNode }) {
  return <span className="micro mt-3 block normal-case tracking-[0.06em]">{children}</span>;
}
