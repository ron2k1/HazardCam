# P16 — Offline bundle, startup scripts, and prebuild freeze

**Phase:** prebuild  
**Wave:** 5  
**Owner:** integrator  
**Remote OK:** true  
**Dependencies:** P12, P13, P14

## Goal

Make the project reproducible offline and snapshot the exact pre-event state.

## Allowed paths

- `scripts/**`
- `Makefile`
- `docs/**`
- `artifacts/**`
- `config/**`
- `package-lock.json`
- `pnpm-lock.yaml`
- `requirements*.txt`
- `uv.lock`

## Acceptance criteria

- [ ] Offline dependency/model/data check
- [ ] One-command fixture start
- [ ] Real-model startup documented
- [ ] snapshot_prebuild.sh succeeds
- [ ] PREBUILD_VERIFICATION.md exists

## Worker report

Before marking complete, write `artifacts/workers/P16.md` with changed files, commands/tests run, results, assumptions, and blockers.
