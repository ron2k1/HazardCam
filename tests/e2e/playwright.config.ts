/**
 * Browser E2E for /ops (P13; P14 with E2E_PROFILE=lite-local).
 *
 *   pnpm --dir apps/web e2e
 *
 * Starts its own servers: the FastAPI app on API_PORT (MODEL_PROFILE=E2E_PROFILE, default
 * fixture; runs written to the OS temp dir) and a production build of the web app on WEB_PORT.
 * Both are stopped by PID tree when the run ends. See tests/e2e/README.md for the env knobs.
 */
import os from "node:os";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

import {
  API_PORT,
  API_URL,
  ARTIFACTS_DIR,
  FIXTURE,
  PROFILE,
  REPO_ROOT,
  RUN_TIMEOUT_MS,
  WEB_DIR,
  WEB_PORT,
  WEB_URL,
} from "./env";

const python =
  process.env.E2E_PYTHON ??
  path.join(REPO_ROOT, ".venv", process.platform === "win32" ? "Scripts\\python.exe" : "bin/python");
const next = `node ${path.join("node_modules", "next", "dist", "bin", "next")}`;
// Default: fresh servers, so a foreign process on the port fails the run instead of being tested.
const reuse = process.env.E2E_REUSE_SERVERS === "1";
// A real-model run keeps its own results file next to the fixture one.
const results = FIXTURE ? "results.json" : `results-${PROFILE}.json`;

export default defineConfig({
  testDir: ".",
  outputDir: "./test-results",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  // one run plus a minute for page load, seeks and the reveal (120 s at the fixture default)
  timeout: RUN_TIMEOUT_MS + 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["json", { outputFile: path.join(ARTIFACTS_DIR, results) }]],
  use: {
    baseURL: WEB_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    serviceWorkers: "block",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1600, height: 960 } },
    },
  ],
  webServer: [
    {
      name: "api",
      command: `"${python}" -m uvicorn apps.api.main:app --host 127.0.0.1 --port ${API_PORT} --log-level warning`,
      cwd: REPO_ROOT,
      url: `${API_URL}/healthz`,
      env: {
        // the API's default profile; /ops offers it beside fixture
        MODEL_PROFILE: PROFILE,
        AUM_RUNS_DIR: path.join(os.tmpdir(), "ambient-mirror-e2e-runs"),
        AUM_CORS_ORIGINS: `${WEB_URL},http://localhost:${WEB_PORT}`,
        PYTHONUTF8: "1",
      },
      reuseExistingServer: reuse,
      timeout: 60_000,
    },
    {
      name: "web",
      // NEXT_PUBLIC_API_BASE_URL is inlined at build time, so the build runs here with the test port.
      command: `${process.env.E2E_SKIP_BUILD === "1" ? "" : `${next} build && `}${next} start -H 127.0.0.1 -p ${WEB_PORT}`,
      cwd: WEB_DIR,
      url: `${WEB_URL}/ops?mock=idle`,
      env: { NEXT_PUBLIC_API_BASE_URL: API_URL, NEXT_TELEMETRY_DISABLED: "1" },
      reuseExistingServer: reuse,
      timeout: 300_000,
    },
  ],
});
