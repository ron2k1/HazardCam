#!/usr/bin/env node
/**
 * Record the /ops beat of the demo video: one real run through the running API, filmed in a
 * headless browser. Nothing is staged in the page. The run is whatever the API and the models
 * return, the browser only clicks Run and, after the run, the "Technical details" switch.
 *
 *   node scripts/demo/record_ops_beat.mjs [--scenario eval_001] [--profile gb10] [--force]
 *
 * Refuses to start while the local vLLM server has requests running or waiting (a shared GPU
 * turned a 37 s run into 155 s in D03) unless --force. Samples the vLLM queue every 2 s during
 * the run, scans the final worker view with the e2e leak pattern, and writes to OUT_DIR
 * (artifacts/event_day/d04/ops_beat): ops_beat_raw.webm, ops_beat.json (run id, profile,
 * timing marks in video seconds, vLLM samples, leak hits, final run record).
 *
 * Env: WEB_BASE_URL (http://127.0.0.1:3000), API_BASE_URL (http://127.0.0.1:8088),
 * QWEN_BASE_URL (http://127.0.0.1:8000/v1), OUT_DIR, RUN_TIMEOUT_S (420).
 */
import { mkdirSync, renameSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
// Playwright lives in the web app's node_modules
const { chromium } = createRequire(join(REPO, "apps/web/package.json"))("@playwright/test");

const { values: args } = parseArgs({
  options: {
    scenario: { type: "string", default: "eval_001" },
    profile: { type: "string", default: "gb10" },
    force: { type: "boolean", default: false },
  },
});
const WEB = process.env.WEB_BASE_URL ?? "http://127.0.0.1:3000";
const API = process.env.API_BASE_URL ?? "http://127.0.0.1:8088";
const QWEN = process.env.QWEN_BASE_URL ?? "http://127.0.0.1:8000/v1";
const OUT = resolve(process.env.OUT_DIR ?? join(REPO, "artifacts/event_day/d04/ops_beat"));
const RUN_TIMEOUT_MS = Number(process.env.RUN_TIMEOUT_S ?? 420) * 1000;
const SIZE = { width: 1600, height: 900 };

// tests/e2e/ops-worker.spec.ts BANNED, copied so the recording is checked the same way
const BANNED = new RegExp(
  [
    String.raw`cam_|region_|blind_zone|obs_|\bz_[a-z]|\b[a-z]+_[a-z0-9_]+\b`,
    String.raw`hypothes|evidence|\bcues?\b|cluster|triangulat|abstain|\bregions?\b|\bprofile\b|\bSSE\b|harness`,
    String.raw`bearing|score|°|\b\d+\.\d+\b|\bX [+-]\d|withheld|ground truth|judge`,
    String.raw`https?:\/\/|www\.|(?:^|\s)[~\/][\w.-]+\/|\b[\w-]+\.(?:mp4|avi|env|json|ya?ml)\b|frame index|\bframe\b`,
  ].join("|"),
  "gi",
);

async function vllmQueue() {
  const res = await fetch(QWEN.replace(/\/v1\/?$/, "") + "/metrics", { signal: AbortSignal.timeout(3000) });
  const text = await res.text();
  const read = (name) => {
    const line = text.split("\n").find((l) => l.startsWith(`vllm:${name}{`));
    return line ? Number(line.split(" ").pop()) : null;
  };
  return { running: read("num_requests_running"), waiting: read("num_requests_waiting") };
}

const before = await vllmQueue();
if ((before.running || before.waiting) && !args.force) {
  console.error(`vLLM busy (${before.running} running, ${before.waiting} waiting); retry when idle or pass --force`);
  process.exit(3);
}

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: SIZE, recordVideo: { dir: OUT, size: SIZE } });
const page = await context.newPage();
const t0 = Date.now(); // the video starts with the page
const at = () => +((Date.now() - t0) / 1000).toFixed(2);
const marks = {};
const samples = [];
let sampling = null;
let run = null;
let phase = null;
let hits = [];
let workerText = "";

