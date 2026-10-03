# Astra video blind-spot review

**Status:** model_review_complete

**Video:** bs_01 · 15.00 s · 450 frames scanned · 35 evidence images

**Model:** nvidia/Qwen3.6-35B-A3B-NVFP4 · **Generated (UTC):** 2026-10-03T19:40:03.170091+00:00

Visual safety screening; observations require qualified safety review.

## Scene

The video shows a warehouse environment with tall racks, stacked pallets, and an IBC tote. Pedestrians are visible in various locations, including walking in aisles and standing near vehicle areas. A forklift is visible in the background and parked in a designated area. The scene is well-lit.

## Findings

### H01 · Pedestrian blind spot at cross-aisle intersection

**HIGH priority · visible_concern · high confidence**

Cited observations: 0.00–14.97 s (sampled, not continuous). Location: Center of the main aisle where it intersects with the cross-aisle on the right

**Observed:** A pedestrian in a white suit is seen walking in the main aisle. At the intersection with the cross-aisle (right side of the frame), the view of the cross-aisle is partially blocked by stacked pallets and the end of the rack row on the left. A forklift is visible further down the main aisle. A pedestrian in a yellow vest is seen walking near the intersection. The pedestrian in the white suit is at risk of not seeing a vehicle or pedestrian coming from the cross-aisle, and vice-versa.

**Potential risk:** A pedestrian or vehicle could emerge from the cross-aisle without being seen by the other party, leading to a collision. This is a classic blind spot scenario at an intersection.

**References:** [1910.178(n)(4)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.178), [1910.176(a)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.176)

**Applicability:** The intersection is a location where vision is obstructed for both pedestrians and potential vehicles. Safe clearances and visibility are required.

**Unknowns:** Vehicle traffic rules at the intersection; Speed of any vehicles

**Actions:** Install a convex mirror at the corner of the cross-aisle to improve visibility.; Mark a stop line for pedestrians and vehicles at the intersection.; Implement a horn-signal protocol for vehicles approaching the intersection.; Consider a designated pedestrian crossing with high-visibility markings.

**Evidence:** [E001](evidence/E001.jpg), [E002](evidence/E002.jpg), [E003](evidence/E003.jpg), [E004](evidence/E004.jpg), [E005](evidence/E005.jpg), [E006](evidence/E006.jpg), [E007](evidence/E007.jpg), [E008](evidence/E008.jpg), [E009](evidence/E009.jpg), [E010](evidence/E010.jpg), [E011](evidence/E011.jpg), [E012](evidence/E012.jpg), [E013](evidence/E013.jpg), [E033](evidence/E033.jpg)

### H02 · Pedestrian walking in vehicle travel lane

**MEDIUM priority · visible_concern · high confidence**

Cited observations: 0.00–14.97 s (sampled, not continuous). Location: Right side of the main aisle, within the yellow-lined area designated for vehicle/pallet storage

**Observed:** A pedestrian in a yellow vest is seen walking along the yellow line that demarcates a vehicle/pallet storage area. A forklift is parked within this area. Another pedestrian in a white shirt is standing near the edge of this area. The pedestrian in the yellow vest is walking in close proximity to where a forklift would operate.

**Potential risk:** A pedestrian walking in a vehicle travel lane is at high risk of being struck by a forklift or other vehicle, especially if the vehicle is reversing or turning.

**References:** [1910.176(a)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.176), [1910.22(a)(3)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.22)

**Applicability:** Aisles and passageways must be kept clear and appropriately marked. Walking-working surfaces must be free of hazards.

**Unknowns:** Whether the area is exclusively for vehicles; If pedestrians are authorized to walk there

**Actions:** Clearly mark pedestrian walkways separate from vehicle lanes.; Enforce a policy that pedestrians must use designated walkways.; Install physical barriers (e.g., guardrails) to separate pedestrian and vehicle areas if possible.; Train pedestrians on the importance of staying out of vehicle lanes.

