/**
 * Plain-language helpers for the worker view: friendly camera names, the progress line built
 * from SSE camera/tool events, message wording, click-to-seek targets, and a deterministic leak
 * check for every string a card shows. Pure and local: no model calls, no network.
 * Relative imports only, so the e2e suite can import it directly.
 */
import type {
  AlertDeliveryStatus,
  AlertKind,
  AlertLevel,
  AlertMessage,
  PublicCamera,
} from "./contracts";
import type { RunView } from "./run-view";

/* ------------------------------------------------------------------ cameras */

/**
 * "cam_b" -> "Camera B", "cam_02" -> "Camera 2". Any other id is named by its 1-based slot,
 * so a scenario with ids like "dock_left" still reads "Camera 1". Never shows the raw id.
 */
export function cameraName(id: string, index?: number): string {
  const m = /^cam(?:era)?[_\-\s]?([a-z]|\d{1,3})$/i.exec(id.trim());
  if (m) return `Camera ${/^\d+$/.test(m[1]) ? String(Number(m[1])) : m[1].toUpperCase()}`;
  return index != null && index >= 0 ? `Camera ${index + 1}` : "Camera";
}

/**
 * Camera id -> friendly name for the cameras on screen, in their display order. The API's
 * display_name wins (the alert messages use the same one); cameraName() is the fallback.
 */
export function cameraNames(cameras: readonly Pick<PublicCamera, "id" | "display_name">[]): Map<string, string> {
  return new Map(cameras.map((c, i) => [c.id, c.display_name?.trim() || cameraName(c.id, i)]));
}

/** "Camera A, Camera B and Camera C". */
export function joinNames(names: readonly string[]): string {
  const u = [...new Set(names)];
  if (u.length <= 1) return u[0] ?? "";
  return `${u.slice(0, -1).join(", ")} and ${u[u.length - 1]}`;
}

/* ----------------------------------------------------------------- progress */

export type ProgressTone = "idle" | "busy" | "done" | "failed";

export interface WorkerProgress {
  text: string;
  tone: ProgressTone;
  /** Steps finished / all steps: one per camera, then comparing, then deciding. */
  done: number;
  total: number;
}

const CAMERA_TOOLS = new Set(["sample_video", "inspect_camera"]);
const COMPARE_TOOLS = new Set(["correlate_observations", "triangulate_region"]);
const DECIDE_TOOLS = new Set(["get_supporting_frames", "reason_hypothesis", "submit_hypothesis"]);

/**
 * The one-line status under the Run button, from events the run already streams (camera phases
 * and tool calls). Order-tolerant: an agent that calls tools in another order still reads right.
 */
export function workerProgress(view: RunView, names: ReadonlyMap<string, string>): WorkerProgress {
  const ids = view.cameraIds.length ? view.cameraIds : [...names.keys()];
  const nameOf = (id: string) => names.get(id) ?? cameraName(id, ids.indexOf(id));
  const total = ids.length + 2;
  const camerasDone = ids.filter((id) => view.cameras[id]?.phase === "complete").length;

  if (view.phase === "idle") return { text: "Ready. Press Run to check the cameras.", tone: "idle", done: 0, total };
  if (view.phase === "complete") return { text: "Done. All cameras checked.", tone: "done", done: total, total };
  if (view.phase === "failed") {
    return { text: "Stopped before it finished. Press Run to try again.", tone: "failed", done: camerasDone, total };
  }

  const running = [...view.trace].reverse().find((r) => r.status === "running")?.tool ?? null;
  const finished = (tools: ReadonlySet<string>) => view.trace.some((r) => tools.has(r.tool) && r.status !== "running");
  const deciding = (running !== null && DECIDE_TOOLS.has(running)) || view.hypothesis !== null;
  const comparing = !deciding && running !== null && COMPARE_TOOLS.has(running);
  const compareDone = deciding || finished(new Set(["triangulate_region"]));
  const steps = Math.min(camerasDone + (compareDone ? 1 : 0), total - 1);

  if (deciding) return { text: "Working out what happened…", tone: "busy", done: steps, total };
  if (comparing) return { text: "Comparing cameras…", tone: "busy", done: steps, total };

  const busy = ids.filter((id) => {
    const p = view.cameras[id]?.phase;
    return p === "sampling" || p === "analyzing";
  });
  if (busy.length) return { text: `Checking ${joinNames(busy.map(nameOf))}…`, tone: "busy", done: steps, total };
  if (running !== null && CAMERA_TOOLS.has(running)) return { text: "Checking the cameras…", tone: "busy", done: steps, total };
  if (camerasDone > 0 && camerasDone === ids.length) return { text: "Comparing cameras…", tone: "busy", done: steps, total };
  if (camerasDone > 0) return { text: `Checking the cameras… ${camerasDone} of ${ids.length} done`, tone: "busy", done: steps, total };
  return { text: "Starting…", tone: "busy", done: 0, total };
}

