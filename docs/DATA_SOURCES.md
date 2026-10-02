# Real Data Sources

The judged demo uses prepared local files only. Internet data is for acquisition before the run and is never a live
dependency. Full comparison and evidence: `artifacts/data/research.md` (checked live 2026-10-02).

## Source comparison (summary)

| Source | Registration | License | Geometry | Event labels | Verdict |
|---|---|---|---|---|---|
| [MEVA KF1](https://mevadata.org/) ([S3](https://mevadata-public-01.s3.amazonaws.com/), [annotations](https://gitlab.kitware.com/meva/meva-data-repo)) | None | CC BY 4.0 | KRTD calibration in one ENU metric frame, 3-D site mesh | 37 activity types, KPF | **Chosen** |
| [StreetAware](https://doi.org/10.58153/q1byv-qc065) | Globus login for video | CC BY-SA 4.0 | Sensor map PDFs only | None | Backup only; needs login (see `artifacts/data/BLOCKERS.md`) |
| [Sci Data 2026 multi-perspective](https://zenodo.org/records/18375218) ([article](https://www.nature.com/articles/s41597-026-06907-y)) | None | CC BY 4.0 (data) | Lens metadata only | Simulated fall vs normal | Fallback; all views see the event, so no blind zone |
| [WILDTRACK](https://www.epfl.ch/labs/cvlab/data/data-wildtrack/) | None | Not stated | Full calibration | Pedestrian boxes only | Rejected (license, no events) |
| [PETS2009](http://www.cvg.reading.ac.uk/PETS2009/a.html) | None | Research use only | Tsai calibration | Scripted crowd events | Rejected (servers unreachable, all views overlap) |
| [AI City CityFlowV2](https://www.aicitychallenge.org/ai-city-challenge-dataset-access/) | Form removed; download accepts the license | Non-commercial, no redistribution | GPS + calibration | Tracking only | Rejected (license, no events) |
| [NVIDIA PhysicalAI-TAR](https://huggingface.co/datasets/nvidia/PhysicalAI-Traffic-Anomaly-Reasoning) | None | CC BY 4.0 annotations; videos not redistributed | n/a | Anomaly reasoning | Rejected (single camera, third-party videos) |
| [LUMPI](https://service.tib.eu/ldmservice/dataset/luh-lumpi) / [MTID](https://www.kaggle.com/datasets/andreasmoegelmose/multiview-traffic-intersection-dataset) | None | CC BY-NC 3.0 / CC BY 4.0 | Extrinsics / unverified | Boxes / masks only | Rejected (no events; MTID has 2 views) |

## Chosen approach: MEVA bus-station pocket

The camera configuration is fixed across all scenarios:

| Role | Camera | Location | Notes |
|---|---|---|---|
| Withheld GT (`hidden_ground_truth.mp4`, `model_access: false`) | G341 | Hospital rooftop | Sees the pocket |
| `cam_a` | G506 | Bus station canopy | Footprint ends 6–9 m from the pocket |
| `cam_b` | G436 | Hospital, long view of the approach road | Footprint ends 6–9 m from the pocket |
| `cam_c` | G340 | Bus station, facing the north lot | Footprint ends 6–9 m from the pocket |

The pocket is the curb and lot east of the bus-station building, where people are dropped off and picked up and
vehicles turn around. The visible cameras see cars and people go into and out of it, but not what happens there.

- **Prepared scenarios.** `data/manifests/scenario_001.json` is the flagship drop-off. `eval_001`…`eval_021` hold 7
  positives, 7 ambiguous and 7 negatives, drawn from 9 MEVA slots. Each prepared scenario directory contains:
  - `data/prepared/<id>/cam_{a,b,c}.mp4` and `hidden_ground_truth.mp4`: 24–30 s, H.264, yuv420p, faststart, no
    audio, 1280 px wide. Every file starts at scenario t = 0, so `time_offset_s` is 0.
  - `expected.json`: judge-only. Labels come from MEVA annotations.
  - `evidence/contact_sheet.jpg`
- **Geometry.** Positions are local metres (x east, y north) from the MEVA ENU frame minus origin (-5, -101). Heading
  is the compass bearing of the KRTD optical axis, and FOV is the horizontal FOV at 1920 px. Expect about 1–3 m and
  1–2 deg of error, and 2–5 m for mapped event points.
- **Sync.** All cameras are placed on the common wall clock from clip filenames, ±1 s. The MEVA clip table agrees
  exactly with the filenames once its offset sign is read as t0_A = t0_ref − offset/30. The README states the
  opposite sign; see `artifacts/data/research.md`.
- **Attribution** (required, CC BY 4.0, also embedded in every manifest's `provenance`): "'Multiview Extended Video
  with Activities' (MEVA) dataset by Kitware Inc. and the Intelligence Advanced Research Projects Activity (IARPA) is
  licensed under a Creative Commons Attribution 4.0 International License."
  Clips were trimmed, scaled and re-encoded.

### Reproduce (no credentials, about 10.5 GB raw: 6.2 GB video + 4.3 GB repo clone)

Keep the raw dir outside OneDrive and outside the repo. The event-day machine can use any path.

```bash
RAW=~/aum-data/raw
python scripts/data/fetch_meva.py --raw-dir $RAW index      # S3 listing (476 GB available; nothing downloaded yet)
python scripts/data/fetch_meva.py --raw-dir $RAW repo       # sparse clone: metadata + kitware annotations
python scripts/data/fetch_meva.py --raw-dir $RAW ground     # 31 MB ground mesh
python scripts/data/fetch_meva.py --raw-dir $RAW clips --cameras G341,G506,G436,G340 \
  --slots 2018-03-07.17-00-00,2018-03-07.10-55-00,2018-03-12.10-55-00,2018-03-12.11-00-00,2018-03-13.16-05-00,2018-03-15.14-55-00,2018-03-15.15-00-00,2018-03-15.15-35-00,2018-03-15.15-40-00
python scripts/data/find_candidates.py --raw-dir $RAW --gt G341 --visible G506,G436,G340 --slots <same list>
python scripts/data/prepare_scenario.py --raw-dir $RAW      # reads scripts/data/scenario_specs.json
```

`*.mp4` under `data/prepared/` is gitignored. Ship the prepared files in the offline bundle or rebuild them with the
commands above.

## Candidate-finding strategy (implemented in `scripts/data/find_candidates.py`)

1. **Annotation signal (preferred).** Every annotated activity in the GT camera is located on the ground and tested
   for direct visibility in each visible camera. Visibility means either the projected point lands in the image, or
   the same activity is co-annotated there. Windows are ranked by:
   - salience;
   - the number of visible cameras with concurrent annotated activity nearby;
   - a penalty for direct visibility.
2. **Motion signal (confirmation, and the only signal for unannotated footage).**
   - Decode with ffmpeg at 2 fps, in grayscale.
   - Compute frame-difference energy and robust-z normalize it per camera.
   - Rank windows where one camera spikes and the others change within ±2 s.
   - Report pairwise cross-correlation lags.
   - `--scenario-dir` runs this on any folder of aligned videos.
3. Inspect the top windows with contact sheets, cut scenarios of 24–30 s, and keep one camera as the withheld GT.

## Live public streams

Only use automated access where the provider permits it. Never make the judged path depend on a public stream staying
online. If a live feed is shown, treat it as optional ambience or context, never as the only demo scenario.
