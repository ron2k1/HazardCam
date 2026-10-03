# Astra video hazard review

**Status:** model_review_complete

**Video:** hz_03 · 16.98 s · 421 frames scanned · 35 evidence images

**Model:** nvidia/Qwen3.6-35B-A3B-NVFP4 · **Generated (UTC):** 2026-10-03T19:48:28.117883+00:00

Visual safety screening; observations require qualified safety review.

## Scene

The video shows an industrial manufacturing floor with large machinery, including a blue press, on the left side. A marked aisle with yellow and green painted lines runs along the right side. A worker is observed operating the blue press, and another worker walks through the aisle. A loose circular metal object is present on the floor near the machinery.

## Findings

### H01 · Loose material on walking-working surface

**MEDIUM priority · visible_concern · high confidence**

Cited observations: 0.00–16.94 s (sampled, not continuous). Location: Floor area between the blue press and the marked aisle

**Observed:** A loose circular metal object is resting on the floor in an open area adjacent to the marked aisle. The object is not contained within a designated storage zone and is situated on the walking-working surface.

**Potential risk:** Loose material left on a walking surface outside a marked storage area is a trip hazard under 1910.22(a)(3).

**References:** [1910.22(a)(3)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.22)

**Applicability:** Loose material is on a walking-working surface outside a marked storage area.

**Unknowns:** None listed by model

**Actions:** Relocate the loose object to a designated storage area.; Ensure all raw materials are stored in marked zones to keep walking surfaces clear.

**Evidence:** [E001](evidence/E001.jpg), [E002](evidence/E002.jpg), [E003](evidence/E003.jpg), [E004](evidence/E004.jpg), [E005](evidence/E005.jpg), [E006](evidence/E006.jpg), [E007](evidence/E007.jpg), [E008](evidence/E008.jpg), [E009](evidence/E009.jpg), [E010](evidence/E010.jpg), [E011](evidence/E011.jpg), [E022](evidence/E022.jpg), [E023](evidence/E023.jpg), [E030](evidence/E030.jpg), [E031](evidence/E031.jpg), [E035](evidence/E035.jpg)

## Zone review

- **Z01 — ordinary_scene**: Worker operating a large blue press machine.

- **Z02 — ordinary_scene**: Worker walking along the marked aisle.

- **Z03 — ordinary_scene**: Machinery and yellow safety fencing.

- **Z04 — ordinary_scene**: Aisle area with a worker walking.

- **Z05 — ordinary_scene**: Machinery with yellow safety guards.

- **Z06 — hazard_candidate**: Loose circular metal object on the floor near the blue press.

- **Z07 — ordinary_scene**: Machinery and equipment.

- **Z08 — ordinary_scene**: Aisle area with containers and fire extinguisher.

- **Z09 — ordinary_scene**: Machinery and safety fencing.

- **Z10 — hazard_candidate**: Loose circular metal object on the floor.

## Dismissed or unsubstantiated candidates

- **Machine guarding**: Machinery is present, but no worker is visibly in danger or reaching into a hazard zone. No immediate violation observed.

- **Lockout/Tagout**: No visible servicing or maintenance activity is occurring. The absence of a lock/tag does not establish a violation.

- **PPE (Eye protection)**: No visible eye/face hazard exposure is confirmed in the video frames.

## Limitations

- Visual screening against OSHA General Industry references; jurisdiction and legal compliance are not established.

- All frames scanned by CV; Qwen reviewed only the listed sampled frames and crops. No audio analyzed.

- Observation spans do not establish continuity; hidden controls, energy state, and training cannot be verified.

- Static region ranking is heuristic, not a complete obstruction detector; no clear-scene baseline or metric clearance calibration is available.

- Camera housing, occlusion, resolution and sampling can hide hazards.

- The bounded citation library is not an exhaustive factory-safety checklist; machine-specific rules need further review.

- No reliable floor-like mask found; static-zone ranking uses general scene candidates.

- No reliable floor-like mask found; static-zone ranking uses general scene candidates.

- Machine operation status and energy isolation state are inferred from still frames and cannot be confirmed.

## Processing evidence

Segmentation: local YOLO11s boxes on the temporal background + edge contours

![Proposed zones](zones_overview.jpg)

![Motion heatmap](motion_heatmap.png)

[Annotated video](processed.mp4)

[Evidence manifest](evidence_manifest.json)

[Full machine-readable report](hazard_report.json)

## Official references

- [1910.22(a)(3) — Walking-working surfaces](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.22) · checked 2026-10-03

- [1910.176(a) — Aisles and material handling](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.176) · checked 2026-10-03

- [1910.176(b) — Secure material storage](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.176) · checked 2026-10-03

- [1910.212(a)(3)(ii) — Point-of-operation guarding](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.212) · checked 2026-10-03

- [1910.217(c)(1)(i) — Mechanical power press safeguarding](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.217) · checked 2026-10-03

- [1910.147(a)(2) — Hazardous energy control applicability](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.147) · checked 2026-10-03

- [1910.133(a)(1) — Eye and face protection](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.133) · checked 2026-10-03

- [1910.37(a)(3) — Unobstructed exit routes](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.37) · checked 2026-10-03