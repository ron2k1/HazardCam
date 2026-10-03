// Demo recording: home wall -> hazard reasoning tab -> /hazards -> blind spot -> reasoning -> wall.
// Live API (replay mode) + dev web app only. No mock, nothing injected except a visible cursor dot.
import { chromium } from "/home/dell/ambient-urban-mirror/apps/web/node_modules/@playwright/test/index.mjs";
import { mkdirSync, writeFileSync, renameSync } from "node:fs";

const WEB = "http://127.0.0.1:3000";
const OUT = "/home/dell/ambient-urban-mirror/artifacts/hazards/demo";
const RAW = OUT + "/raw";
mkdirSync(RAW, { recursive: true });
const SIZE = { width: 1920, height: 1080 };
const CAP_S = 122; // aim under the 2:05 hard cap

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: SIZE, recordVideo: { dir: RAW, size: SIZE } });
// visible cursor (headless video has none); pointer-events none, no page data touched
await ctx.addInitScript(() => {
  const mk = () => {
    if (document.getElementById("__demo_cursor")) return;
    const c = document.createElement("div");
    c.id = "__demo_cursor";
    c.innerHTML =
      '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M3 2l7 19 2.5-7.5L20 11z" fill="#f4f1ea" stroke="#050505" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, { position: "fixed", left: "0", top: "0", zIndex: "2147483647", pointerEvents: "none", transform: "translate(-100px,-100px)", transition: "none" });
    const ring = document.createElement("div");
    ring.id = "__demo_ring";
    Object.assign(ring.style, { position: "fixed", left: "0", top: "0", width: "34px", height: "34px", marginLeft: "-17px", marginTop: "-17px", border: "2px solid #f4f1ea", zIndex: "2147483646", pointerEvents: "none", opacity: "0", transition: "opacity 300ms, transform 300ms" });
    document.documentElement.appendChild(ring);
    document.documentElement.appendChild(c);
    const pos = window.__demo_pos || [-100, -100];
    c.style.transform = `translate(${pos[0] - 3}px,${pos[1] - 2}px)`;
  };
  document.addEventListener("mousemove", (e) => {
    mk();
    window.__demo_pos = [e.clientX, e.clientY];
    const c = document.getElementById("__demo_cursor");
    c.style.transform = `translate(${e.clientX - 3}px,${e.clientY - 2}px)`;
  }, true);
  document.addEventListener("mousedown", (e) => {
    mk();
    const r = document.getElementById("__demo_ring");
    r.style.transition = "none";
    r.style.left = e.clientX + "px";
    r.style.top = e.clientY + "px";
    r.style.opacity = "0.9";
    r.style.transform = "scale(0.6)";
    requestAnimationFrame(() => { r.style.transition = "opacity 450ms, transform 450ms"; r.style.opacity = "0"; r.style.transform = "scale(1.4)"; });
  }, true);
  if (document.readyState !== "loading") mk(); else document.addEventListener("DOMContentLoaded", mk);
});

const starts = new Map();
ctx.on("page", (p) => starts.set(p, Date.now()));
const page = await ctx.newPage();
const T0 = starts.get(page) ?? Date.now();
const g = () => +((Date.now() - T0) / 1000).toFixed(2); // global == final timeline (tabs replace concurrent main time)
const marks = {};
const mark = (k) => { marks[k] = g(); console.log(k, marks[k]); };
const errors = [];
const watch = (p, name) => p.on("console", (m) => m.type() === "error" && errors.push(`${name}: ${m.text().slice(0, 160)}`));
watch(page, "main");
const pause = (p, ms) => p.waitForTimeout(ms);
const cur = new Map();
async function glide(p, x, y, ms = 900) {
  const [x0, y0] = cur.get(p) ?? [960, 540];
  const steps = Math.max(8, Math.round(ms / 25));
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    const e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
    await p.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e);
    await p.waitForTimeout(ms / steps);
  }
  cur.set(p, [x, y]);
}
async function glideTo(p, loc, ms = 900, dx = 0.5, dy = 0.5) {
  await loc.scrollIntoViewIfNeeded().catch(() => {});
  const b = await loc.boundingBox();
  if (!b) throw new Error("no box");
  await glide(p, b.x + b.width * dx, b.y + b.height * dy, ms);
  return b;
}
async function wheel(p, total, ms) {
  const n = Math.max(1, Math.round(ms / 60));
  for (let i = 0; i < n; i++) { await p.mouse.wheel(0, total / n); await p.waitForTimeout(ms / n); }
}
async function openTab(p, loc) {
  await glideTo(p, loc, 800);
  await pause(p, 500);
  const [tab] = await Promise.all([ctx.waitForEvent("page"), loc.click()]);
  watch(tab, "tab");
  return tab;
}
const segs = []; // {src:'main'|tab index, from_g, to_g}
const tabs = [];

