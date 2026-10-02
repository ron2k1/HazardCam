# P15 — Full/intended model benchmark where hardware permits

**Phase:** prebuild  
**Wave:** 4  
**Owner:** inference  
**Remote OK:** false  
**Dependencies:** P12, P14

## Goal

Benchmark intended or closest practical Qwen/Mistral models and preserve reproducible serving/preprocessing settings.

## Allowed paths

- `artifacts/model/**`
- `artifacts/eval/**`
- `config/models/**`
- `scripts/eval/**`

## Acceptance criteria

- [ ] Exact configuration recorded
- [ ] At least one representative scenario run if hardware permits
- [ ] Fallback documented if not possible
- [ ] No app contract changes

## Worker report

Before marking complete, write `artifacts/workers/P15.md` with changed files, commands/tests run, results, assumptions, and blockers.
