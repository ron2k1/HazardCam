"""Detector client: loopback-only, never raises from health(), strict /detect parsing."""

from __future__ import annotations

import cv2
import httpx
import numpy as np
import pytest

from hazards.detector.client import (
    DEFAULT_URL,
    URL_ENV,
    DetectorClient,
    DetectorError,
)
from tests.unit.hazards._helpers import StubDetector, unreachable_transport

PNG_1X1 = cv2.imencode(".png", np.zeros((1, 1, 3), np.uint8))[1].tobytes()


@pytest.fixture
def stub():
    server = StubDetector(
        objects=[{"model": "yolo11s", "label": "person", "conf": 0.9, "box": [1, 2, 3, 4]}]
    ).start()
    try:
        yield server
    finally:
        server.stop()


def test_health_and_detect_against_a_stub_server(stub):
    client = DetectorClient(stub.url)
    health = client.health()
    assert health.ok and health.device == "cuda:0" and health.error is None
    assert set(health.models) == {"yolo11s", "yolov8s-worldv2"}
    result = client.detect(PNG_1X1, models=("yolo11s",), conf=0.3)
    assert (result.width, result.height, result.elapsed_ms) == (1, 1, 12.5)
    (obj,) = result.objects
    assert obj.as_dict() == {
        "model": "yolo11s",
        "label": "person",
        "conf": 0.9,
        "box": [1, 2, 3, 4],
    }
    (request,) = stub.requests
    assert request["query"] == {"models": ["yolo11s"], "conf": ["0.3"]}
    assert request["content_type"] == "image/png" and request["body"] == PNG_1X1


def test_health_never_raises_when_unreachable():
    client = DetectorClient(DEFAULT_URL, transport=unreachable_transport())
    health = client.health()
    assert not health.ok and health.error == "unreachable (ConnectError)"
    with pytest.raises(DetectorError, match="unreachable"):
        client.detect(PNG_1X1)


def test_health_reports_http_errors_and_bad_bodies():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.port == 8101:
            return httpx.Response(503, json={"ok": False})
        if request.url.port == 8102:
            return httpx.Response(200, content=b"not json")
        return httpx.Response(200, json={"ok": False, "error": "warming up", "models": {}})

    transport = httpx.MockTransport(handler)
    assert DetectorClient("http://127.0.0.1:8101", transport=transport).health().error == (
        "HTTP 503"
    )
    assert DetectorClient("http://127.0.0.1:8102", transport=transport).health().error == (
        "malformed /health body"
    )
    assert DetectorClient("http://127.0.0.1:8103", transport=transport).health().error == (
        "warming up"
    )


@pytest.mark.parametrize(
    "body",
    [
        {"width": 1, "height": 1, "objects": [{"model": "m", "label": "l", "conf": 1}]},
        {"width": 1, "height": 1, "objects": [{"model": "m", "label": "l", "conf": 1, "box": [1]}]},
        {"height": 1, "objects": []},
        {"width": 0, "height": 1, "objects": []},
    ],
)
def test_detect_rejects_malformed_bodies(body):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    with pytest.raises(DetectorError, match="malformed /detect body"):
        DetectorClient(DEFAULT_URL, transport=transport).detect(PNG_1X1)


def test_detect_reports_http_errors():
    transport = httpx.MockTransport(lambda request: httpx.Response(415, text="bad image"))
    with pytest.raises(DetectorError, match="HTTP 415: bad image"):
        DetectorClient(DEFAULT_URL, transport=transport).detect(PNG_1X1)


def test_detect_needs_a_model():
    with pytest.raises(ValueError, match="at least one model"):
        DetectorClient(DEFAULT_URL, transport=unreachable_transport()).detect(PNG_1X1, models=())


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5:8003",
        "http://192.168.1.4:8003",
        "http://example.com:8003",
        "https://detector.internal",
        "ftp://127.0.0.1:8003",
        "127.0.0.1:8003",
    ],
)
def test_only_loopback_urls_are_accepted(url):
    with pytest.raises(ValueError, match="loopback|http"):
        DetectorClient(url)


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:8003/", "http://localhost:9", "http://[::1]:8003"]
)
def test_loopback_urls_are_accepted(url):
    assert DetectorClient(url).base_url == url.rstrip("/")


def test_url_from_environment(monkeypatch):
    monkeypatch.setenv(URL_ENV, "http://127.0.0.1:9999")
    assert DetectorClient().base_url == "http://127.0.0.1:9999"
    monkeypatch.setenv(URL_ENV, "http://8.8.8.8:80")
    with pytest.raises(ValueError, match="not loopback"):
        DetectorClient()
    monkeypatch.delenv(URL_ENV)
    assert DetectorClient().base_url == DEFAULT_URL


def test_proxies_from_the_environment_are_ignored(monkeypatch, stub):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    assert DetectorClient(stub.url).health().ok
