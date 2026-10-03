"use client";

import { Panel } from "@/components/hud/panel";
import type { HazardFindingRaw, HazardTechnical, HazardZone } from "@/lib/hazards-v1";
import { cn } from "@/lib/utils";

const fmtNum = (x: unknown, digits = 2): string => {
  if (typeof x !== "number" || !Number.isFinite(x)) return "—";
  return Number.isInteger(x) ? String(x) : x.toFixed(digits);
};

const secs = (x: unknown) => (typeof x === "number" && Number.isFinite(x) ? `${x.toFixed(2)}s` : "—");

function scalar(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") return Number.isFinite(v) ? String(Number(v.toPrecision(6))) : "—";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (Array.isArray(v)) return v.map(scalar).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** Nested model metadata as dotted rows; the identifying keys first. */
function flatten(obj: Record<string, unknown>, prefix = ""): [string, string][] {
  const rows: [string, string][] = [];
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) rows.push(...flatten(v as Record<string, unknown>, key));
    else rows.push([key, scalar(v)]);
  }
  return rows;
}

const MODEL_FIRST = ["model", "model_id", "id", "name", "inference_source", "base_url", "profile", "elapsed_seconds", "elapsed_s"];

function modelRows(model: Record<string, unknown>): [string, string][] {
  const rows = flatten(model);
  const rank = (k: string) => {
    const i = MODEL_FIRST.indexOf(k);
    return i === -1 ? MODEL_FIRST.length : i;
  };
  return rows.map((r, i) => ({ r, i })).sort((a, b) => rank(a.r[0]) - rank(b.r[0]) || a.i - b.i).map((x) => x.r);
}

function Mono({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cn("font-mono text-[11px] tracking-[0.04em] break-all text-fg/90", className)}>{children}</span>;
}

