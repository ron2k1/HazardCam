// Real-browser screenshots of the built app. Expects `next start` already listening.
//   node scripts/screenshots.mjs [baseUrl]
// Writes PNGs + report.json to ../../design/screenshots/. Exits 1 on console/page errors,
// any failed request, or any request that leaves the app origin.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = join(here, "..", "..", "..", "design", "screenshots");
const base = (process.argv[2] ?? "http://127.0.0.1:3000").replace(/\/+$/, "");
const origin = new URL(base).origin;
mkdirSync(outDir, { recursive: true });

const report = { base, shots: [], consoleErrors: [], pageErrors: [], external: [], failed: [], prefetchCancelled: [], checks: {} };

async function open(browser, path, { width = 1440, height = 900, reducedMotion = "no-preference" } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height }, reducedMotion, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  page.on("console", (m) => {
    if (m.type() === "error") report.consoleErrors.push({ path, text: m.text() });
  });
  page.on("pageerror", (e) => report.pageErrors.push({ path, text: String(e) }));
  page.on("request", (r) => {
    const u = r.url();
    if (!u.startsWith(origin) && !u.startsWith("data:") && !u.startsWith("blob:")) report.external.push({ path, url: u });
  });
  page.on("requestfailed", (r) => {
    const entry = { path, url: r.url(), err: r.failure()?.errorText };
    // For a dynamic route Next sends a route-tree prefetch and a full prefetch together and
    // cancels the full one when the tree lands first. That abort is the page's own; anything
    // else that fails is a real failure.
    const cancelledPrefetch =
      entry.err === "net::ERR_ABORTED" && entry.url.startsWith(origin) && r.headers()["next-router-prefetch"] === "1";
    (cancelledPrefetch ? report.prefetchCancelled : report.failed).push(entry);
  });
  await page.goto(base + path, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(1400);
  return { ctx, page };
}

async function shot(page, name) {
  const file = join(outDir, `${name}.png`);
  await page.screenshot({ path: file });
  report.shots.push(file);
  return file;
}

const browser = await chromium.launch();
try {
  // landing
  {
    const { ctx, page } = await open(browser, "/");
    await shot(page, "landing-1440x900");
    report.checks.landingHeadline = (await page.locator("h1").innerText()).replace(/\s+/g, " ").trim();
    report.checks.enterSystemHref = await page.getByRole("link", { name: "ENTER SYSTEM" }).getAttribute("href");
    await ctx.close();
  }
  // ops, default (complete fixture replay)
  {
    const { ctx, page } = await open(browser, "/ops");
    await shot(page, "ops-1440x900");
    report.checks.cameraTiles = await page.locator("[data-testid=camera-grid] figure").count();
    report.checks.gtLabel = await page.getByText("JUDGE GROUND TRUTH — NOT MODEL INPUT").count();
    report.checks.harnessLabel = await page.getByText("DEV SEQUENCE · NON-AGENT").count();
    report.checks.traceRows = await page.locator("li[data-status]").count();
    report.checks.hypothesisState = await page.locator("[data-hypothesis-state]").getAttribute("data-hypothesis-state");

    // evidence click -> camera seek highlight
    await page.locator("[data-evidence-id=obs_b_001]").click();
    await page.waitForTimeout(500);
    report.checks.seekHighlightsCam02 = await page
      .locator("figure[aria-label='cam_02 input camera']")
      .evaluate((el) => el.className.includes("border-fg/80"));
    await shot(page, "ops-evidence-selected-1440x900");

    // judge reveal
    await page.getByRole("button", { name: "REVEAL FOR JUDGE" }).click();
    await page.waitForTimeout(600);
    report.checks.gtRevealed = await page.locator("figure[data-state=revealed]").count();
    await shot(page, "ops-gt-revealed-1440x900");

    // re-run: mid-stream state
    await page.getByTestId("run-button").click();
    await page.waitForTimeout(2200);
    report.checks.midRunPhase = await page.locator("[data-run-phase]").getAttribute("data-run-phase");
    await shot(page, "ops-midrun-1440x900");
    await page.waitForTimeout(6500);
    report.checks.afterRunPhase = await page.locator("[data-run-phase]").getAttribute("data-run-phase");
    await ctx.close();
  }
  // abstain + idle variants
  for (const [q, name] of [
    ["abstain", "ops-abstain-1440x900"],
    ["idle", "ops-idle-1440x900"],
  ]) {
    const { ctx, page } = await open(browser, `/ops?mock=${q}`);
    await shot(page, name);
    await ctx.close();
  }
  // other desktop sizes
  for (const [w, h] of [
    [1920, 1080],
    [1280, 800],
  ]) {
    const { ctx, page } = await open(browser, "/ops", { width: w, height: h });
    await shot(page, `ops-${w}x${h}`);
    report.checks[`overflowX_${w}`] = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    await ctx.close();
    const l = await open(browser, "/", { width: w, height: h });
    await shot(l.page, `landing-${w}x${h}`);
    await l.ctx.close();
  }
  // reduced motion
  for (const path of ["/", "/ops"]) {
    const { ctx, page } = await open(browser, path, { reducedMotion: "reduce" });
    report.checks[`reducedMotionMatches${path === "/" ? "Landing" : "Ops"}`] = await page.evaluate(
      () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    );
    report.checks[`smilAnimations${path === "/" ? "Landing" : "Ops"}Reduced`] = await page.evaluate(
      () => document.querySelectorAll("animate, animateTransform").length,
    );
    await shot(page, `${path === "/" ? "landing" : "ops"}-reduced-motion-1440x900`);
    await ctx.close();
  }
  {
    const { ctx, page } = await open(browser, "/");
    report.checks.smilAnimationsLandingFull = await page.evaluate(() => document.querySelectorAll("animate, animateTransform").length);
    await ctx.close();
  }
} finally {
  await browser.close();
}

writeFileSync(join(outDir, "report.json"), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
const bad = report.consoleErrors.length + report.pageErrors.length + report.external.length + report.failed.length;
process.exit(bad ? 1 : 0);
