// Copy the contracts/examples files that src/mocks/mock.ts imports into
// src/mocks/contract-examples/ so the web app can render standalone (Turbopack does not
// import files outside the app root). Anything else in the destination is removed.
// Run after the contract examples change: `node scripts/sync-contract-examples.mjs`.
import { copyFileSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// keep in step with the imports in src/mocks/mock.ts
const USED = [
  "alert_delivery.json",
  "alert_message.json",
  "alert_message_ping.json",
  "alert_message_unconfirmed.json",
  "evidence_bundle.json",
  "hypothesis.json",
  "hypothesis_abstain.json",
  "run.json",
  "scenario_001.json",
];

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "..", "..", "..", "contracts", "examples");
const dst = join(here, "..", "src", "mocks", "contract-examples");

mkdirSync(dst, { recursive: true });
for (const f of USED) copyFileSync(join(src, f), join(dst, f));
const stale = readdirSync(dst).filter((f) => !USED.includes(f));
for (const f of stale) rmSync(join(dst, f));
console.log(`synced ${USED.length} example(s), removed ${stale.length} unused -> ${dst}`);
