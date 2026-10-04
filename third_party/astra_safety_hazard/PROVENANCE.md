# astra_video_hazard.py: provenance

| | |
|---|---|
| File | `astra_video_hazard.py` (byte-identical copy, never edited) |
| sha256 | `ae92565bdd6daff3332f2fe4d3c6669533b7eee16d32ce6fef23e42986eba132` |
| Author | Ronil Basu (Safety hazard track, event day 2026-10-03) |
| Origin | operator's USB drive `GB10_BUNDLE/safety_hazard/astra_video_hazard.py`; same bytes as the local copy `/home/dell/factory-safety-agent/safety_hazard/astra_video_hazard.py` |
| Pipeline version | `astra-1.1` (`CFG["pipeline_version"]`) |
| Example run | `example_output/` next to the script: Ollama `qwen3.6:35b-a3b` (digest `a7eb95c5…`) on macOS 26.6.2 x86_64, Python 3.10.16, OpenCV 4.12, FastSAM-s weights (`c9f78716…`); input `4_tr1.mp4` (sha256 `d80a7143…`, 315 frames at 24.99 fps, 1920x1080); status `model_review_complete`, 10 zones, 35 evidence images, 2 findings (aisle obstruction; worker near the press point of operation) |

The file is reference material. Nothing imports or runs it. The app runs the port in
`hazards/` (`scan.py`, `review.py`, `report.py`, `pipeline.py`), whose tests compare the
prompts, the STANDARDS table, `CFG`, the quality-warning wording, the limitations and the
step messages against this file through `ast` (`tests/unit/hazards/test_upstream_parity.py`).

## What the port changes, and why

