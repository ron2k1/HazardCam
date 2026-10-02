/**
 * The judged browser path: real API, real SSE, real scenario media. Each test starts a fresh run
 * from the UI. The eval_001 test runs under E2E_PROFILE (fixture by default: recorded model
 * outputs, no model calls); the eval_012 / eval_005 tests check recorded outcomes, so they always
 * run the fixture profile.
 */
import type { Page } from "@playwright/test";

import { API_URL, FIXTURE, PROFILE, RUN_TIMEOUT_MS, TOOL_SEQUENCE } from "./env";
import {
  apiJson,
  containsGroundTruth,
  expect,
  groundTruthTokens,
  meta,
  missingRevealTokens,
  openOps,
  runEvents,
  runToEnd,
  saveJson,
  seekVia,
  shot,
  test,
  ui,
  watchGroundTruth,
  type ApiScenario,
  type RunRecord,
} from "./fixtures";

interface JudgeView {
  scenario_id: string;
  ground_truth_camera: { id: string; video_url: string | null; video_available: boolean };
  expected: { event_type?: string } | null;
}

interface Bar {
  id: string;
  cameraId: string;
  t: number;
}

const label = (id: string) => id.replace(/[_.]+/g, " ").trim().toUpperCase();
/** The event readout; the `unknown` class is an abstention, not a claim. */
const eventText = (eventType: string) => (eventType === "unknown" ? "ABSTAIN — UNKNOWN" : label(eventType));

/** Record every distinct trace-row count while the run streams in (proves rows arrive live). */
async function watchTrace(page: Page): Promise<() => Promise<{ counts: number[]; sawRunning: boolean }>> {
  await page.evaluate(() => {
    const w = window as unknown as { __trace: { counts: number[]; sawRunning: boolean } };
    w.__trace = { counts: [], sawRunning: false };
    new MutationObserver(() => {
      const n = document.querySelectorAll("li[data-tool]").length;
      const counts = w.__trace.counts;
      if (counts[counts.length - 1] !== n) counts.push(n);
      if (document.querySelector('li[data-tool][data-status="running"]')) w.__trace.sawRunning = true;
    }).observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["data-status"] });
  });
  return () =>
    page.evaluate(() => (window as unknown as { __trace: { counts: number[]; sawRunning: boolean } }).__trace);
}

async function timelineBars(page: Page): Promise<Bar[]> {
  return page.locator("button[data-evidence-id]").evaluateAll((els) =>
    els.map((e) => ({
      id: e.getAttribute("data-evidence-id") ?? "",
      cameraId: e.getAttribute("data-camera-id") ?? "",
      t: Number(e.getAttribute("data-t-start")),
    })),
  );
}

const latest = (bars: Bar[]) => bars.reduce((a, b) => (b.t > a.t ? b : a));

/**
 * Under any profile the page is checked against the server's own record and event log, so the
 * test holds for real models; expectations about the recorded fixture outputs sit behind FIXTURE.
 */
