"""The detector service's HTTP layer (``hazards/detector/server.py``) against the real client.

The real handler runs in-process on 127.0.0.1:<ephemeral> with a stub model state, so no torch,
GPU or ultralytics is needed; ``DetectorState.detect`` still goes through the single GPU worker
thread. The live container is checked by ``scripts/hazards/detector_up.sh``.
"""

from __future__ import annotations

import http.client
import os
import socket
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from typing import Any

import cv2
import numpy as np
import pytest

from hazards.detector.client import DetectorClient, DetectorError

SHA_A = "85a76fe86dd8afe384648546b56a7a78580c7cb7b404fc595f97969322d502d5"
SHA_B = "9b2c17ab6124a913e9b3a5c170617920d91b0f01111a8479da69f00e2cf27792"


@pytest.fixture(scope="module")
def server_mod() -> Any:
    # The module sets offline env defaults on import; keep them out of the test process.
    saved = dict(os.environ)
    try:
        from hazards.detector import server
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return server


class StubState:
    """Factory for a ``DetectorState`` whose ``_detect`` returns canned boxes."""

    @staticmethod
    def make(server_mod: Any, *, ready: bool = True) -> Any:
        state = server_mod.DetectorState(
            {"yolo11s": "/models/a.pt", "yolov8s-worldv2": "/models/b.pt"}, half=True
        )
        state.calls = []
        if ready:
            state.ready, state.error = True, None
            state.device, state.half = "cuda:0 (stub)", True
            state.sha256 = {"yolo11s": SHA_A, "yolov8s-worldv2": SHA_B}

        def _detect(image: np.ndarray, names: list[str], conf: float, imgsz: int) -> list[dict]:
            state.calls.append(
                {
                    "shape": image.shape,
                    "names": names,
                    "conf": conf,
                    "imgsz": imgsz,
                    "thread": threading.current_thread().name,
                }
            )
            return [
                {"model": n, "label": "suitcase", "conf": 0.5, "box": [1.0, 2.0, 30.5, 40.25]}
                for n in names
            ]

        state._detect = _detect
        return state


@pytest.fixture
def running(server_mod: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, str]]:
    state = StubState.make(server_mod)
    monkeypatch.setattr(server_mod, "STATE", state)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, args=(0.02,), daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    try:
        yield state, f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        state.gpu.shutdown(wait=True)


def _png(w: int = 64, h: int = 48) -> bytes:
    img = np.zeros((h, w, 3), np.uint8)
    cv2.rectangle(img, (5, 5), (30, 30), (0, 200, 255), -1)
    return cv2.imencode(".png", img)[1].tobytes()


def _jpeg(w: int = 80, h: int = 60) -> bytes:
    return cv2.imencode(".jpg", np.full((h, w, 3), 127, np.uint8))[1].tobytes()


def _post(url: str, path: str, body: bytes, headers: dict[str, str] | None = None):
    host, port = url.removeprefix("http://").split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=10)
    conn.request("POST", path, body=body, headers=headers or {})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def test_parse_model_specs(server_mod: Any) -> None:
    specs = server_mod.parse_model_specs(" yolo11s=/m/a.pt, yolov8s-worldv2=/m/b.pt ,")
    assert list(specs.items()) == [("yolo11s", "/m/a.pt"), ("yolov8s-worldv2", "/m/b.pt")]
    for bad in ("", "yolo11s", "=/m/a.pt", "Bad Name=/m/a.pt", "yolo11s="):
        with pytest.raises(ValueError):
            server_mod.parse_model_specs(bad)


def test_health_matches_client_contract(running: tuple[Any, str]) -> None:
    _, url = running
    health = DetectorClient(url).health()
    assert health.ok is True
    assert health.device == "cuda:0 (stub)"
    assert health.models == {"yolo11s": SHA_A, "yolov8s-worldv2": SHA_B}
    assert health.error is None