**Evidence:** [E001](evidence/E001.jpg), [E002](evidence/E002.jpg), [E003](evidence/E003.jpg), [E004](evidence/E004.jpg), [E005](evidence/E005.jpg), [E006](evidence/E006.jpg), [E007](evidence/E007.jpg), [E008](evidence/E008.jpg), [E009](evidence/E009.jpg), [E010](evidence/E010.jpg), [E011](evidence/E011.jpg), [E014](evidence/E014.jpg), [E015](evidence/E015.jpg), [E022](evidence/E022.jpg), [E023](evidence/E023.jpg), [E035](evidence/E035.jpg)

### H03 · Obstructed view of pedestrian in rack aisle

**MEDIUM priority · visible_concern · high confidence**

Cited observations: 0.00–14.97 s (sampled, not continuous). Location: Left side of the main aisle, in the area with tall racks and stacked pallets

**Observed:** A pedestrian in a white vest is seen standing among stacked pallets and racks. The tall racks and pallet stacks create significant blind spots. A pedestrian in a yellow hard hat is seen moving behind the pallets. It is difficult to see if a vehicle is approaching from the end of the aisle or if a pedestrian is about to step out.

**Potential risk:** A vehicle or pedestrian could emerge from behind the racks or pallets without being seen, leading to a collision. The pedestrian is also at risk of being struck by a vehicle if they step out unexpectedly.

**References:** [1910.178(n)(4)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.178), [1910.178(n)(6)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.178), [1910.176(a)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.176)

**Applicability:** Vision is obstructed by racks and stacked goods. Drivers must keep a clear view of the path of travel and slow down where vision is obstructed.

**Unknowns:** Vehicle traffic in the rack aisles; Pedestrian movement patterns in the rack aisles

**Actions:** Install convex mirrors at the ends of the rack aisles.; Implement a horn-signal protocol for vehicles entering and exiting the rack aisles.; Mark pedestrian walkways within the rack aisles if pedestrians are present.; Consider using spotters for vehicles operating in these areas.

**Evidence:** [E001](evidence/E001.jpg), [E002](evidence/E002.jpg), [E003](evidence/E003.jpg), [E004](evidence/E004.jpg), [E005](evidence/E005.jpg), [E006](evidence/E006.jpg), [E007](evidence/E007.jpg), [E008](evidence/E008.jpg), [E009](evidence/E009.jpg), [E010](evidence/E010.jpg), [E011](evidence/E011.jpg), [E016](evidence/E016.jpg), [E017](evidence/E017.jpg), [E024](evidence/E024.jpg), [E025](evidence/E025.jpg), [E032](evidence/E032.jpg)

### H04 · Pedestrian near forklift operating area

**MEDIUM priority · visible_concern · high confidence**

Cited observations: 0.00–14.97 s (sampled, not continuous). Location: Right side of the main aisle, near the parked forklift and stacked pallets

**Observed:** A pedestrian in a white shirt is standing very close to a parked forklift and stacked pallets. Another pedestrian in a yellow vest is seen walking near the forklift. The forklift is within a yellow-lined area, but the pedestrian is standing just outside the line, in a position where they could be obscured by the forklift or pallets if the forklift were to move.

**Potential risk:** A pedestrian standing too close to a forklift is at risk of being struck if the forklift moves unexpectedly. The pedestrian may also be in the forklift driver's blind spot.

**References:** [1910.178(n)(6)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.178), [1910.176(a)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.176)

**Applicability:** Drivers must keep a clear view of the path of travel. Aisles and passageways must be kept clear.

**Unknowns:** If the forklift is operational; If the pedestrian is authorized to be in that area

**Actions:** Enforce a minimum safe distance between pedestrians and forklifts.; Mark a no-entry zone around the forklift when it is in operation.; Train forklift operators to check for pedestrians before moving.; Train pedestrians to maintain a safe distance from forklifts.

