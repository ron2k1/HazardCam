"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiUrl } from "@/lib/config";

import {
  checkResult,
  fetchView,
  followJob,
  isPlainText,
  kindWord,
  beginCheck,
  WALL,
  type CheckResult,
  type Detection,
  type WallCamera,
  type WatchKind,
} from "@/lib/wall";

export type TilePhase = "watching" | "checking" | "done" | "failed";

/** One camera's check, as the wall knows it in this browser session. */
export interface TileRun {
  phase: TilePhase;
  jobId: string | null;
  step: number;
  total: number;
  /** The API's plain step words ("Looking for movement"). */
  stepWord: string | null;
  startedAt: number | null;
  finishedAt: number | null;
  /** Latest plain narration line from the safety agent, when the run has one. */
  agentLine: string | null;
  /** Set only after the check's "done" event and a fresh read of its stored result. */
  result: CheckResult | null;
  error: string | null;
}

export interface WallNotification {
  id: string;
  clipId: string;
  cam: number;
  kind: WatchKind;
  title: string;
  jobId: string;
  at: number;
  detections: Detection[];
}

export interface WallToast {
  id: string;
  kind: WatchKind;
  text: string;
  detection: Detection | null;
}

/** The site run: one lead agent over six concurrent checkers (POST /api/wall/run). */
export type CheckerState = "queued" | "running" | "done" | "failed";
export interface SiteAlert {
  cam: number;
  clip_id: string;
  severity: string;
  line: string;
  job_id: string | null;
}
/** One line of the lead agent's own trace, verbatim from the API (`lead` SSE event). */
export interface LeadLine {
  t: number;
  /** plan | tool | alerts | turn | say: "tool" and "alerts" lines are the lead's tool calls. */
  kind: string;
  text: string;
}
export interface SiteState {
  id: string;
  /** "replay" re-plays the latest recorded lead run (compressed); "live" is a new one. */
  mode: string;
  /** How many checkers the run had; a replay on this wall may follow fewer of them. */
  runCams: number | null;
  state: "running" | "done";
  checkers: Record<number, CheckerState>;
  alerts: SiteAlert[] | null;
  lead: LeadLine[];
}

const LEAD_LINES_KEPT = 200;

const IDLE: TileRun = {
  phase: "watching",
  jobId: null,
  step: 0,
  total: 6,
  stepWord: null,
  startedAt: null,
  finishedAt: null,
  agentLine: null,
  result: null,
  error: null,
};

/* UI messages for transport problems; the API's own failure text is used when it sends one. */
const MSG = {
  noStart: "Couldn't start the check. The camera system didn't answer.",
  stopped: "The check stopped before it finished.",
  lost: "Lost contact with the check.",
  noResult: "The check finished, but its result couldn't be loaded.",
};

const VIEW_RETRIES = 3;

/**
 * Starts each camera's safety check by itself, staggered (WALL.hazardStartS / blindspotStartS),
 * follows its job events, and only after "done" reads that clip's stored result. Detections
 * become notifications and toasts. Every check goes through POST /api/hazards/clips/{id}/review,
 * so in demo replay it replays that clip's own stored run and nothing is invented here.
 */
// Finished checks survive going to a hazard and back (same tab, for KEEP_MS), so returning to
// the wall shows the results at once instead of checking every camera again.
const SAVE_KEY = "cv-wall-checks-v3";
const KEEP_MS = 10 * 60_000;

// `origin`: when the wall first loaded in this tab. Restored runs keep their real start/finish
// times, so the timeline and log measure them from that load, not from this one.
type SavedWall = { at: number; origin?: number; runs: Record<string, TileRun>; notifications: WallNotification[] };

function readSaved(): SavedWall | null {
  try {
    const raw = window.sessionStorage.getItem(SAVE_KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw) as SavedWall;
    return Date.now() - saved.at < KEEP_MS && saved.runs ? saved : null;
  } catch {
    return null;
  }
}

function writeSaved(saved: SavedWall) {
  try {
    window.sessionStorage.setItem(SAVE_KEY, JSON.stringify(saved));
  } catch {
    // Storage blocked: the wall simply checks again next time.
  }
}

