# Evaluation Plan

A flashy single example is not enough. Build a compact eval set so the team knows whether the concept works before event day.

## Scenario mix target

Aim for 20–30 short scenarios if data availability permits:
- positive incidents with indirect cues
- subtle positives
- negative/no-event clips
- ambiguous clips where abstention is acceptable

Use real footage wherever licensing/access permits. Synthetic or staged data may supplement tests but must be labeled as such.

## Scenario ground truth

Each eval manifest should contain:
- scenario ID
- allowed input cameras
- withheld ground-truth camera if available
- event class or acceptable class set
- coarse target region
- direct-visibility flag
- ambiguity/abstention policy
- provenance/license metadata

## Metrics

Perception:
- schema validity
- cue recall against manually verified cues
- unsupported/fabricated cue rate

Fusion:
- time-cluster correctness
- region-candidate correctness

Final hypothesis:
- event-class acceptance
- coarse-region acceptance
- evidence count
- abstention correctness
- schema validity

System:
- E2E latency
- per-camera latency
- model errors/timeouts
- run completion rate

## Comparison matrix

Where hardware allows, compare at least:
- fixture baseline
- lite perception + lite reasoner
- intended/full perception + intended/full reasoner

The purpose is not a publication-quality benchmark. It is to identify failure modes and prove that larger models materially improve the judged scenario if they do.

## Robust assertions

Do not assert exact natural-language strings. Assert:
- valid schema
- accepted event category
- valid confidence range
- minimum supporting evidence
- acceptable region set
- correct abstention behavior
