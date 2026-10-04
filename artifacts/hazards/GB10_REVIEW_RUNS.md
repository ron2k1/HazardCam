# Safety hazard: live GB10 review runs (2026-10-03)

**Setup**
- Model: `nvidia/Qwen3.6-35B-A3B-NVFP4` on the local vLLM at `127.0.0.1:8000`.
- Profile `gb10`, with env `QWEN_MODEL=nvidia/Qwen3.6-35B-A3B-NVFP4` and `MISTRAL_MODEL=nvidia/Cosmos-Reason2-8B`.
- Request settings: strict json_schema, thinking off, temperature 0, seed 42.
- Object proposals: local detector `yolo11s` (sha256 `85a76fe8…d502d5`) on `cuda:0 (NVIDIA GB10)` at `127.0.0.1:8003`.
- Pipeline `astra-1.1-gb10`, ported from `astra_video_hazard.py` (sha256 `ae92565b…eba132`).
- No network access beyond loopback.

**Clips.** For each target label, the first test-split clip by natural sort that decodes cleanly. `prepare_clips.py --labels 0,1,3 --prune --force --import-example` checks this with a full ffmpeg decode plus a cv2 decode. `ffprobe -count_frames` exited 0 with empty stderr on every clip, so no swap was needed.

**Concurrency.** hz_01..hz_03 and the hz_00 port run ran as four separate concurrent processes, from 18:11:31 to 18:13:45 UTC. hz_02 was rerun alone after a fix (see below).

The dataset-label column is for judges only. Labels live in `data/hazards/labels/`, and neither the pipeline nor the model ever sees them.

## Results

| Clip | Neutral title | Dataset label (judge only) | Findings | Top priority | Findings (priority) | Review s | Audit s | Run total s | Review tokens in / out | Audit tokens in / out | Images | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hz_01 | Floor camera 01 | `3_carrying_overload_with_forklift` (test, `3_te1.mp4`) | 2 | Medium | Forklift encroaching on marked aisle boundary (M); Worker proximity to operating machinery (M, needs a check) | 69.49 | 56.14 | 133.19 | 23609 / 2199 | 25730 / 1803 | 29 | model_review_complete |
| hz_02 | Floor camera 02 | `0_safe_walkway_violation` (test, `0_te1.mp4`) | 2 | High | Obstruction of marked aisle by stored materials (M); Worker proximity to machinery (H, needs a check) | 22.08 | 12.28 | 45.77 | 25831 / 1673 | 27498 / 1317 | 29 | model_review_complete |
| hz_03 | Floor camera 03 | `1_unauthorized_intervention` (test, `1_te1.mp4`) | 2 | High | Mechanical power press point-of-operation guarding (H, needs a check); Obstruction of marked aisle by stored material (L) | 59.11 | 29.62 | 105.53 | 29239 / 2121 | 31272 / 1689 | 35 | model_review_complete |
| hz_00 (our port, 2nd run dir) | Press line camera | `4_safe_walkway` (train, `4_tr1.mp4`) | 2 | High | Worker exposure at machine point of operation (H, needs a check); Obstruction of marked aisle (M) | 59.98 | 33.41 | 106.39 | 28938 / 2184 | 31013 / 1732 | 35 | model_review_complete |
| hz_00 (original run, **default shown**) | Press line camera | `4_safe_walkway` (train, `4_tr1.mp4`) | 2 | Medium | Obstruction in marked aisle (M); Worker proximity to machine point of operation (M, needs a check) | 68.95 | 27.79 | n/a | 27500 / 1790 | 29234 / 1670 | 35 | model_review_complete (Ollama `qwen3.6:35b-a3b`, macOS, FastSAM-s) |

How to read the timing columns:
- Review s and Audit s are the model calls' `elapsed_seconds`. Every review took one call; no repair turn was needed.
- Run total is `run_manifest.json` `timings_s.total`: scan plus review plus audit.
- The first four runs shared the GPU with each other and with one extra job, described below. The same work run alone is faster: hz_02 took 22 s to review and 12 s to audit.
- Wall clock from `/usr/bin/time`: hz_01 133.7 s, hz_00 port 106.9 s, hz_03 106.1 s, hz_02 rerun 46.0 s.

**Run dirs** (under `data/hazards/reports/<clip>/`):
- hz_01 `83f6d4a4b4755d26`
- hz_02 `ed02d540b08f6395`
- hz_03 `03085f3782c5f322`
- hz_00 port `f12f98a9f3b78349`
- hz_00 original `ed487eb3f1181f38`. `reports/hz_00/latest_run.json` points here, so this run stays the default view.

**Segmentation.** All four GB10 runs read `local YOLO11s boxes on the temporal background + edge contours`. The only quality warning on any of them is the upstream "No reliable floor-like mask found…".