export function useWallOrchestrator(cameras: WallCamera[], loadedAt: number | null) {
  const [runs, setRuns] = useState<Record<string, TileRun>>({});
  const [notifications, setNotifications] = useState<WallNotification[]>([]);
  const [toasts, setToasts] = useState<WallToast[]>([]);

  const plannedAt = useRef(new Map<string, number>());
  const started = useRef(new Set<string>());
  const closers = useRef(new Map<string, () => void>());
  const aborts = useRef(new Map<string, AbortController>());
  const toastTimers = useRef(new Set<ReturnType<typeof setTimeout>>());
  const alive = useRef(true);
  const lateCount = useRef(0);
  // A check whose job vanished (e.g. the API restarted mid-check) is started again once, by itself.
  const autoRetried = useRef(new Set<string>());
  const rerun = useRef<((cam: WallCamera) => void) | null>(null);
  // Site run: "pending" until POST /api/wall/run answers; "site" follows the lead's checkers;
  // "direct" is the old per-camera staggered checks (fallback when the site run fails).
  const [site, setSite] = useState<SiteState | null>(null);
  const [direct, setDirect] = useState(false);
  const siteMode = useRef<"pending" | "site" | "direct">("pending");
  const siteAsked = useRef(false);
  const alertOrder = useRef<SiteAlert[] | null>(null);
  const finished = useRef(new Map<string, { cam: WallCamera; jobId: string; result: CheckResult }>());
  const announced = useRef(new Set<string>());
  const [restoredOrigin, setRestoredOrigin] = useState<number | null>(null);
  const origin = restoredOrigin ?? loadedAt;

  const patch = useCallback((clipId: string, p: Partial<TileRun>) => {
    if (!alive.current) return;
    setRuns((prev) => ({ ...prev, [clipId]: { ...(prev[clipId] ?? IDLE), ...p } }));
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const announce = useCallback(
    (cam: WallCamera, jobId: string, result: CheckResult) => {
      if (!alive.current || !result.detections.length) return;
      const at = Date.now();
      const words = kindWord(cam.kind);
      const n = result.detections.length;
      setNotifications((prev) => [
        { id: `${cam.clip_id}:${jobId}`, clipId: cam.clip_id, cam: cam.cam, kind: cam.kind, title: cam.title, jobId, at, detections: result.detections },
        ...prev.filter((x) => x.id !== `${cam.clip_id}:${jobId}`),
      ]);
      const toast: WallToast = {
        id: `${cam.clip_id}:${jobId}:${at}`,
        kind: cam.kind,
        text: n === 1 ? `New ${words.one} on CAM ${cam.cam}` : `${n} new ${words.many} on CAM ${cam.cam}`,
        detection: result.detections[0] ?? null,
      };
      setToasts((prev) => [...prev.slice(-3), toast]);
      const timer = setTimeout(() => {
        toastTimers.current.delete(timer);
        if (alive.current) setToasts((prev) => prev.filter((t) => t.id !== toast.id));
      }, WALL.toastMs);
      toastTimers.current.add(timer);
    },
    [],
  );

  const loadResult = useCallback(
    async (cam: WallCamera, jobId: string, signal: AbortSignal) => {
      for (let attempt = 0; attempt < VIEW_RETRIES; attempt++) {
        try {
          const view = await fetchView(cam.clip_id, signal);
          if (!view.worker) throw new Error("no result");
          const result = checkResult(view);
          patch(cam.clip_id, { phase: "done", result, finishedAt: Date.now(), error: null });
          if (siteMode.current === "site") {
            // The lead agent decides who is notified: announce only cameras it alerted.
            finished.current.set(cam.clip_id, { cam, jobId, result });
            const alerted = alertOrder.current?.some((a) => a.clip_id === cam.clip_id);
            if (alerted && !announced.current.has(cam.clip_id)) {
              announced.current.add(cam.clip_id);
              announce(cam, jobId, result);
            }
          } else {
            announce(cam, jobId, result);
          }
          return;
        } catch {
          if (signal.aborted || !alive.current) return;
          await new Promise((r) => setTimeout(r, 800 * (attempt + 1)));
        }
      }
      patch(cam.clip_id, { phase: "failed", error: MSG.noResult, finishedAt: Date.now() });
    },
    [announce, patch],
  );

  const run = useCallback(
    async (cam: WallCamera, presetJobId?: string) => {
      const id = cam.clip_id;
      started.current.add(id);
      closers.current.get(id)?.();
      aborts.current.get(id)?.abort();
      const ctrl = new AbortController();
      aborts.current.set(id, ctrl);
      patch(id, { ...IDLE, phase: "checking", startedAt: Date.now() });
      let jobId: string;
      try {
        jobId = presetJobId ?? (await beginCheck(id, ctrl.signal));
      } catch {
        if (ctrl.signal.aborted) return;
        patch(id, { phase: "failed", error: MSG.noStart, finishedAt: Date.now() });
        return;
      }
      if (ctrl.signal.aborted || !alive.current) return;
      patch(id, { jobId });
      const close = followJob(jobId, {
        onProgress: (p) =>
          patch(id, { step: p.step, total: p.total, stepWord: isPlainText(p.plain_message) ? p.plain_message : null }),
        onAgent: (text) => {
          if (isPlainText(text)) patch(id, { agentLine: text });
        },
        onDone: () => {
          closers.current.delete(id);
          void loadResult(cam, jobId, ctrl.signal);
        },
        onFailed: (message) => {
          closers.current.delete(id);
          patch(id, { phase: "failed", error: isPlainText(message) ? message : MSG.stopped, finishedAt: Date.now() });
        },
        onLost: () => {
          closers.current.delete(id);
          if (!autoRetried.current.has(id) && alive.current) {
            autoRetried.current.add(id);
            patch(id, { stepWord: null, step: 0, agentLine: null });
            const timer = setTimeout(() => {
              toastTimers.current.delete(timer);
              if (alive.current) rerun.current?.(cam);
            }, 2000);
            toastTimers.current.add(timer);
            return;
          }
          patch(id, { phase: "failed", error: MSG.lost, finishedAt: Date.now() });
        },
      });
      closers.current.set(id, close);
    },
    [loadResult, patch],
  );

  // Restore finished checks from this tab before planning, so they are not run again.
  useEffect(() => {
    const saved = readSaved();
    if (!saved) return;
    const done = Object.entries(saved.runs).filter(([, r]) => r.phase === "done");
    if (!done.length) return;
    // Mark them started now (the planner below skips them); fill the tiles just after.
    for (const [clipId] of done) started.current.add(clipId);
    queueMicrotask(() => {
      if (!alive.current) return;
      if (typeof saved.origin === "number") setRestoredOrigin(saved.origin);
      setRuns((prev) => ({ ...Object.fromEntries(done), ...prev }));
      setNotifications((prev) => (prev.length ? prev : (saved.notifications ?? [])));
    });
  }, []);

  // Save once checks finish (only finished ones are restored).
  useEffect(() => {
    if (Object.values(runs).some((r) => r.phase === "done")) {
      writeSaved({ at: Date.now(), origin: origin ?? undefined, runs, notifications });
    }
  }, [runs, notifications, origin]);

  // One site run for the whole wall: the lead agent starts the six checkers at once; each tile
  // follows its checker's own hazard job. Any failure falls back to the direct staggered checks.
  useEffect(() => {
    if (loadedAt === null || !cameras.length || siteAsked.current) return;
    siteAsked.current = true;
    // Coming back to the wall: the checks already finished in this tab, so do not run them again.
    if (cameras.every((c) => started.current.has(c.clip_id))) return;
    let source: EventSource | null = null;
    const fallBack = () => {
      source?.close();
      if (siteMode.current === "direct") return;
      siteMode.current = "direct";
      if (alive.current) setDirect(true);
    };
    const parseData = (e: Event) => {
      try {
        return JSON.parse((e as MessageEvent).data) as Record<string, unknown>;
      } catch {
        return null;
      }
    };
    const takeAlerts = (alerts: SiteAlert[]) => {
      alertOrder.current = alerts;
      setSite((prev) => (prev ? { ...prev, alerts } : prev));
      for (const a of alerts) {
        const f = finished.current.get(a.clip_id);
        if (f && !announced.current.has(a.clip_id)) {
          announced.current.add(a.clip_id);
          announce(f.cam, f.jobId, f.result);
        }
      }
    };
    void (async () => {
      try {
        const res = await fetch(apiUrl("/api/wall/run"), {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: "{}",
        });
        if (!res.ok) throw new Error(String(res.status));
        const body = (await res.json()) as { site_run_id: string; mode?: string; run_cams?: number; events_url: string };
        if (!alive.current) return;
        siteMode.current = "site";
        setSite({
          id: body.site_run_id,
          mode: typeof body.mode === "string" ? body.mode : "live",
          runCams: typeof body.run_cams === "number" ? body.run_cams : null,
          state: "running",
          checkers: {},
          alerts: null,
          lead: [],
        });
        const es = new EventSource(apiUrl(body.events_url));
        source = es;
        es.addEventListener("lead", (e) => {
          const d = parseData(e);
          if (!d || typeof d.text !== "string" || !alive.current) return;
          const line: LeadLine = { t: Number(d.t_s) || 0, kind: String(d.kind ?? "say"), text: d.text };
          setSite((prev) => (prev ? { ...prev, lead: [...prev.lead, line].slice(-LEAD_LINES_KEPT) } : prev));
        });
        es.addEventListener("checker", (e) => {
          const d = parseData(e);
          if (!d || !alive.current) return;
          const state = String(d.state) as CheckerState;
          // Keyed by the wall's own CAM number: a replayed run keeps the numbers it was recorded
          // with, which differ once the wall lineup changes. The clip id is the stable join.
          const cam = cameras.find((c) => c.clip_id === d.clip_id);
          if (!cam) return;
          setSite((prev) => (prev ? { ...prev, checkers: { ...prev.checkers, [cam.cam]: state } } : prev));
          if (typeof d.job_id === "string" && d.job_id && !started.current.has(cam.clip_id)) {
            void run(cam, d.job_id);
          }
        });
        es.addEventListener("alerts", (e) => {
          const d = parseData(e);
          if (d && Array.isArray(d.alerts)) takeAlerts(d.alerts as SiteAlert[]);
        });
        es.addEventListener("done", (e) => {
          const d = parseData(e);
          if (d && Array.isArray(d.alerts) && !alertOrder.current) takeAlerts(d.alerts as SiteAlert[]);
          setSite((prev) => (prev ? { ...prev, state: "done" } : prev));
          es.close();
        });
        es.onerror = () => {
          if (es.readyState === EventSource.CLOSED && !alertOrder.current) fallBack();
        };
      } catch {
        fallBack();
      }
    })();
    return () => source?.close();
  }, [announce, cameras, loadedAt, run]);

  // Plan each camera's first check once: cameras known at load use the fixed stagger; a camera
  // that joins later starts a little after it appears. Only in "direct" mode (site run failed).
  useEffect(() => {
    if (loadedAt === null || !direct) return;
    const now = Date.now();
    let hz = 0;
    let bs = 0;
    for (const cam of cameras) {
      const offsets = cam.kind === "blindspot" ? WALL.blindspotStartS : WALL.hazardStartS;
      const index = cam.kind === "blindspot" ? bs++ : hz++;
      if (plannedAt.current.has(cam.clip_id)) continue;
      const configuredS = typeof cam.check_after_s === "number" && cam.check_after_s >= 0 ? cam.check_after_s : null;
      const offsetS = configuredS ?? offsets[index] ?? offsets[offsets.length - 1] + 5 * (index - offsets.length + 1);
      const fixed = loadedAt + 1000 * offsetS;
      const late = now - loadedAt > 1000;
      const at = late ? Math.max(fixed, now + 1000 * (WALL.lateStartS + WALL.lateGapS * lateCount.current++)) : fixed;
      plannedAt.current.set(cam.clip_id, at);
    }
    const timers: ReturnType<typeof setTimeout>[] = [];
    for (const cam of cameras) {
      if (started.current.has(cam.clip_id)) continue;
      const at = plannedAt.current.get(cam.clip_id) ?? now;
      timers.push(setTimeout(() => void run(cam), Math.max(0, at - Date.now())));
    }
    return () => timers.forEach(clearTimeout);
  }, [cameras, direct, loadedAt, run]);

  // Close every stream, request and toast timer when the wall goes away.
  useEffect(() => {
    alive.current = true;
    const c = closers.current;
    const a = aborts.current;
    const t = toastTimers.current;
    return () => {
      alive.current = false;
      c.forEach((close) => close());
      c.clear();
      a.forEach((ctrl) => ctrl.abort());
      a.clear();
      t.forEach(clearTimeout);
      t.clear();
    };
  }, []);

  useEffect(() => {
    rerun.current = (cam: WallCamera) => void run(cam);
  }, [run]);

  const retry = useCallback((cam: WallCamera) => void run(cam), [run]);

  return { runs, notifications, toasts, dismissToast, retry, idle: IDLE, site, direct, origin };
}
