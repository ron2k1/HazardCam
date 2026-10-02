"""submit_hypothesis: the final deterministic gate between the reasoner and the UI.

Every rule here is mechanical and visible in ``limitations`` so a judge can see
why a claim was softened. The reasoning model never gets the last word on
evidence references, region names or confidence under thin evidence.
"""

from __future__ import annotations

from apps.api.schemas import UNKNOWN, Alternative, EvidenceBundle, Hypothesis

NOT_DIRECTLY_VISIBLE = "The event itself is not directly visible to any model input camera."
INSUFFICIENT_CONFIDENCE_CAP = 0.35
SINGLE_CAMERA_CONFIDENCE_CAP = 0.6
MAX_ALTERNATIVES = 5


def submit_hypothesis(
    hypothesis: Hypothesis | dict, evidence_bundle: EvidenceBundle | dict
) -> Hypothesis:
    """Validate and normalize a hypothesis against the bundle it claims to explain.

    Inputs are re-validated from their dumped form: callers may pass plain JSON (the
    event-day agent will) or models built with ``model_copy(update=...)``, which skips
    validation.

    Rules, in order:
    1. evidence_ids not in the bundle are dropped.
    2. a region that is not a bundle region candidate (or ``unknown``) becomes ``unknown``.
    3. a non-abstaining claim with no remaining evidence becomes an abstention; the
       original claim is kept as an alternative.
    4. confidence is capped when the bundle is ``insufficient`` or the cited evidence
       comes from a single camera.
    5. alternatives: the main event_type is removed, duplicates collapse to their max
       confidence, sorted by confidence desc then name, capped at ``MAX_ALTERNATIVES``.
    6. the not-directly-visible limitation is always present.
    """
    hypothesis = Hypothesis.model_validate(
        hypothesis.model_dump() if isinstance(hypothesis, Hypothesis) else hypothesis
    )
    evidence_bundle = EvidenceBundle.model_validate(
        evidence_bundle.model_dump()
        if isinstance(evidence_bundle, EvidenceBundle)
        else evidence_bundle
    )
    limitations = list(dict.fromkeys(hypothesis.limitations))
    known = evidence_bundle.evidence_ids()

    evidence_ids = list(dict.fromkeys(e for e in hypothesis.evidence_ids if e in known))
    dropped = [e for e in hypothesis.evidence_ids if e not in known]
    if dropped:
        limitations.append(f"Dropped {len(dropped)} evidence reference(s) not in the bundle.")

    region = hypothesis.region
    candidate_ids = {c.id for c in evidence_bundle.region_candidates}
    if region != UNKNOWN and region not in candidate_ids:
        limitations.append(f"Region {region!r} is not a fusion candidate; reported as unknown.")
        region = UNKNOWN

    event_type, confidence = hypothesis.event_type, hypothesis.confidence
    alternatives = list(hypothesis.alternatives)
    if event_type != UNKNOWN and not evidence_ids:
        alternatives.append(Alternative(event_type=event_type, confidence=confidence))
        limitations.append("No valid supporting evidence; claim downgraded to an abstention.")
        event_type, region, confidence = UNKNOWN, UNKNOWN, min(confidence, 0.2)

    if event_type != UNKNOWN:
        if evidence_bundle.status == "insufficient" and confidence > INSUFFICIENT_CONFIDENCE_CAP:
            confidence = INSUFFICIENT_CONFIDENCE_CAP
            limitations.append("Fusion marked the evidence insufficient; confidence capped.")
        cameras = {e.camera_id for e in evidence_bundle.evidence if e.id in set(evidence_ids)}
        if len(cameras) < 2 and confidence > SINGLE_CAMERA_CONFIDENCE_CAP:
            confidence = SINGLE_CAMERA_CONFIDENCE_CAP
            limitations.append("Cited evidence comes from one camera; confidence capped.")

    best: dict[str, float] = {}
    for alt in alternatives:
        if alt.event_type != event_type:
            best[alt.event_type] = max(best.get(alt.event_type, 0.0), alt.confidence)
    ranked = sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_ALTERNATIVES]

    if NOT_DIRECTLY_VISIBLE not in limitations:
        limitations.append(NOT_DIRECTLY_VISIBLE)

    return Hypothesis(
        event_type=event_type,
        region=region,
        confidence=round(confidence, 4),
        evidence_ids=evidence_ids,
        reason=hypothesis.reason,
        alternatives=[Alternative(event_type=k, confidence=v) for k, v in ranked],
        limitations=limitations,
    )
