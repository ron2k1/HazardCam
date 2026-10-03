/**
 * The plain-language worker view, /ops's default. Three groups:
 *
 *   - pure checks of the worker text helpers (sanitizer, camera names, progress) and the
 *     alert.message / alert.delivery reducer, imported straight from apps/web/src/lib;
 *   - the offline mock (/ops?mock=...), which needs no API;
 *   - live fixture runs, which need the backend to emit alert.message / alert.delivery.
 *
 * The worker view must never show internal ids, coordinates, bearings, scores, decimals or
 * pipeline jargon, and never anything about the withheld camera.
 */
import type { Page } from "@playwright/test";

import { API_URL } from "./env";
import {
  apiJson,
  containsGroundTruth,
  expect,
  groundTruthTokens,
  runToEnd,
  seekVia,
  shot,
  test,
  ui,
  watchGroundTruth,
  type RunRecord,
} from "./fixtures";
import { parseEnvelope, type SseEnvelope } from "../../apps/web/src/lib/contracts";
import { cameraName, cameraNames, kindWord, plainOr, plainText, recordingName, workerProgress } from "../../apps/web/src/lib/plain";
import { applyEvent, EMPTY_RUN_VIEW, replayEvents } from "../../apps/web/src/lib/run-view";

/**
 * What may not appear anywhere in the worker view: visible text, folded text (a closed
 * "Earlier heads-up"), accessible names or tooltips. Kept separate from the app's own LEAK
 * pattern on purpose, so a regression there cannot weaken this check.
 */
const BANNED = new RegExp(
  [
    String.raw`cam_|region_|blind_zone|obs_|\bz_[a-z]|\b[a-z]+_[a-z0-9_]+\b`,
    String.raw`hypothes|evidence|\bcues?\b|cluster|triangulat|abstain|\bregions?\b|\bprofile\b|\bSSE\b|harness`,
    String.raw`bearing|score|°|\b\d+\.\d+\b|\bX [+-]\d|withheld|ground truth|judge`,
    String.raw`https?:\/\/|www\.|(?:^|\s)[~\/][\w.-]+\/|\b[\w-]+\.(?:mp4|avi|env|json|ya?ml)\b|frame index|\bframe\b`,
  ].join("|"),
  "i",
);

const KINDS = ["ping", "alert", "unconfirmed", "all_clear"];
const DELIVERED = /^(sent|skipped|failed|not_connected)$/;

/**
 * Visible text, the text of every leaf element (so folded and hidden text counts too), and every
 * aria-label and title inside the worker view.
 */
async function workerText(page: Page): Promise<string> {
  const root = ui(page).worker;
  const text = await root.innerText();
  const rest = await root.evaluate((el) => {
    const leaves = [...el.querySelectorAll("*")]
      .filter((e) => e.children.length === 0 && !["SCRIPT", "STYLE"].includes(e.tagName))
      .map((e) => e.textContent ?? "");
    const attrs = [...el.querySelectorAll("[aria-label], [title]")].flatMap((e) => [
      e.getAttribute("aria-label") ?? "",
      e.getAttribute("title") ?? "",
    ]);
    return [...leaves, ...attrs].join("\n");
  });
  return `${text}\n${rest}`;
}

async function expectNoLeaks(page: Page): Promise<void> {
  const text = await workerText(page);
  const hits = text.match(new RegExp(BANNED.source, "gi")) ?? [];
  expect(hits, `technical words in the worker view:\n${text}`).toEqual([]);
}

/** Every distinct progress line from now on (proves the line follows the run live). */
async function watchProgress(page: Page): Promise<() => Promise<string[]>> {
  await page.evaluate(() => {
    const w = window as unknown as { __progress: string[] };
    w.__progress = [];
    const read = () => {
      const t = document.querySelector('[data-testid="worker-progress"] p')?.textContent ?? "";
      if (t && w.__progress[w.__progress.length - 1] !== t) w.__progress.push(t);
    };
    read();
    new MutationObserver(read).observe(document.body, { subtree: true, childList: true, characterData: true });
  });
  return () => page.evaluate(() => (window as unknown as { __progress: string[] }).__progress);
}