// ---------- 1. Home wall ----------
await page.goto(WEB + "/", { waitUntil: "domcontentloaded" });
await glide(page, 980, 560, 600);
mark("wall_open");
const tiles = page.locator("[data-testid=cctv-tile]");
await tiles.first().waitFor({ timeout: 20000 });
let firstPop = null;
let lastPhaseLog = "";
const tour = [[420, 330], [960, 330], [1480, 330], [420, 760], [960, 760], [1480, 760]];
let ti = 0;
let nextMove = 0;
while (g() < 28) {
  const pops = await page.locator("[data-testid=detection-popout]").count();
  if (pops && firstPop == null) { firstPop = g(); mark("first_popout"); }
  const phases = await page.$$eval("[data-testid=tile-readout]", (els) => els.map((e) => e.getAttribute("data-phase")));
  const done = phases.filter((x) => x === "found" || x === "clear" || x === "failed").length;
  const s = phases.join(",");
  if (s !== lastPhaseLog) { console.log(g(), s); lastPhaseLog = s; }
  if (done >= 6 && g() >= 23) { mark("all_done"); break; }
  if (firstPop != null && g() - firstPop < 2.5) { await pause(page, 300); continue; } // hold on the first big pop-out
  if (g() >= nextMove) {
    const [x, y] = tour[ti++ % tour.length];
    const box = await tiles.nth((ti - 1) % 6).boundingBox().catch(() => null);
    if (box) await glide(page, box.x + box.width * 0.55, box.y + box.height * 0.45, 1400); else await glide(page, x, y, 1400);
    nextMove = g() + 2.2;
  }
  await pause(page, 300);
}
mark("wall_end");

// close any open pop-out so the tray is clear (a user click)
for (const d of await page.locator("[data-testid=popout-dismiss]").all()) {
  if (await d.isVisible().catch(() => false)) { await glideTo(page, d, 500); await d.click().catch(() => {}); await pause(page, 300); }
}

// ---------- 2. Hazard notification -> Open reasoning (new tab) ----------
const hzSel = ["1", "2", "3"].map((c) => `[data-testid=wall-notification][data-cam="${c}"]`).join(",");
const hzNote = page.locator(`[data-testid=wall-notification][data-cam="1"]`).count().then((n) => (n ? page.locator(`[data-testid=wall-notification][data-cam="1"]`).first() : page.locator(hzSel).first()));
const note = await hzNote;
await note.waitFor({ timeout: 15000 });
const hzCam = await note.getAttribute("data-cam");
await glideTo(page, note, 900, 0.5, 0.35);
await pause(page, 1200);
const tabA = await openTab(page, note.locator("[data-testid=notification-reasoning]"));
await tabA.waitForSelector("[data-testid=process-app]", { timeout: 20000 });
await tabA.waitForTimeout(700);
const aIn = g();
mark("reasoning_tab_open");
await glide(tabA, 900, 450, 700);
await pause(tabA, 2500);
await wheel(tabA, 900, 4500);
await pause(tabA, 1500);
await wheel(tabA, 1300, 5000);
await pause(tabA, 2000);
const aOut = g();
mark("reasoning_tab_close");
tabs.push({ page: tabA, start: starts.get(tabA), in: aIn, out: aOut });
await tabA.close();
await pause(page, 600);

// ---------- 3. View the hazard on /hazards ----------
await glideTo(page, note.locator("[data-testid=notification-view]"), 900);
await pause(page, 500);
await note.locator("[data-testid=notification-view]").click();
await page.waitForURL(/\/hazards\?/, { timeout: 15000 });
const hzUrl = page.url();
await page.locator("[data-testid=hazard-card]").first().waitFor({ timeout: 20000 });
mark("hazards_open");
await pause(page, 1500);
const pin = page.locator("[data-testid=hazard-pin]").first();
if (await pin.count()) { await glideTo(page, pin, 1100); mark("hazard_pins"); await pause(page, 2600); }
// scroll through hazard cards
const cards = page.locator("[data-testid=hazard-card]");
const nCards = await cards.count();
await glideTo(page, cards.first(), 900, 0.5, 0.3);
await pause(page, 1500);
for (let i = 1; i < Math.min(nCards, 4); i++) {
  await wheel(page, 380, 1300);
  await pause(page, 900);
}
await cards.first().scrollIntoViewIfNeeded();
await pause(page, 600);
const show = cards.first().locator("[data-testid=show-on-video]");
await glideTo(page, show, 900);
await pause(page, 500);
await show.click();
mark("show_on_video");
await pause(page, 1400);
const vid = page.locator("[data-testid=evidence-video]");
await glideTo(page, vid, 900, 0.5, 0.5);
await page.evaluate(() => { const v = document.querySelector("[data-testid=evidence-video]"); if (v) { v.muted = true; v.play().catch(() => {}); } });
mark("video_play");
await pause(page, 4500);
await page.evaluate(() => document.querySelector("[data-testid=evidence-video]")?.pause());
const gallery = page.locator("[data-testid=picture-gallery] [data-testid=picture]");
const nPics = await gallery.count();
const pics = nPics ? gallery : page.locator("[data-testid=picture]");
const picCount = await pics.count();
for (const idx of [Math.min(2, picCount - 1), Math.min(7, picCount - 1)]) {
  if (idx < 0) break;
  const pic = pics.nth(idx);
  await glideTo(page, pic, 1000);
  await pause(page, 500);
  await pic.click();
  mark(`picture_${idx}`);
  await pause(page, 2200);
  if (await page.locator("[data-testid=lightbox]").isVisible().catch(() => false)) {
    await page.locator("[data-testid=lightbox-close]").click();
    await pause(page, 500);
  }
}
mark("hazards_end");

