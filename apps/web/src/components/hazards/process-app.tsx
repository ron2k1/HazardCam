"use client";

import { useEffect, useMemo, useState } from "react";

import { Panel } from "@/components/hud/panel";
import {
  clock,
  hazardsApi,
  mediaUrl,
  plainError,
  STEP_MESSAGES,
  STEP_WORDS,
  subscribeJob,
  type AgentLine,
  type AgentTraceItem,
  type ClipSummary,
  type HazardInstructions,
  type HazardProgress,
  type HazardReplayInfo,
  type HazardTechnical,
  type HazardView,
  type HazardWorker,
  type JobDone,
} from "@/lib/hazards";
import { cn } from "@/lib/utils";

import { zoneName } from "./derive";
import { HazardsHeader } from "./hazards-header";
import { InstructionsPanel } from "./instructions-panel";
import { CleanImage } from "./picture-grid";
import { RuntimeRows, useRuntimeStatus } from "./runtime-strip";
import { FindingRaw, KV, modelRows, Mono, scalar, ZonesTable } from "./technical-report";

export interface ProcessAppProps {
  clipId: string | null;
  jobId: string | null;
}

type Phase = "connecting" | "no_job" | "running" | "done" | "failed" | "lost" | "error";

interface StepRow {
  step: number;
  message: string;
  plain: string;
  t_s?: number;
  received_at: number;
}

const PRE = "thin-scroll max-h-[28rem] overflow-auto px-3 py-2 font-mono text-[11px] leading-[17px] whitespace-pre-wrap text-fg/90";

function replayInfo(t: HazardTechnical | null | undefined, done: JobDone | null): { at: string | null } | null {
  const r = t?.replay;
  if (r && typeof r === "object") return { at: (r as HazardReplayInfo).reviewed_at ?? null };
  if (r === true || done?.replay) return { at: done?.reviewed_at ?? null };
  return null;
}

function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/**
 * /hazards/process: the reasoning and process behind one camera's check, in its own tab. It
 * attaches to the job (live while it runs; the full log from the start when it is late), then
 * shows the stack, the agent trace, the steps, the exact instructions, the raw evidence, the model
 * run and the raw report.
 */
