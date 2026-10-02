/**
 * Actions taken on /ops while a request is still in flight, or just after one. A test that holds
 * a real request in the browser (POST /api/runs or the judge call) checks the page, then lets it
 * go on to the real API. Fixture profile throughout: these tests need a fixed run, not a model.
 */
import type { Page } from "@playwright/test";

import { WEB_URL } from "./env";
import {
  EVENTS_ROUTE,
  containsGroundTruth,
  expect,
  groundTruthTokens,
  openOps,
  runToEnd,
  test,
  ui,
  watchGroundTruth,
} from "./fixtures";

const RUNS_ROUTE = /\/api\/runs$/;
const JUDGE_ROUTE = /\/api\/judge\/scenarios\//;

/** The reveal button only: a revealed tile also has HIDE. */
const revealButton = (page: Page) => ui(page).groundTruth.getByRole("button", { name: /^(REVEAL|FETCHING)/ });

/**
 * Hold `method` requests to `url` in the browser. releaseOne(i) lets the i-th held request on to
 * the real API; release() lets every held and later one through.
 */
async function hold(page: Page, url: RegExp, method: "GET" | "POST") {
  const held: string[] = [];
  const gates: (() => void)[] = [];
  let open = false;
  await page.route(url, async (route) => {
    if (route.request().method() !== method || open) return route.fallback();
    held.push(route.request().url());
    await new Promise<void>((r) => gates.push(r));
    return route.fallback();
  });
  return {
    held,
    releaseOne: (i: number) => gates[i]?.(),
    release: () => {
      open = true;
      for (const g of gates) g();
    },
  };
}

test("run request in flight [fixture]: scenario, profile and REVEAL stay locked until the API answers", async ({ page }) => {
  const u = ui(page);
  await openOps(page, "?scenario=eval_001");
  await runToEnd(page);
  const revealBtn = revealButton(page);
  await expect(revealBtn).toBeEnabled();

  // A scenario switch here would pair the coming run with another scenario's ground truth.
  const post = await hold(page, RUNS_ROUTE, "POST");
  const rerun = runToEnd(page);
  await expect.poll(() => post.held.length).toBe(1);
  await expect(u.select).toBeDisabled();
  await expect(u.profile).toBeDisabled();
  await expect(u.run).toBeDisabled();
  await expect(revealBtn).toBeDisabled();

  post.release();
  await rerun;
  await expect(u.select).toBeEnabled();
  await expect(revealBtn).toBeEnabled();
});

test("judge reply after RE-RUN [fixture]: a reveal still in flight when the next run starts is dropped", async ({ page }) => {
  const u = ui(page);
  const gtTokens = groundTruthTokens("eval_001");
  await openOps(page, "?scenario=eval_001");
  await runToEnd(page);

  const judge = await hold(page, JUDGE_ROUTE, "GET");
  const revealBtn = revealButton(page);
  await revealBtn.click();
  await expect(revealBtn).toHaveText("FETCHING JUDGE DATA");
  const stopGtWatch = await watchGroundTruth(page, gtTokens);

  const posted = page.waitForRequest((r) => r.method() === "POST" && RUNS_ROUTE.test(r.url()));
  const rerun = runToEnd(page);
  await posted;
  const judged = page.waitForResponse(JUDGE_ROUTE);
  judge.release();
  // the stale reply has reached the page before the state is read
  await (await judged).finished();
  await rerun;

  await expect(u.groundTruth).toHaveAttribute("data-state", "withheld");
  expect(await stopGtWatch(), "ground-truth tokens added to the DOM after RE-RUN").toEqual([]);
  expect(containsGroundTruth(await page.content(), gtTokens)).toBe(false);
});

test("reveal across a RE-RUN [fixture]: the dropped reveal neither keeps FETCHING nor unlocks the next one", async ({ page }) => {
  const u = ui(page);
  const judgeCalls: string[] = [];
  page.on("request", (r) => {
    if (JUDGE_ROUTE.test(r.url())) judgeCalls.push(r.url());
  });
  // pace 0: the page aborts a judge call after LIVE.requestTimeoutMs (6 s), so the held first
  // reveal must still be open when the second one starts, a RE-RUN later
  await openOps(page, "?scenario=eval_001&pace=0");
  await runToEnd(page);

  const judge = await hold(page, JUDGE_ROUTE, "GET");
  const revealBtn = revealButton(page);
  await revealBtn.click();
  await expect(revealBtn).toHaveText("FETCHING JUDGE DATA");

  // the RE-RUN drops that reveal: nothing is fetching for the new run, during it or after
  const posted = page.waitForRequest((r) => r.method() === "POST" && RUNS_ROUTE.test(r.url()));
  const rerun = runToEnd(page);
  await posted;
  // the RE-RUN itself clears it: the dropped reveal's own end, even its 6 s abort, may not
  await expect(revealBtn, "FETCHING ends when the RE-RUN starts").not.toHaveText("FETCHING JUDGE DATA", { timeout: 2_000 });
  await rerun;
  await expect(revealBtn).toHaveText("REVEAL FOR JUDGE");
  await expect(revealBtn).toBeEnabled();

  await revealBtn.click();
  await expect.poll(() => judge.held.length).toBe(2);
  await expect(revealBtn).toHaveText("FETCHING JUDGE DATA");
  // the dropped reveal's reply lands while the new one is still held (a short wait: if the page
  // already timed that call out, no reply comes and the test fails here instead of hanging)
  const firstReply = page.waitForResponse(JUDGE_ROUTE, { timeout: 4_000 });
  judge.releaseOne(0);
  await (await firstReply).finished();
  // absence check, so a fixed wait: an unlock by the stale reply would show up here
  await page.waitForTimeout(300);
  await expect(revealBtn).toHaveText("FETCHING JUDGE DATA");
  await expect(revealBtn).toBeDisabled();
  await expect(u.groundTruth).toHaveAttribute("data-state", "withheld");

  judge.releaseOne(1);
  await expect(u.groundTruth).toHaveAttribute("data-state", "revealed");
  expect(judgeCalls, "one judge call per reveal click").toHaveLength(2);
});

