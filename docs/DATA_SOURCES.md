# Real Data Sources

The judged demo should use prepared local files. Internet data is for acquisition before the run, not a live dependency.

## 1) AI City Challenge real multi-camera data

2021 page (details and historical data):
https://www.aicitychallenge.org/2021-data-and-evaluation/

Current quick-access page:
https://www.aicitychallenge.org/ai-city-challenge-dataset-access/

Useful characteristics documented by AI City:
- synchronized urban traffic camera video exists in historical multi-camera tracks
- CityFlowV2 has multiple cameras/intersections with per-video start offsets for synchronization
- traffic anomaly track includes real crash/stalled-vehicle anomalies

**Important current availability note:** the quick-access page may expose only selected historical tracks. Use whichever currently downloadable track meets the demo need; do not assume every 2021 track remains downloadable from the quick-access page.

## 2) NVIDIA PhysicalAI Traffic Anomaly Reasoning (TAR)

Dataset:
https://huggingface.co/datasets/nvidia/PhysicalAI-Traffic-Anomaly-Reasoning

Download guide:
https://huggingface.co/datasets/nvidia/PhysicalAI-Traffic-Anomaly-Reasoning/blob/main/DOWNLOADING.md

The release provides reasoning annotations and scripts for retrieving source videos. Do not download the full corpus unless needed. Prefer a small source subset.

Example from the current dataset docs:
```bash
python download_videos.py --install-deps
python download_videos.py --out ./videos --only htv tad_bench vad_r1
```

Check upstream licenses/terms for each source and record them in the scenario manifest.

## Candidate-finding strategy

Do not manually scrub dozens of hours.

1. downsample synchronized clips to ~2 fps
2. compute frame difference / optical flow energy per camera
3. cross-correlate camera timelines
4. rank windows where one camera has a strong event and neighbors show near-synchronous secondary changes
5. inspect the top ~20 windows
6. select 10–20 second scenario
7. keep one camera as withheld ground truth

## Live public streams

Only use automated access where the provider permits it. Never make the judged path depend on a public stream staying online. If a live feed is shown, treat it as optional ambience/context rather than the only demo scenario.
