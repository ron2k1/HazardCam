# P05 data research: real multi-camera footage for the blind-zone demo

Date: 2026-10-02. Every fact below comes from a URL fetched or curled live that day, or from files downloaded and
opened in this session. "UNVERIFIED" marks claims that could not be checked.

## What the demo needs

- Three or more real cameras recorded at the same time, plus one ground-truth (GT) camera.
- A real event that the GT camera sees and the visible cameras do not, with only indirect cues in the visible views.
- Camera geometry (position, heading, FOV) in a metric frame, so the deterministic triangulation in `tools/` has
  something real to work with.
- Labels from annotations, not from our own judgment.
- A license that allows showing derived clips in a public demo.
- Download with no login, so the pipeline can be rebuilt anywhere.

## Comparison

| Source | Access / registration | License | Sync | Geometry | Event annotations | Size | Downloadable today | Blind-zone fit |
|---|---|---|---|---|---|---|---|---|
| **MEVA KF1** (Kitware/IARPA) | Public S3 bucket, no registration; annotations on public GitLab | CC BY 4.0 | Common wall clock across clips, about 1 s; clip table gives frame offsets inside camera sets | KRTD (K, R, T, distortion) for 29 outdoor cameras in one ENU metric frame; 3-D site mesh | 37 activity types in KPF (769 kitware activity files), with actors and per-frame boxes | 3956 clips, 475.9 GB (drops-123-r13); 5-min 1080p30 H.264 | **Yes**: 39 clips downloaded and size-checked here | **Strong**: wide site; cameras with non-overlapping views; many vehicle and person events |
| StreetAware (NYU) | Metadata open; **video only through Globus (login)** | CC BY-SA 4.0 | Radio-synced, within about 2 frames | Sensor positions on map PDFs; no intrinsics or extrinsics | **None** (only automatic pose and face detections) | About 236 GB audio and video | Metadata yes; video NOT verified (Globus answered "No credentials supplied") | Medium: real streets with 8 synced views, but no labels and ShareAlike |
| Multi-perspective traffic, Sci Data 2026 (Murcia) | Zenodo, open | Data CC BY 4.0 (article text CC BY-NC-ND) | Aligned by hand on a hand-raise frame | Roadside lens metadata only; no extrinsics | Simulated pedestrian fall versus normal crossing (file level) | 10.07 GB zip | Yes (200, Content-Length 10072213813) | Weak: all 3 devices see the fall directly, so there is no blind zone |
| WILDTRACK (EPFL) | Open | **None stated**: treat as all rights reserved | Synced frames | Full OpenCV intrinsics and extrinsics | Pedestrian boxes only, no events | 6.8 GB | Yes (200) | Weak: no events, every camera sees the same plaza, unclear license |
| PETS2009 (Reading) | Anonymous FTP/HTTP | Free for the workshop and research, credit required; no redistribution grant | Approximate; frame drops noted | Tsai calibration | Scripted crowd events (S3) | 1.2 GB (S3 Event Recognition) | **No**: DNS fails and the mirror times out | Weak: low-resolution scripted crowds, all views overlap |
| AI City CityFlowV2 (2022 Track 1) | Google Drive; the access form is gone, but downloading accepts the license | **Non-commercial, academic; no redistribution** | Per-video start offsets | GPS and calibration per camera | Vehicle tracking only, no events | 16.9 GB | Yes (206) | Ruled out by the license and the lack of events |
| NVIDIA PhysicalAI-Traffic-Anomaly-Reasoning | HF, not gated; annotations only | CC BY 4.0 annotations; **videos not redistributed** (8 third-party sources, each with its own terms) | n/a | n/a | Anomaly reasoning text | About 100 MB annotations, about 150 GB videos | Annotations yes | Unusable: single camera only |
| LUMPI (Hannover) | Open directory | CC BY-NC 3.0 | GNSS-pulse synced cameras and LiDAR | Per-session extrinsics to UTM | Boxes and tracks only | About 2.1 GB per measurement | Yes | Weak: non-commercial, no events |
| MTID (Aalborg, Kaggle) | Kaggle API without auth worked | CC BY 4.0 | Synced | Calibration UNVERIFIED | Instance masks only | 3.23 GB | Yes | Unusable: only 2 views |

### Source URLs

- MEVA: https://mevadata.org/ (states "All MEVA data is available for use under a CC BY-4.0 license");
  S3 https://mevadata-public-01.s3.amazonaws.com/ (prefix `drops-123-r13/`);
  annotations, calibration and clip table https://gitlab.kitware.com/meva/meva-data-repo;
  3-D model https://mevadata-public-01.s3.amazonaws.com/mutc-3d-model/;
  site map and camera CSV https://data.kitware.com/api/v1/item/5ce40a518d777f072bc1e920/download;
  paper: Corona et al., "MEVA: A Large-Scale Multiview, Multimodal Video Dataset for Activity Detection", WACV 2021.
- StreetAware: https://doi.org/10.58153/q1byv-qc065 (data record), https://pmc.ncbi.nlm.nih.gov/articles/PMC10099242/
  (Sensors 2023, DOI 10.3390/s23073710), https://github.com/reip-project/street-aware. The Globus endpoint is linked
  from the record.
