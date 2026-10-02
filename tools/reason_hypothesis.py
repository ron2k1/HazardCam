"""reason_hypothesis: fused EvidenceBundle -> bounded Hypothesis (or an abstention).

Thin tool wrapper over the reasoning adapter selected by the active model profile. The
bundle is re-validated first so referential integrity holds even for bundles built with
``model_copy``; it is the only input the reasoning model receives.
"""

from __future__ import annotations

from apps.api.schemas import EvidenceBundle, Hypothesis
from inference.base import ReasoningAdapter, ReasoningOptions, get_reasoning_adapter
from inference.profiles import load_profile


def reason_hypothesis(
    evidence_bundle: EvidenceBundle | dict,
    reasoning_options: ReasoningOptions | None = None,
    *,
    adapter: ReasoningAdapter | None = None,
) -> Hypothesis:
    """Return a schema-valid hypothesis whose ids and region come from ``evidence_bundle``.

    Model failures degrade to an ``unknown`` abstention with the failure in
    ``limitations``; details go to ``reasoning_options.telemetry`` / ``adapter.last_call``
    (or raise with ``strict``). ``tools.submit.submit_hypothesis`` remains the final gate.
    """
    bundle = EvidenceBundle.model_validate(
        evidence_bundle.model_dump()
        if isinstance(evidence_bundle, EvidenceBundle)
        else evidence_bundle
    )
    if adapter is None:
        adapter = get_reasoning_adapter(load_profile())
    return adapter.reason(bundle, reasoning_options or ReasoningOptions())