**Evidence:** [E001](evidence/E001.jpg), [E002](evidence/E002.jpg), [E003](evidence/E003.jpg), [E004](evidence/E004.jpg), [E005](evidence/E005.jpg), [E006](evidence/E006.jpg), [E007](evidence/E007.jpg), [E008](evidence/E008.jpg), [E009](evidence/E009.jpg), [E010](evidence/E010.jpg), [E011](evidence/E011.jpg), [E014](evidence/E014.jpg), [E015](evidence/E015.jpg), [E022](evidence/E022.jpg), [E023](evidence/E023.jpg), [E026](evidence/E026.jpg), [E027](evidence/E027.jpg), [E028](evidence/E028.jpg), [E029](evidence/E029.jpg), [E035](evidence/E035.jpg)

### H05 · Obstructed view at end of rack row

**MEDIUM priority · visible_concern · high confidence**

Cited observations: 0.00–14.97 s (sampled, not continuous). Location: Left side of the main aisle, at the end of the rack row where stacked pallets and an IBC tote are located

**Observed:** The end of the rack row on the left is blocked by stacked pallets and an IBC tote. This creates a blind spot for anyone looking down the main aisle from the right, and for anyone looking from the main aisle towards the end of the rack row. A pedestrian is seen walking behind the stacked pallets.

**Potential risk:** A vehicle or pedestrian could emerge from behind the stacked pallets without being seen, leading to a collision. The stacked pallets also obstruct the view of the end of the rack row.

**References:** [1910.178(n)(4)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.178), [1910.176(a)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.176)

**Applicability:** Vision is obstructed by stacked goods. Aisles and passageways must be kept clear.

**Unknowns:** Vehicle traffic near the end of the rack row; Pedestrian movement near the end of the rack row

**Actions:** Remove or relocate the stacked pallets and IBC tote to improve visibility.; Install a convex mirror at the end of the rack row.; Mark a stop line for vehicles and pedestrians at the end of the rack row.; Implement a horn-signal protocol for vehicles approaching the end of the rack row.

**Evidence:** [E001](evidence/E001.jpg), [E002](evidence/E002.jpg), [E003](evidence/E003.jpg), [E004](evidence/E004.jpg), [E005](evidence/E005.jpg), [E006](evidence/E006.jpg), [E007](evidence/E007.jpg), [E008](evidence/E008.jpg), [E009](evidence/E009.jpg), [E010](evidence/E010.jpg), [E011](evidence/E011.jpg), [E018](evidence/E018.jpg), [E019](evidence/E019.jpg), [E020](evidence/E020.jpg), [E021](evidence/E021.jpg), [E030](evidence/E030.jpg), [E031](evidence/E031.jpg), [E032](evidence/E032.jpg), [E034](evidence/E034.jpg)

## Zone review

- **Z01 — hazard_candidate**: Main aisle and cross-aisle intersection. High pedestrian and potential vehicle traffic. Blind spots at the intersection.

- **Z02 — hazard_candidate**: Right side of the main aisle, near a parked forklift and stacked pallets. Pedestrians are seen walking in this area.

- **Z03 — hazard_candidate**: Left side of the main aisle, with tall racks and stacked pallets. Pedestrians are seen in this area.

- **Z04 — hazard_candidate**: End of the rack row on the left, blocked by stacked pallets and an IBC tote. Creates a blind spot.

- **Z05 — hazard_candidate**: Corner of the rack row on the left. Obstructed view.

- **Z06 — hazard_candidate**: Right side of the main aisle, near a parked forklift and stacked pallets. Pedestrians are seen walking in this area.

- **Z07 — hazard_candidate**: Left side of the main aisle, with tall racks and stacked pallets. Pedestrians are seen in this area.

- **Z08 — hazard_candidate**: Right side of the main aisle, near a parked forklift and stacked pallets. Pedestrians are seen standing near the forklift.

- **Z09 — hazard_candidate**: Right side of the main aisle, near a parked forklift and stacked pallets. Pedestrians are seen standing near the forklift.

- **Z10 — hazard_candidate**: End of the rack row on the left, blocked by stacked pallets and an IBC tote. Creates a blind spot.

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

- No reliable floor-like mask found; static-zone ranking uses general scene candidates.

- Vehicle speed, horn use, and traffic rules are unknown.

- Continuity between sampled frames is not claimed.

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