# Astra video blind-spot review

**Status:** preprocessing_only

**Video:** bs_02 · 15.00 s · 450 frames scanned · 24 evidence images

**Model:** not run · **Generated (UTC):** 2026-10-03T19:40:11.122929+00:00

Visual safety screening; observations require qualified safety review.

## Scene

Qwen review not completed; no hazard conclusions are available.

## Findings

No model findings available.

## Zone review

## Dismissed or unsubstantiated candidates

## Limitations

- Visual screening against OSHA General Industry references; jurisdiction and legal compliance are not established.

- All frames scanned by CV; Qwen reviewed only the listed sampled frames and crops. No audio analyzed.

- Observation spans do not establish continuity; hidden controls, energy state, and training cannot be verified.

- Static region ranking is heuristic, not a complete obstruction detector; no clear-scene baseline or metric clearance calibration is available.

- Camera housing, occlusion, resolution and sampling can hide hazards.

- The bounded citation library is not an exhaustive factory-safety checklist; machine-specific rules need further review.

- A single fixed camera cannot see behind racks or stacks; blind spots are judged from this one view and need a walk-through to confirm.

- No reliable floor-like mask found; static-zone ranking uses general scene candidates.

## Processing evidence

Segmentation: local YOLO11s boxes on the temporal background + edge contours

![Proposed zones](zones_overview.jpg)

![Motion heatmap](motion_heatmap.png)

[Annotated video](processed.mp4)

[Evidence manifest](evidence_manifest.json)

[Full machine-readable report](hazard_report.json)

## Official references

- [1910.178(n)(4) — Truck travel where vision is obstructed](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.178) · checked 2026-10-03

- [1910.178(n)(6) — Clear view of the path of travel](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.178) · checked 2026-10-03

- [1910.176(a) — Aisles and material handling](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.176) · checked 2026-10-03

- [1910.22(a)(3) — Walking-working surfaces](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.22) · checked 2026-10-03