test("scenario change during a reveal [fixture]: FETCHING ends, and the old reply reveals nothing, even back on its scenario", async ({ page }) => {
  const u = ui(page);
  const gtTokens = groundTruthTokens("eval_001");
  const judgeCalls: string[] = [];
  page.on("request", (r) => {
    // the judge record itself, not the revealed camera's video
    const path = new URL(r.url()).pathname;
    if (/^\/api\/judge\/scenarios\/[^/]+$/.test(path)) judgeCalls.push(path);
  });
  await openOps(page, "?scenario=eval_001");
  await runToEnd(page);

  const judge = await hold(page, JUDGE_ROUTE, "GET");
  const revealBtn = revealButton(page);
  await revealBtn.click();
  await expect(revealBtn).toHaveText("FETCHING JUDGE DATA");

  // the scenario select stays open while a reveal is pending; switching drops that reveal
  await u.select.selectOption("eval_005");
  await expect(revealBtn, "FETCHING ends with the scenario change").toHaveText("REVEAL AFTER RUN", { timeout: 2_000 });
  await expect(revealBtn).toBeDisabled();

  // back on eval_001 before its reply lands: a reply matched by scenario alone would reveal the
  // camera now, with no run on screen and no click
  await u.select.selectOption("eval_001");
  await expect(revealBtn).toHaveText("REVEAL AFTER RUN");
  const stopGtWatch = await watchGroundTruth(page, gtTokens, { checkPage: true });
  const staleReply = page.waitForResponse(JUDGE_ROUTE, { timeout: 4_000 });
  judge.release();
  await (await staleReply).finished();
  // absence check, so a fixed wait
  await page.waitForTimeout(300);
  await expect(u.groundTruth).toHaveAttribute("data-state", "withheld");
  await expect(revealBtn).toHaveText("REVEAL AFTER RUN");
  expect(await stopGtWatch(), "ground-truth tokens shown by the dropped reply").toEqual([]);

  // nor was the reply kept: the next reveal asks the judge again
  await runToEnd(page);
  await revealBtn.click();
  await expect(u.groundTruth).toHaveAttribute("data-state", "revealed");
  expect(judgeCalls).toEqual(["/api/judge/scenarios/eval_001", "/api/judge/scenarios/eval_001"]);
});

test("RE-RUN after a reveal [fixture]: the cached ground truth stays withheld until it is revealed again", async ({ page }) => {
  const u = ui(page);
  const gtTokens = groundTruthTokens("eval_001");
  const judgeCalls: string[] = [];
  page.on("request", (r) => {
    if (JUDGE_ROUTE.test(r.url())) judgeCalls.push(r.url());
  });
  await openOps(page, "?scenario=eval_001");
  await runToEnd(page);
  const revealBtn = revealButton(page);
  await revealBtn.click();
  await expect(u.groundTruth).toHaveAttribute("data-state", "revealed");

  // the judge reply stays cached for this scenario; the new run must not show it
  const stopGtWatch = await watchGroundTruth(page, gtTokens);
  await runToEnd(page);
  await expect(u.groundTruth).toHaveAttribute("data-state", "withheld");
  await expect(u.groundTruth).toContainText("POSITION WITHHELD");
  await expect(page.getByTestId("gt-expected")).toHaveCount(0);
  expect(await stopGtWatch(), "ground-truth tokens added to the DOM during the RE-RUN").toEqual([]);
  expect(containsGroundTruth(await page.content(), gtTokens)).toBe(false);

  await revealBtn.click();
  await expect(u.groundTruth).toHaveAttribute("data-state", "revealed");
  expect(judgeCalls, "the second reveal reuses the cached reply").toHaveLength(1);
});

test("leaving /ops while the run request is in flight [fixture]: no event stream opens afterwards", async ({ page }) => {
  const u = ui(page);
  const streams: string[] = [];
  page.on("request", (r) => {
    if (EVENTS_ROUTE.test(r.url())) streams.push(r.url());
  });
  await openOps(page, "?scenario=eval_001");

  const post = await hold(page, RUNS_ROUTE, "POST");
  const answered = page.waitForResponse((r) => r.request().method() === "POST" && RUNS_ROUTE.test(r.url()));
  await u.run.click();
  await expect.poll(() => post.held.length).toBe(1);
  // client-side navigation: the page's JS (and the pending POST) outlives the /ops tree
  await page.getByRole("link", { name: "AMBIENT/MIRROR" }).click();
  await expect(page).toHaveURL(`${WEB_URL}/`);
  post.release();
  expect((await answered).status()).toBe(202);

  // absence check, so a fixed wait: a stream opened by the stale reply would show up here
  await page.waitForTimeout(1_500);
  expect(streams).toEqual([]);
});
