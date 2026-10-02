# P09 — Mistral reasoning adapter and finalized hypothesis prompt

**Phase:** prebuild  
**Wave:** 2  
**Owner:** reasoning  
**Remote OK:** true  
**Dependencies:** P01, P06, P08

## Goal

Implement reasoning adapter that consumes evidence bundles and returns bounded structured hypotheses with alternatives/limitations/abstention.

## Allowed paths

- `inference/**`
- `tools/reason_hypothesis.py`
- `prompts/mistral_fusion.txt`
- `tests/integration/mistral/**`

## Acceptance criteria

- [ ] Schema-valid Hypothesis
- [ ] Alternatives supported
- [ ] Unknown/abstain supported
- [ ] Fixture/local adapters share interface

## Worker report

Before marking complete, write `artifacts/workers/P09.md` with changed files, commands/tests run, results, assumptions, and blockers.
