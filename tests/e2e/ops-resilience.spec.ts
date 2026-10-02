/**
 * Failure handling on /ops. The API and its runs are real; where a failure cannot be produced by
 * the fixture backend on demand (a dropped stream, a failed tool), the test rewrites the SSE
 * response inside the browser and says so in its title. Runs use the fixture profile whatever
 * E2E_PROFILE is (openOps' default): these tests need a fixed event log, not a model.
 */
import type { APIRequestContext, Page, Route } from "@playwright/test";

import { API_URL } from "./env";
import {
  EVENTS_ROUTE,
  SSE_HEADERS,
  expect,
  frameEnvelope,
  meta,
  openOps,
  runEvents,
  runToEnd,
  shot,
  sseFrames,
  test,
  toFrame,
  ui,
  watchEventSource,
  type Envelope,
} from "./fixtures";

test("API down: offline notice, RUN disabled, recovers when the API answers again", async ({ page }) => {
  const u = ui(page);
  let down = true;
  await page.route(`${API_URL}/**`, (route) => (down ? route.abort("connectionrefused") : route.fallback()));

  await page.goto("/ops?scenario=eval_001");
  await expect(u.notice).toContainText("API OFFLINE");
  await expect(u.notice).toHaveAttribute("role", "alert");
  await expect(u.healthRow("API")).toHaveAttribute("data-status", "offline");
  await expect(u.run).toBeDisabled();
  await expect(u.select).toBeDisabled();
  await expect(u.groundTruth).toHaveAttribute("data-state", "withheld");
  await page.screenshot({ path: shot("ops-api-offline.png"), animations: "disabled" });

  down = false;
  // the offline poll (4 s) picks the API back up, then scenarios load
  await expect(u.healthRow("API")).toHaveAttribute("data-status", "online", { timeout: 15_000 });
  await expect(u.notice).toHaveCount(0);
  await expect(u.select).toHaveValue("eval_001");
  await expect(u.run).toBeEnabled();
});

const CUT = 20;

/**
 * Serve the first events connection only the first CUT events of the real log, then end it so the
 * browser's EventSource reconnects. `resume` answers the reconnect, which is held until
 * `release()` so the test can observe the RESUMING state first.
 */
async function cutStreamAt(page: Page, resume: (route: Route) => Promise<void>) {
  const urls: string[] = [];
  let release: () => void = () => undefined;
  const gate = new Promise<void>((r) => (release = r));
  await page.route(EVENTS_ROUTE, async (route) => {
    urls.push(route.request().url());
    if (urls.length === 1) {
      const full = await (await route.fetch()).text();
      const body = `retry: 150\n\n${sseFrames(full).slice(0, CUT).join("\n\n")}\n\n`;
      return route.fulfill({ status: 200, headers: SSE_HEADERS, body });
    }
    await gate;
    return resume(route);
  });
  return { urls, release: () => release() };
}

/** Start a run on eval_001, wait for the RESUMING state, let the reconnect through, wait for the end. */
async function runThroughCut(page: Page, cut: { release: () => void }) {
  const u = ui(page);
  await openOps(page, "?scenario=eval_001");
  const done = runToEnd(page);
  await expect(u.link).toHaveAttribute("data-link-status", "reconnecting", { timeout: 30_000 });
  await expect(u.notice).toContainText("RESUMING FROM LAST SEQ");
  await expect(u.traceRows.first()).toBeVisible();
  cut.release();
  return done;
}

/** The UI holds exactly what the server's event log says: every tool call and observation once. */
async function expectMatchesServerLog(page: Page, request: APIRequestContext, eventsUrl: string) {
  const u = ui(page);
  const events = await runEvents(request, eventsUrl);
  const started = events.filter((e) => e.type === "tool.started").map((e) => String(e.payload.tool));
  const obsIds = new Set<string>();
  for (const e of events) {
    if (e.type === "camera.observation") obsIds.add(String((e.payload.observation as { id: string }).id));
    if (e.type === "evidence.linked") for (const ev of e.payload.evidence as { id: string }[]) obsIds.add(ev.id);
  }
  await expect(u.traceRows).toHaveCount(started.length);
  expect(await u.traceRows.evaluateAll((els) => els.map((e) => e.getAttribute("data-tool")))).toEqual(started);
  await expect(meta(u.trace, "CALLS")).toHaveText(`${started.length} CALLS`);
  await expect(meta(u.trace, "SEQ")).toHaveText(`SEQ ${String(events.at(-1)?.seq ?? 0).padStart(4, "0")}`);
  await expect(meta(u.timeline, "OBS")).toHaveText(`${obsIds.size} OBS`);
  await expect(u.hypothesisState).toHaveAttribute("data-hypothesis-state", "FINAL");
  await expect(u.link).toHaveAttribute("data-link-status", "closed");
  await expect(u.notice).toHaveCount(0);
}

test("SSE resume [fixture] (first connection cut in the browser): the reconnect sends Last-Event-ID and the API resumes after it", async ({
  page,
  request,
}) => {
  const wire = await watchEventSource(page);
  const cut = await cutStreamAt(page, (route) => route.fallback());
  const { run } = await runThroughCut(page, cut);

  // the browser's own reconnect (same URL, no ?after_seq), carrying the last id it received
  expect(cut.urls).toHaveLength(2);
  expect(cut.urls[1]).toBe(cut.urls[0]);
  expect(wire.lastEventIds.filter((v) => v !== null)).toEqual([String(CUT)]);
  // and the API resumed after it: the reconnect's first event is CUT + 1
  expect([...wire.received.values()].at(-1)?.[0]).toBe(String(CUT + 1));
  await expectMatchesServerLog(page, request, run.events_url);
});

