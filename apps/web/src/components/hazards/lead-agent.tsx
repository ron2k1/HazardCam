"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { apiUrl } from "@/lib/config";

interface SiteSnapshot {
  site_run_id: string;
  state: string;
  elapsed_s: number;
  checkers: { cam: number; clip_id: string; kind: string; state: string; job_id: string | null; started_s: number | null; ended_s: number | null }[];
  lead_trace: { t_s: number; text: string }[];
  alerts: { cam: number; severity: string; line: string }[] | null;
  alerts_source: string | null;
}

/** "Lead agent" section of /hazards/process?site=<id>: the lead's trace and its six checkers. */
export function LeadAgent({ siteRunId }: { siteRunId: string }) {
  const [snap, setSnap] = useState<SiteSnapshot | null>(null);
  useEffect(() => {
    let stop = false;
    const load = async () => {
      try {
        const res = await fetch(apiUrl(`/api/wall/runs/${encodeURIComponent(siteRunId)}`));
        if (res.ok && !stop) {
          const s = (await res.json()) as SiteSnapshot;
          setSnap(s);
          if (s.state === "running") setTimeout(load, 2000);
        }
      } catch {
        if (!stop) setTimeout(load, 4000);
      }
    };
    void load();
    return () => {
      stop = true;
    };
  }, [siteRunId]);
  if (!snap) return null;
  return (
    <section className="border border-line p-3" data-testid="lead-agent">
      <h2 className="tele mb-2">
        LEAD AGENT · 6 CHECKERS · {snap.state} · {snap.elapsed_s.toFixed(0)} s
      </h2>
      <ul className="mb-2 grid grid-cols-2 gap-1 text-[12px] sm:grid-cols-3">
        {snap.checkers.map((c) => (
          <li key={c.cam}>
            <Link className="underline-offset-2 hover:underline" href={`/hazards/process?clip=${encodeURIComponent(c.clip_id)}${c.job_id ? `&job=${encodeURIComponent(c.job_id)}` : ""}`}>
              CAM {c.cam} · {c.state}
              {c.ended_s != null && c.started_s != null ? ` · ${(c.ended_s - c.started_s).toFixed(0)} s` : ""}
            </Link>
          </li>
        ))}
      </ul>
      {snap.alerts?.length ? (
        <ol className="mb-2 text-[12px] text-fg">
          {snap.alerts.map((a) => (
            <li key={a.cam}>
              {a.severity.toUpperCase()} · {a.line}
            </li>
          ))}
        </ol>
      ) : null}
      <ol className="max-h-40 overflow-auto text-[11px] text-fg/70">
        {snap.lead_trace.map((r, i) => (
          <li key={i} className="tabular-nums">
            {r.t_s.toFixed(1)}s {r.text}
          </li>
        ))}
      </ol>
    </section>
  );
}
