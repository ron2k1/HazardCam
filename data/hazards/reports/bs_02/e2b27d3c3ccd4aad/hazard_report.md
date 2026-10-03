# Astra video blind-spot review

**Status:** model_review_complete

**Video:** bs_02 · 15.00 s · 450 frames scanned · 24 evidence images

**Model:** nvidia/Qwen3.6-35B-A3B-NVFP4 · **Generated (UTC):** 2026-10-03T19:40:28.660376+00:00

Visual safety screening; observations require qualified safety review.

## Scene

The video shows a warehouse environment with multiple pedestrians and a forklift operating. Pedestrians are walking in aisles and near vehicle routes. A forklift is visible in the background, maneuvering near stacked goods. The layout includes high-density storage racks and palletized goods, which can create visual obstructions.

## Findings

### H01 · Blind Spot at Aisle Intersection with Forklift

**HIGH priority · visible_concern · high confidence**

Cited observations: 0.00–14.97 s (sampled, not continuous). Location: Center-right background, where the main aisle meets the cross-aisle near the forklift

**Observed:** At t=12.8s (E007), a pedestrian is seen walking near the intersection of the main aisle and the cross-aisle. A forklift is visible in the background, maneuvering near the same intersection (E007, E008, E009, E010, E016). The rack structure and stacked goods at this intersection create a blind spot where the forklift driver cannot see the pedestrian, and the pedestrian cannot see the approaching forklift until they are very close.

**Potential risk:** A collision between a forklift and a pedestrian is highly likely if either party enters the blind spot without warning. This is a high-severity hazard due to the potential for serious injury or fatality.

**References:** [1910.178(n)(4)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.178), [1910.178(n)(6)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.178), [1910.176(a)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.176)

**Applicability:** The forklift driver's vision is obstructed by the rack structure and stacked goods at the intersection. The pedestrian is walking in an area where they may not be visible to the forklift driver.

**Unknowns:** Forklift speed; Horn usage by forklift driver; Pedestrian awareness of forklift

**Actions:** Install a convex mirror at the intersection to provide a view of the cross-aisle for both the forklift driver and the pedestrian.; Mark a stop line for pedestrians and forklifts at the intersection.; Implement a 'stop and horn' policy for forklifts at this intersection.; Consider separating pedestrian and vehicle traffic with physical barriers if possible.

**Evidence:** [E001](evidence/E001.jpg), [E007](evidence/E007.jpg), [E008](evidence/E008.jpg), [E009](evidence/E009.jpg), [E010](evidence/E010.jpg), [E015](evidence/E015.jpg), [E016](evidence/E016.jpg), [E022](evidence/E022.jpg)

### H02 · Pedestrian Walking Near Vehicle Route

**MEDIUM priority · visible_concern · high confidence**

Cited observations: 0.00–14.97 s (sampled, not continuous). Location: Left side of the warehouse, near the racks and palletized goods

**Observed:** At t=0.0s (E001), a pedestrian is seen walking in the area near the racks and palletized goods on the left side of the warehouse. At t=14.9s (E010), another pedestrian is seen walking in the same area. This area is adjacent to the main vehicle route. While there are marked walkways, pedestrians are sometimes seen walking close to the edge of the marked area or between pallets.

**Potential risk:** Pedestrians are at risk of being struck by a forklift or other vehicle if they wander too close to the vehicle route or if a vehicle deviates from its path. The proximity of pedestrians to the vehicle route increases the risk of an incident.

**References:** [1910.176(a)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.176), [1910.22(a)(3)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.22)

**Applicability:** The area is a walking-working surface where pedestrians and vehicles may interact. The presence of pedestrians near the vehicle route creates a potential hazard.

**Unknowns:** Pedestrian training on safe walking practices; Vehicle speed in this area

**Actions:** Reinforce pedestrian safety training, emphasizing the importance of staying within marked walkways.; Ensure that marked walkways are clearly visible and unobstructed.; Consider installing physical barriers between pedestrian walkways and vehicle routes in high-traffic areas.; Monitor pedestrian behavior and provide feedback if they are seen walking outside of designated areas.

**Evidence:** [E001](evidence/E001.jpg), [E002](evidence/E002.jpg), [E003](evidence/E003.jpg), [E004](evidence/E004.jpg), [E005](evidence/E005.jpg), [E006](evidence/E006.jpg), [E007](evidence/E007.jpg), [E008](evidence/E008.jpg), [E009](evidence/E009.jpg), [E010](evidence/E010.jpg), [E011](evidence/E011.jpg), [E012](evidence/E012.jpg), [E013](evidence/E013.jpg), [E014](evidence/E014.jpg), [E021](evidence/E021.jpg), [E023](evidence/E023.jpg)

## Zone review

- **Z01 — hazard_candidate**: The zone shows a rack structure with stacked goods. Pedestrians are seen walking near this area. The rack structure can create blind spots for vehicles.

- **Z02 — hazard_candidate**: The zone shows a rack structure and palletized goods. Pedestrians are seen walking near this area. The area is adjacent to the main vehicle route.

- **Z03 — hazard_candidate**: The zone shows an intersection of aisles with a forklift operating. A pedestrian is seen near the intersection. This is a high-risk area due to the blind spot created by the rack structure and stacked goods.

- **Z04 — ordinary_scene**: The zone shows a rack structure with stacked goods. No pedestrians or vehicles are observed in this specific zone, but it is part of the overall storage area.

- **Z05 — ordinary_scene**: The zone shows a rack structure with stacked goods. No pedestrians or vehicles are observed in this specific zone, but it is part of the overall storage area.

## Dismissed or unsubstantiated candidates

- **Pedestrian walking on the marked walkway**: The pedestrian is walking within the marked walkway, which is the designated safe path. This is not a blind spot or obstruction.

- **Forklift operating in the background**: The forklift is operating in a designated area. The concern is the interaction with pedestrians at the intersection, not the forklift's operation itself.

## Limitations

- Visual screening against OSHA General Industry references; jurisdiction and legal compliance are not established.

- All frames scanned by CV; Qwen reviewed only the listed sampled frames and crops. No audio analyzed.

- Observation spans do not establish continuity; hidden controls, energy state, and training cannot be verified.

- Static region ranking is heuristic, not a complete obstruction detector; no clear-scene baseline or metric clearance calibration is available.

- Camera housing, occlusion, resolution and sampling can hide hazards.

- The bounded citation library is not an exhaustive factory-safety checklist; machine-specific rules need further review.

- A single fixed camera cannot see behind racks or stacks; blind spots are judged from this one view and need a walk-through to confirm.

- No reliable floor-like mask found; static-zone ranking uses general scene candidates.

- The analysis is based on a limited number of frames. Continuous monitoring would provide a more complete picture of the hazards.

- The speed of the forklift and pedestrians is unknown.

- The use of horns by the forklift driver is unknown.

- The specific traffic rules of the warehouse are unknown.

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