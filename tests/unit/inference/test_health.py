"""P06: endpoint health probe (GET /models) never raises and explains failures."""

from __future__ import annotations

import httpx

from inference.health import check_endpoint
from inference.profiles import EndpointConfig

EP = EndpointConfig(backend="openai_compatible", base_url="http://h:1/v1/", model="qwen3-vl:4b")


def _transport(handler):
    seen: list[httpx.Request] = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    return httpx.MockTransport(wrapped), seen


def test_served_model_is_healthy():
    body = {"object": "list", "data": [{"id": "qwen3-vl:4b"}, {"id": "other"}]}
    transport, seen = _transport(lambda r: httpx.Response(200, json=body))
    health = check_endpoint(EP, transport=transport, env={})
    assert health.ok and health.models == ["qwen3-vl:4b", "other"] and health.error is None
    assert str(seen[0].url) == "http://h:1/v1/models"


def test_missing_model_is_reachable_but_not_ok():
    transport, _ = _transport(lambda r: httpx.Response(200, json={"data": [{"id": "x"}]}))
    health = check_endpoint(EP, transport=transport, env={})
    assert health.reachable and not health.ok and "not served" in health.error


def test_unreachable_server_does_not_raise():
    def refuse(request):
        raise httpx.ConnectError("refused")

    health = check_endpoint(EP, transport=httpx.MockTransport(refuse), env={})
    assert not health.reachable and health.error == "ConnectError"


def test_http_error_and_malformed_body():
    transport, _ = _transport(lambda r: httpx.Response(401, json={}))
    assert check_endpoint(EP, transport=transport, env={}).error == "HTTP 401"
    transport, _ = _transport(lambda r: httpx.Response(200, content=b"<html>"))
    assert check_endpoint(EP, transport=transport, env={}).error == "malformed /models body"


def test_fixture_endpoint_is_not_probed():
    health = check_endpoint(EndpointConfig(backend="fixture", fixture="f.json"))
    assert not health.ok and "openai_compatible" in health.error


def test_key_header_comes_from_named_env():
    ep = EP.model_copy(update={"api_key_env": "NIM_KEY"})
    transport, seen = _transport(lambda r: httpx.Response(200, json={"data": []}))
    check_endpoint(ep, transport=transport, env={"NIM_KEY": "k-1"})
    assert seen[0].headers["authorization"] == "Bearer k-1"