// ---------------------------------------------------------------------------------- pure checks

let seq = 0;
function env(type: string, payload: Record<string, unknown>, runId = "run_t"): SseEnvelope {
  seq += 1;
  const parsed = parseEnvelope(JSON.stringify({ run_id: runId, seq, ts: new Date(seq * 1000).toISOString(), type, payload }));
  if (!parsed) throw new Error(`not an envelope: ${type}`);
  return parsed;
}

const message = (id: string, kind: string, extra: Record<string, unknown> = {}) => ({
  message: {
    id,
    kind,
    level: kind === "alert" ? "danger" : "info",
    headline: `headline ${id}`,
    lines: [{ key: "what", label: "What happened", value: `value ${id}` }],
    evidence_ids: [],
    camera_ids: [],
    t_start: null,
    t_end: null,
    created_at: "2026-10-03T10:00:00Z",
    text: `text ${id}`,
    ...extra,
  },
});

test.describe("worker text and alert reducer (no page)", () => {
  test("the leak check hides sentences that still leak and never rewrites plain ones", () => {
    const leaky =
      "Evidence cam_b.o1, cam_b.o2 and cam_a.o3 converge on REGION_01 X +8.3 Y +44.6 · R 28.0M (bearing 350.3°), " +
      "clustering score (0.7656); triangulation from cam_b agrees. obs_x_7 saw it near z_north_road.";
    expect(plainText(leaky)).toBe("");
    // a leaking sentence goes whole; the plain one next to it stays exactly as written
    expect(plainText("A truck stops near the gate. Seen by cam_gt.")).toBe("A truck stops near the gate.");

    // plain text the server already wrote is left alone, character for character
    for (const plain of [
      "Likely (60%)",
      "0:07–0:27 into the clip",
      "15:41:02–15:41:27 on 15 Mar 2018",
      "In the blind spot about 30 m north of Camera B",
      "No action needed now. A supervisor can review the footage.",
      "Camera A, Camera B and Camera C",
      "Camera 1: Several visible vehicles brake abruptly. Not seen directly; pieced together from the other cameras.",
      "Vehicle turning around in the blind spot north-east of Camera C",
      "A truck turns left at the pickup/dropoff spot.",
      "10:58:33",
    ]) {
      expect(plainText(plain)).toBe(plain);
    }
    // numbers are never rounded into a different safety distance: the sentence is hidden instead
    expect(plainText("The worker is 1.5 m from the edge.")).toBe("");
    expect(plainText("Keep 0.5 m clear.")).toBe("");
    // what the leak review got through the old rewriting sanitizer
    for (const hostile of [
      "seen by cam_gt",
      "confidence=0.42 at 12.6 m",
      "obs_x_7 saw it",
      "See https://evil.example/x?t=1",
      "Saved to /home/dell/.config/cameravision/telegram.env",
      "data/prepared/eval_001/hidden_ground_truth.mp4",
      "Token 123456789:AAHfakefakefakefakefakefake",
      "camera_gt agrees",
      "cam-gt agrees",
      "Alternatives: vehicle_turn.",
      "Heading az 350.",
      "The van heads NNW.",
      "Frame index=12 shows it.",
      "[withheld] saw it.",
    ]) {
      expect(plainText(hostile), hostile).toBe("");
    }
    // headlines are all or nothing
    expect(plainOr("Vehicle stopped: Loading dock", "ALERT")).toBe("Vehicle stopped: Loading dock");
    expect(plainOr("Region 01 near cam_gt", "ALERT")).toBe("ALERT");
    // an alert that needs no action is a NOTICE, never "ALERT" next to "No rush"
    expect(kindWord({ kind: "alert", level: "info" })).toBe("NOTICE");
    expect(kindWord({ kind: "alert", level: "danger" })).toBe("ALERT");
    expect(kindWord({ kind: "ping", level: "warning" })).toBe("HEADS-UP");
  });

  test("camera names are friendly and never the raw id", () => {
    expect(cameraName("cam_b")).toBe("Camera B");
    expect(cameraName("cam_02")).toBe("Camera 2");
    expect(cameraName("CAM-3")).toBe("Camera 3");
    expect(cameraName("dock_left", 0)).toBe("Camera 1");
    expect(cameraName("warehouse_cam_east", 2)).toBe("Camera 3");
    // the API's display_name (the one the alert messages use) wins over the derived name
    const names = cameraNames([{ id: "cam_a", display_name: "Gate camera" }, { id: "cam_b", display_name: null }, { id: "x9" }]);
    expect([...names.values()]).toEqual(["Gate camera", "Camera B", "Camera 3"]);
  });

  test("recording names drop dataset codes and read the date in words", () => {
    expect(recordingName("MEVA KF1 bus station, 2018-03-07 10:58:26", 0)).toBe("Bus station, 7 Mar 2018, 10:58:26");
    // a single acronym is a real word, not a dataset code
    expect(recordingName("PPE check at dock 3", 0)).toBe("PPE check at dock 3");
    expect(recordingName("Warehouse aisle 4, 2025-11-02T08:15:00", 1)).toBe("Warehouse aisle 4, 2 Nov 2025, 08:15:00");
    expect(recordingName("  ", 2)).toBe("Recording 3");
    expect(recordingName(null, 0)).toBe("Recording 1");
  });

  test("alert.message keeps arrival order, replaces by id, drops malformed ones; alert.delivery is per message", () => {
    let v = replayEvents([env("run.started", { scenario_id: "s", profile: "fixture", camera_ids: ["cam_a"], harness: "h" })]);
    v = applyEvent(v, env("alert.message", message("msg_01", "ping")));
    v = applyEvent(v, env("alert.delivery", { message_id: "msg_01", channel: "telegram", status: "not_connected", detail: null }));
    v = applyEvent(v, env("alert.message", message("msg_02", "alert")));
    v = applyEvent(v, env("alert.message", { message: { id: "msg_03" } })); // no headline: dropped
    v = applyEvent(v, env("alert.message", { nope: true })); // no message: dropped
    v = applyEvent(v, env("alert.message", message("msg_01", "ping", { headline: "updated" })));
    v = applyEvent(v, env("alert.delivery", { message_id: "msg_02", channel: "telegram", status: "failed", detail: "x" }));
    v = applyEvent(v, env("alert.delivery", { message_id: "msg_02", channel: "telegram", status: "sent", detail: null }));
    v = applyEvent(v, env("alert.delivery", { message_id: "msg_02", status: "exploded" })); // unknown status: dropped
    expect(v.messages.map((m) => [m.id, m.kind, m.headline])).toEqual([
      ["msg_01", "ping", "updated"],
      ["msg_02", "alert", "headline msg_02"],
    ]);
    expect(Object.fromEntries(Object.entries(v.deliveries).map(([k, d]) => [k, d.status]))).toEqual({
      msg_01: "not_connected",
      msg_02: "sent",
    });
    // unknown kinds/levels read calm, never as an alarm
    v = applyEvent(v, env("alert.message", message("msg_04", "siren", { level: "purple" })));
    expect(v.messages.at(-1)).toMatchObject({ id: "msg_04", kind: "unconfirmed", level: "info" });
    // an unknown event type is not an envelope at all
    expect(parseEnvelope(JSON.stringify({ run_id: "r", seq: 99, ts: "x", type: "alert.unknown", payload: {} }))).toBeNull();
    // the next run starts with an empty feed
    v = applyEvent(v, env("run.started", { scenario_id: "s", profile: "fixture", camera_ids: ["cam_a"], harness: "h" }, "run_2"));
    expect(v.messages).toEqual([]);
    expect(v.deliveries).toEqual({});
  });

  test("the progress line follows camera and tool events in plain words", () => {
    const names = new Map([
      ["cam_a", "Camera A"],
      ["cam_b", "Camera B"],
    ]);
    expect(workerProgress(EMPTY_RUN_VIEW, names).text).toBe("Ready. Press Run to check the cameras.");
    let v = replayEvents([env("run.started", { scenario_id: "s", profile: "fixture", camera_ids: ["cam_a", "cam_b"], harness: "h" })]);
    expect(workerProgress(v, names).text).toBe("Starting…");
    v = applyEvent(v, env("tool.started", { call_id: "c1", tool: "sample_video", args_summary: null }));
    v = applyEvent(v, env("camera.started", { camera_id: "cam_b" }));
    expect(workerProgress(v, names).text).toBe("Checking Camera B…");
    v = applyEvent(v, env("camera.complete", { camera_id: "cam_b", observation_count: 0, latency_ms: 1, adapter: "fixture" }));
    v = applyEvent(v, env("tool.completed", { call_id: "c1", tool: "sample_video", ok: true, latency_ms: 1, result_summary: null }));
    expect(workerProgress(v, names)).toMatchObject({ text: "Checking the cameras… 1 of 2 done", done: 1, total: 4 });
    v = applyEvent(v, env("tool.started", { call_id: "c2", tool: "correlate_observations", args_summary: null }));
    expect(workerProgress(v, names).text).toBe("Comparing cameras…");
    v = applyEvent(v, env("tool.completed", { call_id: "c2", tool: "correlate_observations", ok: true, latency_ms: 1, result_summary: null }));
    v = applyEvent(v, env("tool.started", { call_id: "c3", tool: "reason_hypothesis", args_summary: null }));
    expect(workerProgress(v, names).text).toBe("Working out what happened…");
    v = applyEvent(v, env("run.failed", { stage: "reason_hypothesis", error: "boom" }));
    expect(workerProgress(v, names)).toMatchObject({ tone: "failed" });
    expect(workerProgress(v, names).text).not.toMatch(BANNED);
  });
});

