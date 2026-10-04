"use client";

import { useEffect, useRef, useState } from "react";

import { kindWord, type WallCamera } from "@/lib/wall";

import type { SiteState, TileRun } from "./use-wall-orchestrator";

export type LogTag = "LEAD" | "START" | "STEP" | "AGENT" | "FOUND" | "CLEAR" | "FAULT";

export interface LogRow {
  seq: number;
  at: number;
  cam: number | null;
  tag: LogTag;
  text: string;
}

const MAX_ROWS = 120;

/**
 * The wall's agent log: one row per change the orchestrator already saw (a lead-agent checker
 * state, a check starting, each pipeline step word, the agent's own narration line, the result).
 * Nothing is written here that did not arrive from the API's job and site-run events.
 */
export function useAgentLog(cameras: WallCamera[], runs: Record<string, TileRun>, site: SiteState | null): LogRow[] {
  const [rows, setRows] = useState<LogRow[]>([]);
  const prevRuns = useRef<Record<string, TileRun>>({});
  const prevCheckers = useRef<Record<number, string>>({});
  const seq = useRef(0);

  useEffect(() => {
    const now = Date.now();
    const add: LogRow[] = [];
    const push = (cam: number | null, tag: LogTag, text: string) => add.push({ seq: ++seq.current, at: now, cam, tag, text });

    for (const [n, state] of Object.entries(site?.checkers ?? {})) {
      const cam = Number(n);
      if (prevCheckers.current[cam] !== state) push(cam, "LEAD", `checker ${state}`);
    }
    prevCheckers.current = { ...(site?.checkers ?? {}) };

    for (const cam of cameras) {
      const r = runs[cam.clip_id];
      const p = prevRuns.current[cam.clip_id];
      if (!r || r === p) continue;
      if (r.phase === "checking" && p?.phase !== "checking") push(cam.cam, "START", `${kindWord(cam.kind).one} check started`);
      if (r.phase === "checking" && r.step > 0 && r.step !== p?.step) {
        push(cam.cam, "STEP", `${r.stepWord ?? "step"} · ${r.step}/${r.total}`);
      }
      if (r.agentLine && r.agentLine !== p?.agentLine) push(cam.cam, "AGENT", r.agentLine);
      if (r.phase === "done" && p?.phase !== "done") {
        const found = r.result?.detections ?? [];
        const words = kindWord(cam.kind);
        if (found.length) {
          const d = found[0];
          const where = d.zoneNames.length ? `${d.zoneNames[0]} · ` : "";
          push(cam.cam, "FOUND", `${found.length} ${found.length === 1 ? words.one : words.many} · ${where}${d.shortTitle}`);
        } else {
          push(cam.cam, "CLEAR", words.none.toLowerCase());
        }
      }
      if (r.phase === "failed" && p?.phase !== "failed") push(cam.cam, "FAULT", r.error ?? "check stopped");
    }
    prevRuns.current = runs;

    // a history of transitions: it cannot be derived from the latest state alone
    if (add.length) setRows((prev) => [...prev, ...add].slice(-MAX_ROWS));
  }, [cameras, runs, site]);

  return rows;
}
