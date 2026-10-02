"""Model endpoint health: the active profile plus a reachability probe per role.

The profile comes from ``inference.profiles.load_profile`` (P06) when that import
and call succeed and ``models_dir`` is the directory P06 reads, otherwise from
``<models_dir>/<profile>.yaml`` with the same ``QWEN_*`` / ``MISTRAL_*`` env
overrides. Unfilled profiles are still described (a role with an unset or
``REPLACE*`` endpoint/model is "unconfigured" and not probed). Each configured
OpenAI-compatible endpoint is probed with ``GET <base_url>/models``. No
credentials are sent or reported.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import yaml

logger = logging.getLogger(__name__)

ROLES = ("perception", "reasoning")
ENV_OVERRIDES = {
    "perception": ("QWEN_BASE_URL", "QWEN_MODEL"),
    "reasoning": ("MISTRAL_BASE_URL", "MISTRAL_MODEL"),
}
PLACEHOLDER_MARK = "REPLACE"  # same marker inference.profiles refuses to select


def load_profile_info(name: str, models_dir: Path) -> dict[str, Any]:
    info = _from_inference_profiles(name, models_dir)
    if info is None:
        info = _from_yaml(name, models_dir)
        info["source"] = "yaml"
    return info


def _from_inference_profiles(name: str, models_dir: Path) -> dict[str, Any] | None:
    try:
        from inference import profiles  # lazy: optional P06 module

        if models_dir.resolve() != Path(profiles.PROFILES_DIR).resolve():
            return None  # P06 only reads its own dir; a custom AUM_MODELS_DIR wins
        # require_resolved=False: health describes unfilled profiles, it does not select them
        info = _from_profile_object(profiles.load_profile(name, require_resolved=False), name)
    # Any failure in the P06 loader (missing package, other shape, invalid profile)
    # must degrade to the YAML read, never break health.
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "inference.profiles unusable for %r (%s); reading YAML", name, type(exc).__name__
        )
        return None
    info["source"] = "inference.profiles"
    return info


def _as_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return dict(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    return dict(vars(obj))


def _from_profile_object(profile: Any, name: str) -> dict[str, Any]:
    data = _as_dict(profile)
    roles = {role: _as_dict(data[role]) for role in ROLES}  # KeyError -> YAML fallback
    return {
        "profile": data.get("name") or data.get("profile") or name,
        "mode": data.get("mode"),
        **roles,
    }


def _from_yaml(name: str, models_dir: Path) -> dict[str, Any]:
    doc = yaml.safe_load((models_dir / f"{name}.yaml").read_text(encoding="utf-8")) or {}
    roles: dict[str, dict[str, Any]] = {}
    for role, (url_env, model_env) in ENV_OVERRIDES.items():
        section = dict(doc.get(role) or {})
        if section.get("backend") != "fixture":
            if os.environ.get(url_env):
                section["base_url"] = os.environ[url_env]
            if os.environ.get(model_env):
                section["model"] = os.environ[model_env]
        roles[role] = section
    return {"profile": doc.get("profile") or name, "mode": doc.get("mode"), **roles}


def _without_userinfo(url: str | None) -> str | None:
    if not url:
        return url
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc=parts.netloc.rsplit("@", 1)[1]))


def _unset(value: Any) -> bool:
    return not value or PLACEHOLDER_MARK in str(value)


def _model_listed(response: httpx.Response, model: str | None) -> bool | None:
    try:
        ids = {str(m.get("id")) for m in response.json().get("data", []) if isinstance(m, dict)}
    except (ValueError, AttributeError):
        return None
    return (model in ids) if model and ids else None


async def probe_role(client: httpx.AsyncClient, section: dict[str, Any]) -> dict[str, Any]:
    backend = section.get("backend")
    if backend == "fixture":
        return {
            "backend": "fixture",
            "base_url": None,
            "model": None,
            "status": "fixture",
            "reachable": None,
        }
    base_url = section.get("base_url")
    out = {
        "backend": backend,
        "base_url": _without_userinfo(base_url),
        "model": section.get("model"),
    }
    missing = [key for key in ("base_url", "model") if _unset(section.get(key))]
    if missing:
        return out | {"status": "unconfigured", "reachable": None, "missing": missing}
    started = time.perf_counter()
    try:
        response = await client.get(f"{base_url.rstrip('/')}/models")
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        return out | {"status": "unreachable", "reachable": False, "error": type(exc).__name__}
    out |= {
        "reachable": True,
        "http_status": response.status_code,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }
    if not response.is_success:
        return out | {"status": "http_error"}
    return out | {"status": "ok", "model_listed": _model_listed(response, section.get("model"))}


async def models_health(name: str, models_dir: Path, timeout_s: float) -> dict[str, Any]:
    info = load_profile_info(name, models_dir)
    async with httpx.AsyncClient(timeout=timeout_s, trust_env=False) as client:
        results = await asyncio.gather(*(probe_role(client, info[role]) for role in ROLES))
    statuses = {r["status"] for r in results}
    if statuses == {"fixture"}:
        status = "fixture"
    elif statuses <= {"ok", "fixture"}:
        status = "ok"
    else:
        status = "degraded"
    return {
        "profile": info["profile"],
        "mode": info.get("mode"),
        "source": info["source"],
        "status": status,
        **dict(zip(ROLES, results, strict=True)),
    }