// --------------------------------------------------------------------------- offline mock

test("worker view (mock): plain alert cards by default, no ids or jargon, no API calls", async ({ page }) => {
  const u = ui(page);
  const apiHits: string[] = [];
  page.on("request", (r) => {
    if (r.url().startsWith(API_URL)) apiHits.push(r.url());
  });
  await page.goto("/ops?mock=default");
  await expect(u.worker).toBeVisible();
  await expect(u.viewToggle).toHaveAttribute("aria-checked", "false");
  // the technical console is not mounted at all
  await expect(u.hypothesis).toHaveCount(0);
  await expect(u.groundTruth).toHaveCount(0);

  await expect(u.cards).toHaveCount(2);
  expect(await u.cards.evaluateAll((els) => els.map((e) => e.getAttribute("data-kind")))).toEqual(["ping", "alert"]);
  await expect(page.getByTestId("alert-kind")).toHaveText(["HEADS-UP", "ALERT"]);
  // alerts are on screen only: no Telegram channel is connected, so no delivery line is shown
  // (the status still rides on the card for tooling)
  expect(await u.cards.evaluateAll((els) => els.map((e) => e.getAttribute("data-delivery")))).toEqual([
    "not_connected",
    "not_connected",
  ]);
  await expect(page.getByTestId("alert-delivery")).toHaveCount(0);
  const last = u.cards.last();
  // the level follows config/alerts.yaml for the event type (contracts/examples/alert_message.json)
  await expect(last).toHaveAttribute("data-level", /^(danger|warning)$/);
  await expect(last.getByTestId("alert-level")).toHaveText(/^(Act now|Check soon)$/);
  await expect(last.locator('[data-line="how_sure"] dd')).toHaveText("Likely (74%)");
  await expect(last.locator('[data-line="seen_on"] dd')).toHaveText("Camera 1, Camera 2 and Camera 3");
  // "What to do" comes straight after the headline, before every other row
  expect(await last.locator("[data-line]").evaluateAll((els) => els.map((e) => e.getAttribute("data-line")))).toEqual([
    "what_to_do",
    "how_sure",
    "where",
    "when",
    "seen_on",
    "what",
  ]);
  // the send time is shown once, labelled, and never as a bare clock next to "When"
  await expect(last.locator("time")).toHaveText(/^Sent \d/);
  await expect(last.locator("footer")).not.toContainText(/\d:\d\d/);
  // the heads-up is answered by the alert: it goes quiet (grey, folded), never amber
  const first = u.cards.first();
  await expect(first).toHaveAttribute("data-resolved", "true");
  await expect(first.getByTestId("alert-kind")).toHaveText("HEADS-UP");
  await expect(first.getByTestId("alert-resolved")).toHaveText("Checked. See the result below.");
  await expect(first.locator(".bg-warning")).toHaveCount(0);
  await expect(first.locator("details")).not.toHaveAttribute("open", /.*/);
  await expect(last).not.toHaveAttribute("data-resolved", /./);
  // no tooltips anywhere on a card (a delivery detail is technical and may hold secrets)
  await expect(u.cards.locator("[title]")).toHaveCount(0);
  // readable: headline >= 20px, body >= 14px
  const sizes = await last.evaluate((el) => ({
    headline: parseFloat(getComputedStyle(el.querySelector("h3")!).fontSize),
    body: Math.min(...[...el.querySelectorAll("dt, dd")].map((e) => parseFloat(getComputedStyle(e).fontSize))),
  }));
  expect(sizes.headline).toBeGreaterThanOrEqual(20);
  expect(sizes.body).toBeGreaterThanOrEqual(14);
  await expectNoLeaks(page);

  // "Show on video" marks every camera the alert cites
  await last.getByTestId("show-on-video").click();
  await expect(page.locator("figure[data-highlighted]")).toHaveCount(3);
  await expect(last.getByTestId("show-on-video")).toHaveAttribute("aria-pressed", "true");
  expect(apiHits).toEqual([]);
});

