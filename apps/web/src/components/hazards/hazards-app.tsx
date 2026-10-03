"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { API_BASE_URL } from "@/lib/config";
import {
  hazardsApi,
  mediaUrl,
  plainError,
  sortHazards,
  sourceVideoPath,
  type ClipSummary,
  type HazardView,
  type WallTiles,
  type WorkerHazard,
} from "@/lib/hazards";
import { cn } from "@/lib/utils";
import { MOCK_CLIPS } from "@/mocks/hazards";

import { CctvFeed } from "./cctv-feed";
import { CheckStatus, initialCheck, type CheckState } from "./check-status";
import { camLabel, cameraOrder, CameraSelect, CameraStrip, type CameraState } from "./clip-rail";
import { galleryPictures, isBlindspot, sourceSize, viewZones, type Pic } from "./derive";
import { EvidencePlayer, type SeekRequest } from "./evidence-player";
import { HazardsHeader } from "./hazards-header";
import { Lightbox, PictureGallery } from "./picture-grid";
import { RuntimeLine, useRuntimeStatus } from "./runtime-strip";
import { liveSource, mockSource, type HazardsSource } from "./sources";
import { HazardList } from "./worker-report";

export type HazardsMock = "default" | "empty";

export interface HazardsAppProps {
  /** ?mock: development data from src/mocks/hazards (never used for the recording). */
  mock: HazardsMock | null;
  /** ?clip= as the server read it. */
  initialClipId: string | null;
  /** ?job= : attach to this job (no automatic check). */
  initialJobId: string | null;
}

const POLL_MS = 3_000;
/** The automatic check starts this long after the feed starts playing. */
const AUTO_CHECK_MS = 2_500;
/** ...or this long after the camera was picked, if the feed never plays. */
const AUTO_CHECK_FALLBACK_MS = 7_000;

/**
 * Layout: before a result the feed is large with the check's progress under it. After it, a side
 * column holds the feed tile, the finished check (reasoning link, Check again) and the footnotes;
 * the report (headline, agent summary, hazard cards) is one column so the first hazard sits above
 * the fold; the AI-marked video and its pictures sit beside it. The side column ends in a 1fr row
 * so the report's height never spreads the tile, the check and the footnotes apart.
 */
const LAYOUT_CSS = `
.hzw-grid{display:grid;gap:16px;grid-template-columns:minmax(0,1fr);grid-template-areas:"feed" "status" "main" "notes" "evidence";align-items:start}
.hzw-feed{grid-area:feed}.hzw-status{grid-area:status}.hzw-main{grid-area:main}.hzw-notes{grid-area:notes}.hzw-evidence{grid-area:evidence}
.hzw-grid:not([data-revealed]) .hzw-feed,.hzw-grid:not([data-revealed]) .hzw-status{width:100%;max-width:calc((100dvh - 15rem) * 16 / 9);min-width:min(100%,640px);justify-self:center}
.hzw-reveal{animation:hzw-in .45s ease-out both}
@keyframes hzw-in{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@media (min-width:1024px){.hzw-grid[data-revealed]{grid-template-columns:260px minmax(0,1fr);grid-template-rows:auto auto 1fr auto;grid-template-areas:"feed main" "status main" "notes main" "evidence evidence"}}
@media (min-width:1280px){.hzw-grid[data-revealed]{grid-template-columns:248px minmax(0,1.08fr) minmax(0,1fr);grid-template-rows:auto auto 1fr;grid-template-areas:"feed main evidence" "status main evidence" "notes main evidence"}}
@media (min-width:1024px){.hzw-grid[data-revealed] .hzw-summary{-webkit-line-clamp:3}}
`;

function processHref(clipId: string, jobId: string | null): string {
  const q = new URLSearchParams({ clip: clipId });
  if (jobId) q.set("job", jobId);
  return `/hazards/process?${q.toString()}`;
}

function resultState(view: HazardView, kindWord: string): CameraState {
  const hz = view.worker?.hazards ?? [];
  if (!hz.length) return { text: `No ${kindWord.toLowerCase()}s seen`, tone: "muted" };
  const needs = hz.filter((h) => h.needs_check).length;
  const base = `${hz.length} ${kindWord.toLowerCase()}${hz.length === 1 ? "" : "s"}`;
  return { text: needs ? `${base} · ${needs} need${needs === 1 ? "s" : ""} a check` : base, tone: "warning" };
}

