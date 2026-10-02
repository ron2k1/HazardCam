# P00 — Preflight, capability map, repo lock

**Phase:** prebuild  
**Wave:** 0  
**Owner:** integrator  
**Remote OK:** true  
**Dependencies:** none

## Goal

Inspect local and optional remote machines, freeze actual hardware/software plan, and identify fallbacks.

## Allowed paths

- `artifacts/**`
- `TASK_STATUS.json`
- `config/**`

## Acceptance criteria

- [ ] PREFLIGHT_REPORT.md exists
- [ ] Remote probe recorded when configured
- [ ] No secrets committed
- [ ] Task status updated

## Worker report

Before marking complete, write `artifacts/workers/P00.md` with changed files, commands/tests run, results, assumptions, and blockers.
