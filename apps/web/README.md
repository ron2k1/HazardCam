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
- `/ops`: run console. It currently renders `OpsMock`, which replays `contracts/examples` through the live reducer with no network.
  - `/ops?mock=abstain`: the abstain hypothesis.
  - `/ops?mock=idle`: an empty console before any run.

## Wiring the live API (P11)

`OpsConsole` (`src/components/ops/ops-console.tsx`) is prop-driven. A live container replaces `OpsMock` and feeds it:

- `scenarios` and `scenario`: from `GET /api/scenarios` (`ScenarioList`) and `GET /api/scenarios/{id}` (`PublicScenario`).
- `view`: reduce SSE envelopes into a `RunView`:
  - `const env = parseEnvelope(e.data); if (env) view = applyEvent(view, env);` (`parseEnvelope` from `src/lib/contracts.ts` takes the raw `data` string and returns `null` for a malformed envelope; `applyEvent` from `src/lib/run-view.ts`).
  - Start from `EMPTY_RUN_VIEW`.
  - The reducer drops other run ids and `seq <= lastSeq`, so `Last-Event-ID` replays are safe.
- `health`: from `GET /api/models/health?profile=` (`ModelsHealth`).
- `apiStatus` and `apiDetail`: from `GET /healthz` (`ServiceHealth`).
- `judge`: from `GET /api/judge/scenarios/{id}` (`JudgeGroundTruth`). Fetch it only for the reveal action.
- `onRun`:
  - `POST /api/runs` with a `RunRequest`; the response is a `RunResponse`.
  - Then open `new EventSource(apiUrl(events_url))` and listen on `onmessage` only, because the API sends no named events.

Media is requested only when the API reports it present (`media_available` / `video_available`). Seeking and GT-reveal state are handled inside `OpsConsole`.