- Sci Data 2026: https://www.nature.com/articles/s41597-026-06907-y, https://zenodo.org/records/18375218
- WILDTRACK: https://www.epfl.ch/labs/cvlab/data/data-wildtrack/,
  https://openaccess.thecvf.com/content_cvpr_2018/papers/Chavdarova_WILDTRACK_A_Multi-Camera_CVPR_2018_paper.pdf
- PETS2009: http://www.cvg.reading.ac.uk/PETS2009/a.html (unreachable 2026-10-02; terms read from the Wayback snapshot of 2021-07-22)
- AI City: https://www.aicitychallenge.org/ai-city-challenge-dataset-access/,
  https://www.aicitychallenge.org/2022-track1-download/,
  http://www.aicitychallenge.org/wp-content/uploads/2022/02/Dataset-License-AIC2022.pdf
- NVIDIA TAR: https://huggingface.co/datasets/nvidia/PhysicalAI-Traffic-Anomaly-Reasoning
- LUMPI: https://service.tib.eu/ldmservice/dataset/luh-lumpi
- MTID: https://www.kaggle.com/datasets/andreasmoegelmose/multiview-traffic-intersection-dataset

## Decision: MEVA KF1, bus-station pocket configuration

MEVA is the only source that meets all of these at once:

- real, simultaneous multi-camera footage of a real site;
- cameras calibrated into one metric frame;
- human activity annotations that can serve as ground-truth labels;
- a license that allows redistributing derived clips with attribution;
- download with no registration.

The blind zone is a real property of the camera layout; no camera is cropped or hidden to create it.

### Chosen configuration

The selection was made with `scripts/data/find_candidates.py`. Its scratch run covered 49 slots and 5 candidate
visible cameras; the final run covered the 9 downloaded slots and 3 visible cameras. All four cameras are on S3 for 138 five-minute slots
(March 2018), and 91 of those have kitware annotations for the GT camera. More scenarios can be cut from the same setup.

| Role | MEVA camera | Where | ENU position (m) | Heading / H-FOV (deg) |
|---|---|---|---|---|
| GT (`hidden_ground_truth.mp4`, model_access=false) | G341 | Hospital rooftop, about 13 m up | (31.1, -112.7) | 300 / 31.8 |
| cam_a | G506 | Bus station, under the canopy | (-19.6, -93.2) | 353 / 65.2 |
| cam_b | G436 | Hospital, long view to the north | (20.9, -130.1)* | 350 / 28.7* |
| cam_c | G340 | Bus station, facing the north lot | (-16.2, -80.5) | 58 / 34.0 |

\* G436's KRTD changes by date (03-07: 350 deg / 28.7; 03-15: 358.5 deg / 25.5). Each scenario uses the KRTD that
the clip table assigns to that clip.

**Blind pocket.** The curb and lot east of the bus-station building, around ENU (-6, -85). It is drop-off, pick-up and
turnaround space. The GT camera sees it head-on. The visible cameras' ground footprints stop 6–9 m short of it:

- G506 looks north past its west side;
- G340 looks north-east over the lot;
- G436 sees the approach road.

Cars that are seen arriving or leaving in cam_b or cam_c disappear into the pocket. Pedestrians in cam_a/cam_c walk
toward or away from it.

### Sync

MEVA clip names carry wall-clock start times at 1 s resolution. The clip table (`metadata/meva-clip-camera-and-time-table.txt`)
gives frame offsets to a reference camera inside each camera set.

The README (`clip-table-readme.md`) says frame f of clip A equals frame f + offset of reference B. The data fits the
opposite sign:

- With t0_A = t0_B - offset/30, all 1224 referenced rows match their own filename start times to the second.
- With the README's sign, the residuals spread from -8 s to +14 s.
- With the README's sign, the flagship car would leave G436 after it had already reached G341.

So all cameras are placed on the common wall clock from filenames, with ±1 s uncertainty. The clip table confirms this
but does not independently check it, because it agrees exactly. Motion cross-correlation between non-overlapping views
is weak (ncc 0.2–0.45), so it neither confirms nor refutes sync at that level. The flagship hand-off is consistent: the
sedan leaves cam_b about 2 s before it appears in cam_gt.

### Labels

`expected.json` is built only from MEVA kitware activity annotations in the GT clip. It includes the activity ids,
dataset labels, frame spans and an event point. The event point is the actor's box bottom-center at mid-activity,
ray-cast onto the MEVA 3-D mesh.

Negatives are windows with zero GT annotations of any type. Inspection was used only to describe cues in the
flagship and three eval notes, and it is marked as inspection wherever it appears.

## Considered and rejected for the pocket

- **G505** (bus station, a second canopy camera) was rejected. Adding it as a fourth visible camera brings its
  footprint within 8.9 m of the pocket and makes the blind cases fewer and more borderline.
- **Murcia (Sci Data 2026)** is the fallback if MEVA becomes unreachable. It has a real event and CC BY, but a blind
  zone would have to be created by hiding the views that see the fall, which turns the "indirect cues" story into
  "no cues".
