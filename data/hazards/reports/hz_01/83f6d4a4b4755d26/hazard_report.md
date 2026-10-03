# Astra video hazard review

**Status:** model_review_complete

**Video:** hz_01 · 10.00 s · 250 frames scanned · 29 evidence images

**Model:** nvidia/Qwen3.6-35B-A3B-NVFP4 · **Generated (UTC):** 2026-10-03T19:39:49.165670+00:00

Visual safety screening; observations require qualified safety review.

## Scene

The video shows an industrial manufacturing floor with hydraulic presses and a forklift transporting stacked orange bins. A worker is seated at a workstation on the right side. The forklift moves through the central aisle, passing the worker and the machinery. The floor is marked with yellow lines indicating a path or boundary.

## Findings

### H01 · Forklift operating near seated worker

**MEDIUM priority · visible_concern · high confidence**

Cited observations: 0.80–9.96 s (sampled, not continuous). Location: Central aisle, right side near workstation

**Observed:** A forklift carrying a load of orange bins is observed moving through the aisle in close proximity to a worker seated at a workstation. The forklift passes within a few feet of the worker.

**Potential risk:** The proximity of a moving heavy vehicle to a stationary worker creates a risk of collision or injury from falling objects. The worker is seated and may have limited mobility or awareness.

**References:** [1910.176(a)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.176)

**Applicability:** The forklift is a mechanical handling equipment using an aisle/passageway. The standard requires safe clearances and keeping aisles clear.

**Unknowns:** Worker's PPE status (e.g., high-vis vest); Forklift operator's line of sight; Specific clearance distance maintained; Whether the path is a designated pedestrian walkway or a shared aisle

**Actions:** Verify that the aisle width and layout provide adequate clearance for forklifts and pedestrians.; Ensure the forklift operator maintains a safe distance from the worker.; Consider physical barriers or designated pedestrian walkways if the area is high-traffic.; Confirm the worker is wearing appropriate PPE.

**Evidence:** [E003](evidence/E003.jpg), [E004](evidence/E004.jpg), [E005](evidence/E005.jpg), [E012](evidence/E012.jpg), [E013](evidence/E013.jpg)

### H02 · Unsecured red bin/cart near machinery

**LOW priority · visible_concern · medium confidence**

Cited observations: 0.00–9.96 s (sampled, not continuous). Location: Near the blue and white hydraulic press on the right

**Observed:** A red bin or small cart is positioned on the floor near the base of a hydraulic press. It appears stationary but is not clearly secured.

**Potential risk:** If the bin is not secured, it could be knocked over by the forklift or machinery vibration, creating a tripping hazard or obstruction.

**References:** [1910.176(b)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.176)

**Applicability:** Materials must be stored so they do not create hazards. An unsecured object near active machinery fits this description.

**Unknowns:** Whether the bin is intended to be there; If it is secured or just placed

**Actions:** Inspect the red bin/cart to ensure it is stable and not a tripping hazard.; Secure the bin or relocate it to a designated storage area if not in use.

**Evidence:** [E001](evidence/E001.jpg), [E002](evidence/E002.jpg), [E003](evidence/E003.jpg), [E004](evidence/E004.jpg), [E005](evidence/E005.jpg), [E006](evidence/E006.jpg), [E007](evidence/E007.jpg), [E008](evidence/E008.jpg), [E009](evidence/E009.jpg), [E010](evidence/E010.jpg), [E011](evidence/E011.jpg), [E016](evidence/E016.jpg), [E017](evidence/E017.jpg)

## Zone review

- **Z01 — hazard_candidate**: The forklift moves through this zone, passing near the worker's station.

- **Z02 — ordinary_scene**: This zone is a small crop of the upper area, showing no significant activity or hazards.

- **Z03 — hazard_candidate**: Contains a red bin/cart near a machine.

- **Z04 — ordinary_scene**: Shows a section of the floor with some debris and a blue beam. No active hazards.

- **Z05 — ordinary_scene**: Shows a control panel on a machine. No visible hazards.

- **Z06 — ordinary_scene**: Shows another machine control panel. No visible hazards.

- **Z07 — ordinary_scene**: Shows the forklift passing by. The forklift is the primary object of interest here.

## Dismissed or unsubstantiated candidates

- **Aisle obstruction by forklift**: The forklift is operating in the designated aisle. While it is a hazard to the worker nearby, it is not an obstruction of the aisle itself in the sense of blocking it permanently.

- **Spill on floor**: There are dark stains on the floor, but they appear to be oil or grease stains rather than a fresh spill. No active leaking is observed.

## Limitations

- Visual screening against OSHA General Industry references; jurisdiction and legal compliance are not established.

- All frames scanned by CV; Qwen reviewed only the listed sampled frames and crops. No audio analyzed.

- Observation spans do not establish continuity; hidden controls, energy state, and training cannot be verified.

- Static region ranking is heuristic, not a complete obstruction detector; no clear-scene baseline or metric clearance calibration is available.

- Camera housing, occlusion, resolution and sampling can hide hazards.

- The bounded citation library is not an exhaustive factory-safety checklist; machine-specific rules need further review.

- No reliable floor-like mask found; static-zone ranking uses general scene candidates.

- No reliable floor-like mask found; static-zone ranking uses general scene candidates.

- Video quality is moderate; fine details like PPE labels or specific machine guards are not clearly resolvable.

- The video is a short clip; continuous operation or other hazards not present in this timeframe are not assessed.

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