test(`eval_001 [${PROFILE}]: live trace in tool order, evidence seeks media, GT withheld until reveal`, async ({
  page,
  request,
}) => {
  const u = ui(page);
  const judgeRequests: string[] = [];
  const consoleErrors: string[] = [];
  page.on("request", (r) => {
    if (new URL(r.url()).pathname.startsWith("/api/judge/")) judgeRequests.push(r.url());
  });
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
  });

  const { scenarios } = await apiJson<{ scenarios: ApiScenario[] }>(request, "/api/scenarios");
  const scenario = scenarios.find((s) => s.id === "eval_001");
  expect(scenario, "eval_001 in GET /api/scenarios").toBeTruthy();
  if (!scenario) return;

  await openOps(page, "", PROFILE);

  // selector = the API's scenario list, in order
  const values = await u.select.locator("option").evaluateAll((os) => os.map((o) => (o as HTMLOptionElement).value));
  expect(values).toEqual(scenarios.map((s) => s.id));
  await u.select.selectOption("eval_001");
  await expect(u.select).toHaveValue("eval_001");

  // runtime status from /healthz + /api/models/health for the chosen profile: recorded outputs
  // (no model calls) for fixture, every model endpoint answering otherwise
  await expect(u.healthRow("PROFILE")).toContainText(PROFILE);
  await expect(u.healthRow("PROFILE")).toHaveAttribute("data-status", FIXTURE ? "fixture" : "ok");
  if (FIXTURE) {
    await expect(u.healthRow("PERCEPTION")).toHaveAttribute("data-status", "fixture");
    await expect(u.healthRow("REASONING")).toHaveAttribute("data-status", "fixture");
  }

  // GT withheld before the run, and no string that names the withheld camera on the page
  const revealBtn = u.groundTruth.getByRole("button");
  await expect(u.groundTruth).toHaveAttribute("data-state", "withheld");
  await expect(revealBtn).toHaveText("REVEAL AFTER RUN");
  await expect(revealBtn).toBeDisabled();
  const gtTokens = groundTruthTokens("eval_001");
  // armed first, so nothing slips in between the snapshot and the watch
  const stopGtWatch = await watchGroundTruth(page, gtTokens);
  expect(containsGroundTruth(await page.content(), gtTokens), "ground-truth tokens on the page before the run").toBe(false);

  const trace = await watchTrace(page);
  const { run, clickToDoneMs } = await runToEnd(page);
  expect(run.profile).toBe(PROFILE);
  expect(clickToDoneMs, `${PROFILE} run under ${RUN_TIMEOUT_MS} ms`).toBeLessThan(RUN_TIMEOUT_MS);
  await expect(u.link).toHaveAttribute("data-link-status", "closed");
  await expect(page.getByTestId("source-label")).toContainText(
    FIXTURE ? "FIXTURE" : `LOCAL MODELS · ${PROFILE.toUpperCase()}`,
  );

  // the readouts equal the server's record, whatever the models concluded
  const record = await apiJson<RunRecord>(request, `/api/runs/${run.run_id}`);
  expect(record.state).toBe("complete");
  expect(record.profile).toBe(PROFILE);
  const h = record.hypothesis;
  expect(h).not.toBeNull();
  if (!h) return;
  if (FIXTURE) expect(h.event_type, "the recorded eval_001 hypothesis is a claim").not.toBe("unknown");
  await expect(u.hypothesisState).toHaveAttribute(
    "data-hypothesis-state",
    h.event_type === "unknown" ? "ABSTAIN · FINAL" : "FINAL",
  );
  await expect(u.hypothesisState).toHaveAttribute("data-event-type", h.event_type);
  await expect(u.hypothesisEvent).toHaveText(eventText(h.event_type));
  await expect(u.confidence).toHaveText(h.confidence.toFixed(2));
  await expect(u.region).toHaveText(h.region.toUpperCase());

  // trace == the server's event log (calls, order, outcomes), tool order == the dev harness sequence
  const events = await runEvents(request, run.events_url);
  expect(events.at(-1)?.type).toBe("run.complete");
  const outcome = new Map(
    events
      .filter((e) => e.type === "tool.completed")
      .map((e): [string, string] => [String(e.payload.call_id), e.payload.ok === true ? "ok" : "error"]),
  );
  const expectedRows = events
    .filter((e) => e.type === "tool.started")
    .map((e) => ({ tool: String(e.payload.tool), status: outcome.get(String(e.payload.call_id)) ?? "running" }));
  const rows = await u.traceRows.evaluateAll((els) =>
    els.map((e) => ({ tool: e.getAttribute("data-tool"), status: e.getAttribute("data-status") })),
  );
  expect(rows).toEqual(expectedRows);
  const failedCalls = rows.filter((r) => r.status === "error").length;
  if (FIXTURE) expect(failedCalls, "failed tool calls in the recorded run").toBe(0);
  if (failedCalls) await expect(meta(u.trace, "FAILED")).toHaveText(`${failedCalls} FAILED`);
  expect([...new Set(rows.map((r) => r.tool))]).toEqual([...TOOL_SEQUENCE]);
  await expect(u.plannedTools).toHaveText([...TOOL_SEQUENCE]);
  await expect(meta(u.trace, "CALLS")).toHaveText(`${rows.length} CALLS`);
  const live = await trace();
  expect(live.sawRunning, "a tool row was seen in the running state").toBe(true);
  expect(live.counts.length, `rows arrived incrementally: ${live.counts.join(",")}`).toBeGreaterThan(3);

  // which perception adapter answered each camera: the recorded outputs, or a real model call
  const adapters = events.filter((e) => e.type === "camera.complete").map((e) => String(e.payload.adapter));
  expect(adapters.length, "camera.complete events").toBeGreaterThan(0);
  for (const adapter of adapters) {
    if (FIXTURE) expect(adapter).toBe("fixture");
    else expect(adapter, "a real model adapter, not the recorded outputs").not.toBe("fixture");
  }

  // alternatives and limitations: each one the final hypothesis carries, in its order
  const final = events.at(-1)?.payload.hypothesis as {
    alternatives: { event_type: string; confidence: number }[];
    limitations: string[];
  };
  if (FIXTURE) {
    expect(final.alternatives.length, "the recorded eval_001 hypothesis lists alternatives").toBeGreaterThan(0);
    expect(final.limitations.length, "the recorded eval_001 hypothesis lists limitations").toBeGreaterThan(0);
  }
  const alternatives = u.hypothesis.getByTestId("hypothesis-alternative");
  await expect(alternatives).toHaveCount(final.alternatives.length);
  expect(
    await alternatives.evaluateAll((els) => els.map((e) => [e.getAttribute("data-event-type"), e.querySelector(".micro")?.textContent])),
  ).toEqual(final.alternatives.map((a) => [a.event_type, a.confidence.toFixed(2)]));
  await expect(u.hypothesis.getByTestId("hypothesis-limitation")).toHaveText(final.limitations.map((l) => `—${l}`));

  // timeline click seeks that camera's video
  const bars = await timelineBars(page);
  expect(bars.length, "evidence on the timeline to seek with").toBeGreaterThan(0);
  const bar = latest(bars);
  const offsetOf = (cameraId: string) => scenario.cameras.find((c) => c.id === cameraId)?.time_offset_s ?? 0;
  const barT = Math.max(0, bar.t - offsetOf(bar.cameraId));
  const landed = await seekVia(u.video(bar.cameraId), barT, () =>
    page.locator(`button[data-evidence-id="${bar.id}"]`).click(),
  );
  expect(Math.abs(landed - barT), `seek ${bar.id} -> ${barT}s, landed ${landed}s`).toBeLessThan(0.25);

  const seeks = [{ via: "timeline", evidence_id: bar.id, camera_id: bar.cameraId, target_s: barT, landed_s: landed }];

  // a cited-evidence chip in the hypothesis panel seeks too, preferably to another bar
  const cited = bars.filter((b) => h.evidence_ids.includes(b.id));
  const others = cited.filter((b) => b.id !== bar.id);
  if (FIXTURE) expect(others.length, "the recorded hypothesis cites evidence besides the latest bar").toBeGreaterThan(0);
  const chip = others.length ? latest(others) : cited.length ? latest(cited) : null;
  if (chip) {
    const chipT = Math.max(0, chip.t - offsetOf(chip.cameraId));
    const chipLanded = await seekVia(u.video(chip.cameraId), chipT, () =>
      u.hypothesis.locator(`[data-cited-evidence="${chip.id}"]`).click(),
    );
    expect(Math.abs(chipLanded - chipT), `seek ${chip.id} -> ${chipT}s, landed ${chipLanded}s`).toBeLessThan(0.25);
    seeks.push({ via: "hypothesis chip", evidence_id: chip.id, camera_id: chip.cameraId, target_s: chipT, landed_s: chipLanded });
  } else {
    // a real-model abstention may cite nothing; the timeline seek above still ran
    test.info().annotations.push({ type: "note", description: `${PROFILE}: hypothesis cites no timeline evidence, chip seek not run` });
  }

  // the chip click scrolled the hypothesis body; show its top (event, confidence) in the artifact
  await u.hypothesis.locator(".overflow-y-auto").first().evaluate((el) => el.scrollTo(0, 0));
  await page.screenshot({ path: shot(`ops-${PROFILE}-eval_001-desktop.png`), animations: "disabled" });

  // still withheld after the run; the judge endpoint has not been called, and no ground-truth
  // token reached the DOM at any point of the run (any case, any attribute)
  expect(judgeRequests).toEqual([]);
  await expect(u.groundTruth).toHaveAttribute("data-state", "withheld");
  await expect(revealBtn).toHaveText("REVEAL FOR JUDGE");
  await expect(u.groundTruth).toContainText("POSITION WITHHELD");
  await expect(page.getByTestId("gt-expected")).toHaveCount(0);
  expect(await stopGtWatch(), "ground-truth tokens added to the DOM during the run").toEqual([]);
  expect(containsGroundTruth(await page.content(), gtTokens), "ground-truth tokens on the page before reveal").toBe(false);

  // the same watcher across REVEAL must fire, so its silence during the run was not a blind spot
  const stopRevealWatch = await watchGroundTruth(page, gtTokens);
  const judgeReply = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/judge/scenarios/eval_001");
  await revealBtn.click();
  const judgeRes = await judgeReply;
  expect(judgeRes.status()).toBe(200);
  const judge = (await judgeRes.json()) as JudgeView;
  const gt = judge.ground_truth_camera;
  expect(gt.id, "the judge's withheld camera is the one the manifest names").toBe(gtTokens.id);
  await expect(u.groundTruth).toHaveAttribute("data-state", "revealed");
  await expect(u.groundTruth).toContainText(gt.id.toUpperCase());
  expect(await stopRevealWatch(), "watcher sees the reveal").not.toEqual([]);
  // every reveal-only rendering is a detector token, so the checks above would have caught each
  expect(missingRevealTokens(await page.content(), gtTokens), "reveal-only tokens missing after REVEAL").toEqual([]);
  expect(containsGroundTruth(await page.content(), gtTokens), "detector finds the revealed camera").toBe(true);
  if (judge.expected?.event_type) {
    await expect(page.getByTestId("gt-expected")).toContainText(`EXPECTED ${label(judge.expected.event_type)}`);
  }
  if (gt.video_available && gt.video_url) {
    const gtVideo = u.groundTruth.locator("video");
    await expect(gtVideo).toHaveAttribute("src", `${API_URL}${gt.video_url}`);
    await expect.poll(() => gtVideo.evaluate((v: HTMLVideoElement) => v.readyState), { timeout: 15_000 }).toBeGreaterThanOrEqual(1);
  }
  expect(judgeRequests.map((r) => new URL(r).pathname)).toContain("/api/judge/scenarios/eval_001");

  await page.screenshot({ path: shot(`ops-${PROFILE}-eval_001-revealed-desktop.png`), animations: "disabled" });

  // narrow: the console stacks into one scrolling column, no horizontal page scroll
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth))
    .toBeLessThanOrEqual(0);
  await page.screenshot({ path: shot(`ops-${PROFILE}-eval_001-narrow-390.png`), fullPage: true, animations: "disabled" });

  expect(consoleErrors).toEqual([]);
  saveJson(`${PROFILE}-run-timing.json`, {
    scenario_id: "eval_001",
    run_id: run.run_id,
    profile: run.profile,
    run_timeout_ms: RUN_TIMEOUT_MS,
    browser_click_to_complete_ms: clickToDoneMs,
    server_created_to_finished_ms:
      record.finished_at != null ? Date.parse(record.finished_at) - Date.parse(record.created_at) : null,
    sse_events: events.length,
    tool_calls: rows.length,
    failed_tool_calls: failedCalls,
    hypothesis: { event_type: h.event_type, region: h.region, confidence: h.confidence },
    trace_row_counts_seen: live.counts,
    seeks,
    measured_at: new Date().toISOString(),
  });
});