export function ProcessApp({ clipId, jobId: initialJob }: ProcessAppProps) {
  const runtime = useRuntimeStatus(true);
  const [clip, setClip] = useState<ClipSummary | null>(null);
  const [jobId, setJobId] = useState<string | null>(initialJob);
  const [phase, setPhase] = useState<Phase>(clipId ? "connecting" : "error");
  const [message, setMessage] = useState<string | null>(clipId ? null : "No camera was given.");
  const [steps, setSteps] = useState<StepRow[]>([]);
  const [agent, setAgent] = useState<AgentLine[]>([]);
  const [done, setDone] = useState<JobDone | null>(null);
  const [view, setView] = useState<HazardView | null>(null);
  const [instructions, setInstructions] = useState<HazardInstructions | null>(null);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);

  // camera title + the instructions (these are not results)
  useEffect(() => {
    const ctl = new AbortController();
    hazardsApi.clips(ctl.signal).then(
      (r) => setClip(r.clips.find((c) => c.clip_id === clipId) ?? null),
      () => undefined,
    );
    hazardsApi.instructions(ctl.signal).then(setInstructions, () => undefined);
    return () => ctl.abort();
  }, [clipId]);

  // no ?job=: the clip's latest job
  useEffect(() => {
    if (!clipId || jobId) return;
    const ctl = new AbortController();
    hazardsApi.latestJob(clipId, ctl.signal).then(
      (j) => {
        if (j?.job_id) setJobId(j.job_id);
        else setPhase("no_job");
      },
      (err) => {
        if (!ctl.signal.aborted) {
          setPhase("error");
          setMessage(plainError(err));
        }
      },
    );
    return () => ctl.abort();
  }, [clipId, jobId]);

  // follow the job
  useEffect(() => {
    if (!clipId || !jobId) return;
    const close = subscribeJob(jobId, {
      onProgress: (p: HazardProgress) => {
        setPhase((ph) => (ph === "connecting" ? "running" : ph));
        if (p.step < 1) return;
        setSteps((rows) =>
          rows.some((r) => r.step === p.step && r.message === p.message)
            ? rows
            : [...rows, { step: p.step, message: p.message, plain: p.plain_message, t_s: p.t_s, received_at: p.received_at ?? Date.now() }],
        );
      },
      onAgent: (line) => {
        setPhase((ph) => (ph === "connecting" ? "running" : ph));
        setAgent((a) => (a.some((x) => x.text === line.text && x.t_s === line.t_s) ? a : [...a, line]));
      },
      onDone: (_id, info) => {
        setDone(info ?? { clip_id: clipId });
        setPhase("done");
        hazardsApi.view(clipId).then(setView, (err) => setMessage(plainError(err)));
        hazardsApi.report(clipId).then(setReport, () => undefined);
      },
      onFailed: (msg) => {
        setPhase("failed");
        setMessage(msg);
        hazardsApi.view(clipId).then(setView, () => undefined);
      },
      onLost: () => setPhase("lost"),
    });
    return close;
  }, [clipId, jobId]);

  const t = view?.technical ?? null;
  const replay = replayInfo(t, done);
  const title = clip?.title ?? view?.clip.title ?? clipId ?? "";
  const found = useMemo(() => {
    if (!t) return undefined;
    const out: Record<string, string> = {};
    for (const z of t.zone_reviews ?? []) out[z.zone_id] = `${z.disposition}: ${z.interpretation}`;
    for (const f of t.findings_raw ?? []) {
      for (const zid of f.zone_ids ?? []) out[zid] = `${f.finding_id} ${f.title}${out[zid] ? ` · ${out[zid]}` : ""}`;
    }
    return out;
  }, [t]);

  return (
    <div className="flex min-h-dvh flex-col bg-bg" data-testid="process-app" data-phase={phase}>
      <HazardsHeader current={null} title="Reasoning and process" runtime={runtime} />

      <main className="flex min-w-0 flex-1 flex-col gap-3 px-4 py-4 lg:px-6">
        <section className="flex flex-col gap-1 border-b border-line pb-3">
          <p className="micro normal-case tracking-[0.08em]">
            {clipId ?? "—"}
            {jobId ? ` · job ${jobId}` : ""}
            {t?.run_id ? ` · run ${t.run_id}` : ""}
          </p>
          <h1 className="text-[22px] leading-[1.2] font-extrabold text-fg">{title || "Reasoning and process"}</h1>
          <p className="text-[13px] text-fg/75" data-testid="process-phase">
            {phase === "connecting"
              ? "Connecting to the check…"
              : phase === "running"
                ? "Check running. This page follows it live."
                : phase === "done"
                  ? `Check finished${view?.reviewed_at ? ` · report generated ${fmtWhen(view.reviewed_at)}` : ""}`
                  : phase === "no_job"
                    ? "No check has run on this camera yet. Start one from the Safety hazards screen."
                    : phase === "lost"
                      ? "Lost touch with the check."
                      : (message ?? "Something went wrong.")}
          </p>
          {replay ? (
            <p className="mt-1 self-start border border-warning/60 px-2 py-0.5 text-[12px] text-warning" data-testid="replay-note">
              Replay of the GB10 run from {fmtWhen(replay.at ?? view?.reviewed_at) || "its stored time"} (no new model call)
            </p>
          ) : null}
        </section>

        <div className="grid gap-3 xl:grid-cols-2 xl:items-start">
          <div className="flex min-w-0 flex-col gap-3">
            <Panel index="01" title="Stack status" meta={<span>polled every 15 s</span>}>
              <RuntimeRows status={runtime} />
            </Panel>

            <Panel index="02" title="Steps" meta={<span>{steps.length ? `${Math.max(...steps.map((s) => s.step))}/6` : "—"}{replay ? " · replay pace, real times in the agent log" : ""}</span>}>
              <StepsTable steps={steps} finished={phase === "done"} />
            </Panel>

            {agent.length || t?.agent ? (
              <Panel index="03" title="Safety agent" meta={<span>{t?.agent?.runner ?? "live"}</span>}>
                <AgentBlock lines={agent} trace={t?.agent?.trace ?? null} technical={t} />
              </Panel>
            ) : null}

            {t ? (
              <Panel index="04" title="Model run" meta={<span>{t.model ? "local" : "none"}</span>}>
                {t.model ? <KV rows={modelRows(t.model)} /> : <p className="px-3 py-2 text-[11px] text-fg/70">No model call recorded.</p>}
                <KV
                  rows={[
                    ["request sha256", <Mono key="sha">{t.request_sha256 ?? "—"}</Mono>],
                    ["segmentation", t.segmentation_method ?? "—"],
                    ["pipeline", scalar((t.pipeline as { version?: unknown } | null)?.version ?? null)],
                    ["run status", t.run_status ?? "—"],
                    ["model error", t.model_error ?? "—"],
                  ]}
                />
              </Panel>
            ) : null}

            {t ? (
              <Panel index="05" title="Quality warnings">
                {t.quality_warnings.length ? (
                  <ul className="flex flex-col gap-1 px-3 py-2">
                    {t.quality_warnings.map((w, i) => (
                      <li key={i} className="text-[11px] leading-4 text-warning">
                        {w}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="px-3 py-2 text-[11px] text-fg/70">none</p>
                )}
                <section className="hatch m-3 border border-dashed border-line-strong px-3 py-2.5" data-testid="dataset-label">
                  <p className="micro">Dataset label (withheld from the AI)</p>
                  <p className="mt-1 font-mono text-[13px] tracking-[0.06em] text-fg">{t.dataset_label ?? "— (not a labelled dataset clip)"}</p>
                </section>
              </Panel>
            ) : null}
          </div>

          <div className="flex min-w-0 flex-col gap-3">
            <Panel index="06" title="What the AI was asked to check">
              <div className="flex flex-col gap-3 p-3">
                {instructions || view?.vision?.instructions ? (
                  <InstructionsPanel instructions={view?.vision?.instructions ?? (instructions as HazardInstructions)} />
                ) : null}
                <Block title="System prompt (verbatim)" testId="system-prompt">
                  {t?.system_prompt || instructions?.system_prompt || "—"}
                </Block>
                <Block title="Standards sent with it">
                  {t ? <StandardsList technical={t} /> : instructions?.standards ? JSON.stringify(instructions.standards, null, 2) : "Shown after the check."}
                </Block>
                <Block title="Answer schema">
                  {instructions?.schema ? JSON.stringify(instructions.schema, null, 2) : "Strict JSON schema with this run's evidence ids, zone ids and standard keys as enums (not exposed by this API build)."}
                </Block>
                <Block title="Audit instructions (verbatim)" testId="audit-prompt">
                  {t?.audit_prompt || instructions?.audit_prompt || "—"}
                </Block>
              </div>
            </Panel>
          </div>
        </div>

        {t ? (
          <>
            <Panel index="07" title="Zones (computer vision proposals)" meta={<span>{t.zones.length} zones</span>}>
              <ZonesTable zones={t.zones} found={found} />
            </Panel>

            <Panel index="08" title="Findings (raw)" meta={<span>{t.findings_raw.length} findings</span>}>
              {t.findings_raw.length ? (
                t.findings_raw.map((f) => <FindingRaw key={f.finding_id} f={f} standards={t.standards} />)
              ) : (
                <p className="px-3 py-3 text-[11px] text-fg/70">No findings returned in the sampled evidence; this is not a safety clearance.</p>
              )}
            </Panel>

            {view?.worker ? <WorkerText worker={view.worker} /> : null}

            <Panel index="09" title="Evidence manifest (exactly as sent)" meta={<span>{t.evidence.length} images</span>}>
              <ol className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-3 lg:grid-cols-5 2xl:grid-cols-7" data-testid="raw-evidence">
                {t.evidence.map((e) => {
                  const url = e.image_url ?? "";
                  return (
                    <li key={e.evidence_id} className="flex min-w-0 flex-col border border-line">
                      <a href={mediaUrl(url) ?? undefined} target="_blank" rel="noopener" className="relative block aspect-[16/10] bg-black">
                        <CleanImage pic={{ src: url, raw: null }} alt={`${e.evidence_id} ${e.kind}`} className="absolute inset-0 h-full w-full" raw />
                      </a>
                      <span className="truncate border-t border-line px-1.5 py-0.5 font-mono text-[10px] leading-4 text-fg/85">
                        {e.evidence_id} · {e.kind} · {e.zone_id ? `${e.zone_id} (${zoneName(e.zone_id)})` : "scene"} · f{e.frame_index} · {e.timestamp_s.toFixed(2)}s
                      </span>
                    </li>
                  );
                })}
              </ol>
            </Panel>

            <details className="border border-line bg-panel/80" data-testid="raw-report">
              <summary className="cursor-pointer px-3 py-2 text-[11px] tracking-[0.16em] text-fg uppercase">
                10 — Raw report JSON {report ? "(hazard_report.json)" : "(technical block)"}
              </summary>
              <pre className={cn(PRE, "max-h-[40rem] border-t border-line")}>{JSON.stringify(report ?? t, null, 2)}</pre>
            </details>
          </>
        ) : phase === "running" || phase === "connecting" ? (
          <p className="border border-line px-3 py-3 text-[12px] text-fg/70">The zones, findings, evidence and report appear here when the check finishes.</p>
        ) : null}
      </main>
    </div>
  );
}

function Block({ title, children, testId }: { title: string; children: React.ReactNode; testId?: string }) {
  return (
    <section className="border border-line">
      <h3 className="micro border-b border-line px-3 py-1.5">{title}</h3>
      <div className={PRE} data-testid={testId}>
        {children}
      </div>
    </section>
  );
}

function StandardsList({ technical: t }: { technical: HazardTechnical }) {
  const entries = Object.entries(t.standards ?? {});
  if (!entries.length) return <>—</>;
  return (
    <ul className="flex flex-col gap-2 font-sans whitespace-normal">
      {entries.map(([k, s]) => (
        <li key={k}>
          <span className="font-bold text-fg">{k}</span> · {s.title}
          <span className="block text-fg/75">{s.summary}</span>
          {s.url ? (
            <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-fg/80 underline decoration-line-strong underline-offset-2">
              {s.url}
            </a>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function StepsTable({ steps, finished }: { steps: StepRow[]; finished: boolean }) {
  const byStep = new Map(steps.map((s) => [s.step, s]));
  // without recorded times, times count from the first step this tab saw
  const attachedAt = steps.length ? Math.min(...steps.map((s) => s.received_at)) : 0;
  const last = steps.length ? Math.max(...steps.map((s) => s.step)) : 0;
  return (
    <ol className="divide-y divide-line" data-testid="process-steps">
      {STEP_WORDS.map((word, i) => {
        const n = i + 1;
        const s = byStep.get(n);
        const next = byStep.get(n + 1);
        const at = s ? (s.t_s ?? (s.received_at - attachedAt) / 1000) : null;
        const nextAt = next ? (next.t_s ?? (next.received_at - attachedAt) / 1000) : null;
        const took = at != null && nextAt != null ? Math.max(0, nextAt - at) : null;
        const state = !s ? "pending" : n < last || finished ? "done" : "running";
        return (
          <li key={n} className="grid grid-cols-[1.5rem_minmax(0,1fr)_auto] items-start gap-2 px-3 py-1.5 text-[11px] leading-4" data-state={state}>
            <span className={cn("font-bold", state === "pending" ? "text-fg/35" : "text-fg")}>{n}</span>
            <span className="min-w-0">
              <span className={cn(state === "pending" ? "text-fg/45" : "text-fg")}>{s?.plain || word}</span>
              <span className="block font-mono text-[10px] text-muted">{s?.message || STEP_MESSAGES[i]}</span>
            </span>
            <span className="text-right whitespace-nowrap text-fg/70 tabular-nums">
              {at != null ? `+${clock(at)}` : "—"}
              {took != null ? <span className="block text-muted">{took.toFixed(1)} s</span> : state === "running" ? <span className="blink block">running</span> : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function AgentBlock({ lines, trace, technical }: { lines: AgentLine[]; trace: AgentTraceItem[] | null; technical: HazardTechnical | null }) {
  const a = technical?.agent;
  return (
    <div className="flex flex-col" data-testid="agent-trace">
      {a ? (
        <KV
          rows={[
            ["runner", a.runner],
            ["sandbox", a.sandbox ?? "—"],
            ["agent", a.agent_id ?? "—"],
            ["summary", a.summary?.headline ?? "—"],
            ["first action", a.summary?.first_action ?? "—"],
            ["confirmed findings", (a.summary?.confirmed_finding_ids ?? []).join(", ") || "—"],
          ]}
        />
      ) : null}
      <ol className="divide-y divide-line border-t border-line">
        {(trace?.length ? trace : lines.map((l) => ({ t_s: l.t_s ?? NaN, kind: l.kind ?? "say", tool: l.tool ?? null, text: l.text }))).map((x, i) => (
          <li key={i} className="grid grid-cols-[3.25rem_3rem_minmax(0,1fr)] gap-2 px-3 py-1.5 text-[11px] leading-4">
            <span className="text-fg/60 tabular-nums">{Number.isFinite(x.t_s) ? `+${x.t_s.toFixed(1)}s` : "—"}</span>
            <span className={cn("micro self-center", x.kind === "tool" && "text-fg")}>{x.kind}</span>
            <span className="min-w-0 break-words text-fg/90">
              {x.tool ? <Mono className="mr-1.5 text-fg">{x.tool}</Mono> : null}
              {x.text}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Everything the worker screen no longer shows: scene summary, agent summary, per-hazard prose. */
function WorkerText({ worker: w }: { worker: HazardWorker }) {
  const p = "text-[12px] leading-5 text-fg/90";
  return (
    <Panel index="08b" title="Worker report (full text)" meta={<span>{w.hazards.length} hazards</span>}>
      <div className="flex flex-col gap-3 px-3 py-3" data-testid="worker-text">
        <section>
          <p className="micro">Headline</p>
          <p className={cn(p, "font-bold text-fg")}>{w.headline}</p>
        </section>
        {w.summary ? (
          <section data-testid="scene-summary">
            <p className="micro">Scene summary</p>
            <p className={p}>{w.summary}</p>
          </section>
        ) : null}
        {w.agent_summary?.headline ? (
          <section data-testid="agent-summary-text">
            <p className="micro">Safety agent&apos;s summary</p>
            <p className={cn(p, "font-semibold text-fg")}>{w.agent_summary.headline}</p>
            {w.agent_summary.first_action ? <p className={p}>Do this first: {w.agent_summary.first_action}</p> : null}
          </section>
        ) : null}
        {w.hazards.map((h) => (
          <article key={h.id} className="border-t border-line pt-2" data-testid="worker-hazard-text">
            <h3 className="text-[12px] font-bold tracking-[0.06em] text-fg">
              {h.title} <span className="micro">· {h.priority} priority{h.needs_check ? " · needs a check" : ""}</span>
            </h3>
            <dl className="mt-1 grid grid-cols-[7rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-[12px] leading-5">
              <dt className="micro">What we saw</dt>
              <dd className="text-fg/90">{h.what_we_saw}</dd>
              <dt className="micro">Why it matters</dt>
              <dd className="text-fg/90">{h.why_it_matters}</dd>
              <dt className="micro">What to do</dt>
              <dd className="text-fg/90">{h.what_to_do.join("; ") || "—"}</dd>
              <dt className="micro">Where</dt>
              <dd className="text-fg/90">{h.where}</dd>
              <dt className="micro">When</dt>
              <dd className="text-fg/90">{h.when}</dd>
              <dt className="micro">How sure</dt>
              <dd className="text-fg/90">{h.how_sure}</dd>
              <dt className="micro">Safety rule</dt>
              <dd className="text-fg/90">{h.safety_rule ?? "None of the listed rules"}</dd>
              <dt className="micro">Not sure about</dt>
              <dd className="text-fg/90">{h.not_sure_about.join("; ") || "—"}</dd>
            </dl>
          </article>
        ))}
        <section className="border-t border-line pt-2" data-testid="ruled-out-text">
          <p className="micro">Checked and ruled out</p>
          {w.ruled_out.length ? (
            <ul className="flex flex-col gap-1">
              {w.ruled_out.map((r, i) => (
                <li key={i} className={p}>
                  <span className="font-semibold text-fg">{r.what}</span> — {r.why}
                </li>
              ))}
            </ul>
          ) : (
            <p className={p}>Nothing was ruled out on this camera.</p>
          )}
        </section>
        <section data-testid="cannot-tell-text">
          <p className="micro">What we could not tell</p>
          {w.cannot_tell.length ? (
            <ul className="flex flex-col gap-1">
              {w.cannot_tell.map((c, i) => (
                <li key={i} className={p}>
                  – {c}
                </li>
              ))}
            </ul>
          ) : (
            <p className={p}>—</p>
          )}
        </section>
      </div>
    </Panel>
  );
}
