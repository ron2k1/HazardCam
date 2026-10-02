# P07 — Qwen perception adapter and finalized observation prompt

**Phase:** prebuild  
**Wave:** 2  
**Owner:** vision  
**Remote OK:** false  
**Dependencies:** P01, P04, P06

## Goal

Implement real local multimodal perception adapter plus fixture adapter; force observation-only structured output.

## Allowed paths

- `inference/**`
- `tools/inspect_camera.py`
- `prompts/qwen_perception.txt`
- `tests/integration/qwen/**`

## Acceptance criteria

- [ ] Schema-valid ObservationBatch
- [ ] No final event conclusion in perception prompt
- [ ] Retries/timeouts
- [ ] Same interface in fixture and local modes

## Worker report

Before marking complete, write `artifacts/workers/P07.md` with changed files, commands/tests run, results, assumptions, and blockers.
