# P05 — Real-data acquisition and candidate ranking

**Phase:** prebuild  
**Wave:** 1  
**Owner:** data  
**Remote OK:** true  
**Dependencies:** P00

## Goal

Acquire legally usable real footage, prepare compact scenarios, and rank candidate windows using cheap motion/correlation heuristics.

## Allowed paths

- `scripts/data/**`
- `data/manifests/**`
- `docs/DATA_SOURCES.md`
- `artifacts/data/**`

## Acceptance criteria

- [ ] At least one real prepared scenario
- [ ] Provenance/license metadata recorded
- [ ] Candidate ranking report
- [ ] No judged-path network dependency

## Worker report

Before marking complete, write `artifacts/workers/P05.md` with changed files, commands/tests run, results, assumptions, and blockers.
