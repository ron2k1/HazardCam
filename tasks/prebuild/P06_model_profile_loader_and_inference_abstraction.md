# P06 — Model profile loader and inference abstraction

**Phase:** prebuild  
**Wave:** 2  
**Owner:** inference  
**Remote OK:** true  
**Dependencies:** P00, P01

## Goal

Create stable model configuration/profile loading for fixture, lite-local, remote16gb, full-local, and gb10.

## Allowed paths

- `config/models/**`
- `inference/**`
- `tests/unit/inference/**`

## Acceptance criteria

- [ ] Profiles load/validate
- [ ] Secrets excluded
- [ ] Endpoint/checkpoint settings configurable
- [ ] Unit tests pass

## Worker report

Before marking complete, write `artifacts/workers/P06.md` with changed files, commands/tests run, results, assumptions, and blockers.