test("worker view (mock): the Technical details switch flips views, lives in the URL and is remembered", async ({ page }) => {
  const u = ui(page);
  await page.goto("/ops?mock=default");
  await expect(u.worker).toBeVisible();

  await u.viewToggle.click();
  await expect(page).toHaveURL(/[?&]view=technical\b/);
  await expect(u.viewToggle).toHaveAttribute("aria-checked", "true");
  await expect(u.hypothesisState).toHaveAttribute("data-hypothesis-state", /FINAL/);
  await expect(u.worker).toHaveCount(0);

  // no ?view= on the next visit: the last choice on this browser
  await page.goto("/ops?mock=default");
  await expect(u.hypothesis).toBeVisible();
  await expect(u.viewToggle).toHaveAttribute("aria-checked", "true");

  await u.viewToggle.click();
  await expect(page).not.toHaveURL(/[?&]view=/);
  await expect(page).toHaveURL(/[?&]mock=default\b/);
  await expect(u.worker).toBeVisible();
  await page.goto("/ops?mock=default");
  await expect(u.worker).toBeVisible();

  // an explicit ?view= wins over the stored choice
  await page.goto("/ops?mock=default&view=technical");
  await expect(u.hypothesis).toBeVisible();
});

test("worker view (mock): Run streams a plain progress line and the heads-up before the alert", async ({ page }) => {
  const u = ui(page);
  await page.goto("/ops?mock=idle");
  await expect(page.getByTestId("message-empty")).toHaveText("No alerts yet. Press Run to check the cameras.");
  const progress = await watchProgress(page);
  await u.run.click();
  await expect(page.getByTestId("worker-progress")).toHaveAttribute("data-run-phase", "complete", { timeout: 20_000 });
  const lines = await progress();
  expect(lines[0]).toBe("Ready. Press Run to check the cameras.");
  expect(lines).toContain("Checking Camera 1…");
  expect(lines).toContain("Comparing cameras…");
  expect(lines.at(-1)).toBe("Done. All cameras checked.");
  for (const l of lines) expect(l).not.toMatch(BANNED);
  expect(await u.cards.evaluateAll((els) => els.map((e) => e.getAttribute("data-kind")))).toEqual(["ping", "alert"]);
  // once the run is complete the heads-up is answered: quiet, no amber edge
  await expect(u.cards.first()).toHaveAttribute("data-resolved", "true");
  await expect(u.cards.first().locator(".bg-warning")).toHaveCount(0);
  await expect(u.run).toHaveText(/RUN AGAIN/);
});

