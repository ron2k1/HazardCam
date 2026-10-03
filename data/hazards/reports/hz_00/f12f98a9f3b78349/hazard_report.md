# Astra video hazard review

**Status:** model_review_complete

**Video:** hz_00 · 12.61 s · 315 frames scanned · 35 evidence images

**Model:** nvidia/Qwen3.6-35B-A3B-NVFP4 · **Generated (UTC):** 2026-10-03T19:48:36.460820+00:00

Visual safety screening; observations require qualified safety review.

## Scene

The video shows an industrial manufacturing area with a large blue press machine on the left and a marked pedestrian walkway on the right. A worker is seated at the machine, appearing to be in a stationary position near the point of operation. A large metal coil is stored on a pallet in the central area, adjacent to a marked yellow line. A worker is observed walking along the marked green walkway in the background.

## Findings

### H01 · Trip hazard from loose material on walking surface

**MEDIUM priority · visible_concern · high confidence**

Cited observations: 0.00–12.57 s (sampled, not continuous). Location: Central floor area, adjacent to the yellow aisle marking

**Observed:** A large metal coil is resting on a wooden pallet on the floor. The coil and pallet are positioned immediately adjacent to a yellow painted line, with the coil encroaching across the boundary of the marked path/aisle. This loose material on a walking surface constitutes a trip hazard.

**Potential risk:** The coil presents a tripping hazard for personnel moving through the area. Its placement on the walking surface is a violation of walking-working surface standards.

**References:** [1910.22(a)(3)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.22)

**Applicability:** The object is a loose material (coil) left on a walking surface outside a marked storage area, creating a trip hazard.

**Unknowns:** Applicability of 1910.176(a) regarding mechanical handling equipment and intended aisle clearance requires site verification.

**Actions:** Relocate the metal coil to a designated storage area that does not obstruct marked aisles or walking surfaces.; Ensure all materials are stored in a manner that does not create hazards on walking-working surfaces.

**Evidence:** [E001](evidence/E001.jpg), [E002](evidence/E002.jpg), [E003](evidence/E003.jpg), [E004](evidence/E004.jpg), [E005](evidence/E005.jpg), [E006](evidence/E006.jpg), [E007](evidence/E007.jpg), [E008](evidence/E008.jpg), [E009](evidence/E009.jpg), [E010](evidence/E010.jpg), [E011](evidence/E011.jpg), [E030](evidence/E030.jpg), [E031](evidence/E031.jpg)

## Zone review

- **Z01 — ordinary_scene**: A marked pedestrian walkway (green with yellow borders) is visible. A worker is seen walking along this path in the background.

- **Z02 — ordinary_scene**: A yellow industrial fan is visible in the background. It is stationary and not encroaching on the main walkway.

- **Z03 — hazard_candidate**: A worker is seated at a large blue press machine. The worker is positioned close to the machine's controls and point of operation. The worker's hands are near the machine opening.

- **Z04 — ordinary_scene**: An orange machine (possibly a shear or cutter) is visible. No personnel are in the immediate danger zone.

- **Z05 — ordinary_scene**: Close-up of the blue press machine's control panel and warning labels.

- **Z06 — ordinary_scene**: The marked pedestrian walkway is clear of obstructions. A worker is seen walking along it.

- **Z07 — ordinary_scene**: A purple bin containing metal shavings is located near the machine. It is stationary and does not obstruct the main path.

- **Z08 — ordinary_scene**: A yellow safety cage/guard is visible near the machine base.

- **Z09 — ordinary_scene**: Close-up of the blue press machine's warning labels and structure.

- **Z10 — hazard_candidate**: A large metal coil on a pallet is stored on the floor, encroaching on a marked yellow line/aisle.

## Dismissed or unsubstantiated candidates

- **Machine guarding/LOTO for the blue press**: The worker is seated at the machine, but the machine's energy state (running vs. stopped) and whether the worker is performing active operation or maintenance cannot be determined from the still frames. Without visible movement or clear servicing activity, a guarding or LOTO violation cannot be confirmed.

- **Eye protection for the worker**: The worker's face is partially obscured by their hand and the angle. It is not possible to confirm if they are wearing safety glasses or if they are exposed to eye hazards.

## Limitations

- Visual screening against OSHA General Industry references; jurisdiction and legal compliance are not established.

- All frames scanned by CV; Qwen reviewed only the listed sampled frames and crops. No audio analyzed.

- Observation spans do not establish continuity; hidden controls, energy state, and training cannot be verified.

- Static region ranking is heuristic, not a complete obstruction detector; no clear-scene baseline or metric clearance calibration is available.

- Camera housing, occlusion, resolution and sampling can hide hazards.

- The bounded citation library is not an exhaustive factory-safety checklist; machine-specific rules need further review.

- No reliable floor-like mask found; static-zone ranking uses general scene candidates.

- No reliable floor-like mask found; static-zone ranking uses general scene candidates.

- Machine operation status is unknown; no continuous movement is visible to confirm active cycles.

- PPE compliance cannot be fully verified due to image resolution and occlusion.

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