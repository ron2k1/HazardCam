# P12 — Evaluation dataset manifest and scoring harness

**Phase:** prebuild  
**Wave:** 3  
**Owner:** eval  
**Remote OK:** true  
**Dependencies:** P05, P07, P08, P09, P10

## Goal

Create repeatable scenario evaluation, structural metrics, failure capture, and model-profile comparison.

## Allowed paths

- `eval/**`
- `scripts/eval/**`
- `data/eval/**`
- `artifacts/eval/**`
- `tests/unit/eval/**`

## Acceptance criteria

- [ ] Eval command runs
- [ ] Negative/ambiguous cases supported
- [ ] summary.json generated
- [ ] No exact-string scoring

## Worker report

Before marking complete, write `artifacts/workers/P12.md` with changed files, commands/tests run, results, assumptions, and blockers.