function KV({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="divide-y divide-line">
      {rows.map(([k, v]) => (
        <div key={k} className="grid grid-cols-[minmax(7rem,38%)_minmax(0,1fr)] gap-3 px-3 py-1.5">
          <dt className="micro min-w-0 self-center break-all">{k}</dt>
          <dd className="min-w-0 text-[11px] leading-4 break-words text-fg/90">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function StandardLinks({ keys, standards }: { keys: string[]; standards: HazardTechnical["standards"] }) {
  if (!keys.length) return <span className="text-muted">none</span>;
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-1">
      {keys.map((k) => {
        const s = standards[k];
        return s?.url ? (
          <a key={k} href={s.url} target="_blank" rel="noopener noreferrer" className="text-fg underline decoration-line-strong underline-offset-2 hover:decoration-fg">
            {k}
          </a>
        ) : (
          <span key={k}>{k}</span>
        );
      })}
    </span>
  );
}

function FindingRaw({ f, standards }: { f: HazardFindingRaw; standards: HazardTechnical["standards"] }) {
  return (
    <article className="border-t border-line px-3 py-3 first:border-t-0" data-testid="finding-raw" aria-labelledby={`raw-${f.finding_id}`}>
      <h3 id={`raw-${f.finding_id}`} className="flex flex-wrap items-baseline gap-x-2 text-[12px] font-bold tracking-[0.06em] text-fg">
        <span className="text-muted">{f.finding_id}</span>
        <span>{f.title}</span>
      </h3>
      <p className="micro mt-1">
        {f.status} · {f.severity} severity · {f.confidence} confidence
      </p>
      <p className="mt-1 text-[11px] text-fg/75">
        Cited observations: {secs(f.first_observed_s)}–{secs(f.last_observed_s)} (sampled, not continuous) · {f.location}
      </p>
      <dl className="mt-2 grid grid-cols-[6.5rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[11px] leading-4">
        <dt className="micro">Observed</dt>
        <dd className="text-fg/90">{f.observation}</dd>
        <dt className="micro">Risk</dt>
        <dd className="text-fg/90">{f.risk_interpretation}</dd>
        <dt className="micro">Standards</dt>
        <dd>
          <StandardLinks keys={f.standards} standards={standards} />
        </dd>
        <dt className="micro">Applicability</dt>
        <dd className="text-fg/90">{f.applicability_reason}</dd>
        <dt className="micro">Unknowns</dt>
        <dd className="text-fg/90">{f.unknowns.join("; ") || "none listed"}</dd>
        <dt className="micro">Actions</dt>
        <dd className="text-fg/90">{f.recommended_actions.join("; ")}</dd>
        <dt className="micro">Zones</dt>
        <dd>
          <Mono>{f.zone_ids.join(", ") || "[]"}</Mono>
        </dd>
        <dt className="micro">Evidence</dt>
        <dd>
          <Mono>{f.evidence_ids.join(", ")}</Mono>
          {f.observed_times_s?.length ? <span className="text-muted"> @ {f.observed_times_s.map((t) => secs(t)).join(", ")}</span> : null}
        </dd>
      </dl>
    </article>
  );
}

function ZonesTable({ zones }: { zones: HazardZone[] }) {
  return (
    <div className="thin-scroll overflow-x-auto">
      <table className="w-full min-w-[640px] border-collapse text-left text-[11px] tabular-nums" data-testid="zones-table">
        <thead>
          <tr className="border-b border-line">
            {["Zone", "Kind", "BBox (source px)", "Score", "Start", "End", "Peak frame", "Stab / floor / paint"].map((h) => (
              <th key={h} scope="col" className="micro px-3 py-1.5 font-normal whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {zones.map((z) => (
            <tr key={z.zone_id} className="border-b border-line last:border-b-0">
              <th scope="row" className="px-3 py-1.5 font-bold text-fg">
                {z.zone_id}
              </th>
              <td className="px-3 py-1.5 text-fg/85">{z.kind}</td>
              <td className="px-3 py-1.5 whitespace-nowrap text-fg/85">{z.bbox_source ? `[${z.bbox_source.join(", ")}]` : "—"}</td>
              <td className="px-3 py-1.5 text-fg/85">{fmtNum(z.proposal_score, 3)}</td>
              <td className="px-3 py-1.5 text-fg/85">{secs(z.active_start_s)}</td>
              <td className="px-3 py-1.5 text-fg/85">{secs(z.active_end_s)}</td>
              <td className="px-3 py-1.5 text-fg/85">{fmtNum(z.peak_frame)}</td>
              <td className="px-3 py-1.5 whitespace-nowrap text-fg/70">
                {z.stability != null ? `${fmtNum(z.stability)} / ${fmtNum(z.floor_contact)} / ${fmtNum(z.paint_proximity)}` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export interface TechnicalReportProps {
  technical: HazardTechnical;
}

/** Left column of the technical view: the model's findings and its per-zone review, verbatim. */
export function TechnicalFindings({ technical: t }: TechnicalReportProps) {
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <Panel index="01" title="Findings (raw)" meta={<span>{t.findings_raw.length} findings</span>}>
        {t.findings_raw.length ? (
          t.findings_raw.map((f) => <FindingRaw key={f.finding_id} f={f} standards={t.standards} />)
        ) : (
          <p className="px-3 py-3 text-[11px] text-fg/70">No findings returned in the sampled evidence; this is not a safety clearance.</p>
        )}
      </Panel>
      <Panel index="02" title="Zone review" meta={<span>{t.zone_reviews.length} zones</span>}>
        <ul className="divide-y divide-line">
          {t.zone_reviews.map((z) => (
            <li key={z.zone_id} className="grid grid-cols-[2.75rem_minmax(0,1fr)] gap-2 px-3 py-1.5 text-[11px] leading-4">
              <span className="font-bold text-fg">{z.zone_id}</span>
              <span className="min-w-0">
                <span className={cn("micro mr-2", z.disposition === "hazard_candidate" && "text-warning")}>{z.disposition}</span>
                <span className="text-fg/85">{z.interpretation}</span>
                <Mono className="ml-2 text-muted">{z.evidence_ids.join(", ")}</Mono>
              </span>
            </li>
          ))}
        </ul>
      </Panel>
      {t.dismissed?.length ? (
        <Panel index="03" title="Dismissed" meta={<span>{t.dismissed.length}</span>}>
          <ul className="divide-y divide-line">
            {t.dismissed.map((d, i) => (
              <li key={i} className="px-3 py-1.5 text-[11px] leading-4">
                <span className="font-bold text-fg">{d.concern}</span>
                <span className="text-fg/80"> — {d.reason}</span>
                <Mono className="ml-2 text-muted">{d.evidence_ids.join(", ")}</Mono>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
    </div>
  );
}

/** Full-width technical panels: zones, model and run metadata, limitations, prompts. */
export function TechnicalDetails({ technical: t }: TechnicalReportProps) {
  const runRows: [string, React.ReactNode][] = [
    ["request sha256", <Mono key="sha">{t.request_sha256 ?? "—"}</Mono>],
    ["segmentation", t.segmentation_method ?? "—"],
    [
      "quality warnings",
      t.quality_warnings.length ? (
        <ul key="qw" className="flex flex-col gap-1">
          {t.quality_warnings.map((w, i) => (
            <li key={i} className="text-warning">
              {w}
            </li>
          ))}
        </ul>
      ) : (
        "none"
      ),
    ],
  ];
  const cfg = Object.entries(t.config ?? {});

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <Panel index="06" title="Zones (CV proposals)" meta={<span>{t.zones.length} zones</span>}>
        <ZonesTable zones={t.zones} />
      </Panel>

      <div className="grid gap-3 lg:grid-cols-2">
        <Panel index="07" title="Model" meta={<span>{t.model ? "recorded" : "none"}</span>}>
          {t.model ? <KV rows={modelRows(t.model)} /> : <p className="px-3 py-2 text-[11px] text-fg/70">No model call recorded.</p>}
        </Panel>
        <div className="flex min-w-0 flex-col gap-3">
          <Panel index="08" title="Run">
            <KV rows={runRows} />
          </Panel>
          <section
            aria-label="Dataset label (withheld from the AI)"
            className="hatch relative border border-dashed border-line-strong px-3 py-2.5"
            data-testid="dataset-label"
          >
            <p className="micro">Dataset label (withheld from the AI)</p>
            <p className="mt-1 font-mono text-[13px] tracking-[0.06em] text-fg">{t.dataset_label ?? "— (not a labelled dataset clip)"}</p>
          </section>
        </div>
      </div>

      {cfg.length ? (
        <Panel index="09" title="Config">
          <dl className="grid grid-cols-2 gap-px bg-line sm:grid-cols-3 lg:grid-cols-5">
            {cfg.map(([k, v]) => (
              <div key={k} className="bg-panel px-3 py-1.5">
                <dt className="micro truncate">{k}</dt>
                <dd className="text-[11px] text-fg/90 tabular-nums">{scalar(v)}</dd>
              </div>
            ))}
          </dl>
        </Panel>
      ) : null}

      {t.limitations?.length ? (
        <Panel index="10" title="Limitations">
          <ul className="flex flex-col gap-1 px-3 py-2">
            {t.limitations.map((l, i) => (
              <li key={i} className="text-[11px] leading-4 text-fg/85">
                — {l}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}

      {/* full width: the prompts keep their own line breaks (~100 columns) */}
      <div className="flex flex-col gap-3">
        <Panel index="11" title="System prompt (verbatim)">
          <pre className="thin-scroll max-h-96 overflow-auto px-3 py-2 text-[11px] leading-[17px] whitespace-pre-wrap text-fg/90" data-testid="system-prompt">
            {t.system_prompt}
          </pre>
        </Panel>
        <Panel index="12" title="Audit prompt (verbatim)">
          <pre className="thin-scroll max-h-96 overflow-auto px-3 py-2 text-[11px] leading-[17px] whitespace-pre-wrap text-fg/90" data-testid="audit-prompt">
            {t.audit_prompt}
          </pre>
        </Panel>
      </div>
    </div>
  );
}
