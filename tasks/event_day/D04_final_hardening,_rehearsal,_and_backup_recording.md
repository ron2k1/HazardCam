# D04 — Final hardening, rehearsal, and backup recording

**Phase:** event_day  
**Wave:** 14  
**Owner:** integrator  
**Remote OK:** true  
**Dependencies:** D03

## Goal

EVENT DAY: eliminate fragile dependencies, warm models, rehearse 3-minute story, and record fallback demo.

## Allowed paths

- `apps/**`
- `scripts/**`
- `docs/**`
- `artifacts/**`

## Acceptance criteria

- [ ] demo-check passes 3x
- [ ] Backup recording exists
- [ ] 3-minute script rehearsed
- [ ] verify_event_delta.sh succeeds
- [ ] FINAL_VERIFICATION.md exists

## Worker report

Before marking complete, write `artifacts/workers/D04.md` with changed files, commands/tests run, results, assumptions, and blockers.

## Event-day integrity

This task must be performed on event day. Do not copy a prebuilt finished agent/runtime implementation into place and represent it as newly authored. Use the prepared libraries/interfaces, then create the agent integration now.

## Fresh-build requirement

Implement the OpenClaw-specific portion for this task from the current repository state during the event-day session. Reuse already-tested ordinary libraries/interfaces, but do not source or copy a prewritten hidden OpenClaw implementation from outside the event-day working tree. Record commands/tests in `artifacts/event_day/workers/`.

## Operator addendum (event day, 2026-10-03)

- **The story centres on Safety hazards** (`/hazards`, single-camera factory hazard review with the computer-vision evidence video). The operator called it the strongest part. The bus-station `/ops` multi-camera run is a secondary beat, about 30 s at most, to show the OpenClaw agent through NemoClaw/OpenShell. Write the 3-minute script in `docs/DEMO_SCRIPT.md`, in plain words for a non-technical audience.
- The demo can run in the hazards replay mode (`HAZARDS_DEMO_REPLAY=1`), which replays real GB10 runs recorded today and says so in Technical details. A backup recording is at `artifacts/hazards/demo/hazards_demo.mp4` if it exists; reuse it rather than re-recording, and add one short `/ops` clip if time allows.
- Some parts can start before D03 finishes: the script, `make demo-check` three times, and removing fragile dependencies. `FINAL_VERIFICATION.md` comes last, after D03's artifacts exist.
- Time budget: about 40 minutes. Keep the worker views leak-free: no ids, coordinates, scores or schema words. Never push.
- **No live demo (operator, later on 2026-10-03).** The demo is a staged screen recording, so the recording is the main deliverable and `demo-check` is a supporting check. Staging is fine, but nothing on screen may be hardcoded. Every value comes from real runs through the app's API: the hazard replay reads stored real GB10 runs, and the `/ops` beat is a real run. Never use `?mock=1` in the recording.
- **State at D04 start (operator, 13:25 CDT).** D02 (`fc49486`) and D03 (`86cb7e0`) are committed. Qwen fills both model slots on :8000, and Cosmos (:8001) is stopped, so run demo-check with `API_BASE_URL=http://127.0.0.1:8088 MISTRAL_BASE_URL=http://127.0.0.1:8000/v1`. Add a `/hazards` check to `scripts/demo_check.sh` if it is missing. `/` now redirects to `/hazards`.
- **The hazard screen is being rebuilt right now** by another workflow. The new flow: a CCTV-style feed plays on load; the check starts by itself; the structured result, the AI-marked video and the pictures appear only after the check; reasoning and process open in a second tab at `/hazards/process`. That workflow also builds an API runtime-status endpoint, and a separate worker is routing hazard checks through the OpenClaw agent (`agent/**`). Until both finish, do NOT edit `apps/web/src/{app,components}/hazards/**`, `apps/web/src/lib/hazards.ts`, `apps/api/{routes,services}/hazards.py`, `apps/api/main.py`, `hazards/**` or `agent/**`, and do not restart :8088.
- **Recording order.** Do the script (`docs/DEMO_SCRIPT.md`, written for the new flow), the demo-check runs and the dependency hardening first. The hazard workflow writes `artifacts/hazards/demo/hazards_demo.mp4` when it finishes, around 14:15 CDT. Wait for that file before judging the recording. Watch it with ffprobe and its key frames, and re-record only if it shows mock data, a stuck step, leaked ids or the old layout. Record the ~30 s `/ops` beat as a real gb10 run (`/ops?profile=gb10`), with no other model jobs running. Pause hazard reviews while recording: the shared GPU turned a 37 s run into 155 s in D03.
- `make verify-event-delta` and `FINAL_VERIFICATION.md` come last, after the hazard work is committed. If time runs short, write `FINAL_VERIFICATION.md` with what is verified and list plainly what is not.
