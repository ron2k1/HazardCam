# /ops browser E2E

Run from the repo root with one command. The default is fixture mode: recorded model outputs, no model calls.

```
pnpm --dir apps/web e2e
```

To run with real local models (P14), set the profile and a larger run budget. Only the eval_001 test follows the profile; the rest would redo their fixture runs and rewrite the fixture screenshots, so select it:

```
E2E_PROFILE=lite-local E2E_RUN_TIMEOUT_S=600 pnpm --dir apps/web e2e -g eval_001
```

`scripts/run.sh lite-e2e` / `full-e2e` do this for you. In PowerShell, set the two variables first: `$env:E2E_PROFILE='lite-local'; $env:E2E_RUN_TIMEOUT_S='600'`. Extra arguments go to Playwright.

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

## Views

`/ops` opens the plain worker view by default. The console checks below run in the technical view: `openOps` adds `?view=technical` to every query that does not pick a view itself, and the specs that call `page.goto` directly pass it too.

## What is covered

- **`ops-fixture.spec.ts`**
  - **eval_001, under `E2E_PROFILE`.**
    - The scenario list equals `GET /api/scenarios`. Health shows the chosen profile: `fixture` for fixture, `ok` (every model endpoint answering) otherwise.
    - The live trace matches the server's event log: the same calls, in the same order, with the same ok or error outcome. The distinct tools follow the 7-tool harness order.
    - The event, confidence and region readouts equal `GET /api/runs/{id}`.
    - Clicking a timeline bar seeks the camera `<video>`, and so does a cited hypothesis chip when the hypothesis cites evidence. Both are checked through `seeked` and `currentTime`.
    - GT stays withheld, with no `/api/judge` request, until REVEAL, and is shown after it. From the loaded scenario until then, nothing on the page names the withheld camera. The tokens come from its manifest: id, file stem, label, MEVA id, and what only a revealed console draws. The page is checked as the watch starts, and a MutationObserver then scans every change, including values overwritten before it could look. After REVEAL the same detector, with the same bounds, must find each reveal token, so it has been shown able to fire. A blank-page test checks the detector itself.
    - The run must finish within `E2E_RUN_TIMEOUT_S`. Screenshots are taken at desktop and at 390 px.
    - Fixture only: the recorded hypothesis is a claim that cites other evidence, and no tool failed. These are not asserted for real models.
  - **eval_012 and eval_005, always fixture.** The real `no_event` claim and the real abstention (`unknown`).
- **`ops-worker.spec.ts`**, the worker view (always fixture where a run is needed).
  - **No page.** The server writes plain text; the page's leak check only hides a sentence that still holds an id, snake_case name, coordinate, bearing, score, decimal, URL, path or pipeline jargon, and leaves plain text exactly as written (`plainOr` falls back whole). An `alert` at level `info` reads NOTICE. Camera ids become "Camera B" / "Camera 2" / "Camera <slot>". `alert.message` keeps arrival order and replaces by id, malformed messages and unknown event types are dropped, `alert.delivery` is kept per message, and the next run starts with an empty feed. The progress line follows camera and tool events.
  - **Mock** (`/ops?mock=...`, no API). The worker view is the default: HEADS-UP then ALERT cards. Each urgent card shows its urgency in words ("Check soon"), "What to do" straight under the headline, then How sure, Where, When, Seen on and What happened, and "Sent <time>" in the header only. Once the final message is in, the heads-up is quiet: "Checked. See the result below.", no amber, its rows folded behind "Earlier heads-up". No delivery line while no Telegram channel is connected (the card carries `data-delivery="not_connected"`), readable sizes (headline at least 20 px, body at least 14 px), "Show on video" marks the cited cameras. The "Technical details" switch writes `?view=technical`, is remembered across visits (localStorage), and an explicit `?view=` wins. Run streams the progress line. The abstain mock reads COULDN'T CONFIRM with no amber or red card and no urgency word, and its "What to do" is visible. 390 px has no horizontal scroll.
  - **Live, eval_001.** At most one heads-up, then a final alert (or unconfirmed). Every heads-up and alert has its delivery status (`data-delivery`) before the run ends; a line is shown only for sent or failed. "Show on video" seeks the cited camera's `<video>`. No judge request and no ground-truth token in the worker view.
  - **Live, eval_005 / eval_012.** The abstention reads COULDN'T CONFIRM, "No action needed now. A supervisor can review the footage."; `no_event` reads ALL CLEAR, "Nothing to do."
  - Every worker check also scans the view's visible text, the text folded inside closed `<details>`, accessible names and `title` attributes for internal ids (`cam_`, `region_`, `obs_`), snake_case names, coordinates, bearings, scores, decimals, URLs, paths, file names, frame talk and jargon (hypothesis, evidence, cue, cluster, triangulation, abstain, region, profile, SSE, harness).
- **`ops-races.spec.ts`**, always fixture. Most tests hold a real request in the browser while they act on the page.
  - While the run POST is in flight, the scenario, profile and REVEAL stay locked.
  - A judge reply that lands after RE-RUN or a scenario change shows no ground truth, and FETCHING ends with the RE-RUN or the change, not with the reply. After a scenario change the reply is dropped outright: back on its own scenario it reveals nothing, and the next reveal asks the judge again.
  - RE-RUN after a reveal withholds the cached ground truth again.
  - Leaving /ops while the run POST is in flight opens no event stream.
- **`ops-resilience.spec.ts`**, always fixture where a run is needed, because these tests need a fixed event log, not a model.
  - **API offline and recovery**, before the page loads and after the scenarios loaded.
  - **Failed requests.**
    - A scenario list answered 500 is asked for again without a reload.
    - A run POST reset at the network, or answered 202 with a cut body, reads RUN NOT CONFIRMED, not REJECTED.
  - **Profile.** If the API restarts with another `MODEL_PROFILE`, the models health follows the profile RUN posts.
  - **SSE resume.** The stream is cut in the browser. The test asserts the `Last-Event-ID` reconnect and that the replayed events are not duplicated.
  - **SSE retries.** The page's own `?after_seq` reconnect is checked. With the API gone mid-run, the page stops after its retry budget and marks the stream lost.
  - **Injected failure.** A failed tool and `run.failed` are rewritten into the stream in the browser; the backend run itself succeeds.
  - **Mock route.** `/ops?mock=default&view=technical` makes no API calls.