test("SSE replay [fixture] (reconnect answered from seq 1 in the browser): events already applied are dropped, not duplicated", async ({
  page,
  request,
}) => {
  const MARK = "replayed_duplicate";
  let replayFrom = -1;
  let markedStarts = 0;
  const cut = await cutStreamAt(page, async (route) => {
    // a server or proxy that ignores Last-Event-ID: the whole log again
    const headers = Object.fromEntries(Object.entries(route.request().headers()).filter(([k]) => k !== "last-event-id"));
    const full = sseFrames(await (await route.fetch({ headers })).text()).map(frameEnvelope);
    replayFrom = full[0].seq;
    // Tag the copies of events the page already applied. The reducer is idempotent by id for most
    // events, so identical copies would not show a missing seq guard; tagged ones would.
    const replay = full.map((e) => {
      if (e.seq > CUT || e.type !== "tool.started") return e;
      markedStarts += 1;
      return { ...e, payload: { ...e.payload, args_summary: { [MARK]: true } } };
    });
    return route.fulfill({ status: 200, headers: SSE_HEADERS, body: `${replay.map(toFrame).join("\n\n")}\n\n` });
  });
  const { run } = await runThroughCut(page, cut);

  expect(cut.urls).toHaveLength(2);
  expect(replayFrom, "the reconnect really was handed events the page already had").toBe(1);
  expect(markedStarts, "tool.started events among the replayed duplicates").toBeGreaterThan(0);
  await expect(ui(page).trace).not.toContainText(MARK);
  await expectMatchesServerLog(page, request, run.events_url);
});

test("tool failure + run.failed [fixture] (injected in the browser; the backend run itself succeeds) render as a failed run", async ({
  page,
}) => {
  const u = ui(page);
  const FAILED_TOOL = "reason_hypothesis";
  const error = "e2e injected: reasoning adapter unavailable";
  let requests = 0;

  await page.route(EVENTS_ROUTE, async (route) => {
    requests += 1;
    const full = sseFrames(await (await route.fetch()).text()).map(frameEnvelope);
    const cut = full.findIndex((e) => e.type === "tool.started" && e.payload.tool === FAILED_TOOL);
    expect(cut).toBeGreaterThan(0);
    const kept = full.slice(0, cut + 1);
    const last = kept[kept.length - 1];
    const next = (n: number, type: string, payload: Record<string, unknown>): Envelope => ({
      run_id: last.run_id,
      seq: last.seq + n,
      ts: new Date().toISOString(),
      type,
      payload,
    });
    const injected = [
      next(1, "tool.completed", {
        call_id: last.payload.call_id,
        tool: FAILED_TOOL,
        ok: false,
        latency_ms: 12.5,
        result_summary: {},
        error,
      }),
      next(2, "run.failed", { stage: FAILED_TOOL, error }),
    ];
    // retry: 150 would make a client that does not close on run.failed reconnect almost at once
    const body = `retry: 150\n\n${[...kept, ...injected].map(toFrame).join("\n\n")}\n\n`;
    return route.fulfill({ status: 200, headers: SSE_HEADERS, body });
  });

  await openOps(page, "?scenario=eval_001");
  await runToEnd(page, "failed");

  const failedRow = page.locator(`li[data-tool="${FAILED_TOOL}"][data-status="error"]`);
  await expect(failedRow).toHaveCount(1);
  await expect(failedRow).toContainText(error);
  await expect(meta(u.trace, "FAILED")).toHaveText("1 FAILED");
  await expect(u.failure).toContainText(`RUN FAILED · STAGE REASON HYPOTHESIS · ${error}`);
  await expect(u.hypothesisState).toHaveAttribute("data-hypothesis-state", "NO RESULT");
  await expect(u.hypothesisEvent).toHaveText("—");
  await expect(u.hypothesis).toContainText("RUN FAILED · NO HYPOTHESIS");
  await expect(u.groundTruth.getByRole("button")).toBeDisabled();
  await expect(u.run).toBeEnabled();
  await expect(u.run).toHaveText("▶ RE-RUN");
  await expect(u.link).toHaveAttribute("data-link-status", "closed");
  await page.screenshot({ path: shot("ops-injected-failure.png"), animations: "disabled" });

  // closed on the terminal event: no reconnect loop (absence check, so a fixed wait)
  await page.waitForTimeout(1_000);
  expect(requests).toBe(1);
});

test("/ops?mock=default still renders the offline mock and never calls the API", async ({ page }) => {
  const apiHits: string[] = [];
  page.on("request", (r) => {
    if (r.url().startsWith(API_URL)) apiHits.push(r.url());
  });
  await page.goto("/ops?mock=default");
  await expect(page.getByTestId("source-label")).toContainText("MOCK");
  await expect(ui(page).hypothesisState).toHaveAttribute("data-hypothesis-state", /FINAL/);
  await expect(ui(page).traceRows.first()).toBeVisible();
  await expect(ui(page).link).toHaveCount(0);
  expect(apiHits).toEqual([]);
});