test("eval_012 [fixture]: a real no_event claim renders as a negative claim on its region", async ({ page, request }) => {
  const u = ui(page);
  await openOps(page, "", "fixture");
  await u.select.selectOption("eval_012");
  await expect(page).toHaveURL(/[?&]scenario=eval_012\b/);

  const { run } = await runToEnd(page);
  expect(run.profile).toBe("fixture");
  const record = await apiJson<RunRecord>(request, `/api/runs/${run.run_id}`);
  const h = record.hypothesis;
  expect(h?.event_type).toBe("no_event");
  if (!h) return;

  await expect(u.hypothesisState).toHaveAttribute("data-event-type", "no_event");
  await expect(u.hypothesisState).toHaveAttribute("data-hypothesis-state", "FINAL");
  await expect(u.hypothesisEvent).toHaveText("NO EVENT");
  await expect(u.hypothesis).toContainText("NEGATIVE CLAIM · REASONER REPORTS NO EVENT IN THE REGION BELOW");
  await expect(u.hypothesis).not.toContainText("ABSTAIN");
  await expect(u.region).toHaveText(h.region.toUpperCase());
  await expect(u.confidence).toHaveText(h.confidence.toFixed(2));
  for (const id of h.evidence_ids) await expect(u.hypothesis.locator(`[data-cited-evidence="${id}"]`)).toHaveCount(1);

  await page.screenshot({ path: shot("ops-fixture-eval_012-no-event.png"), animations: "disabled" });
});

