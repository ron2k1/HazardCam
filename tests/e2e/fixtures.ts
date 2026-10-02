import fs from "node:fs";
import path from "node:path";

import { test as base, expect, type APIRequestContext, type Locator, type Page } from "@playwright/test";

import { signedCoord } from "../../apps/web/src/lib/format";
import { API_URL, ARTIFACTS_DIR, REPO_ROOT, RUN_TIMEOUT_MS } from "./env";

const LOCAL_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);

export function isLocalUrl(raw: string): boolean {
  const u = new URL(raw);
  return u.protocol === "data:" || u.protocol === "blob:" || LOCAL_HOSTS.has(u.hostname);
}

interface Fixtures {
  /** Non-local URLs the page tried to load; every one is aborted and fails the test. */
  offHost: string[];
  /** Uncaught page exceptions; any one fails the test. */
  pageErrors: string[];
}

export const test = base.extend<Fixtures>({
  offHost: [
    async ({ context }, use) => {
      const offHost: string[] = [];
      // Context-level, so it sees every request; page.route handlers in a spec run first.
      await context.route("**/*", (route) => {
        const url = route.request().url();
        if (isLocalUrl(url)) return route.continue();
        offHost.push(url);
        return route.abort("blockedbyclient");
      });
      await use(offHost);
      expect(offHost, "requests to hosts other than 127.0.0.1/localhost").toEqual([]);
    },
    { auto: true },
  ],
  pageErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await use(errors);
      expect(errors, "uncaught page errors").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

// ---------------------------------------------------------------------------------------------
// API (Playwright's request context; not routed through the page, never the judge endpoint
// before the UI reveal has been asserted)

export interface ApiScenario {
  id: string;
  title?: string | null;
  cameras: { id: string; time_offset_s?: number | null; media_available: boolean }[];
}

export interface RunRecord {
  run_id: string;
  scenario_id: string;
  profile: string;
  state: string;
  created_at: string;
  finished_at: string | null;
  hypothesis: {
    event_type: string;
    region: string;
    confidence: number;
    evidence_ids: string[];
  } | null;
  events_url: string;
}

export interface Envelope {
  run_id: string;
  seq: number;
  ts: string;
  type: string;
  payload: Record<string, unknown>;
}

export async function apiJson<T>(request: APIRequestContext, urlPath: string): Promise<T> {
  const res = await request.get(`${API_URL}${urlPath}`);
  expect(res.status(), `GET ${urlPath}`).toBe(200);
  return (await res.json()) as T;
}

/** SSE body -> frames (each "id: n\ndata: {...}"); comments/pings dropped. */
export function sseFrames(body: string): string[] {
  return body
    .replace(/\r\n/g, "\n")
    .split(/\n\n+/)
    .map((f) => f.trim())
    .filter((f) => /^data:/m.test(f));
}

export function frameEnvelope(frame: string): Envelope {
  const data = frame
    .split("\n")
    .filter((l) => l.startsWith("data:"))
    .map((l) => l.slice(5).trimStart())
    .join("\n");
  return JSON.parse(data) as Envelope;
}

export function toFrame(env: Envelope): string {
  return `id: ${env.seq}\ndata: ${JSON.stringify(env)}`;
}

/** The finished run's full event log (the server replays from seq 1 and closes after the terminal event). */
export async function runEvents(request: APIRequestContext, eventsUrl: string): Promise<Envelope[]> {
  const res = await request.get(`${API_URL}${eventsUrl}`, { headers: { accept: "text/event-stream" } });
  expect(res.status()).toBe(200);
  return sseFrames(await res.text()).map(frameEnvelope);
}

export const SSE_HEADERS = { "content-type": "text/event-stream", "cache-control": "no-cache" };
export const EVENTS_ROUTE = /\/api\/runs\/[^/]+\/events/;

export interface EventSourceWire {
  /** Last-Event-ID of each EventSource request that went to the network (null = none sent). */
  lastEventIds: (string | null)[];
  /** SSE ids the page received, per connection (CDP requestId), in arrival order. */
  received: Map<string, string[]>;
}

/**
 * EventSource traffic as Chromium sees it. Playwright's request.headers()/allHeaders() omit
 * Last-Event-ID on intercepted requests although the browser sends it, so read the wire via CDP.
 */
export async function watchEventSource(page: Page): Promise<EventSourceWire> {
  const wire: EventSourceWire = { lastEventIds: [], received: new Map() };
  const cdp = await page.context().newCDPSession(page);
  cdp.on("Network.requestWillBeSentExtraInfo", (e) => {
    const h = Object.fromEntries(Object.entries(e.headers).map(([k, v]) => [k.toLowerCase(), String(v)]));
    if (h.accept === "text/event-stream") wire.lastEventIds.push(h["last-event-id"] ?? null);
  });
  cdp.on("Network.eventSourceMessageReceived", (e) => {
    const ids = wire.received.get(e.requestId) ?? [];
    wire.received.set(e.requestId, [...ids, e.eventId]);
  });
  await cdp.send("Network.enable");
  return wire;
}

// ---------------------------------------------------------------------------------------------
// UI

export const ui = (page: Page) => ({
  select: page.getByTestId("scenario-select"),
  profile: page.locator("#profile-select"),
  run: page.getByTestId("run-button"),
  phase: page.locator("[data-run-phase]"),
  link: page.locator("[data-link-status]"),
  notice: page.getByTestId("ops-notice"),
  failure: page.getByTestId("run-failure"),
  hypothesisState: page.locator("[data-hypothesis-state]"),
  hypothesis: page.getByRole("region", { name: "Hypothesis", exact: true }),
  /** Exact readouts: panel-wide toContainText would also match the reason prose. */
  hypothesisEvent: page.getByTestId("hypothesis-event"),
  confidence: page.getByTestId("hypothesis-confidence"),
  region: page.getByTestId("hypothesis-region"),
  trace: page.getByRole("region", { name: "Agent Trace", exact: true }),
  timeline: page.getByRole("region", { name: "Evidence Timeline", exact: true }),
  traceRows: page.locator("li[data-tool]"),
  plannedTools: page.getByRole("list", { name: "Planned tool sequence" }).locator("li > span:first-child"),
  groundTruth: page.getByTestId("ground-truth"),
  healthRow: (k: string) => page.locator(`[data-health-row="${k}"]`),
  video: (cameraId: string) => page.locator(`figure[data-camera-id="${cameraId}"] video`),
});

/**
 * One span of a panel's header meta, e.g. meta(trace, "CALLS") -> "12 CALLS". The spans' text
 * runs together in textContent ("SEQ 005112 CALLS"), so match the span, not the panel.
 */
export function meta(panel: Locator, unit: string): Locator {
  const re = unit === "SEQ" ? /^\s*SEQ \d+\s*$/ : new RegExp(`^\\s*\\d+ ${unit}\\s*$`);
  return panel.locator("header span").filter({ hasText: re });
}

/**
 * /ops once the API answered and the scenario list loaded, with `profile` chosen for the next
 * run. The page offers fixture plus the API's default profile (MODEL_PROFILE), nothing else.
 */
export async function openOps(page: Page, query = "", profile = "fixture"): Promise<void> {
  await page.goto(`/ops${query}`);
  const u = ui(page);
  await expect(u.healthRow("API")).toHaveAttribute("data-status", "online");
  await expect(u.select).toBeEnabled();
  await expect(u.select.locator("option").first()).toHaveAttribute("value", /\S/);
  const offered = u.profile.locator(`option[value="${profile}"]`);
  await expect(offered, `profile ${profile} offered (start the API with MODEL_PROFILE=${profile})`).toHaveCount(1);
  await u.profile.selectOption(profile);
  await expect(u.profile).toHaveValue(profile);
}

export interface FinishedRun {
  run: RunRecord;
  /** Browser wall time from the RUN click until the terminal phase was in the DOM. */
  clickToDoneMs: number;
}

/**
 * Click RUN and wait (polling every animation frame) for this run's terminal phase, which must
 * be `terminal`. Either end stops the wait, so a failed real-model run fails at once with its
 * banner text instead of using up the whole RUN_TIMEOUT_MS. Matching the run id keeps a second
 * run on the same page from ending on the previous run's phase.
 */
export async function runToEnd(page: Page, terminal: "complete" | "failed" = "complete"): Promise<FinishedRun> {
  const u = ui(page);
  const posted = page.waitForResponse((r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/runs");
  await expect(u.run).toBeEnabled();
  const t0 = Date.now();
  await u.run.click();
  const res = await posted;
  expect(res.status(), "POST /api/runs").toBe(202);
  const run = (await res.json()) as RunRecord;
  const ended = await page.waitForFunction(
    (runId) => {
      const phase = document.querySelector(`[data-run-id="${CSS.escape(runId)}"]`)?.getAttribute("data-run-phase");
      return phase === "complete" || phase === "failed" ? phase : null;
    },
    run.run_id,
    { polling: "raf", timeout: RUN_TIMEOUT_MS },
  );
  const clickToDoneMs = Date.now() - t0;
  const phase = await ended.jsonValue();
  const banner = (await u.failure.allTextContents()).join(" ");
  expect(phase, `run ${run.run_id} (${run.profile}) ended ${phase}${banner ? `: ${banner}` : ""}`).toBe(terminal);
  return { run, clickToDoneMs };
}

// ---------------------------------------------------------------------------------------------
// Ground-truth exclusion

export interface GroundTruthTokens {
  /** The withheld camera's id, e.g. cam_gt. */
  id: string;
  /**
   * Every string that would identify it: id, media file stem, label, MEVA camera id, and what
   * the console draws once it is revealed (`revealed`).
   */
  tokens: string[];
  /**
   * What only a revealed console shows: the plan's marker and label and the tile's position
   * readout. The position is the secret itself, and none of it names the camera.
   */
  revealed: string[];
  /** Case-insensitive regex source, bounded so "cam_gt" matches "CAM_GT" but not "cam_gtx". */
  pattern: string;
}

/**
 * The scenario's withheld camera as its manifest on disk describes it. Read from the repo, not
 * the judge API, so nothing calls the judge endpoint before the UI reveal does.
 */
export function groundTruthTokens(scenarioId: string): GroundTruthTokens {
  const file = path.join(REPO_ROOT, "data", "manifests", `${scenarioId}.json`);
  const gt = (
    JSON.parse(fs.readFileSync(file, "utf8")) as {
      ground_truth_camera: { id: string; file?: string; label?: string; position?: [number, number] | null };
    }
  ).ground_truth_camera;
  // blind-zone-plan.tsx's marker and label; ground-truth-tile.tsx's readout, formatted by the
  // app's own helper so the token cannot drift from what the UI prints
  const revealed = ['data-camera="ground-truth"', "GT · JUDGE"];
  if (gt.position) revealed.push(`X ${signedCoord(gt.position[0])} Y ${signedCoord(gt.position[1])}`);
  const tokens = [gt.id];
  if (gt.file) tokens.push(path.posix.basename(gt.file).replace(/\.[^.]+$/, ""));
  if (gt.label) tokens.push(gt.label, ...(/\bG\d{3,4}\b/.exec(gt.label) ?? []));
  tokens.push(...revealed);
  const escaped = tokens.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return { id: gt.id, tokens, revealed, pattern: `(?<![A-Za-z0-9])(?:${escaped.join("|")})(?![A-Za-z0-9])` };
}

export function containsGroundTruth(html: string, gt: GroundTruthTokens): boolean {
  return new RegExp(gt.pattern, "i").test(html);
}

/** The reveal-only tokens `html` lacks: after REVEAL this must be empty, or the detector is blind. */
export function missingRevealTokens(html: string, gt: GroundTruthTokens): string[] {
  return gt.revealed.filter((t) => !html.includes(t));
}

/**
 * Watch every DOM change from now on (added nodes, attribute values, text edits) for the
 * ground-truth tokens; returns a stop() that disconnects and yields the hits. Scanning only
 * what changed keeps it cheap through a minutes-long real-model run. Values written after
 * arming and overwritten before the callback runs are seen through the records' old values;
 * the value a node held when the watch began is not, since a reveal before arming legitimately
 * shows the camera. Where nothing may show it yet, `checkPage` scans the page in the same task
 * that starts the watch, so no change falls between the two. One watcher at a time per page.
 */
export async function watchGroundTruth(
  page: Page,
  gt: GroundTruthTokens,
  { checkPage = false } = {},
): Promise<() => Promise<string[]>> {
  await page.evaluate(({ pattern, checkPage }) => {
    const re = new RegExp(pattern, "i");
    const hits: string[] = [];
    const scan = (text: string | null, where: string) => {
      const m = text ? re.exec(text) : null;
      if (m && text && hits.length < 10) hits.push(`${where}: …${text.slice(Math.max(0, m.index - 60), m.index + 60)}…`);
    };
    if (checkPage) scan(document.documentElement.outerHTML, "page at arming");
    // The first record for a node and key carries the value from before arming; every later one
    // carries a value written since. A node inserted after arming has no value from before.
    const seen = new WeakMap<Node, Set<string>>();
    const inserted = new WeakSet<Node>();
    const writtenSinceArming = (node: Node, key: string) => {
      const keys = seen.get(node) ?? new Set<string>();
      seen.set(node, keys);
      const later = keys.has(key);
      keys.add(key);
      for (let n: Node | null = node; !later && n; n = n.parentNode) if (inserted.has(n)) return true;
      return later;
    };
    const observer = new MutationObserver((records) => {
      for (const r of records) {
        if (r.type === "attributes") {
          // as name="value", so an attribute that turns an element into the plan's marker matches
          const name = r.attributeName ?? "";
          scan(`${name}="${(r.target as Element).getAttribute(name)}"`, `@${name}`);
          if (writtenSinceArming(r.target, `@${name}`)) scan(`${name}="${r.oldValue}"`, `@${name} (old)`);
        } else if (r.type === "characterData") {
          scan(r.target.textContent, "text");
          if (writtenSinceArming(r.target, "#text")) scan(r.oldValue, "text (old)");
        } else
          for (const n of r.addedNodes) {
            inserted.add(n);
            scan(n instanceof Element ? n.outerHTML : n.textContent, "node");
          }
      }
    });
    observer.observe(document.documentElement, {
      subtree: true,
      childList: true,
      attributes: true,
      characterData: true,
      attributeOldValue: true,
      characterDataOldValue: true,
    });
    (window as unknown as { __gtWatch: () => string[] }).__gtWatch = () => {
      observer.disconnect();
      return hits;
    };
  }, { pattern: gt.pattern, checkPage });
  return () => page.evaluate(() => (window as unknown as { __gtWatch: () => string[] }).__gtWatch());
}

type ProbeVideo = HTMLVideoElement & { __seeked?: Promise<number> };

/**
 * Park the camera video away from `target`, arm a `seeked` listener, run `act`, and return the
 * media time the video landed on. Proves the click moved the media, not just the UI.
 */
export async function seekVia(video: Locator, target: number, act: () => Promise<void>): Promise<number> {
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState), { timeout: 15_000 }).toBeGreaterThanOrEqual(1);
  await video.evaluate(async (v: ProbeVideo, t: number) => {
    v.pause();
    const park = t >= 4 ? 0.5 : Math.min(t + 6, Math.max(v.duration - 0.5, 0));
    await new Promise<void>((resolve) => {
      v.addEventListener("seeked", () => resolve(), { once: true });
      v.currentTime = park;
    });
    v.__seeked = new Promise<number>((resolve) =>
      v.addEventListener("seeked", () => resolve(v.currentTime), { once: true }),
    );
  }, target);
  await act();
  // NaN when no seek follows the action, so the caller's assertion fails fast
  return video.evaluate((v: ProbeVideo) =>
    Promise.race([
      v.__seeked ?? Promise.resolve(Number.NaN),
      new Promise<number>((resolve) => setTimeout(() => resolve(Number.NaN), 5_000)),
    ]),
  );
}

export function saveJson(name: string, data: unknown): void {
  fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });
  fs.writeFileSync(path.join(ARTIFACTS_DIR, name), `${JSON.stringify(data, null, 2)}\n`);
}

export const shot = (name: string) => path.join(ARTIFACTS_DIR, name);
