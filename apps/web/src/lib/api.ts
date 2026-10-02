/**
 * Typed JSON calls to the local FastAPI (apps/api). Every request goes to API_BASE_URL;
 * nothing here reaches a non-local host.
 */
import { apiUrl, LIVE } from "./config";
import type {
  JudgeGroundTruth,
  ModelsHealth,
  RunRequest,
  RunResponse,
  ScenarioList,
  ServiceHealth,
} from "./contracts";

/** A failed call: HTTP status (0 = network/timeout) plus the API's `detail`, if any. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(status ? `HTTP ${status} · ${detail}` : detail);
    this.name = "ApiError";
  }
}

function detailOf(body: unknown, fallback: string): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  // FastAPI 422: [{loc, msg, ...}]
  if (Array.isArray(d) && d.length && typeof d[0]?.msg === "string") return d[0].msg;
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  const timeout = AbortSignal.timeout(LIVE.requestTimeoutMs);
  let res: Response;
  try {
    res = await fetch(apiUrl(path), {
      ...init,
      cache: "no-store",
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    });
  } catch (err) {
    if (signal?.aborted) throw err;
    throw new ApiError(0, timeout.aborted ? "timeout" : "unreachable");
  }
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, detailOf(body, res.statusText || "error"));
  return body as T;
}

export const api = {
  serviceHealth: (signal?: AbortSignal) => request<ServiceHealth>("/healthz", {}, signal),
  modelsHealth: (profile: string, signal?: AbortSignal) =>
    request<ModelsHealth>(`/api/models/health?profile=${encodeURIComponent(profile)}`, {}, signal),
  scenarios: (signal?: AbortSignal) => request<ScenarioList>("/api/scenarios", {}, signal),
  /** JUDGE-ONLY. Called from the reveal action and nowhere else. */
  judge: (scenarioId: string, signal?: AbortSignal) =>
    request<JudgeGroundTruth>(`/api/judge/scenarios/${encodeURIComponent(scenarioId)}`, {}, signal),
  createRun: (body: RunRequest) =>
    request<RunResponse>("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

/** Short operator-facing reason for a failed call. */
export function describeError(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return err instanceof Error ? err.message : "error";
}
