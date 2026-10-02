"""Load and validate against the JSON Schemas in ``contracts/`` (the source of truth)."""

from __future__ import annotations

import json
from functools import cache, lru_cache
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from ._base import CONTRACTS_DIR

SCHEMA_FILES = {
    "scenario": "scenario.schema.json",
    "observation_batch": "observation.schema.json",
    "media_manifest": "media_manifest.schema.json",
    "evidence_bundle": "evidence.schema.json",
    "hypothesis": "hypothesis.schema.json",
    "run": "run.schema.json",
    "sse_envelope": "sse_envelope.schema.json",
    "tool_call": "tools.schema.json",
}


@cache
def load_schema(name: str) -> dict[str, Any]:
    return json.loads((CONTRACTS_DIR / SCHEMA_FILES[name]).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _registry() -> Registry:
    resources = [
        (schema["$id"], Resource.from_contents(schema))
        for schema in (load_schema(n) for n in SCHEMA_FILES)
    ]
    return Registry().with_resources(resources)


@cache
def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(
        load_schema(name), registry=_registry(), format_checker=FormatChecker()
    )


@cache
def def_validator(name: str, def_name: str) -> Draft202012Validator:
    """Validator for ``$defs/<def_name>`` of contract ``name``; its refs resolve as usual."""
    ref = f"{load_schema(name)['$id']}#/$defs/{def_name}"
    return Draft202012Validator({"$ref": ref}, registry=_registry(), format_checker=FormatChecker())


def validate_json(name: str, instance: Any) -> None:
    """Raise ``jsonschema.ValidationError`` if ``instance`` violates contract ``name``."""
    validator(name).validate(instance)


def is_valid(name: str, instance: Any) -> bool:
    return validator(name).is_valid(instance)