/**
 * /hazards: the safety check screen. A camera's raw feed plays like CCTV; a check starts on its
 * own, its plain progress shows under the feed, and only when the result is in do the structured
 * report, the AI-marked video and the pictures the AI looked at appear. Nothing from a stored
 * report is shown before a check finishes in this browser session.
 */
export function HazardsApp({ mock, initialClipId, initialJobId }: HazardsAppProps) {
  const [source] = useState<HazardsSource>(() => (mock ? mockSource(mock) : liveSource));
  const runtime = useRuntimeStatus(!mock);

  const [clips, setClips] = useState<ClipSummary[] | null>(() => (mock ? (mock === "empty" ? [] : MOCK_CLIPS) : null));
  const [clipsError, setClipsError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(initialClipId);
  const [check, setCheck] = useState<CheckState | null>(null);
  const [result, setResult] = useState<HazardView | null>(null);
  const [states, setStates] = useState<Record<string, CameraState | undefined>>({});
  const [seek, setSeek] = useState<SeekRequest | null>(null);
  const [activeHazard, setActiveHazard] = useState<string | null>(null);
  const [focusZones, setFocusZones] = useState<number[]>([]);
  const [lightbox, setLightbox] = useState<Pic | null>(null);

  const token = useRef(0);
  const closeStream = useRef<(() => void) | null>(null);
  const autoTimer = useRef<number | null>(null);
  const pendingJob = useRef<string | null>(initialJobId);
  const evidenceRef = useRef<HTMLDivElement>(null);
  const checkRef = useRef<CheckState | null>(null);
  const feedPlayed = useRef<string | null>(null);
  useEffect(() => {
    checkRef.current = check;
  }, [check]);

  const [wall, setWall] = useState<WallTiles | null>(null);
  useEffect(() => {
    if (mock) return;
    const ctl = new AbortController();
    hazardsApi.wall(ctl.signal).then(setWall, () => undefined);
    return () => ctl.abort();
  }, [mock]);
  const { ordered, cams } = useMemo(() => cameraOrder(clips ?? [], wall), [clips, wall]);

  const clipId = useMemo(() => {
    if (!ordered.length) return null;
    if (selectedId && ordered.some((c) => c.clip_id === selectedId)) return selectedId;
    return (ordered.find((c) => !isBlindspot(c.kind)) ?? ordered[0]).clip_id;
  }, [ordered, selectedId]);
  const clip = ordered.find((c) => c.clip_id === clipId) ?? null;
  const cam = clip ? cams[clip.clip_id] : undefined;
  const kindWord = isBlindspot(clip?.kind ?? result?.clip.kind) ? "Blind spot" : "Hazard";

  /* ---------------------------------------------------------------- clip list */
  const loadClips = useCallback(
    (signal?: AbortSignal) =>
      source.clips(signal).then(
        (list) => {
          setClips(list);
          setClipsError(null);
        },
        (err) => {
          if (!signal?.aborted) setClipsError(plainError(err));
        },
      ),
    [source],
  );
  useEffect(() => {
    if (source.kind === "mock") return;
    const ctl = new AbortController();
    void loadClips(ctl.signal);
    return () => ctl.abort();
  }, [source, loadClips]);
  const offline = source.kind === "live" && clipsError !== null;
  useEffect(() => {
    if (!offline) return;
    const id = window.setInterval(() => void loadClips(), POLL_MS);
    return () => window.clearInterval(id);
  }, [offline, loadClips]);

  /* ---------------------------------------------------------------- the check */
  const setState = useCallback((id: string, st: CameraState | undefined) => setStates((p) => ({ ...p, [id]: st })), []);

  const attach = useCallback(
    (id: string, jobId: string, myToken: number) => {
      const mine = () => token.current === myToken;
      closeStream.current?.();
      setCheck((c) => (c && c.clipId === id ? { ...c, phase: "running", jobId } : c));
      setState(id, { text: "Checking…", tone: "fg", busy: true });
      closeStream.current = source.subscribe(jobId, {
        onProgress: (p) => {
          if (!mine()) return;
          setCheck((c) => {
            if (!c || c.jobId !== jobId) return c;
            const stepStarted = p.step in c.stepStarted ? c.stepStarted : { ...c.stepStarted, [p.step]: p.received_at ?? Date.now() };
            return { ...c, phase: "running", progress: p.step >= (c.progress?.step ?? 0) ? p : c.progress, stepStarted };
          });
        },
        onAgent: (line) => {
          if (!mine()) return;
          setCheck((c) => {
            if (!c || c.jobId !== jobId) return c;
            if (c.agent.some((a) => a.text === line.text && a.t_s === line.t_s)) return c;
            return { ...c, agent: [...c.agent, line] };
          });
        },
        onDone: () => {
          if (!mine()) return;
          closeStream.current = null;
          source.view(id).then(
            (v) => {
              if (!mine()) return;
              setResult(v);
              setCheck((c) => (c && c.jobId === jobId ? { ...c, phase: "done" } : c));
              setState(id, resultState(v, isBlindspot(v.clip.kind) ? "Blind spot" : "Hazard"));
            },
            (err) => {
              if (!mine()) return;
              setCheck((c) => (c && c.jobId === jobId ? { ...c, phase: "failed", message: plainError(err) } : c));
              setState(id, { text: "Didn't finish", tone: "danger" });
            },
          );
        },
        onFailed: (message) => {
          if (!mine()) return;
          closeStream.current = null;
          setCheck((c) => (c && c.jobId === jobId ? { ...c, phase: "failed", message } : c));
          setState(id, { text: "Didn't finish", tone: "danger" });
        },
        onLost: () => {
          if (!mine()) return;
          closeStream.current = null;
          setCheck((c) => (c && c.jobId === jobId ? { ...c, phase: "lost" } : c));
          setState(id, undefined);
        },
      });
    },
    [source, setState],
  );

  const startCheck = useCallback(
    (id: string) => {
      const myToken = token.current;
      if (autoTimer.current !== null) window.clearTimeout(autoTimer.current);
      autoTimer.current = null;
      closeStream.current?.();
      closeStream.current = null;
      setResult(null);
      setActiveHazard(null);
      setFocusZones([]);
      setCheck({ ...initialCheck(id, "starting") });
      setState(id, { text: "Checking…", tone: "fg", busy: true });
      source.review(id).then(
        (jobId) => {
          if (token.current !== myToken) return;
          setCheck((c) => (c && c.clipId === id ? { ...c, jobId } : c));
          attach(id, jobId, myToken);
        },
        (err) => {
          if (token.current !== myToken) return;
          setCheck((c) => (c && c.clipId === id ? { ...c, phase: "failed", message: plainError(err) } : c));
          setState(id, { text: "Didn't finish", tone: "danger" });
        },
      );
    },
    [source, attach, setState],
  );

  // a new camera: reset to its live feed; attach to ?job= once, otherwise wait for the feed
  useEffect(() => {
    if (!clipId) return;
    token.current += 1;
    const myToken = token.current;
    closeStream.current?.();
    closeStream.current = null;
    const job = pendingJob.current;
    pendingJob.current = null;
    // reset on a timer tick, not in the effect body (the feed for the new camera mounts first)
    const reset = window.setTimeout(() => {
      if (token.current !== myToken) return;
      setResult(null);
      setActiveHazard(null);
      setFocusZones([]);
      setLightbox(null);
      if (job) {
        setCheck({ ...initialCheck(clipId, "running"), jobId: job });
        attach(clipId, job, myToken);
      } else {
        const waiting = initialCheck(clipId, "waiting");
        checkRef.current = waiting;
        setCheck(waiting);
        autoTimer.current = window.setTimeout(
          () => {
            if (token.current === myToken) startCheck(clipId);
          },
          feedPlayed.current === clipId ? AUTO_CHECK_MS : AUTO_CHECK_FALLBACK_MS,
        );
      }
    }, 0);
    return () => {
      window.clearTimeout(reset);
      if (autoTimer.current !== null) window.clearTimeout(autoTimer.current);
      autoTimer.current = null;
    };
  }, [clipId, attach, startCheck]);

  useEffect(
    () => () => {
      closeStream.current?.();
      if (autoTimer.current !== null) window.clearTimeout(autoTimer.current);
    },
    [],
  );

  const onFeedPlaying = useCallback(() => {
    if (!clipId) return;
    feedPlayed.current = clipId;
    const c = checkRef.current;
    if (!c || c.clipId !== clipId || c.phase !== "waiting") return;
    const myToken = token.current;
    if (autoTimer.current !== null) window.clearTimeout(autoTimer.current);
    autoTimer.current = window.setTimeout(() => {
      if (token.current === myToken) startCheck(clipId);
    }, AUTO_CHECK_MS);
  }, [clipId, startCheck]);

  const selectClip = useCallback((id: string) => {
    setSelectedId(id);
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("clip", id);
      url.searchParams.delete("job");
      window.history.replaceState(null, "", url);
    } catch {
      // the URL is a convenience only
    }
  }, []);

  /* ---------------------------------------------------------------- result */
  const revealed = !!result && check?.phase === "done" && result.clip.clip_id === clipId;
  const worker = revealed ? result.worker : null;
  const hazards = useMemo(() => sortHazards(worker?.hazards ?? []), [worker]);
  const zones = useMemo(() => (revealed ? viewZones(result) : []), [revealed, result]);
  const gallery = useMemo(() => (revealed ? galleryPictures(result) : []), [revealed, result]);
  const srcSize = revealed ? sourceSize(result) : null;
  const tileZones = useMemo(() => zones.filter((z) => z.has_hazard), [zones]);

  const seekTo = useCallback((t: number) => {
    setSeek((s) => ({ t, nonce: (s?.nonce ?? 0) + 1 }));
  }, []);
  const revealEvidence = () => {
    const el = evidenceRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    if (r.top < 0 || r.top > window.innerHeight * 0.6) {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      el.scrollIntoView({ block: "start", behavior: reduce ? "auto" : "smooth" });
    }
  };
  const onShow = (h: WorkerHazard, zoneNumbers: number[]) => {
    seekTo(h.start_s);
    setActiveHazard(h.id);
    setFocusZones(zoneNumbers);
    revealEvidence();
  };
  const onCardPicture = (p: Pic, h: WorkerHazard) => {
    seekTo(p.time_s);
    setActiveHazard(h.id);
    setLightbox(p);
  };
  const onGalleryPicture = (p: Pic) => {
    seekTo(p.time_s);
    setActiveHazard(null);
    revealEvidence();
  };

  const jobId = check?.clipId === clipId ? check.jobId : null;
  const reasoning = clipId ? processHref(clipId, jobId) : null;
  const feedUrl = clip
    ? mediaUrl(source.kind === "mock" ? (clip.clip_id === "hz_00" ? "/mock-hazards/source.mp4" : null) : sourceVideoPath(clip.clip_id))
    : null;
  const feedState = !check
    ? "Watching"
    : check.phase === "running" || check.phase === "starting"
      ? "Watching · checking"
      : revealed && hazards.length
        ? `${hazards.length} ${kindWord.toLowerCase()}${hazards.length === 1 ? "" : "s"} found`
        : "Watching";

  return (
    <div className="flex min-h-dvh flex-col bg-bg" data-testid="hazards-app" data-revealed={revealed || undefined}>
      <style>{LAYOUT_CSS}</style>
      <HazardsHeader
        current="/hazards"
        title="Safety hazards"
        runtime={runtime}
        badge={
          mock ? (
            <span className="border border-line-strong px-2 py-0.5 text-[12px] tracking-[0.12em] text-fg/75 uppercase" data-testid="hazards-source">
              Development data
            </span>
          ) : null
        }
      />

      {clips && clips.length > 0 ? (
        <div className="hidden lg:block">
          <CameraStrip clips={ordered} selectedId={clipId} onSelect={selectClip} states={states} cams={cams} />
        </div>
      ) : null}

      {offline && clips ? (
        <div role="alert" className="shrink-0 border-b border-danger/50 bg-danger/10 px-4 py-2.5 text-[15px] text-danger lg:px-6">
          Can&apos;t reach the camera system. Trying again on its own…
        </div>
      ) : null}

      <main className="min-w-0 flex-1 px-4 py-4 lg:px-6">
        {clips === null ? (
          offline ? (
            <StateBox tone="danger" title="Can't reach the camera system" testId="hazards-offline">
              Trying again on its own…
              <span className="micro mt-3 block normal-case tracking-[0.06em]">API {API_BASE_URL}</span>
            </StateBox>
          ) : (
            <StateBox title="Connecting to the cameras…" testId="hazards-loading" />
          )
        ) : clips.length === 0 ? (
          <StateBox title="No camera clips are ready yet" testId="hazards-empty">
            When camera clips are added, they will show up here.
          </StateBox>
        ) : clip ? (
          <>
            <div className="mb-3 lg:hidden">
              <CameraSelect clips={ordered} selectedId={clipId} onSelect={selectClip} states={states} cams={cams} />
            </div>
            <div className="hzw-grid" data-revealed={revealed || undefined} data-testid="hazard-screen" data-clip-id={clip.clip_id}>
              <div className="hzw-feed">
                <CctvFeed
                  key={clip.clip_id}
                  src={feedUrl}
                  cam={camLabel(cam)}
                  title={clip.title}
                  state={feedState}
                  stateTone={revealed && hazards.length ? "warning" : "fg"}
                  zones={revealed ? tileZones : undefined}
                  aspect={srcSize ? srcSize.w / srcSize.h : null}
                  compact={revealed}
                  onFirstPlay={onFeedPlaying}
                  className={cn("w-full", "aspect-video")}
                />
              </div>

              <div className="hzw-status flex min-w-0 flex-col gap-2">
                {check ? (
                  <CheckStatus
                    check={check}
                    headline={revealed ? worker?.headline : null}
                    reasoningHref={reasoning}
                    onCheckAgain={() => clipId && startCheck(clipId)}
                    disabled={offline}
                  />
                ) : null}
                <RuntimeLine status={runtime} lead="checked" wrap className="md:hidden" />
              </div>

              {revealed && worker ? (
                <>
                  <div className="hzw-main hzw-reveal flex min-w-0 flex-col gap-3">
                    <section aria-labelledby="hz-headline" className="flex min-w-0 flex-col gap-3" data-testid="result-head">
                      <div>
                        <p className="text-[12px] tracking-[0.14em] text-fg/55 uppercase">
                          {camLabel(cam)} · {clip.title}
                        </p>
                        <h1
                          id="hz-headline"
                          className={cn("mt-1 text-[24px] leading-[1.15] font-extrabold tracking-[0.01em] sm:text-[28px]", hazards.length ? "text-warning" : "text-fg")}
                          data-testid="hazard-headline"
                        >
                          {worker.headline}
                        </h1>
                      </div>
                    </section>

                    <div className="flex min-w-0 flex-col gap-3" data-testid="alert-panel">
                      {hazards.length ? (
                        <HazardList
                          view={result}
                          hazards={hazards}
                          activeHazardId={activeHazard}
                          kindWord={kindWord}
                          reasoningHref={reasoning}
                          onShow={onShow}
                          onPicture={onCardPicture}
                        />
                      ) : (
                        <p className="border border-line bg-panel/60 px-4 py-4 text-[16px] leading-[24px] text-fg" data-testid="no-hazards">
                          Nothing needs attention on this camera right now. This doesn&apos;t mean the area is safe: the AI only looked
                          at still pictures from the clip.
                        </p>
                      )}
                    </div>
                  </div>

                  <section
                    ref={evidenceRef}
                    aria-labelledby="hz-cv"
                    className="hzw-evidence hzw-reveal flex min-w-0 scroll-mt-3 flex-col gap-3"
                    data-testid="cv-section"
                  >
                    <h2 id="hz-cv" className="text-[14px] font-bold tracking-[0.14em] text-fg uppercase">
                      What the computer vision saw
                    </h2>
                    <EvidencePlayer
                      processedUrl={mediaUrl(result.vision?.processed_video_url)}
                      sourceUrl={mediaUrl(result.vision?.source_video_url ?? sourceVideoPath(clip.clip_id))}
                      duration={result.vision?.duration_s ?? clip.duration_s}
                      hazards={hazards}
                      images={result.vision?.shown_images ?? []}
                      zones={zones}
                      source={srcSize}
                      seek={seek}
                      activeHazardId={activeHazard}
                      focusZones={focusZones}
                      onSeek={(t, hid) => {
                        seekTo(t);
                        setActiveHazard(hid);
                      }}
                      kindWord={kindWord}
                    />
                    {gallery.length ? (
                      <section aria-labelledby="hz-pictures" className="mt-2 flex flex-col gap-2" data-testid="pictures-section">
                        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                          <h2 id="hz-pictures" className="text-[14px] font-bold tracking-[0.14em] text-fg uppercase">
                            Pictures the AI looked at ({gallery.length})
                          </h2>
                          <p className="text-[12px] text-fg/60">Pick one to see that moment.</p>
                        </div>
                        <PictureGallery pics={gallery} onPicture={onGalleryPicture} />
                      </section>
                    ) : null}
                  </section>
                </>
              ) : null}
            </div>
          </>
        ) : null}
      </main>

      <footer className="flex min-h-8 shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-line px-4 py-1.5 lg:px-6">
        <span className="text-[12px] text-fg/60">Runs on this computer. Video never leaves it.</span>
        {reasoning ? (
          <a href={reasoning} target="_blank" rel="noopener" className="text-[12px] text-fg/70 underline decoration-line-strong underline-offset-2 hover:text-fg">
            Reasoning and process ↗
          </a>
        ) : null}
      </footer>

      <Lightbox pic={lightbox} onClose={() => setLightbox(null)} />
    </div>
  );
}

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
