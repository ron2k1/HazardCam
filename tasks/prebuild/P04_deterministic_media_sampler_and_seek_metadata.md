# P04 — Deterministic media sampler and seek metadata

**Phase:** prebuild  
**Wave:** 1  
**Owner:** vision  
**Remote OK:** true  
**Dependencies:** P00, P01

## Goal

Extract representative frames/clips deterministically with timestamps, frame IDs, and evidence seek metadata.

## Allowed paths

- `tools/sample_video.py`
- `tools/media/**`
- `tests/unit/media/**`

## Acceptance criteria

- [ ] ffmpeg path works
- [ ] Manifest deterministic
- [ ] Timestamp/frame tests pass
- [ ] Short clip mode supported

## Worker report

Before marking complete, write `artifacts/workers/P04.md` with changed files, commands/tests run, results, assumptions, and blockers.
