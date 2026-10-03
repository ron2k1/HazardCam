# Next.js app

T02/T11 own this directory. Use `reference/theme-reference.jpeg` and `docs/FRONTEND_SPEC.md` as the design source of truth.

Next.js 16 (App Router, Turbopack), React 19, Tailwind 4, shadcn (base-nova), `motion`. All fonts and assets are local; the judged path makes no internet requests. Component provenance is in `design/COMPONENTS.md`.

## Commands

Run from the repo root:

```
pnpm --dir apps/web install
pnpm --dir apps/web dev          # http://localhost:3000
pnpm --dir apps/web lint         # eslint (next lint was removed in Next 16)
pnpm --dir apps/web build
pnpm --dir apps/web start        # next start, port 3000
```

From `apps/web`:

```
node scripts/sync-contract-examples.mjs   # copy the ../../contracts/examples files mock.ts imports into src/mocks/contract-examples/
node scripts/screenshots.mjs [baseUrl]    # Playwright captures + checks -> design/screenshots/ (needs a running server)
```

Turbopack cannot import files outside the app root, so the contract examples are copied in. The script's `USED` list must match the imports in `src/mocks/mock.ts`, and anything else in the destination is deleted. Re-run it after `contracts/examples` changes.

`next dev` rewrites a generic `AGENTS.md` / `CLAUDE.md` here whenever an AI agent runs it. Both are gitignored, so they never get committed.

## Config

| Env | Default | Where |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://127.0.0.1:8080` | `src/lib/config.ts` (`API_BASE_URL`, `apiUrl(path)`). It is inlined at build time, so rebuild after changing it. |

## Routes

- `/`: landing.
- `/ops`: run console on the local API (`OpsLive`). `?scenario=<id>` preselects a scenario; `?pace=<s>` (0-5) slows a run for a demo; `?profile=<name>` preselects the run profile when the API offers it (fixture, or the API's own `MODEL_PROFILE`), otherwise fixture.
  - The default is the **worker view** (`src/components/ops/worker-view.tsx`): plain-language alert cards from the `alert.message` / `alert.delivery` SSE events, the camera videos with friendly names ("Camera B"), one Run button and a progress line built from camera and tool events. It shows no ids, coordinates, scores or model prose. It has no profile select, so it runs fixture (tagged "Recorded results") unless the profile is chosen with `?profile=` (e.g. `/ops?profile=gb10`) or in the technical view.
  - A card leads with its kind and, for a heads-up or alert, the urgency in words ("Check soon"), then the headline and "What to do" straight under it. Once the run's final message is in, the heads-up turns quiet ("Checked. See the result below.") and folds its rows away.
  - A card shows a delivery line only for `sent` or `failed`, in fixed words (the delivery `detail` is never shown); with no Telegram channel connected (`not_connected`, this build) the alert is on screen only and no line is shown (the status stays in the card's `data-delivery`).
  - `?view=technical` (or the "Technical details" switch, which also remembers the choice in localStorage) opens the full technical console: hypothesis, blind-zone plan, trace, stack health, ground-truth reveal.
- `/ops?mock`: `OpsMock`, which replays `contracts/examples` through the live reducer with no network (design checks).
  - `/ops?mock=abstain`: the abstain hypothesis.
  - `/ops?mock=idle`: an empty console before any run.

## How `/ops` uses the API (P11)

`OpsScreen` (`src/components/ops/ops-screen.tsx`) mounts either `WorkerView` or `OpsConsole` (`src/components/ops/ops-console.tsx`); both are prop-driven from the same props. `OpsLive` (`src/components/ops/ops-live.tsx`) feeds them:

- `scenarios` and `scenario`: from `GET /api/scenarios` (`ScenarioList`) and `GET /api/scenarios/{id}` (`PublicScenario`).
- `view`: reduce SSE envelopes into a `RunView`:
  - `const env = parseEnvelope(e.data); if (env) view = applyEvent(view, env);` (`parseEnvelope` from `src/lib/contracts.ts` takes the raw `data` string and returns `null` for a malformed envelope; `applyEvent` from `src/lib/run-view.ts`).
  - Start from `EMPTY_RUN_VIEW`.
  - The reducer drops other run ids and `seq <= lastSeq`, so `Last-Event-ID` replays are safe.
  - `alert.message` messages are kept in arrival order (a repeated id replaces in place) and `alert.delivery` per message id; both are shape-checked (`normalizeAlertMessage` / `normalizeAlertDelivery`), so a malformed one is dropped instead of breaking the view.
  - Worker text goes through `plainText` (`src/lib/plain.ts`) as a second line of defence. It never rewrites: the server already writes plain text, and a sentence that still holds an id, snake_case name, coordinate, bearing, score, decimal, URL, path or jargon is hidden whole (`plainOr` falls back for a headline or label).
- `health`: from `GET /api/models/health?profile=` (`ModelsHealth`).
- `apiStatus` and `apiDetail`: from `GET /healthz` (`ServiceHealth`).
- `judge`: from `GET /api/judge/scenarios/{id}` (`JudgeGroundTruth`). Fetch it only for the reveal action.
- `onRun`:
  - `POST /api/runs` with a `RunRequest`; the response is a `RunResponse`. The scenario and profile selects and REVEAL stay locked until it answers.
  - Then `src/hooks/use-run-stream.ts` opens `new EventSource(apiUrl(events_url))` and listens on `onmessage` only, because the API sends no named events. Failed connection attempts (the browser's retries and its own `?after_seq=` reconnects) share `LIVE.streamMaxRetries`; past it the run shows as lost.

Media is requested only when the API reports it present (`media_available` / `video_available`). Seeking and GT-reveal state are handled inside `OpsConsole`.