| Clip | yolo11s boxes on the background (conf ≥ 0.25) | Zones | Zone from a YOLO box |
|---|---|---|---|
| hz_01 | tv 0.36, person 0.32, person 0.30 | 7 (2 movement) | Z03 "person (0.30)" |
| hz_02 | 0 boxes (detector answered: `status: no_boxes`) | 7 (2 movement) | none; static zones are edge contours |
| hz_03 | tv 0.49 | 10 (5 movement) | none |
| hz_00 port | person 0.66 / 0.43 / 0.38, traffic light 0.39, suitcase 0.25 | 10 (5 movement) | Z07 "traffic light (0.39)", which is really the purple scrap bin |

## Do the findings match the dataset labels?

The model was never asked to classify the clip. It does a general hazard screen, so the dataset label is only a reference point.

- **hz_01, `3_carrying_overload_with_forklift`: partial.**
  - The model saw the forklift "carrying a stack of orange bins" and flagged it for crossing the painted aisle line.
  - It did not flag the overload or the stability of the load, which is what the label is about.
  - It also flagged the seated worker next to the press as needing a check.
- **hz_02, `0_safe_walkway_violation`: no match for the labelled behaviour.**
  - It flagged a pallet encroaching on the green walkway and a worker standing inside the press railing.
  - Its scene summary notes "workers … moving within the machine zone", but no finding says a person walked outside the safe walkway.
- **hz_03, `1_unauthorized_intervention`: related, but it cannot judge authorisation.**
  - The top finding (High, needs a check) is the worker at the mechanical press control station, with "hands raised near the machine's interface".
  - The actions it lists are to verify whether the press is in production or maintenance and to check the guarding.
  - Whether the intervention is authorised can't be seen, and the model correctly leaves that open.
  - The second finding (Low) is containers stored on the green walkway.
- **hz_00, `4_safe_walkway` (a "safe" label): different hazards.**
  - Both the original run and our port flag the round metal object on the aisle and the seated worker at the press point of operation.
  - The label only describes walkway behaviour, so these findings are additional scene hazards, not a contradiction.

## Comparison on the same video: hz_00, original run vs our port

Our port on the GB10 is set against the original run on macOS (Ollama `qwen3.6:35b-a3b`, FastSAM-s). Both runs used the same source file (sha256 `d80a7143…53d5eb`).

**Video handling: the same assumptions.**
- Both decoded 315 frames at 24.99 fps (12.61 s) and analysed at 768x432.
- Both produced 35 evidence images: 11 full-scene, 20 zone crops and 4 scene tiles, in the same order with the same ids.
- 32 of 35 items have the same (id, kind, zone id, frame). The other 3 differ only by motion-peak frame: E002 frame 7 vs 3, E014 frame 7 vs 1 (Z02 peak), and E016 frame 16 vs 15 (Z03 peak). This is the known decoder/platform difference documented in `third_party/astra_safety_hazard/PROVENANCE.md`. On the same machine, the port and the upstream code are byte-identical (`tests/unit/hazards/test_upstream_video_parity.py`).

**Movement zones: 5 of 5 match.** Each pair is original vs port.

| Zone | Original box | Port box | IoU | Peak frame (original / port) |
|---|---|---|---|---|
| Z01 | `[553,0,658,155]` | `[553,0,658,155]` | 1.00 | 311 / 311 |
| Z02 | `[246,26,293,80]` | `[246,26,293,80]` | 1.00 | 7 / 1 |
| Z03 | `[255,281,322,331]` | `[255,281,322,331]` | 1.00 | 16 / 15 |
| Z04 | `[374,65,400,108]` | `[374,66,400,108]` | 0.98 | 312 / 312 |
| Z05 | `[199,244,225,282]` | `[199,244,228,282]` | 0.90 | 29 / 29 |

Active windows are the same, apart from Z03 ending at 4.32 s vs 4.36 s.

**Static zones: 1 of 5 match.** This is the one intended change: FastSAM masks are replaced by local YOLO boxes plus edge contours.
- The match: original Z09, the purple scrap bin, is port Z07 (the yolo11s "traffic light" box), IoU 0.94.
- Not selected by the port:
  - original Z06, the floor section;
  - **original Z07, the round metal object in the aisle**. yolo11s does see it ("suitcase" 0.251), but it ranks below the top-5 static candidates;
  - original Z08, the document stand;
  - original Z10, the pallet.
- Selected by the port instead (all edge contours): Z06 the right-hand green walkway, Z08 the machine guard cage, Z09 the press side panel, Z10 the coil/stand area.

**Findings: the same two concerns, with different detail.**