try {
  await page.goto(`${WEB}/ops?profile=${encodeURIComponent(args.profile)}&scenario=${encodeURIComponent(args.scenario)}`, {
    waitUntil: "networkidle",
    timeout: 90_000,
  });
  const runButton = page.getByTestId("run-button");
  await runButton.waitFor({ state: "visible" });
  await page.waitForFunction(() => !document.querySelector('[data-testid="run-button"]')?.hasAttribute("disabled"));
  marks.page_ready = at();
  await page.waitForTimeout(2500);

  const posted = page.waitForResponse((r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/runs");
  sampling = setInterval(async () => {
    try {
      samples.push({ t: at(), ...(await vllmQueue()) });
    } catch {
      samples.push({ t: at(), error: true });
    }
  }, 2000);
  marks.run_clicked = at();
  await runButton.click();
  const res = await posted;
  if (res.status() !== 202) throw new Error(`POST /api/runs answered ${res.status()}: ${await res.text()}`);
  run = await res.json();
  if (run.profile !== args.profile) throw new Error(`run started on profile ${run.profile}, not ${args.profile}`);
  console.log(`run ${run.run_id} (${run.profile}, ${run.scenario_id ?? args.scenario}) started`);

  page
    .getByTestId("alert-card")
    .first()
    .waitFor({ timeout: RUN_TIMEOUT_MS })
    .then(() => (marks.first_card = at()))
    .catch(() => {});
  const ended = await page.waitForFunction(
    (runId) => {
      const p = document.querySelector(`[data-run-id="${CSS.escape(runId)}"]`)?.getAttribute("data-run-phase");
      return p === "complete" || p === "failed" ? p : null;
    },
    run.run_id,
    { polling: "raf", timeout: RUN_TIMEOUT_MS },
  );
  phase = await ended.jsonValue();
  marks.run_ended = at();
  clearInterval(sampling);
  sampling = null;
  console.log(`run ${run.run_id} ended ${phase} after ${(marks.run_ended - marks.run_clicked).toFixed(1)} s`);

  // let the final message settle on screen, then check the worker view as the e2e spec does
  await page.waitForTimeout(6000);
  const worker = page.getByTestId("worker-view");
  workerText = await worker.innerText();
  const rest = await worker.evaluate((el) =>
    [
      ...[...el.querySelectorAll("*")]
        .filter((e) => e.children.length === 0 && !["SCRIPT", "STYLE"].includes(e.tagName))
        .map((e) => e.textContent ?? ""),
      ...[...el.querySelectorAll("[aria-label], [title]")].flatMap((e) => [e.getAttribute("aria-label") ?? "", e.getAttribute("title") ?? ""]),
    ].join("\n"),
  );
  hits = [...new Set(`${workerText}\n${rest}`.match(BANNED) ?? [])];
  marks.worker_shown = at();

  // the judge beat: the technical console with the agent trace and the stack health
  await page.getByRole("switch", { name: "Technical details" }).click();
  marks.technical_on = at();
  await page.waitForTimeout(9000);
  marks.end = at();
} finally {
  if (sampling) clearInterval(sampling);
  const video = page.video();
  await context.close();
  await browser.close();
  if (video) renameSync(await video.path(), join(OUT, "ops_beat_raw.webm"));
}

const record = run ? await (await fetch(`${API}/api/runs/${run.run_id}`)).json() : null;
const doc = {
  recorded_at: new Date(t0).toISOString(),
  web: WEB,
  api: API,
  scenario: args.scenario,
  profile: args.profile,
  run_id: run?.run_id ?? null,
  phase,
  click_to_end_s: marks.run_ended != null ? +(marks.run_ended - marks.run_clicked).toFixed(2) : null,
  marks_video_s: marks,
  vllm_before: before,
  vllm_samples: samples,
  vllm_max_running: Math.max(0, ...samples.map((s) => s.running ?? 0)),
  vllm_max_waiting: Math.max(0, ...samples.map((s) => s.waiting ?? 0)),
  worker_leak_hits: hits,
  worker_text: workerText,
  run_record: record,
};
writeFileSync(join(OUT, "ops_beat.json"), JSON.stringify(doc, null, 2) + "\n");
console.log(JSON.stringify({ run_id: doc.run_id, phase, click_to_end_s: doc.click_to_end_s, marks, leaks: hits, vllm_max_running: doc.vllm_max_running }));
process.exit(phase === "complete" && hits.length === 0 ? 0 : 1);
