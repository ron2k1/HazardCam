# Astra video hazard review

**Status:** model_review_complete

**Video:** hz_02 · 14.98 s · 372 frames scanned · 29 evidence images

**Model:** nvidia/Qwen3.6-35B-A3B-NVFP4 · **Generated (UTC):** 2026-10-03T19:48:22.282297+00:00

Visual safety screening; observations require qualified safety review.

## Scene

The video shows a manufacturing floor with large industrial machinery (presses) on the left and a marked pedestrian aisle on the right. Workers are observed walking in the aisle and standing near the machinery. A large circular metal object is stored on the floor in an open area adjacent to the marked aisle. The scene is generally well-lit, though some areas near the machinery are cluttered.

## Findings

### H01 · Trip hazard from loose material on walking-working surface

**MEDIUM priority · visible_concern · high confidence**

Cited observations: 0.00–14.94 s (sampled, not continuous). Location: Center of the scene, on the floor adjacent to the yellow aisle marking

**Observed:** A large circular metal object is resting directly on the concrete floor. It is positioned outside of any marked storage area and encroaches upon the space adjacent to the marked yellow aisle line. The object is a loose item on a walking-working surface.

**Potential risk:** The object presents a tripping hazard for workers moving through the area or near the aisle. Its placement outside a designated storage zone is a potential violation of walking-working surface requirements.

**References:** [1910.22(a)(3)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.22)

**Applicability:** The object is a loose material left on a walking surface outside a marked storage area.

**Unknowns:** Applicability of 1910.176(a) regarding mechanical handling equipment and intended aisle clearance requires site verification.; The specific identity of the object (e.g., coil, die) is uncertain but does not negate the trip hazard.

**Actions:** Relocate the object to a designated storage area.; Ensure the aisle and surrounding walking surfaces are kept clear of stored materials.

**Evidence:** [E001](evidence/E001.jpg), [E002](evidence/E002.jpg), [E003](evidence/E003.jpg), [E004](evidence/E004.jpg), [E005](evidence/E005.jpg), [E006](evidence/E006.jpg), [E007](evidence/E007.jpg), [E008](evidence/E008.jpg), [E009](evidence/E009.jpg), [E010](evidence/E010.jpg), [E011](evidence/E011.jpg), [E029](evidence/E029.jpg)

## Zone review

- **Z01 — ordinary_scene**: Pedestrian aisle with workers walking and standing.

- **Z02 — ordinary_scene**: Machinery area with workers standing near equipment.

- **Z03 — hazard_candidate**: Floor area containing a large circular metal object stored on the ground.

- **Z04 — ordinary_scene**: Storage area along the wall with bins and containers.

- **Z05 — ordinary_scene**: Machinery area with workers.

- **Z06 — ordinary_scene**: Close-up of machinery side.

- **Z07 — ordinary_scene**: Close-up of machinery component.

## Dismissed or unsubstantiated candidates

- **Machine guarding**: While workers are near machinery, there is no visible evidence of them reaching into a danger zone or operating the machine in a way that suggests immediate guarding failure. The machinery appears to have guards in place.

- **Lockout/Tagout**: No visible servicing or maintenance activity is occurring that would require lockout/tagout. The absence of locks does not indicate a violation.

- **PPE (Eye Protection)**: Workers are visible, but their eye protection status is not clearly discernible in the provided frames. No obvious eye hazard exposure is confirmed.

## Limitations

- Visual screening against OSHA General Industry references; jurisdiction and legal compliance are not established.

- All frames scanned by CV; Qwen reviewed only the listed sampled frames and crops. No audio analyzed.

- Observation spans do not establish continuity; hidden controls, energy state, and training cannot be verified.

- Static region ranking is heuristic, not a complete obstruction detector; no clear-scene baseline or metric clearance calibration is available.

- Camera housing, occlusion, resolution and sampling can hide hazards.

- The bounded citation library is not an exhaustive factory-safety checklist; machine-specific rules need further review.

- No reliable floor-like mask found; static-zone ranking uses general scene candidates.

- No reliable floor-like mask found; static-zone ranking uses general scene candidates.

- Video is a still-frame sequence; continuous motion or activity changes are not fully captured.

- PPE compliance cannot be definitively assessed due to image resolution and distance.

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