| Upstream | Port (`hazards/`) | Why |
|---|---|---|
| Ollama `/api/chat` (`format=schema`, `think=False`, `options`) | The profile's OpenAI-compatible vLLM endpoint through `inference.client.ChatClient`. Each evidence item is a user message holding its JSON text and the image as an `image_url` data URL. `response_format` is `json_schema` with `strict: true`. Thinking is off through the profile's `think_param` (`chat_template_kwargs.enable_thinking=false`). Temperature 0, seed 42, `max_tokens` 6000 (= `num_predict`), 900 s timeout | Qwen is served by vLLM on the GB10 (`nvidia/Qwen3.6-35B-A3B-NVFP4`, profile `gb10`). The app may only call the local model from the active profile |
| `/api/tags` + `/api/show` model check; Ollama digest in the cache key | `GET /v1/models`: the served id, root and `max_model_len` are hashed into a fingerprint, and that fingerprint goes into the request sha256 | vLLM has no digest or capability endpoint |
| `prompt_eval_count` / `eval_count` | `prompt_tokens` / `completion_tokens` from `usage` | OpenAI usage fields |
| FastSAM-s masks on the temporal background (falling back to edge contours) | Local YOLO boxes (`yolo11s.pt`, optional `yolov8s-worldv2.pt` with its built-in vocabulary) from the detector service on `127.0.0.1:8003`, run on the same temporal background image. Each box becomes a rectangular mask. Candidates = YOLO boxes UNION the original edge-contour masks. The floor mask always comes from the edge-contour masks | FastSAM and Ollama are not on this machine and nothing new is downloaded. The `.venv` has no torch, so YOLO runs in a local container. The union keeps recall at or above the original fallback. YOLO gives boxes, not floor regions |
| `segmentation_method` `FastSAM-s temporal-background masks` | `local YOLO11s boxes on the temporal background + edge contours`. When the detector does not answer (unreachable, error, models missing) it stays the original `edge-contour fallback`, and the original quality warning is added. When the detector answers with zero boxes the YOLO method name stays and the candidates are exactly the edge contours (`pipeline.detector.status` = `no_boxes`, `boxes` = 0) | The fallback marks a missing segmenter, as upstream does when FastSAM is not installed. The detector status is recorded in the report (`pipeline.detector`) and in `run_manifest.json` |
| `segmentation_weights_sha256` = FastSAM sha256 | `{model: sha256}` of the YOLO weights the detector used (from its `/health`), also `run_manifest.json` `weights_sha256` and part of the run id | Provenance of the proposal model |
| pandas CSVs, matplotlib figures | `csv` module; `zones_overview.jpg` (annotated first frame) and `motion_heatmap.png` (`cv2.applyColorMap` magma over the background). No `source_overview.png`, `motion_summary.png` or contact sheet | No pandas/matplotlib in the `.venv`, and no new dependencies |
| `cv2.VideoWriter` `avc1`/`mp4v` -> `<stem>_processed.mp4` | cv2 writes a lossless FFV1 intermediate, then ffmpeg makes `processed.mp4`: libx264, yuv420p, `+faststart`, same fps. The frame count is checked with cv2 and with `ffprobe -count_frames` | This OpenCV build cannot encode avc1, and mp4v does not play in Chrome |
| `source_name` = the input file name | `source_name` = a neutral clip id (`hz_00`, `hz_01`, ...) | The original run sent `4_tr1.mp4` to the model. Dataset file names start with the label index (`4_` = `4_safe_walkway`), which leaks the label. Labels live only in judge-only `data/hazards/labels/` |
| `RUN_ID` = sha256(source, CFG, FastSAM sha)[:16] | sha256(source, CFG, detector sha256s, `astra-1.1-gb10`)[:16] | Separates port runs from upstream runs and detector-up from detector-down runs |
| `assert` | Explicit raises (survive `python -O`) | Same checks |
| Audit-pass errors caught: `RequestException`, `ValueError`, `KeyError` | Also catches `ModelCallError` (the ChatClient's HTTP failure) | The equivalent of `requests` HTTP errors |
| print / log capture | `logging`. The six progress messages are passed verbatim to `progress(step, 6, message)` and saved as `progress.json` | The API streams them over SSE |
| — | `hazard_report.json` adds `instructions` {`system_prompt`, `audit_prompt`} and `pipeline` {`version: astra-1.1-gb10`, `ported_from_sha256`, detector, zone sources, quality warnings} | Technical view and provenance |

## Video assumptions kept unchanged

Every video is treated exactly as the script treats it. The tests marked (T) exercise an
item on synthetic video (`tests/unit/hazards/test_video_assumptions.py` and the end-to-end
test).

- Fixed camera: no stabilisation, and zones are image-space boxes for the whole clip.
- Every frame is decoded. Above `max_frames` 15000 the scan aborts, and it needs at least 2 frames (T).
- Frames are resized to `analysis_width` 768 (never upscaled) with `INTER_AREA`, height rounded (T).
- Timing = `frame_index / source_fps` (T).
- Background = per-pixel median of 21 evenly spaced frames, `np.unique(linspace(0, N-1, min(N, 21)).astype(int))` (T).
- Motion = adjacent-frame difference OR background difference `> 18` on 5x5 Gaussian-blurred gray, then open 3x3 and close 7x7 (T).
- Quality warnings, with the same wording and thresholds (T):
  - container vs decoded frame-count mismatch;
  - `step_fraction > 0.35`;
  - `phaseCorrelate` median shift `> 3` px over responses `> 0.2`;
  - no floor-like mask;
  - static-proposal fallback.
- Movement zones: heatmap `> 0.012`, close 11x11, area `>= 0.0008` of the frame and box `<= 0.6` of the frame, peak = argmax of the zone trace, active window where the trace is `> max(0.01, 15%` of its peak`)` (T).
- Floor mask: region `> 4%` of the frame, bottom 3 rows `> 2%` covered, median saturation `< 70`, Canny edge density `< 0.06` (T). Paint = HSV `(18,65,55)`–`(90,255,255)`, dilated 21x21 (restricted to near-floor paint when a floor exists).
- Static candidates: area 0.2%–15% of the frame, box at least 12x12 px and `<= 20%` of the frame. Excluded when `> 50%` floor or `> 60%` paint. Score = `sqrt(area_frac) * stability * (0.05 + floor_contact)^2 * (1 + 2 * paint_proximity)`, with a 15x15 ring for floor contact (0.5 without a floor) (T for the union and the floor rule).
- `select_distinct` with IoU 0.6, at most 5 movement + 5 static zones, ids `Z01`... movement first (T).
- Evidence, identical in order and number (T):
  - 8 uniform full-scene frames plus 3 motion peaks at least 0.7 s apart (sorted, de-duplicated);
  - per zone, a crop at its peak frame and at the opposite end, padded by `max(50, 25%` of the longer side`)`;
  - 4 overlapping 55% scene tiles at the middle frame.
  Images come from original-resolution frames: full scenes at most 1024 px wide, crops at most 768. Each has a 36 px header with the burned-in label `E### | t=…s | kind | Z##`, JPEG quality 92 and a 40-image budget.
- Processed video: analysis resolution, 28 px banner `t=…s | M: movement | S: stationary review candidate`, zone boxes and tags.
- Same SYSTEM_PROMPT, AUDIT_PROMPT, STANDARDS table (checked 2026-10-03), pydantic schema and enums, `validate_model_report` rules, one repair turn, sha256 caches (`qwen_<key>.json`, `qwen_audited_<key>.json`) and the same limitations text (the Markdown keeps "sampled, not continuous").

Same machine, same result: `tests/unit/hazards/test_upstream_video_parity.py` executes the
upstream statements of steps 1-4 (everything except imports, matplotlib, pandas and
print) and the port on five generated clips:
- static scene;
- camera shake (translation warning);
- lighting flash (global-change warning);
- 400x300 six-frame clip;
- outlined floor (floor-mask branch).

Metadata, motion arrays, quality warnings, proposals, zones, the floor mask, annotated
frames and every evidence JPEG are identical, byte for byte where both write a file.

Known platform difference against the original macOS run of `4_tr1.mp4` (edge-contour
fallback on the GB10):
- Movement zones match within ±3 px, with `proposal_score` within 0.5%.
- Two movement zones' peak frames differ: Z02 frame 1 vs 7, Z03 frame 15 vs 16. Their
  zone crops show neighbouring moments.
- One of the three full-scene motion-peak frames differs (frame 3 vs 7).
- The 8 uniform frames and the 4 tiles are identical.
- The cause is H.264 decode, colour conversion and the `np.argsort` tie order, which
  differ slightly between OpenCV/numpy builds (macOS OpenCV 4.12 / numpy 1.26 vs GB10
  OpenCV 5.0 / numpy 2.5).
- The original run's FastSAM static zone on the aisle object (its Z07) is not among the
  edge-contour fallback's zones. That fallback is the recall limit the upstream warning
  describes.