/* ------------------------------------------------------------------ wording */

export const KIND_WORD: Record<AlertKind, string> = {
  ping: "HEADS-UP",
  alert: "ALERT",
  unconfirmed: "COULDN'T CONFIRM",
  all_clear: "ALL CLEAR",
};

/** Urgency in words: how fast to react (config/alerts.yaml `levels` says the same in capitals). */
export const LEVEL_WORD: Record<AlertLevel, string> = {
  danger: "Act now",
  warning: "Check soon",
  info: "No rush",
};

/** The card's kind chip. An alert that needs no action reads NOTICE, so "ALERT" never sits next to "No rush". */
export function kindWord(message: Pick<AlertMessage, "kind" | "level">): string {
  return message.kind === "alert" && message.level === "info" ? "NOTICE" : KIND_WORD[message.kind];
}

/** Kinds that show the urgency word; a calm result (couldn't confirm, all clear) has none. */
export const URGENT_KINDS: ReadonlySet<AlertKind> = new Set<AlertKind>(["ping", "alert"]);

/** Fixed words only: the delivery detail is technical (and may hold secrets), so it is never shown. */
export const DELIVERY_WORD: Record<AlertDeliveryStatus, string> = {
  sent: "Sent to Telegram",
  not_connected: "Telegram not connected",
  failed: "Couldn't send to Telegram. Showing it here only.",
  skipped: "Skipped",
};

/**
 * Delivery statuses a worker sees on a card. Alerts are on screen only until a channel is
 * connected, so "not_connected" and "skipped" stay out of sight (the card still carries the status
 * in data-delivery); only a real send, or a failed one, is worth a word.
 */
export const SHOWN_DELIVERY: ReadonlySet<AlertDeliveryStatus> = new Set<AlertDeliveryStatus>(["sent", "failed"]);

/* --------------------------------------------------------------- recordings */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * A scenario title as a worker reads it: leading dataset codes go ("MEVA KF1 bus station" ->
 * "Bus station"; two or more all-caps codes, so a single real word like "PPE" stays) and an ISO
 * date-time reads "7 Mar 2018, 10:58:26". Falls back to "Recording N".
 */
export function recordingName(title: string | null | undefined, index: number): string {
  let s = (title ?? "").trim();
  const codes = /^(?:[A-Z][A-Z0-9]+\s+){2,}(?=[a-z])/.exec(s);
  if (codes) s = s.slice(codes[0].length);
  // seconds stay: two recordings can start in the same minute
  s = s.replace(
    /\b(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)(?:\.\d+)?\b/g,
    (m, y: string, mo: string, d: string, time: string) => {
      const month = MONTHS[Number(mo) - 1];
      return month ? `${Number(d)} ${month} ${y}, ${time}` : m;
    },
  );
  s = s.replace(/\s{2,}/g, " ").trim();
  return s ? s[0].toUpperCase() + s.slice(1) : `Recording ${index + 1}`;
}

/* --------------------------------------------------------------------- seek */

export interface SeekTarget {
  cameraId: string;
  /** Scenario seconds. */
  t: number;
}

/**
 * Where "Show on video" jumps: for each camera the message cites, its earliest cited moment.
 * Evidence ids are looked up in what the run streamed; without a match, the message's own
 * camera_ids and t_start are used. Only cameras on screen are returned, first-cited first.
 */
export function seekTargets(
  message: Pick<AlertMessage, "evidence_ids" | "camera_ids" | "t_start">,
  view: Pick<RunView, "evidence" | "observations">,
  cameras: readonly Pick<PublicCamera, "id" | "time_offset_s">[],
): SeekTarget[] {
  const visible = new Map(cameras.map((c) => [c.id, c.time_offset_s ?? 0]));
  const best = new Map<string, number>();
  const offer = (cameraId: string, t: number) => {
    if (!visible.has(cameraId) || !Number.isFinite(t)) return;
    const prev = best.get(cameraId);
    if (prev === undefined || t < prev) best.set(cameraId, t);
  };
  for (const id of message.evidence_ids) {
    const fused = view.evidence[id];
    if (fused) {
      offer(fused.camera_id, fused.t_start);
      continue;
    }
    for (const [cameraId, list] of Object.entries(view.observations)) {
      const o = list.find((x) => x.id === id);
      if (o) offer(cameraId, o.t_start + (visible.get(cameraId) ?? 0));
    }
  }
  if (best.size === 0 && message.t_start != null) {
    for (const cameraId of message.camera_ids) offer(cameraId, message.t_start);
  }
  return [...best.entries()].map(([cameraId, t]) => ({ cameraId, t }));
}

