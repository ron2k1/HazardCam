/**
 * Single source for runtime config values in the web app.
 * NEXT_PUBLIC_* values are inlined at build time.
 */

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8080";

export const API_BASE_URL: string = (
  process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL
).replace(/\/+$/, "");

/** Resolve an API path (e.g. "/api/scenarios") or pass through an absolute URL. */
export function apiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

export const APP_VERSION = "v3.0.0-prebuild";

/** Live /ops wiring (P11). */
export const LIVE = {
  /** Profile a run posts unless the operator picks another. Fixture makes no model calls. */
  defaultProfile: "fixture",
  /** RunRequest.pace_s bounds (apps/api/schemas/run.py). */
  maxPaceS: 5,
  /** GET /healthz poll while the API is up / down. */
  healthPollMs: 10_000,
  offlinePollMs: 4_000,
  /** Abort a JSON request after this long; the API is local, so a slow reply means trouble. */
  requestTimeoutMs: 6_000,
  /** Our own SSE reconnects (the browser gave up, e.g. HTTP error), with doubling backoff. */
  streamMaxRetries: 5,
  streamRetryBaseMs: 750,
} as const;

/** Fixed timeline/plan rendering constants. */
export const UI = {
  /** Range of a FOV wedge in the plan view, as a fraction of the plan extent. */
  fovRangeFraction: 0.55,
  /** Padding (metres) around the plan view bounds. */
  planPaddingM: 2.5,
  /** Minimum scenario duration shown on the timeline (seconds). */
  minTimelineS: 5,
} as const;
