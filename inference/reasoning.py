"""Reasoning adapters (Mistral role): EvidenceBundle -> bounded Hypothesis.

The model sees ONLY the evidence bundle (already ground-truth-free). Its answer is then
re-validated against that bundle in code: evidence ids, region, vocabulary, confidence
range, alternative ordering and a non-empty limitations list. A model that cannot produce
usable JSON after one repair yields a schema-valid abstention, never an exception.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx

from apps.api.schemas import UNKNOWN, Alternative, EvidenceBundle, Hypothesis

from .base import CallInfo, ReasoningOptions, load_prompt, report
from .client import ChatClient, ChatResult, ModelCallError, extract_json
from .coerce import coerce_confidence
from .frames import text_tokens
from .profiles import ModelProfile
from .vocab import HYPOTHESIS_EVENT_TYPES, NOT_DIRECTLY_VISIBLE, normalize_event_type

log = logging.getLogger(__name__)

PROMPT_FILE = "mistral_fusion.txt"
MAX_ALTERNATIVES = 3
MAX_LIMITATIONS = 6
REASON_MAX_CHARS = 800
LIMITATION_MAX_CHARS = 240
CONTEXT_SAFETY_TOKENS = 64
REPAIR_ECHO_CHARS = 4000
_MARKDOWN_EMPHASIS = re.compile(r"\*+|`+")


class OutputFormatError(ValueError):
    """Model output is not usable as a hypothesis (triggers one repair)."""


# --- schema + post-processing (pure, unit-tested) ----------------------------------------


def allowed_regions(bundle: EvidenceBundle) -> list[str]:
    """Region values the hypothesis may use: fusion candidate ids, then ``unknown``.

    Zone ids reach this list through fusion (zone_prior / ray-in-zone candidates take
    the zone id); ``tools.submit.submit_hypothesis`` enforces the same set.
    """
    return list(dict.fromkeys([*(c.id for c in bundle.region_candidates), UNKNOWN]))


def hypothesis_schema(bundle: EvidenceBundle) -> dict[str, Any]:
    """Per-bundle structured-output schema: ids and regions are enums of real values.

    ``reason`` comes first so a grammar-constrained model writes its justification
    before committing to a label.
    """
    ids = [e.id for e in bundle.evidence]
    evidence_items: dict[str, Any] = {"type": "string", "enum": ids} if ids else {"type": "string"}
    events = list(HYPOTHESIS_EVENT_TYPES)
    return {
        "type": "object",
        "properties": {
            "reason": {"type": "string"},
            "evidence_ids": {
                "type": "array",
                "items": evidence_items,
                **({} if ids else {"maxItems": 0}),
            },
            "event_type": {"type": "string", "enum": events},
            "region": {"type": "string", "enum": allowed_regions(bundle)},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "alternatives": {
                "type": "array",
                "maxItems": MAX_ALTERNATIVES,
                "items": {
                    "type": "object",
                    "properties": {
                        "event_type": {"type": "string", "enum": events},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["event_type", "confidence"],
                },
            },
            "limitations": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_LIMITATIONS,
                "items": {"type": "string"},
            },
        },
        "required": [
            "reason",
            "evidence_ids",
            "event_type",
            "region",
            "confidence",
            "alternatives",
            "limitations",
        ],
    }


def abstain(reason: str, limitations: list[str]) -> Hypothesis:
    """A schema-valid abstention (``event_type == region == "unknown"``)."""
    limits = list(dict.fromkeys([*limitations, NOT_DIRECTLY_VISIBLE]))
    return Hypothesis(
        event_type=UNKNOWN,
        region=UNKNOWN,
        confidence=0.0,
        evidence_ids=[],
        reason=reason,
        alternatives=[],
        limitations=limits,
    )


def postprocess_hypothesis(raw: Any, bundle: EvidenceBundle) -> tuple[Hypothesis, list[str], int]:
    """Validate parsed model JSON against ``bundle``.

    Returns ``(hypothesis, warnings, dropped_count)``; every correction is also written
    into ``limitations`` so a judge sees why a claim was softened.
    """
    if isinstance(raw, dict) and isinstance(raw.get("hypothesis"), dict):
        raw = raw["hypothesis"]
    if not isinstance(raw, dict) or "event_type" not in raw:
        raise OutputFormatError("expected a JSON object with an event_type")
    warnings: list[str] = []
    limitations = _strings(raw.get("limitations"))
    dropped = 0

    event_type, recognized = normalize_event_type(raw.get("event_type"))
    if not recognized:
        limitations.append(
            f"Event type {str(raw.get('event_type'))[:60]!r} is outside the allowed "
            "vocabulary; reported as unknown."
        )

    region = raw.get("region")
    region = region.strip() if isinstance(region, str) and region.strip() else UNKNOWN
    allowed = allowed_regions(bundle)
    if region not in allowed:
        by_label = {
            (c.label or "").strip().lower(): c.id for c in bundle.region_candidates if c.label
        }
        mapped = by_label.get(region.lower()) or next(
            (r for r in allowed if r.lower() == region.lower()), None
        )
        if mapped is None:
            limitations.append(
                f"Region {region[:60]!r} is not a fusion candidate; reported as unknown."
            )
            warnings.append(f"region {region!r} replaced by unknown")
        region = mapped or UNKNOWN

    known = bundle.evidence_ids()
    cited = raw.get("evidence_ids") if isinstance(raw.get("evidence_ids"), list) else []
    evidence_ids = list(dict.fromkeys(e for e in cited if isinstance(e, str) and e in known))
    bad_refs = len(cited) - len([e for e in cited if isinstance(e, str) and e in known])
    if bad_refs:
        dropped += bad_refs
        limitations.append(f"Dropped {bad_refs} evidence reference(s) not in the bundle.")

    alternatives: dict[str, float] = {}
    alt_raw = raw.get("alternatives") if isinstance(raw.get("alternatives"), list) else []
    for alt in alt_raw:
        label, conf = (
            (alt.get("event_type"), alt.get("confidence")) if isinstance(alt, dict) else (alt, None)
        )
        alt_type, ok = normalize_event_type(label)
        if not ok or alt_type == event_type:
            dropped += int(not ok)
            continue
        alternatives[alt_type] = max(alternatives.get(alt_type, 0.0), coerce_confidence(conf, 0.0))
    ranked = sorted(alternatives.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_ALTERNATIVES]

    reason = raw.get("reason") if isinstance(raw.get("reason"), str) else ""
    if NOT_DIRECTLY_VISIBLE not in limitations:
        limitations.append(NOT_DIRECTLY_VISIBLE)
    hypothesis = Hypothesis(
        event_type=event_type,
        region=region,
        confidence=round(coerce_confidence(raw.get("confidence"), 0.0), 4),
        evidence_ids=evidence_ids,
        reason=_clean(reason, REASON_MAX_CHARS),
        alternatives=[Alternative(event_type=k, confidence=round(v, 4)) for k, v in ranked],
        limitations=list(dict.fromkeys(limitations)),
    )
    return hypothesis, warnings, dropped


def _clean(text: str, limit: int) -> str:
    """Collapse whitespace and drop markdown emphasis (the UI renders plain text)."""
    return " ".join(_MARKDOWN_EMPHASIS.sub("", text).split())[:limit]


def _strings(value: Any) -> list[str]:
    items = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    out = [_clean(s, LIMITATION_MAX_CHARS) for s in items if isinstance(s, str)]
    return [s for s in out if s][:MAX_LIMITATIONS]


def bundle_message(bundle: EvidenceBundle) -> str:
    """The user turn: the bundle JSON plus the id/region lists derived from it."""
    body = json.dumps(
        bundle.model_dump(mode="json", exclude_none=True), separators=(",", ":"), ensure_ascii=False
    )
    return (
        f"EVIDENCE_BUNDLE:\n{body}\n\n"
        f"Bundle status: {bundle.status}\n"
        f"Valid evidence_ids: {json.dumps([e.id for e in bundle.evidence])}\n"
        f"Valid region values: {json.dumps(allowed_regions(bundle))}\n"
        "Return only the JSON object."
    )


# --- adapters ---------------------------------------------------------------------------


class FixtureReasoningAdapter:
    """Deterministic replay of ``<fixture_dir>/<scenario_id>/final_hypothesis.json`` when it
    exists, else the profile's fixture file."""

    name = "fixture"

    def __init__(self, profile: ModelProfile) -> None:
        self.profile = profile
        self.last_call: CallInfo | None = None

    def reason(self, bundle: EvidenceBundle, options: ReasoningOptions) -> Hypothesis:
        start = time.perf_counter()
        path = self.profile.reasoning.fixture_path(bundle.scenario_id)
        info = CallInfo(
            role="reasoning", adapter=self.name, model=None, scenario_id=bundle.scenario_id
        )
        try:
            if path is None:
                raise FileNotFoundError("no reasoning fixture configured")
            hypothesis = Hypothesis.model_validate_json(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            info.ok, info.error = False, f"fixture unreadable: {type(exc).__name__}: {exc}"
            hypothesis = abstain("Reasoning fixture unavailable; abstaining.", [info.error])
        unknown_refs = sorted(set(hypothesis.evidence_ids) - bundle.evidence_ids())
        if unknown_refs:
            info.warnings.append(f"fixture cites evidence not in this bundle: {unknown_refs}")
        info.latency_s = time.perf_counter() - start
        self.last_call = info
        report(info, options.telemetry, options.strict)
        return hypothesis


class OpenAICompatReasoningAdapter:
    """Live reasoner over an OpenAI-compatible ``/chat/completions`` endpoint."""

    def __init__(
        self,
        profile: ModelProfile,
        *,
        transport: httpx.BaseTransport | None = None,
        env: Mapping[str, str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.profile = profile
        self.endpoint = profile.reasoning
        self.client = ChatClient(self.endpoint, transport=transport, env=env, sleep=sleep)
        self.name = f"openai_compatible/{self.endpoint.model}"
        self.last_call: CallInfo | None = None

    def reason(self, bundle: EvidenceBundle, options: ReasoningOptions) -> Hypothesis:
        start = time.perf_counter()
        system, version = load_prompt(PROMPT_FILE)
        info = CallInfo(
            role="reasoning",
            adapter=self.name,
            model=self.endpoint.model,
            scenario_id=bundle.scenario_id,
            prompt_version=version,
        )
        if not bundle.evidence:
            hypothesis = abstain(
                "Fusion produced no evidence items; abstaining without a model call.",
                ["No evidence from any model input camera."],
            )
            info.warnings.append("no evidence: skipped the model call")
        else:
            try:
                hypothesis = self._reason(bundle, options, system, info)
            except ModelCallError as exc:
                info.ok, info.error = False, str(exc)
                info.attempts += exc.attempts
                hypothesis = abstain(
                    "Reasoning model unavailable; abstaining.", [f"Reasoning model failed: {exc}"]
                )
        info.latency_s = time.perf_counter() - start
        self.last_call = info
        log.info(
            "reasoning scenario=%s model=%s ok=%s event=%s latency=%.2fs",
            bundle.scenario_id,
            self.endpoint.model,
            info.ok,
            hypothesis.event_type,
            info.latency_s,
        )
        report(info, options.telemetry, options.strict)
        return hypothesis

    def _reason(
        self, bundle: EvidenceBundle, options: ReasoningOptions, system: str, info: CallInfo
    ) -> Hypothesis:
        max_tokens = options.max_tokens or self.endpoint.max_tokens
        user = bundle_message(bundle)
        ctx = self.endpoint.context_tokens
        overflow = bool(
            ctx
            and text_tokens(system) + text_tokens(user) + max_tokens + CONTEXT_SAFETY_TOKENS > ctx
        )
        if overflow:
            info.warnings.append(f"bundle may exceed the {ctx}-token context window")
        schema = hypothesis_schema(bundle)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        result = self._call(messages, schema, max_tokens, options, info)
        try:
            hypothesis, warnings, dropped = postprocess_hypothesis(
                extract_json(result.content), bundle
            )
        except ValueError as first:  # includes OutputFormatError and pydantic errors
            info.warnings.append(f"invalid output, repairing: {first}")
            info.repaired = True
            repair = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
                {"role": "assistant", "content": result.content[:REPAIR_ECHO_CHARS]},
                {
                    "role": "user",
                    "content": f"That reply could not be used ({first}). Return ONLY the "
                    "required JSON object with keys reason, evidence_ids, event_type, region, "
                    "confidence, alternatives, limitations.",
                },
            ]
            result = self._call(repair, schema, max_tokens, options, info)
            try:
                hypothesis, warnings, dropped = postprocess_hypothesis(
                    extract_json(result.content), bundle
                )
            except ValueError as second:
                info.ok, info.error = False, f"invalid JSON after repair: {second}"
                return abstain(
                    "Reasoning model output was unusable; abstaining.",
                    [f"Reasoning model output invalid after one repair: {second}"],
                )
        if overflow:
            hypothesis = hypothesis.model_copy(
                update={
                    "limitations": [
                        *hypothesis.limitations,
                        "The evidence bundle may have exceeded the reasoning model's context window.",
                    ]
                }
            )
        info.warnings.extend(warnings)
        info.dropped_items = dropped
        return hypothesis

    def _call(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        max_tokens: int,
        options: ReasoningOptions,
        info: CallInfo,
    ) -> ChatResult:
        result = self.client.chat(
            messages,
            response_schema=schema,
            schema_name="hypothesis",
            max_tokens=max_tokens,
            temperature=options.temperature,
        )
        info.attempts += result.attempts
        info.model = result.model
        info.usage = result.usage
        info.finish_reason = result.finish_reason
        return result