test("worker view (mock abstain): a calm COULDN'T CONFIRM card, never an alarm", async ({ page }) => {
  const u = ui(page);
  await page.goto("/ops?mock=abstain");
  const last = u.cards.last();
  await expect(last).toHaveAttribute("data-kind", "unconfirmed");
  await expect(last).toHaveAttribute("data-level", "info");
  await expect(last.getByTestId("alert-kind")).toHaveText("COULDN'T CONFIRM");
  await expect(last.locator('[data-line="what_to_do"] dd')).toHaveText("No action needed now. A supervisor can review the footage.");
  // an unconfirmed result is not offered to Telegram, so it carries no delivery status
  await expect(page.getByTestId("worker-progress")).toHaveAttribute("data-run-phase", "complete");
  await expect(last).not.toHaveAttribute("data-delivery", /./);
  await expect(page.getByTestId("alert-delivery")).toHaveCount(0);
  await expect(page.locator('[data-testid="alert-card"][data-level="danger"]')).toHaveCount(0);
  // calm overall: the earlier heads-up is answered and grey, and a calm card shows no urgency word
  await expect(u.cards.first()).toHaveAttribute("data-resolved", "true");
  await expect(page.locator('[data-testid="alert-card"] .bg-warning, [data-testid="alert-card"] .bg-danger')).toHaveCount(0);
  await expect(last.getByTestId("alert-level")).toHaveCount(0);
  await expect(last.locator('[data-line="what_to_do"]')).toBeVisible();
  await expectNoLeaks(page);
});