| | Original (macOS, FastSAM) | Our port (GB10, YOLO + edge) |
|---|---|---|
| Worker at the press | H02 *Worker Proximity to Machine Point of Operation*; Medium, needs_verification, conf medium; zone Z03; evidence E016, E017, E034; standard 1910.217(c)(1)(i) | H01 *Worker Exposure at Machine Point of Operation*; **High**, needs_verification, conf high; zones Z03, Z05; evidence includes E016, E017, E034; standards 1910.212(a)(3)(ii) and 1910.147(a)(2) |
| Round metal object in the aisle | H01 *Obstruction in Marked Aisle*; Medium, visible_concern, conf high; zone **Z07** (the object's own zone); evidence E024, E025, E035; standard 1910.176(a) | H02 *Obstruction of Marked Aisle*; Medium, visible_concern, conf high; zone **Z06**; evidence E001–E011, E022, E023, E035; standards 1910.22(a)(3) and 1910.176(a) |

Both runs reported exactly these two concerns, the aisle one as visible_concern and the worker one as needs_verification. Where they differ:
- **Severity.** The port rates the worker exposure High; the original run rated it Medium.
- **Zone attribution.** The port has no zone on the round object, so the model attached the obstruction to Z06, the green walkway on the right of the frame. The Z06 crops (E022, E023) show only the walkway; the object is visible in the full-scene frames and in scene tile E035.
- **Wording.** The port's text says the object sits "on top of the green painted aisle marking". In the frames it is on the grey aisle by the yellow line, which is what the original run says.

**Run-to-run agreement on the identical request.** Three GB10 calls sent the byte-identical request (sha256 `f2dee4678dc44c2b…`).

| Run | Worker finding | Second finding |
|---|---|---|
| Earlier smoke run (18:05 UTC) | High | "Material storage adjacent to aisle": a coil on a pallet, zone Z10. This run *dismissed* the round floor object |
| The live port run above | High | "Obstruction of marked aisle": the round object |
| A concurrent job started through the API (18:12–18:14 UTC; see note) | High | "Unsecured material coil on the floor", zone Z06: the round object framed as a storage-stability issue (1910.176(b)) |

- The worker-at-press finding came out every time, and High every time.
- The second finding changes between calls even at temperature 0 and seed 42, because vLLM batching does not give bit-exact results across batch compositions.
- The original run's aisle-obstruction finding was reproduced in 1 of the 3 calls.
- The weak link is the missing static zone on the round object. With FastSAM the object had its own zone and close-up crops.

## Fix made during these runs

In the first concurrent pass, hz_02 came out as `edge-contour fallback` with the upstream "FastSAM unavailable/no masks…" warning. The detector was up and answered (`status: no_boxes`, 27.5 ms); yolo11s simply found no object at conf 0.25 on that background.

**Root cause.** `hazards/scan.py` `propose_static` took the fallback whenever YOLO contributed no boxes. The spec reserves the fallback for a detector that does not answer.

**Fix:**
- The fallback now applies only when the detector did not answer (unreachable, error, models missing, disabled).
- When the detector answers with zero boxes, the method name stays and the candidate set is exactly the edge contours. The report records `pipeline.detector.status: no_boxes, boxes: 0`.
- The test is updated in `tests/unit/hazards/test_static_proposals.py`, and the wording in `PROVENANCE.md`.

**Rerun.** hz_02 was rerun alone with `--refresh`. Its request changed (the warning is part of the request), so the model call was fresh.

The superseded fallback run had 3 findings: aisle obstruction (M), unsecured coil (M) and guarding (H). It is kept only in the session scratchpad, not in `data/`.

## Output checks (all passed)

**processed.mp4** in all five run dirs:
- h264 / yuv420p, 768x460;
- top-level atoms `ftyp, moov, free, mdat`, so faststart;
- `ffprobe -count_frames` equals the decoded frame count (315, 250, 372, 421, 315).

**Evidence.**
- Each JPEG's sha256 matches both `hazard_report.json` and `evidence_manifest.json`.
- The manifest and the report list the same ids in the same order.
- The files on disk are exactly the listed ones.

**Model requests.**
- Each live request was rebuilt from a deterministic re-scan. The rebuilt sha256 equals the stored `request_sha256` for all four runs (f2dee467…, cadabc39…, cb390119…, 21c8f96a…).
- Each request's text, with the image data removed, contains only the neutral clip id as `source_name`.
- No request contains a dataset label, a label fragment or an original file name.

**Data root.** `grep -r` over `data/hazards` for the label strings and original names (`0_te1`, `1_te1`, `3_te1`, `4_tr1`, and so on) hits only `labels/hz_0{0..3}.json`.

## Note: a concurrent API job on hz_00

At 18:12 UTC another client, likely the concurrent UI work, started a review of hz_00 through the API on `:8088`.
- It wrote into the same run dir id, `f12f98a9f3b78349`, because a run id depends only on the video, CFG and weights.
- At 18:14 UTC it repointed `reports/hz_00/latest_run.json` at that run.

What I did:
- Replaced `f12f98a9f3b78349` with a clean copy of the port run recorded above. The copy matches the scratchpad file for file by sha256.
- Restored `latest_run.json` to the original run `ed487eb3f1181f38`.
- Kept that job's audit output in the scratchpad, outside the repo. It is the third sample in the agreement table.

Any later "Check this clip" on hz_00 will again make a port run the default for hz_00.
