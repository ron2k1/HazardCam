"""Shared test helpers for the hazard pipeline: synthetic video, stub detector, stub vLLM.

All media here is GENERATED TEST MEDIA (a moving square over a static drawn scene); no
network is used. The stub detector is a stdlib HTTP server on 127.0.0.1 and the stub vLLM
is an ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import cv2
import httpx
import numpy as np

FIXTURES = Path(__file__).parent / "fixtures"
STUB_MODEL = "nvidia/Qwen3.6-35B-A3B-NVFP4"
STUB_BASE_URL = "http://127.0.0.1:8000/v1"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def scene_background(width: int = 960, height: int = 540) -> np.ndarray:
    """A static factory-like scene: textured wall, grey floor, yellow aisle line, boxes."""
    img = np.zeros((height, width, 3), np.uint8)
    img[: height // 2] = (90, 80, 70)
    for x in range(0, width, 48):  # wall panels give edges/contours
        cv2.rectangle(img, (x + 4, 20), (x + 40, height // 2 - 20), (120, 110, 100), 2)
    img[height // 2 :] = (128, 128, 128)  # low-saturation floor
    cv2.rectangle(
        img, (0, int(height * 0.72)), (width, int(height * 0.74)), (0, 210, 230), -1
    )  # yellow paint line (BGR)
    cv2.rectangle(
        img,
        (int(width * 0.10), int(height * 0.55)),
        (int(width * 0.22), int(height * 0.68)),
        (40, 60, 120),
        -1,
    )
    cv2.rectangle(
        img,
        (int(width * 0.60), int(height * 0.60)),
        (int(width * 0.70), int(height * 0.70)),
        (30, 30, 30),
        -1,
    )
    cv2.circle(img, (int(width * 0.45), int(height * 0.62)), int(height * 0.05), (60, 60, 60), -1)
    return img


def write_video(path: Path, frames: Iterable[np.ndarray], fps: float) -> Path:
    """Write BGR frames as an mp4v .mp4 (cv2 only; no ffmpeg needed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = None
    try:
        for frame in frames:
            if writer is None:
                h, w = frame.shape[:2]
                writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
                assert writer.isOpened(), "mp4v writer unavailable"
            writer.write(frame)
    finally:
        if writer is not None:
            writer.release()
    return path


def moving_square_frames(
    background: np.ndarray, frames: int, square: int = 60
) -> Iterator[np.ndarray]:
    """The static scene with a white square crossing the floor in frames 5..frames-5."""
    height, width = background.shape[:2]
    for i in range(frames):
        frame = background.copy()
        if 5 <= i <= frames - 5:
            x = int((i - 5) / max(1, frames - 10) * (width - square - 40)) + 20
            y = int(height * 0.78)
            cv2.rectangle(frame, (x, y), (x + square, y + square), (255, 255, 255), -1)
        yield frame


def make_synthetic_video(
    path: Path,
    *,
    width: int = 960,
    height: int = 540,
    frames: int = 40,
    fps: float = 10.0,
    square: int = 60,
) -> Path:
    """A fixed-camera clip: static scene plus a white square moving left to right."""
    return write_video(
        path, moving_square_frames(scene_background(width, height), frames, square), fps
    )


# --- stub detector (real loopback HTTP server) ----------------------------------------------


@dataclass
class StubDetector:
    """``hazards/detector/server.py`` API on 127.0.0.1:<ephemeral>."""

    objects: list[dict[str, Any]] = field(default_factory=list)
    models: dict[str, str] = field(
        default_factory=lambda: {
            "yolo11s": "85a76fe8" + "0" * 56,
            "yolov8s-worldv2": "9b2c17ab" + "0" * 56,
        }
    )
    ok: bool = True
    requests: list[dict[str, Any]] = field(default_factory=list)
    server: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        assert self.server is not None
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> StubDetector:
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:
                pass

            def _send(self, status: int, body: dict[str, Any]) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                if urlsplit(self.path).path == "/health":
                    self._send(200, {"ok": stub.ok, "device": "cuda:0", "models": stub.models})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self) -> None:
                parts = urlsplit(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                image = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
                stub.requests.append(
                    {
                        "path": parts.path,
                        "query": parse_qs(parts.query),
                        "content_type": self.headers.get("Content-Type"),
                        "image_shape": None if image is None else image.shape,
                        "body": body,
                    }
                )
                if image is None:
                    self._send(415, {"error": "not an image"})
                    return
                h, w = image.shape[:2]
                self._send(
                    200, {"width": w, "height": h, "objects": stub.objects, "elapsed_ms": 12.5}
                )

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()


def unreachable_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    return httpx.MockTransport(handler)


# --- stub vLLM (OpenAI-compatible) ----------------------------------------------------------


def evidence_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The evidence records sent as per-image user messages (text part of each)."""
    out = []
    for message in payload["messages"]:
        content = message.get("content")
        if isinstance(content, list):
            texts = [p["text"] for p in content if p.get("type") == "text"]
            if texts:
                out.append(json.loads(texts[0]))
    return out


def valid_report_for(payload: dict[str, Any]) -> dict[str, Any]:
    """A report that passes ``validate_model_report`` for the request in ``payload``."""
    evidence = evidence_from_payload(payload)
    schema = payload["response_format"]["json_schema"]["schema"]
    zone_ids = schema["$defs"]["ZoneReview"]["properties"]["zone_id"].get("enum", [])
    crops = {}
    for e in evidence:
        if e["zone_id"] and e["zone_id"] not in crops:
            crops[e["zone_id"]] = e["evidence_id"]
    first = evidence[0]["evidence_id"]
    findings = []
    if zone_ids:
        findings.append(
            {
                "title": "Object near the marked aisle",
                "status": "needs_verification",
                "severity": "medium",
                "confidence": "low",
                "zone_ids": [zone_ids[-1]],
                "evidence_ids": [first, crops[zone_ids[-1]]],
                "location": f"Floor area {zone_ids[-1]}",
                "observation": f"A dark object sits near the yellow line ({first}).",
                "risk_interpretation": "It may narrow the walkway.",
                "standards": ["1910.176(a)"],
                "applicability_reason": "Marked aisle visible.",
                "unknowns": ["Intended clearance"],
                "recommended_actions": ["Check the clearance"],
            }
        )
    return {
        "scene_summary": "A synthetic test scene with a moving square.",
        "findings": findings,
        "zone_reviews": [
            {
                "zone_id": z,
                "interpretation": "Test zone.",
                "disposition": "unclear",
                "evidence_ids": [crops[z]],
            }
            for z in zone_ids
        ],
        "dismissed": [],
        "limitations": ["Synthetic scene."],
    }


@dataclass
class StubVLLM:
    """Records every request; ``responder(payload, call_index)`` builds the content."""

    responder: Callable[[dict[str, Any], int], tuple[str, str]] | None = None
    served: list[str] = field(default_factory=lambda: [STUB_MODEL])
    max_model_len: int = 262144
    status: int = 200
    chat_payloads: list[dict[str, Any]] = field(default_factory=list)
    model_calls: int = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/models"):
            self.model_calls += 1
            data = [
                {
                    "id": m,
                    "object": "model",
                    "root": f"/models/{m}",
                    "max_model_len": self.max_model_len,
                }
                for m in self.served
            ]
            return httpx.Response(200, json={"object": "list", "data": data})
        if request.method == "POST" and request.url.path.endswith("/chat/completions"):
            payload = json.loads(request.content)
            self.chat_payloads.append(payload)
            if self.status != 200:
                return httpx.Response(self.status, json={"error": {"message": "bad request"}})
            if self.responder is None:
                content, finish = json.dumps(valid_report_for(payload)), "stop"
            else:
                content, finish = self.responder(payload, len(self.chat_payloads) - 1)
            body = {
                "id": "cmpl-test",
                "object": "chat.completion",
                "model": payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": finish,
                    }
                ],
                "usage": {"prompt_tokens": 1234, "completion_tokens": 321, "total_tokens": 1555},
            }
            return httpx.Response(200, json=body)
        return httpx.Response(404, json={"error": "not found"})

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