test("worker view (mock) at 390 px: one column, no horizontal scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/ops?mock=default");
  await expect(ui(page).cards).toHaveCount(2);
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth))
    .toBeLessThanOrEqual(0);
  await expect(ui(page).run).toBeVisible();
  await expectNoLeaks(page);
});

// -------------------------------------------------------------------------- live (fixture)

/** /ops in the worker view (the default) once the API answered and `scenarioId` is selected. */
async function openWorker(page: Page, scenarioId: string): Promise<void> {
  await page.goto(`/ops?scenario=${scenarioId}`);
  await expect(ui(page).worker).toBeVisible();
  await expect(page.getByTestId("worker-recording")).toHaveValue(scenarioId);
  await expect(ui(page).run).toBeEnabled();
}

/**
 * Heads-ups and alerts got their delivery status before the run ended (the stream closes on
 * run.complete); COULDN'T CONFIRM and ALL CLEAR are never offered to Telegram and carry none.
 * With no channel connected (this build) the status is not_connected and no line is shown.
 */
async function expectDelivered(page: Page): Promise<void> {
  const cards = ui(page).cards;
  const n = await cards.count();
  for (let i = 0; i < n; i++) {
    const card = cards.nth(i);
    const kind = (await card.getAttribute("data-kind")) ?? "";
    if (kind === "ping" || kind === "alert") {
      await expect(card, `${kind} card ${i}`).toHaveAttribute("data-delivery", DELIVERED);
      const status = (await card.getAttribute("data-delivery")) ?? "";
      const shown = status === "sent" || status === "failed" ? 1 : 0;
      await expect(card.getByTestId("alert-delivery"), `${kind} card ${i} delivery line`).toHaveCount(shown);
    } else {
      await expect(card, `${kind} card ${i}`).not.toHaveAttribute("data-delivery", /./);
      await expect(card.getByTestId("alert-delivery"), `${kind} card ${i}`).toHaveCount(0);
    }
  }
}

