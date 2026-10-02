/**
 * Values shared by playwright.config.ts and the specs. Ports come from env so the suite can
 * run beside servers that already own 8080/3000 (E2E_API_PORT / E2E_WEB_PORT); the run profile
 * and its time budget come from E2E_PROFILE / E2E_RUN_TIMEOUT_S.
 */
import fs from "node:fs";
import path from "node:path";

function port(value: string | undefined, fallback: number): number {
  const n = Number(value);
  return Number.isInteger(n) && n > 0 && n < 65536 ? n : fallback;
}

export const REPO_ROOT = path.resolve(__dirname, "..", "..");

// A set-but-invalid profile or timeout stops the run: falling back to fixture would report a
// fixture pass as a real-model pass.
function profileName(value: string | undefined): string {
  const name = value?.trim() || "fixture";
  // apps/api/settings.py PROFILE_NAME_RE, plus the YAML the API resolves the profile from
  const known =
    /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(name) &&
    fs.existsSync(path.join(REPO_ROOT, "config", "models", `${name}.yaml`));
  if (!known) throw new Error(`E2E_PROFILE=${name}: no config/models/${name}.yaml`);
  return name;
}

function seconds(value: string | undefined, fallback: number): number {
  if (!value?.trim()) return fallback;
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) throw new Error(`E2E_RUN_TIMEOUT_S=${value}: expected a positive number of seconds`);
  return n;
}

/**
 * RunRequest profile of the judged-path test (eval_001). The API is started with it as
 * MODEL_PROFILE, because /ops offers fixture plus the API's own default profile.
 */
export const PROFILE = profileName(process.env.E2E_PROFILE);
export const FIXTURE = PROFILE === "fixture";
export const WEB_DIR = path.join(REPO_ROOT, "apps", "web");
export const ARTIFACTS_DIR = path.join(REPO_ROOT, "artifacts", "e2e");

export const API_PORT = port(process.env.E2E_API_PORT, 8080);
export const WEB_PORT = port(process.env.E2E_WEB_PORT, 3000);
export const API_URL = `http://127.0.0.1:${API_PORT}`;
export const WEB_URL = `http://127.0.0.1:${WEB_PORT}`;

/**
 * Budget for one run, click RUN to the final hypothesis in the browser (E2E_RUN_TIMEOUT_S).
 * No target is written in the docs; the 60 s default is this suite's fixture assumption (a
 * fixture run takes ~1-3 s on the dev laptop). Real-model profiles need far more.
 */
export const RUN_TIMEOUT_MS = Math.round(seconds(process.env.E2E_RUN_TIMEOUT_S, 60) * 1000);

/** harness/dev_sequence.py SEQUENCE, the order the dev orchestrator calls tools in. */
export const TOOL_SEQUENCE = [
  "sample_video",
  "inspect_camera",
  "correlate_observations",
  "triangulate_region",
  "reason_hypothesis",
  "get_supporting_frames",
  "submit_hypothesis",
] as const;