test("eval_005 [fixture]: a real abstention renders as ABSTAIN / unknown with no claim", async ({ page, request }) => {
  const u = ui(page);
  await openOps(page, "?scenario=eval_005", "fixture");
  await expect(u.select).toHaveValue("eval_005");

  const { run } = await runToEnd(page);
  expect(run.profile).toBe("fixture");
  const record = await apiJson<RunRecord>(request, `/api/runs/${run.run_id}`);
  const h = record.hypothesis;
  expect(h?.event_type).toBe("unknown");
  if (!h) return;

  await expect(u.hypothesisState).toHaveAttribute("data-event-type", "unknown");
  await expect(u.hypothesisState).toHaveAttribute("data-hypothesis-state", "ABSTAIN · FINAL");
  await expect(u.hypothesisEvent).toHaveText("ABSTAIN — UNKNOWN");
  await expect(u.hypothesis).toContainText("INSUFFICIENT CORROBORATING EVIDENCE · NO CLAIM MADE");
  await expect(u.region).toHaveText(h.region.toUpperCase());
  await expect(u.confidence).toHaveText(h.confidence.toFixed(2));
  await expect(u.hypothesis).not.toContainText("NEGATIVE CLAIM");
  if (h.evidence_ids.length === 0) await expect(u.hypothesis).toContainText("NONE CITED");

  await page.screenshot({ path: shot("ops-fixture-eval_005-abstain.png"), animations: "disabled" });
});

test("ground-truth watcher (blank page, no API): sees a token written and overwritten in one task, not one already there", async ({
  page,
}) => {
  const gt = groundTruthTokens("eval_001");
  await page.setContent('<p id="shown">cam_gt</p><p id="idle">idle</p><p id="tag" data-camera="ground-truth"></p>');

  // values the page held when the watch began are not leaks (a reveal before arming shows them)
  let stop = await watchGroundTruth(page, gt);
  await page.evaluate(() => {
    document.getElementById("shown")!.firstChild!.textContent = "POSITION WITHHELD";
    document.getElementById("tag")!.setAttribute("data-camera", "cam_a");
  });
  expect(await stop()).toEqual([]);

  // a token on screen for less than one callback is caught through the next record's old value
  stop = await watchGroundTruth(page, gt);
  await page.evaluate(() => {
    const text = document.getElementById("idle")!.firstChild!;
    text.textContent = "cam_gt";
    text.textContent = "idle";
    const tag = document.getElementById("tag")!;
    tag.setAttribute("data-camera", "ground-truth");
    tag.setAttribute("data-camera", "cam_a");
  });
  expect(await stop()).toEqual(["text (old): …cam_gt…", '@data-camera (old): …data-camera="ground-truth"…']);
});
