# P08 — Deterministic temporal correlation and coarse triangulation

**Phase:** prebuild  
**Wave:** 2  
**Owner:** fusion  
**Remote OK:** true  
**Dependencies:** P01, P04

## Goal

Fuse time-aligned cues and camera metadata into evidence clusters and coarse region candidates without LLMs.

## Allowed paths

- `tools/correlate.py`
- `tools/triangulate.py`
- `tests/unit/fusion/**`

## Acceptance criteria

- [ ] No LLM dependency
- [ ] Offset tests pass
- [ ] Unknown/insufficient path
- [ ] Evidence IDs preserved

## Worker report

Before marking complete, write `artifacts/workers/P08.md` with changed files, commands/tests run, results, assumptions, and blockers.