test("eval_001 worker view [fixture]: a plain alert card, Show on video seeks, nothing technical or withheld", async ({
  page,
  request,
}) => {
  const u = ui(page);
  const judgeRequests: string[] = [];
  page.on("request", (r) => {
    if (new URL(r.url()).pathname.startsWith("/api/judge/")) judgeRequests.push(r.url());
  });
  await openWorker(page, "eval_001");
  await expect(page.getByTestId("message-empty")).toHaveText("No alerts yet. Press Run to check the cameras.");
  const gtTokens = groundTruthTokens("eval_001");
  const stopGtWatch = await watchGroundTruth(page, gtTokens, { checkPage: true });
  const progress = await watchProgress(page);

  const { run } = await runToEnd(page);
  expect(run.profile).toBe("fixture");
  const record = await apiJson<RunRecord>(request, `/api/runs/${run.run_id}`);
  expect(record.hypothesis?.event_type, "the recorded eval_001 hypothesis is a claim").not.toBe("unknown");

  // the backend's messages, in the order sent: at most one heads-up, then the final message
  await expect(u.cards.first()).toBeVisible();
  const kinds = await u.cards.evaluateAll((els) => els.map((e) => e.getAttribute("data-kind") ?? ""));
  for (const k of kinds) expect(KINDS).toContain(k);
  expect(kinds.filter((k) => k === "ping").length, "heads-ups per run").toBeLessThanOrEqual(1);
  expect(["alert", "unconfirmed"], `final message kind of a claim (${kinds.join(",")})`).toContain(kinds.at(-1));
  if (kinds.includes("ping")) {
    expect(kinds[0]).toBe("ping");
    await expect(u.cards.first(), "the answered heads-up goes quiet").toHaveAttribute("data-resolved", "true");
  }
  await expectDelivered(page);

  const lines = await progress();
  expect(lines.some((l) => /^Checking Camera /.test(l)), `progress: ${lines.join(" | ")}`).toBe(true);
  expect(lines.at(-1)).toBe("Done. All cameras checked.");
  await expectNoLeaks(page);

  // "Show on video" on the final card moves the cited camera's video to the cited moment
  const show = u.cards.last().getByTestId("show-on-video");
  await expect(show, "the final alert cites something to show").toHaveCount(1);
  const cameraId = (await show.getAttribute("data-seek-camera")) ?? "";
  const target = Number(await show.getAttribute("data-seek-t"));
  expect(Number.isFinite(target)).toBe(true);
  const landed = await seekVia(u.video(cameraId), target, () => show.click());
  expect(Math.abs(landed - target), `Show on video -> ${target}s, landed ${landed}s`).toBeLessThan(0.25);
  await expect(page.locator(`figure[data-camera-id="${cameraId}"]`)).toHaveAttribute("data-highlighted", "true");

  await page.screenshot({ path: shot("ops-worker-fixture-eval_001-desktop.png"), animations: "disabled" });

  // the worker view never asks the judge and never shows the withheld camera
  expect(judgeRequests).toEqual([]);
  expect(await stopGtWatch(), "ground-truth tokens in the worker view").toEqual([]);
  expect(containsGroundTruth(await page.content(), gtTokens)).toBe(false);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth))
    .toBeLessThanOrEqual(0);
  await page.screenshot({ path: shot("ops-worker-fixture-eval_001-narrow-390.png"), fullPage: true, animations: "disabled" });
});

test("eval_005 worker view [fixture]: the abstention reads COULDN'T CONFIRM with no action needed", async ({ page }) => {
  const u = ui(page);
  await openWorker(page, "eval_005");
  await runToEnd(page);
  const last = u.cards.last();
  await expect(last).toHaveAttribute("data-kind", "unconfirmed");
  await expect(last).not.toHaveAttribute("data-level", "danger");
  await expect(last.getByTestId("alert-kind")).toHaveText("COULDN'T CONFIRM");
  await expect(last.locator('[data-line="what_to_do"] dd')).toHaveText("No action needed now. A supervisor can review the footage.");
  await expectDelivered(page);
  await expectNoLeaks(page);
  await page.screenshot({ path: shot("ops-worker-fixture-eval_005-unconfirmed.png"), animations: "disabled" });
});

test("eval_012 worker view [fixture]: no_event reads ALL CLEAR with nothing to do", async ({ page }) => {
  const u = ui(page);
  await openWorker(page, "eval_012");
  await runToEnd(page);
  const last = u.cards.last();
  await expect(last).toHaveAttribute("data-kind", "all_clear");
  await expect(last.getByTestId("alert-kind")).toHaveText("ALL CLEAR");
  await expect(last.locator('[data-line="what_to_do"] dd')).toHaveText("Nothing to do.");
  await expectDelivered(page);
  await expectNoLeaks(page);
});
