# /ops browser E2E

Run from the repo root with one command. The default is fixture mode: recorded model outputs, no model calls.

```
pnpm --dir apps/web e2e
```

To run with real local models (P14), set the profile and a larger run budget:

```
E2E_PROFILE=lite-local E2E_RUN_TIMEOUT_S=600 pnpm --dir apps/web e2e
```

In PowerShell, set the two variables first: `$env:E2E_PROFILE='lite-local'; $env:E2E_RUN_TIMEOUT_S='600'`. Extra arguments go to Playwright, e.g. `pnpm --dir apps/web e2e -g eval_001`.

`playwright.config.ts` starts both servers itself and stops them (by PID tree) when the run ends:

| server | command | port |
|---|---|---|
| api | `.venv` python `-m uvicorn apps.api.main:app`, `MODEL_PROFILE=$E2E_PROFILE` (default `fixture`), runs in `%TEMP%/ambient-mirror-e2e-runs` | `E2E_API_PORT` (8080) |
| web | `next build && next start` in `apps/web`, `NEXT_PUBLIC_API_BASE_URL` set to the api | `E2E_WEB_PORT` (3000) |

Each test fails if the page requests any host other than 127.0.0.1/localhost (every request goes through a context route), or if it throws an uncaught error.

The suite writes screenshots, `<profile>-run-timing.json` and `results.json` (or `results-<profile>.json` for a non-fixture profile) to `artifacts/e2e/`. Traces of failed tests go to `tests/e2e/test-results/`, which is gitignored.

## Env

- `E2E_PROFILE`: the profile the eval_001 test runs, default `fixture`. The API starts with it as its default profile, since /ops offers only fixture plus that default. It must have a `config/models/<profile>.yaml`; otherwise the run stops before any server starts.
- `E2E_RUN_TIMEOUT_S`: how long one run may take, from the RUN click to the final hypothesis. The default is 60 s. The per-test timeout is this plus 60 s. A run that ends `failed` fails the test at once, with its banner text, instead of waiting out the budget. An invalid value stops the run.
- `E2E_API_PORT`, `E2E_WEB_PORT`: use other ports when 8080/3000 are taken.
- `E2E_REUSE_SERVERS=1`: test against servers that are already running instead of starting them. By default a busy port fails the run, so a foreign server is never tested by accident. A reused API must have `MODEL_PROFILE` equal to `E2E_PROFILE`.
- `E2E_SKIP_BUILD=1`: `next start` an existing build. It must have been built with the same `NEXT_PUBLIC_API_BASE_URL`. The profile is not part of the build.
- `E2E_PYTHON`: interpreter for the api. The default is the repo `.venv`.

## What is covered

- **`ops-fixture.spec.ts`**
  - **eval_001, under `E2E_PROFILE`.**
    - The scenario list equals `GET /api/scenarios`. Health shows the chosen profile: `fixture` for fixture, `ok` (every model endpoint answering) otherwise.
    - The live trace matches the server's event log: the same calls, in the same order, with the same ok or error outcome. The distinct tools follow the 7-tool harness order.
    - The event, confidence and region readouts equal `GET /api/runs/{id}`.
    - Clicking a timeline bar seeks the camera `<video>`, and so does a cited hypothesis chip when the hypothesis cites evidence. Both are checked through `seeked` and `currentTime`.
    - GT stays withheld, with no `/api/judge` request, until REVEAL, and is shown after it.
    - The run must finish within `E2E_RUN_TIMEOUT_S`. Screenshots are taken at desktop and at 390 px.
    - Fixture only: the recorded hypothesis is a claim that cites other evidence, and no tool failed. These are not asserted for real models.
  - **eval_012 and eval_005, always fixture.** The real `no_event` claim and the real abstention (`unknown`).
- **`ops-resilience.spec.ts`**, always fixture where a run is needed, because these tests need a fixed event log, not a model.
  - **API offline and recovery.**
  - **SSE resume.** The stream is cut in the browser. The test asserts the `Last-Event-ID` reconnect and that the replayed events are not duplicated.
  - **Injected failure.** A failed tool and `run.failed` are rewritten into the stream in the browser; the backend run itself succeeds.
  - **Mock route.** `/ops?mock=default` makes no API calls.
