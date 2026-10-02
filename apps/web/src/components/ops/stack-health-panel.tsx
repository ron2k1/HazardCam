import { StatusDot } from "@/components/hud/barcode";
import { Panel } from "@/components/hud/panel";
import type { ModelRoleHealth, ModelRoleStatus, ModelsHealth } from "@/lib/contracts";
import { ms } from "@/lib/format";
import { cn } from "@/lib/utils";

export type ApiStatus = "online" | "offline" | "checking" | "mock";

/** Any status a row can carry: API reachability, models-health roll-up, or a role probe. */
export type HealthStatus = ApiStatus | ModelRoleStatus | ModelsHealth["status"] | "unknown";

/** Extra row, e.g. event-day NemoClaw / OpenShell / OpenClaw runtime status. */
export interface HealthRow {
  key: string;
  label: string;
  value: string;
  status: HealthStatus;
  detail?: string | null;
}

export interface StackHealthPanelProps {
  health: ModelsHealth | null;
  /** detail: e.g. /healthz version or failing dependencies. */
  api: { status: ApiStatus; baseUrl: string; detail?: string | null };
  extra?: readonly HealthRow[];
  className?: string;
}

const TONE: Record<HealthStatus, "fg" | "muted" | "dim" | "danger"> = {
  ok: "fg",
  online: "fg",
  mock: "muted",
  checking: "muted",
  unconfigured: "muted",
  fixture: "dim",
  unknown: "dim",
  degraded: "danger",
  unreachable: "danger",
  http_error: "danger",
  offline: "danger",
};

function Line({ k, value, status, detail }: { k: string; value: string; status: HealthStatus; detail?: string | null }) {
  const bad = TONE[status] === "danger";
  return (
    <li className="grid grid-cols-[82px_minmax(0,1fr)_auto] items-baseline gap-x-2 border-b border-line/70 py-1.5 last:border-b-0">
      <span className="micro">{k}</span>
      <span className="min-w-0">
        <span className="block truncate text-[11px] text-fg/90" title={value}>
          {value}
        </span>
        {detail ? (
          <span className="micro block truncate normal-case" title={detail}>
            {detail}
          </span>
        ) : null}
      </span>
      <span className={cn("micro flex items-center gap-1.5", bad ? "text-danger" : "text-fg/80")}>
        <StatusDot tone={TONE[status] ?? "dim"} />
        {status.replace("_", " ").toUpperCase()}
      </span>
    </li>
  );
}

function role(r: ModelRoleHealth) {
  const value = [r.backend, r.model].filter(Boolean).join(" · ") || "—";
  const detail = [
    r.status === "fixture" ? "no model calls" : null,
    r.base_url,
    r.latency_ms != null ? ms(r.latency_ms) : null,
    r.http_status != null && r.status === "http_error" ? `HTTP ${r.http_status}` : null,
    r.model_listed === false ? "model not listed" : null,
    r.missing?.length ? `missing ${r.missing.join(", ")}` : null,
    r.error ?? null,
  ]
    .filter(Boolean)
    .join(" · ");
  return { value, detail: detail || null };
}

export function StackHealthPanel({ health, api, extra = [], className }: StackHealthPanelProps) {
  const perception = health ? role(health.perception) : null;
  const reasoning = health ? role(health.reasoning) : null;
  return (
    <Panel
      index="06"
      title="Stack Health"
      className={className}
      meta={<span>PROFILE {health?.profile.toUpperCase() ?? "—"}</span>}
    >
      <ul className="px-2.5 py-1">
        <Line k="API" value={api.baseUrl} status={api.status} detail={api.detail} />
        <Line
          k="PROFILE"
          value={health ? `${health.profile}${health.mode && health.mode !== health.profile ? ` · ${health.mode}` : ""}` : "unknown"}
          detail={health ? `source ${health.source}` : null}
          status={health?.status ?? "unknown"}
        />
        <Line k="PERCEPTION" value={perception?.value ?? "—"} detail={perception?.detail} status={health?.perception.status ?? "unknown"} />
        <Line k="REASONING" value={reasoning?.value ?? "—"} detail={reasoning?.detail} status={health?.reasoning.status ?? "unknown"} />
        {extra.map((r) => (
          <Line key={r.key} k={r.label} value={r.value} detail={r.detail} status={r.status} />
        ))}
      </ul>
    </Panel>
  );
}
