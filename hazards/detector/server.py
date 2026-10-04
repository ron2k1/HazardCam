"""Local YOLO object detector for the Safety hazard scan (runs in the ``detector`` container).

The app's ``.venv`` has no torch, so ``hazards/scan.py`` asks this service for object boxes on
the clip's temporal BACKGROUND image (``hazards/detector/client.py``). It replaces the
original FastSAM masks; ``scan.py`` turns every box into a rectangular mask and unions them
with the original edge-contour masks.

Stdlib ``http.server`` only (ultralytics/torch/cv2 come from the ``cameravision/detector:local``
image). Models load once, half precision on CUDA. All GPU work (load, warm-up, every predict)
runs on ONE long-lived worker thread: that serializes inference, and it matters for speed,
because the first YOLO11 predict on a fresh thread costs ~0.5 s of per-thread CUDA setup on the
GB10 (measured 450-620 ms on a new thread per request vs ~10 ms on a persistent thread), and
``ThreadingHTTPServer`` gives every request a new thread.

API (bind 0.0.0.0:8003 in the container; published on 127.0.0.1:8003 only):

- ``GET /health`` -> ``{ok, device, models: {name: sha256}, ...}``; ``ok`` is false (with
  ``error``) while the models load or if loading failed.
- ``POST /detect?models=yolo11s[,yolov8s-worldv2]&conf=0.25[&imgsz=768]`` with a JPEG/PNG body
  (at most 20 MB) -> ``{width, height, objects: [{model, label, conf, box: [x0, y0, x1, y1]}],
  elapsed_ms}``. Boxes are in the posted image's pixels; objects are grouped by model in the
  requested order, highest confidence first.

Offline by construction: model paths are local files (Ultralytics never resolves them online),
``YOLO_OFFLINE=1`` skips its startup DNS probe and analytics, ``YOLO_AUTOINSTALL=false`` blocks pip,
settings ``sync`` is turned off, nothing is plotted (no font fetch), and YOLO-World runs with the
vocabulary stored in its checkpoint (``set_classes`` would need a CLIP text encoder and is never
called).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

# Offline guards must be in place before ultralytics is imported (it probes DNS at import time
# unless YOLO_OFFLINE is set). The container sets them too; these are the fallback.
os.environ.setdefault("YOLO_OFFLINE", "1")
os.environ.setdefault("YOLO_AUTOINSTALL", "false")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
# Refuse to decode absurd images (a small JPEG header can claim gigapixels).
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(50_000_000))

MAX_BODY_BYTES = 20 * 1024 * 1024
DEFAULT_MODEL_SPECS = (
    "yolo11s=/models/ultralytics__yolo11/yolo11s.pt,"
    "yolov8s-worldv2=/models/ultralytics__yolov8-world/yolov8s-worldv2.pt"
)
DEFAULT_CONF = 0.25
# FastSAM ran on the 768-wide analysis background with imgsz=768; keep the same input size.
DEFAULT_IMGSZ = 768
MAX_DET = 300
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _log(msg: str) -> None:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    print(f"{stamp}Z [detector] {msg}", file=sys.stderr, flush=True)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_model_specs(text: str) -> dict[str, str]:
    """``"name=/path.pt,name2=/path2.pt"`` -> ordered ``{name: path}``."""
    specs: dict[str, str] = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        name, sep, path = part.partition("=")
        name, path = name.strip(), path.strip()
        if not sep or not _NAME_RE.match(name) or not path:
            raise ValueError(f"bad DETECTOR_MODELS entry {part!r} (want name=/path.pt)")
        specs[name] = path
    if not specs:
        raise ValueError("DETECTOR_MODELS is empty")
    return specs


class DetectorState:
    """Models, device and load status shared by request threads."""

    def __init__(self, specs: dict[str, str], half: bool) -> None:
        self.specs = specs
        self.want_half = half
        self.models: dict[str, Any] = {}
        self.sha256: dict[str, str] = {}
        self.labels: dict[str, int] = {}
        self.device = "unknown"
        self.device_arg: Any = "cpu"
        self.half = False
        self.ready = False
        self.error: str | None = "loading models"
        # Ultralytics 8.4 `quantize` (replaces the deprecated `half`): 16 = fp16, 32 = fp32.
        self.precision = 32
        self.versions: dict[str, str] = {}
        # The only thread that touches CUDA/ultralytics (see the module docstring).
        self.gpu = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gpu")
        self.gpu_mem: dict[str, float] | None = None  # refreshed on the GPU thread only

    def load(self) -> None:
        try:
            t0 = time.perf_counter()
            for name, path in self.specs.items():
                if not os.path.isfile(path):
                    raise FileNotFoundError(f"model file for {name!r} not found: {path}")
                self.sha256[name] = _sha256(path)

            import numpy as np
            import torch
            import ultralytics
            from ultralytics import YOLO
            from ultralytics.utils import SETTINGS

            SETTINGS.update({"sync": False})  # no analytics events, ever
            if torch.cuda.is_available():
                self.device_arg = 0
                self.device = f"cuda:0 ({torch.cuda.get_device_name(0)})"
                self.half = self.want_half
            else:
                self.device_arg = "cpu"
                self.device = "cpu"
                self.half = False
            self.precision = 16 if self.half else 32
            self.versions = {
                "ultralytics": ultralytics.__version__,
                "torch": str(torch.__version__),
                "python": sys.version.split()[0],
            }
            blank = np.zeros((432, 768, 3), np.uint8)
            for name, path in self.specs.items():
                # A local file path is used as-is; Ultralytics only downloads names it cannot
                # find on disk. "-world" in the stem routes to YOLOWorld with its stored vocab.
                model = YOLO(path, task="detect")
                model.predict(
                    blank,
                    imgsz=DEFAULT_IMGSZ,
                    conf=DEFAULT_CONF,
                    device=self.device_arg,
                    quantize=self.precision,
                    verbose=False,
                )  # warm-up: CUDA kernels + fp16 weights before the first real request
                self.models[name] = model
                self.labels[name] = len(model.names)
                _log(f"loaded {name} sha256={self.sha256[name][:12]}... classes={len(model.names)}")
            self.gpu_mem = self.gpu_memory()
            self.error = None
            self.ready = True
            _log(
                f"ready on {self.device} half={self.half} models={list(self.models)} "
                f"in {time.perf_counter() - t0:.1f}s; {self.gpu_mem}"
            )
        except Exception as exc:  # noqa: BLE001 - reported through /health, not raised
            self.error = f"model load failed: {type(exc).__name__}: {exc}"
            self.ready = False
            _log(self.error)
            traceback.print_exc(file=sys.stderr)

    def gpu_memory(self) -> dict[str, float] | None:
        try:
            import torch

            if not torch.cuda.is_available():
                return None
            mb = 1024 * 1024
            return {
                "allocated_mb": round(torch.cuda.memory_allocated() / mb, 1),
                "reserved_mb": round(torch.cuda.memory_reserved() / mb, 1),
                "max_allocated_mb": round(torch.cuda.max_memory_allocated() / mb, 1),
            }
        except Exception:  # noqa: BLE001
            return None

    def health(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "ok": self.ready,
            "device": self.device,
            "models": dict(self.sha256) if self.ready else {},
            "half": self.half,
            "classes": dict(self.labels),
            "versions": self.versions,
            "gpu_memory": self.gpu_mem,
        }
        if self.error:
            body["error"] = self.error
        return body

    def detect(self, image: Any, names: list[str], conf: float, imgsz: int) -> list[dict]:
        """Run on the GPU worker thread; blocks the calling request thread until done."""
        return self.gpu.submit(self._detect, image, names, conf, imgsz).result()

    def _detect(self, image: Any, names: list[str], conf: float, imgsz: int) -> list[dict]:
        objects: list[dict] = []
        for name in names:
            result = self.models[name].predict(
                image,
                imgsz=imgsz,
                conf=conf,
                device=self.device_arg,
                quantize=self.precision,
                max_det=MAX_DET,
                verbose=False,
            )[0]
            boxes = result.boxes
            if boxes is None or len(boxes) == 0:
                continue
            xyxy = boxes.xyxy.float().cpu().numpy().tolist()
            confs = boxes.conf.float().cpu().numpy().tolist()
            classes = boxes.cls.int().cpu().numpy().tolist()
            rows = sorted(zip(confs, classes, xyxy, strict=True), key=lambda r: -r[0])
            for c, k, box in rows:
                objects.append(
                    {
                        "model": name,
                        "label": str(result.names[int(k)]),
                        "conf": round(float(c), 4),
                        "box": [round(float(v), 2) for v in box],
                    }
                )
        self.gpu_mem = self.gpu_memory()
        return objects


STATE: DetectorState | None = None


class Handler(BaseHTTPRequestHandler):
    server_version = "cameravision-detector/1"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:
        _log(f"{self.address_string()} {format % args}")

    def _json(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: int, message: str, **extra: Any) -> None:
        self._json(status, {"error": message, **extra})

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/health":
            assert STATE is not None
            self._json(200, STATE.health())
        elif path == "/detect":
            self._error(405, "use POST /detect")
        else:
            self._error(404, "not found")

    def do_POST(self) -> None:
        parts = urlsplit(self.path)
        if parts.path != "/detect":
            self.close_connection = True
            if parts.path == "/health":
                self._error(405, "use GET /health")
            else:
                self._error(404, "not found")
            return
        assert STATE is not None
        t0 = time.perf_counter()

        # --- body: Content-Length required, 20 MB cap, never read an oversized body.
        if self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            self._error(411, "chunked bodies are not supported; send Content-Length")
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.close_connection = True
            self._error(411, "Content-Length required")
            return
        if length > MAX_BODY_BYTES:
            self.close_connection = True
            self._error(413, f"body over {MAX_BODY_BYTES} bytes", max_bytes=MAX_BODY_BYTES)
            return
        if length <= 0:
            self._error(400, "empty body; POST a JPEG or PNG image")
            return
        body = self._read_exact(length)
        if body is None:
            self.close_connection = True
            self._error(400, "body shorter than Content-Length")
            return

        # --- query
        query = parse_qs(parts.query, keep_blank_values=True)
        try:
            names = self._parse_models(query)
            conf = float(query.get("conf", [str(DEFAULT_CONF)])[-1])
            if not 0.0 < conf <= 1.0:
                raise ValueError("conf must be in (0, 1]")
            imgsz = int(query.get("imgsz", [str(DEFAULT_IMGSZ)])[-1])
            if imgsz % 32 or not 160 <= imgsz <= 1920:
                raise ValueError("imgsz must be a multiple of 32 in [160, 1920]")
        except ValueError as exc:
            self._error(400, str(exc), available=list(STATE.specs))
            return
        if not STATE.ready:
            self._error(503, STATE.error or "models not loaded")
            return

        # --- image
        if not body.startswith((_JPEG_MAGIC, _PNG_MAGIC)):
            self._error(415, "body must be a JPEG or PNG image")
            return
        import cv2
        import numpy as np

        image = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.ndim != 3 or image.shape[2] != 3:
            self._error(400, "image could not be decoded")
            return
        height, width = int(image.shape[0]), int(image.shape[1])
        try:
            objects = STATE.detect(image, names, conf, imgsz)
        except Exception as exc:  # noqa: BLE001
            _log(f"detect failed: {type(exc).__name__}: {exc}")
            traceback.print_exc(file=sys.stderr)
            self._error(500, f"inference failed: {type(exc).__name__}")
            return
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        _log(
            f"detect {width}x{height} models={','.join(names)} conf={conf:g} imgsz={imgsz} "
            f"-> {len(objects)} objects in {elapsed_ms} ms"
        )
        self._json(
            200,
            {"width": width, "height": height, "objects": objects, "elapsed_ms": elapsed_ms},
        )

    def _read_exact(self, length: int) -> bytes | None:
        chunks, left = [], length
        while left > 0:
            chunk = self.rfile.read(min(left, 1 << 20))
            if not chunk:
                return None
            chunks.append(chunk)
            left -= len(chunk)
        return b"".join(chunks)

    @staticmethod
    def _parse_models(query: dict[str, list[str]]) -> list[str]:
        assert STATE is not None
        raw = query.get("models", [os.environ.get("DETECTOR_DEFAULT_MODELS", "yolo11s")])[-1]
        names = list(dict.fromkeys(n.strip() for n in raw.split(",") if n.strip()))
        if not names:
            raise ValueError("models must name at least one model")
        unknown = [n for n in names if n not in STATE.specs]
        if unknown:
            raise ValueError(f"unknown model(s): {', '.join(unknown)}")
        return names


def main() -> None:
    global STATE
    # Container-internal bind; docker publishes it on 127.0.0.1 only.
    host = os.environ.get("DETECTOR_HOST", "0.0.0.0")
    port = int(os.environ.get("DETECTOR_PORT", "8003"))
    specs = parse_model_specs(os.environ.get("DETECTOR_MODELS", DEFAULT_MODEL_SPECS))
    half = os.environ.get("DETECTOR_HALF", "1").strip().lower() not in {"0", "false", "no"}
    # Marker for scripts/hazards/detector_up.sh: its download check reads the log from here on
    # (the NVIDIA entrypoint banner above it carries license URLs).
    _log(f"starting pid={os.getpid()} YOLO_OFFLINE={os.environ.get('YOLO_OFFLINE')}")
    STATE = DetectorState(specs, half)
    STATE.gpu.submit(STATE.load)  # load + warm up on the GPU worker thread
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    _log(f"listening on {host}:{port}; models={list(specs)} (loading)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
