# P03 — FastAPI run lifecycle and SSE event bus

**Phase:** prebuild  
**Wave:** 1  
**Owner:** backend  
**Remote OK:** true  
**Dependencies:** P00, P01

## Goal

Implement health, scenario, run creation, run state, and SSE progress streaming.

## Allowed paths

- `apps/api/**`
- `tests/unit/api/**`
- `tests/integration/api/**`

## Acceptance criteria

- [ ] POST /api/runs returns run_id
- [ ] SSE fixture run completes
- [ ] Health exposes dependencies
- [ ] pytest passes

## Worker report

Before marking complete, write `artifacts/workers/P03.md` with changed files, commands/tests run, results, assumptions, and blockers.