def test_health_while_loading_reports_not_ok(
    server_mod: Any, running: tuple[Any, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, url = running
    loading = StubState.make(server_mod, ready=False)
    monkeypatch.setattr(server_mod, "STATE", loading)
    try:
        health = DetectorClient(url).health()
        assert health.ok is False
        assert health.models == {}
        assert health.error == "loading models"
        status, body = _post(url, "/detect", _png())
        assert status == 503
        assert b"loading models" in body
    finally:
        loading.gpu.shutdown(wait=True)


def test_detect_png_defaults(running: tuple[Any, str]) -> None:
    state, url = running
    result = DetectorClient(url).detect(_png(64, 48), content_type="image/png")
    assert (result.width, result.height) == (64, 48)
    assert [(o.model, o.label, o.conf, o.box) for o in result.objects] == [
        ("yolo11s", "suitcase", 0.5, (1.0, 2.0, 30.5, 40.25))
    ]
    assert result.elapsed_ms is not None and result.elapsed_ms >= 0
    (call,) = state.calls
    assert call["shape"] == (48, 64, 3)
    assert call["names"] == ["yolo11s"]  # client default: yolo11s only
    assert call["conf"] == 0.25
    assert call["imgsz"] == 768  # FastSAM's input size on the 768-wide background
    assert call["thread"].startswith("gpu")  # all inference on the one GPU worker thread


def test_detect_jpeg_both_models_in_order(running: tuple[Any, str]) -> None:
    state, url = running
    result = DetectorClient(url).detect(
        _jpeg(80, 60), content_type="image/jpeg", models=("yolov8s-worldv2", "yolo11s"), conf=0.4
    )
    assert (result.width, result.height) == (80, 60)
    assert [o.model for o in result.objects] == ["yolov8s-worldv2", "yolo11s"]
    assert state.calls[-1]["names"] == ["yolov8s-worldv2", "yolo11s"]
    assert state.calls[-1]["conf"] == 0.4


def test_server_default_models_without_query(running: tuple[Any, str]) -> None:
    state, url = running
    status, _ = _post(url, "/detect", _png())
    assert status == 200
    assert state.calls[-1]["names"] == ["yolo11s"]


@pytest.mark.parametrize(
    ("path", "body", "status", "needle"),
    [
        ("/detect", b"", 400, b"empty body"),
        ("/detect", b"GIF89a" + b"0" * 64, 415, b"JPEG or PNG"),
        ("/detect", b"\xff\xd8\xff" + b"0" * 64, 400, b"could not be decoded"),
        ("/detect?models=yolo99", None, 400, b"unknown model"),
        ("/detect?models=,", None, 400, b"at least one model"),
        ("/detect?conf=0", None, 400, b"conf must be"),
        ("/detect?conf=1.5", None, 400, b"conf must be"),
        ("/detect?imgsz=700", None, 400, b"imgsz must be"),
        ("/health", None, 405, b"GET /health"),
        ("/nope", None, 404, b"not found"),
    ],
)
def test_detect_rejects_bad_requests(
    running: tuple[Any, str], path: str, body: bytes | None, status: int, needle: bytes
) -> None:
    state, url = running
    got_status, got_body = _post(url, path, _png() if body is None else body)
    assert got_status == status
    assert needle in got_body
    assert state.calls == []


def test_client_raises_detector_error_on_http_error(running: tuple[Any, str]) -> None:
    _, url = running
    with pytest.raises(DetectorError, match="HTTP 400"):
        DetectorClient(url).detect(_png(), models=("yolo99",))


def test_oversized_body_is_refused_unread(server_mod: Any, running: tuple[Any, str]) -> None:
    state, url = running
    host, port = url.removeprefix("http://").split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=10)
    conn.putrequest("POST", "/detect")
    conn.putheader("Content-Length", str(server_mod.MAX_BODY_BYTES + 1))
    conn.endheaders()  # announce 20 MB + 1 but send nothing: the server must not wait for it
    resp = conn.getresponse()
    assert resp.status == 413
    assert b"body over" in resp.read()
    conn.close()
    assert state.calls == []


def test_get_detect_is_405_and_unknown_get_is_404(running: tuple[Any, str]) -> None:
    _, url = running
    host, port = url.removeprefix("http://").split(":")
    for path, status in (("/detect", 405), ("/", 404)):
        conn = http.client.HTTPConnection(host, int(port), timeout=10)
        conn.request("GET", path)
        assert conn.getresponse().status == status
        conn.close()


def test_missing_length_and_chunked_bodies_are_411(running: tuple[Any, str]) -> None:
    _, url = running
    host, port = url.removeprefix("http://").split(":")
    for extra in (b"", b"Transfer-Encoding: chunked\r\n"):
        with socket.create_connection((host, int(port)), timeout=10) as sock:
            sock.sendall(b"POST /detect HTTP/1.1\r\nHost: x\r\n" + extra + b"\r\n")
            reply = sock.recv(4096)
        assert reply.startswith(b"HTTP/1.0 411"), reply[:40]