// ---------- 4. Back to the wall -> blind-spot View ----------
await page.goto(WEB + "/", { waitUntil: "domcontentloaded" });
await glide(page, 960, 700, 500);
mark("wall2_open");
const bsSel = ["4", "5", "6"].map((c) => `[data-testid=wall-notification][data-cam="${c}"]`).join(",");
const bsNote = page.locator(bsSel).first();
let k = 0;
while (!(await bsNote.count()) && g() < marks.wall2_open + 30) {
  const box = await tiles.nth(3 + (k++ % 3)).boundingBox().catch(() => null);
  if (box) await glide(page, box.x + box.width * 0.5, box.y + box.height * 0.45, 1300);
  await pause(page, 700);
}
await bsNote.waitFor({ timeout: 10000 });
for (const d of await page.locator("[data-testid=popout-dismiss]").all()) {
  if (await d.isVisible().catch(() => false)) { await glideTo(page, d, 500); await d.click().catch(() => {}); await pause(page, 300); }
}
const bsCam = await bsNote.getAttribute("data-cam");
await glideTo(page, bsNote, 900, 0.5, 0.35);
await pause(page, 1000);
const bsView = bsNote.locator("[data-testid=notification-view]");
await glideTo(page, bsView, 700);
await pause(page, 400);
await bsView.click();
await page.waitForURL(/\/hazards\?/, { timeout: 15000 });
const bsUrl = page.url();
await page.locator("[data-testid=evidence-video], [data-testid=hazard-card]").first().waitFor({ timeout: 20000 });
mark("blindspot_open");
await pause(page, 1200);
await glideTo(page, page.locator("[data-testid=evidence-video]"), 900);
await pause(page, 2500);
const bsCard = page.locator("[data-testid=hazard-card]").first();
if (await bsCard.count()) { await glideTo(page, bsCard, 900, 0.5, 0.3); await pause(page, 1800); }
const bsPics = page.locator("[data-testid=picture-gallery]");
if (await bsPics.count()) { await glideTo(page, bsPics.first(), 1000, 0.5, 0.2); await pause(page, 2200); }
const reason = page.locator("[data-testid=open-reasoning]").first();
const tabB = await openTab(page, reason);
await tabB.waitForSelector("[data-testid=process-app]", { timeout: 20000 });
await tabB.waitForTimeout(700);
const bIn = g();
mark("bs_reasoning_open");
await glide(tabB, 900, 450, 600);
await pause(tabB, 1800);
await wheel(tabB, 1100, 4200);
await pause(tabB, 1500);
const bOut = g();
mark("bs_reasoning_close");
tabs.push({ page: tabB, start: starts.get(tabB), in: bIn, out: bOut });
await tabB.close();
await pause(page, 500);

// ---------- 5. End on the wall ----------
await page.goto(WEB + "/", { waitUntil: "domcontentloaded" });
await glide(page, 960, 560, 700);
mark("wall_final");
const endHold = Math.max(3000, Math.min(7000, (CAP_S - g()) * 1000));
await pause(page, endHold);
mark("end");

const mainVideo = page.video();
await ctx.close();
await browser.close();
const mainPath = await mainVideo.path();
renameSync(mainPath, RAW + "/main_raw.webm");
const tabInfo = [];
for (const [i, t] of tabs.entries()) {
  const p = await t.page.video().path();
  const dest = `${RAW}/tab${i + 1}_raw.webm`;
  renameSync(p, dest);
  tabInfo.push({ file: dest, offset_s: +((t.start - T0) / 1000).toFixed(3), in: t.in, out: t.out });
}
const info = { marks, hzCam, bsCam, hzUrl, bsUrl, main: RAW + "/main_raw.webm", tabs: tabInfo, errors: errors.slice(0, 20) };
writeFileSync(OUT + "/recording.json", JSON.stringify(info, null, 1));
console.log(JSON.stringify(info, null, 1));
