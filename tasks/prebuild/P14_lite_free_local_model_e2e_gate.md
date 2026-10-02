# P14 — Lite/free local model E2E gate

**Phase:** prebuild  
**Wave:** 4  
**Owner:** verifier  
**Remote OK:** true  
**Dependencies:** P07, P09, P10, P11, P13

## Goal

Run the full application with small/free local models on available development hardware or compatible remote worker.

## Allowed paths

- `tests/e2e/**`
- `artifacts/model/**`
- `config/models/**`

## Acceptance criteria

- [ ] Real model calls occur
- [ ] Observation/hypothesis schemas valid
- [ ] Latency recorded
- [ ] Limitations documented

## Worker report

Before marking complete, write `artifacts/workers/P14.md` with changed files, commands/tests run, results, assumptions, and blockers.