/* --------------------------------------------------------------- leak check */

/**
 * Anything a worker must never read: ids (snake_case, observation suffixes, camera-ids), URLs,
 * paths, token shapes, the withheld camera or the judge, pipeline jargon, bearings and degrees,
 * decimals, coordinates, frame/pixel talk and time codes. Mirrors is_technical() in
 * apps/api/services/alert_messages.py, which drops such sentences before a message is sent; this
 * is the second line of defence.
 */
export const LEAK = new RegExp(
  [
    String.raw`\b[a-z]+_[a-z0-9_]+\b`,
    String.raw`\b[a-z][\w-]*\.o\d+\b`,
    String.raw`\bcam(?:era)?-[a-z0-9]+\b`,
    String.raw`https?:\/\/|www\.|\b[\w-]+\.(?:com|org|net|io|ai|dev|app|xyz|ru|cn)\b`,
    String.raw`(?:^|[\s('"])(?:~|[a-z]:)?[\\/][\w.@-]+[\\/]|~\/|\b[\w.-]+\/[\w.-]+\/[\w.-]+`,
    String.raw`\b[\w-]+\.(?:mp4|avi|mov|mkv|webm|json|jsonl|ya?ml|py|env|txt|log|csv|jpe?g|png|db|sqlite|pem|key)\b`,
    String.raw`\b\d{6,}:[\w-]{10,}|\b[\w-]{32,}\b|\bsk-[\w-]{8,}|\beyJ[\w-]*\.|\d{7,}|\bbearer\s+\S{8,}`,
    String.raw`\b(?:token|api[_-]?key|secret|password|passwd|chat_id)\s*[=:]`,
    String.raw`\[withheld\]|\bwithheld\b|\bground[\s_-]*truth\b|\bjudge[sd]?\b|\bhidden[\s_-]+cam`,
    String.raw`\b(?:hypothes[ie]s|evidence|cues?|cluster\w*|triangulat\w*|abstain\w*|regions?|profile|sse|harness|scores?|candidates?|bearings?|azimuth|fusion)\b`,
    String.raw`°|º|\b\d+(?:\.\d+)?\s*deg(?:rees)?\b|\baz\s*\d`,
    String.raw`\d*\.\d+`,
    String.raw`\b[xyz]\s*[=:+-]\s*\d|\br\s*[=:]?\s*\d+(?:\.\d+)?\s*m\b`,
    String.raw`\bframe\s*(?:index|idx|#)|\bframes?\s*[=:#]?\s*\d|\bpixels?\b|\bbbox\b|\bfov\b|\btrack\s*ids?\b|\bquadrants?\b|\bconfidence\b`,
    String.raw`\bt\s*=\s*\d`,
  ].join("|"),
  "i",
);
/** Compass abbreviations ("NNW"); case-sensitive so ordinary words like "new" pass. */
const COMPASS_CODE = /\b(?:NNE|ENE|ESE|SSE|SSW|WSW|WNW|NNW|NE|NW|SE|SW)\b/;

/** True when `text` holds anything a worker must not read (see LEAK). */
export function leaks(text: string): boolean {
  return LEAK.test(text) || COMPASS_CODE.test(text);
}

/**
 * The sentences of `input` that pass the leak check, unchanged; "" when none does. It never
 * rewrites words or rounds numbers (a "1.5 m" safety distance must not become "2 m"): the server
 * already wrote plain text, so anything that still leaks is hidden, not repaired.
 */
export function plainText(input: string): string {
  return input
    .split(/(?<=[.!?])\s+/)
    .filter((sentence) => sentence.trim() && !leaks(sentence))
    .join(" ")
    .trim();
}

/** `text` when every bit of it is plain, else `fallback` (headlines, labels: all or nothing). */
export function plainOr(text: string, fallback: string): string {
  return text.trim() && !leaks(text) ? text : fallback;
}
