"""Endpoint health: is a role's OpenAI-compatible server up, and does it serve the model?

Uses ``GET <base_url>/models`` (served by Ollama /v1, vLLM and NIM alike). Never raises
for an unreachable server; the result says why. Used by live tests to skip cleanly and
available to the API for the local-model health panel.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import httpx

from .profiles import EndpointConfig

HEALTH_TIMEOUT_S = 3.0


@dataclass
class EndpointHealth:
    base_url: str | None
    model: str | None
    reachable: bool = False
    model_served: bool = False
    models: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.reachable and self.model_served


def check_endpoint(
    endpoint: EndpointConfig,
    *,
    env: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout_s: float = HEALTH_TIMEOUT_S,
) -> EndpointHealth:
    health = EndpointHealth(base_url=endpoint.base_url, model=endpoint.model)
    if endpoint.backend != "openai_compatible" or not endpoint.base_url:
        health.error = "not an openai_compatible endpoint"
        return health
    key = endpoint.api_key(env)
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        with httpx.Client(transport=transport, timeout=timeout_s) as client:
            resp = client.get(endpoint.base_url.rstrip("/") + "/models", headers=headers)
    except httpx.HTTPError as exc:
        health.error = type(exc).__name__
        return health
    health.reachable = True
    if resp.status_code != 200:
        health.error = f"HTTP {resp.status_code}"
        return health
    try:
        data = resp.json().get("data") or []
        health.models = [m["id"] for m in data if isinstance(m, dict) and "id" in m]
    except (ValueError, AttributeError):
        health.error = "malformed /models body"
        return health
    health.model_served = endpoint.model in health.models
    if not health.model_served:
        health.error = f"model {endpoint.model!r} not served"
    return health
