# Local YOLO detector (Safety hazard scan)

`hazards/scan.py` needs object boxes on each clip's temporal **background** image, in place of
the original script's FastSAM masks. The app's `.venv` has no torch, so YOLO runs here: a stdlib
`http.server` in the container `detector`, published on **127.0.0.1:8003 only**.

| File | Runs where | What |
|---|---|---|
| `server.py` | container | Loads the models once, serves `/health` and `/detect` |
| `client.py` | app `.venv` | httpx client used by `scan.py` (loopback URLs only) |
| `../../scripts/hazards/detector_up.sh` | host | Idempotent: build image if missing, start container, wait for health |

```bash
scripts/hazards/detector_up.sh              # build if needed, start if needed, wait for /health
scripts/hazards/detector_up.sh --recreate   # new container (after changing env/mounts)
scripts/hazards/detector_up.sh --rebuild    # rebuild cameravision/detector:local too
scripts/hazards/detector_up.sh --load-base  # fresh machine: load the bundle pytorch tar (below)
```

`server.py` is mounted read-only from the repo, so after editing it run `docker restart detector`.

## API

- `GET /health` returns `{ok, device, models: {name: sha256}, half, classes, versions, gpu_memory}`.
  `ok` is false, with an `error`, while models load (about 3 s) or if loading failed.
- `POST /detect?models=yolo11s[,yolov8s-worldv2]&conf=0.25[&imgsz=768]` takes a JPEG/PNG body
  (20 MB max). It returns `{width, height, objects: [{model, label, conf, box: [x0, y0, x1, y1]}],
  elapsed_ms}`.
  - Boxes are in the posted image's pixels, grouped by model in the requested order, highest
    confidence first.
  - Defaults are `models=yolo11s`, `conf=0.25` and `imgsz=768`, the same input size FastSAM used
    on the 768-wide background.
- Errors are JSON `{error}`:
  - 400: bad parameters or an image that cannot be decoded;
  - 411: no `Content-Length`, or a chunked body;
  - 413: body over 20 MB (refused without reading it);
  - 415: not JPEG/PNG;
  - 503: models not loaded.

```bash
curl -s --noproxy '*' 127.0.0.1:8003/health | jq
curl -s --noproxy '*' -H 'Content-Type: image/png' --data-binary @background.png \
  '127.0.0.1:8003/detect?models=yolo11s&conf=0.25' | jq
```

## Models (read-only from `~/bundle/models`)

| name | file | sha256 |
|---|---|---|
| `yolo11s` (default) | `ultralytics__yolo11/yolo11s.pt` | `85a76fe86dd8afe384648546b56a7a78580c7cb7b404fc595f97969322d502d5` |
| `yolov8s-worldv2` | `ultralytics__yolov8-world/yolov8s-worldv2.pt` | `9b2c17ab6124a913e9b3a5c170617920d91b0f01111a8479da69f00e2cf27792` |

`/health` hashes the mounted files at startup, so `scan.py` can record them in
`run_manifest.json`. YOLO-World runs with the 80-class vocabulary stored in its checkpoint;
`set_classes` needs a CLIP text encoder that is not on this machine, and the server never calls it.
Pose weights are not loaded.

## Offline by construction

These settings and checks keep the detector from fetching anything:

- **Build:**
  - The build container runs with `--network none`.
  - pip uses only the bundle wheelhouse (`--no-index`).
  - The image's `PIP_CONSTRAINT` is kept, and torch, torchvision and numpy are pinned. The
    script checks that torch is unchanged and that CUDA works.
  - The result is `docker commit`ted as `cameravision/detector:local`; nothing is pulled or pushed.
- **Runtime env:**
  - `YOLO_OFFLINE=1` skips Ultralytics' DNS probe at import, and also its analytics.
  - `YOLO_AUTOINSTALL=false` blocks pip.
  - `HF_HUB_OFFLINE=1` keeps the Hugging Face hub offline.
  - Settings `sync=false`.
  - `HTTP(S)_PROXY` points at a closed local port, so any stray HTTP fetch would fail loudly
    rather than download.
- **Code:**
  - Models load from local file paths, which Ultralytics never resolves online.
  - Nothing is ever plotted, so Ultralytics never fetches a font.
- **Check:** `detector_up.sh` greps the server's log for download-looking lines on every run.
  On 2026-10-03:
  - the server log had none;
  - the only URLs in the whole log are the NVIDIA license banner;
  - `docker diff detector` showed no new files besides NVIDIA's local kernel JIT cache and the
    settings file.

## Image notes (deviations from the plain recipe)

1. **Headless OpenCV.** The wheelhouse's `opencv-python` (GUI build) needs `libGL`, `libX11`,
   `libxcb`, `libSM`, `libICE` and `libXext`. The CUDA image ships none of them, and they can't be
   installed offline. So after `pip install ultralytics`, the build swaps in
   `opencv-python-headless` at the same version (5.0.0.93):
   - It is the wheel pinned in `uv.lock` that the app's `.venv` already installed.
   - It is repacked from `.venv` with every file checked against its RECORD sha256.
   - Ultralytics only does `import cv2`. As a result, `pip check` will say ultralytics wants
     `opencv-python`, which is expected.
2. **Bundle pytorch tar.** A plain `docker load -i ~/bundle/containers/pytorch-26.04-py3-arm64.tar`
   imports, but containers then fail with "mismatched image rootfs and manifest layers" (Docker
   uses the containerd image store here). The tar's `manifest.json` lists 62 deduplicated layers,
   while the config has 78 diff_ids, because the empty layer repeats.
   - `--load-base` hashes every layer, then streams the same blobs and config with a manifest that
     lists all 78. The image ID is `sha256:608b4824…` and the config stays `sha256:48901b31…`.
3. **One GPU thread.** All loading and inference run on one long-lived worker thread.
   `ThreadingHTTPServer` gives each request a new thread, and the first YOLO11 predict on a fresh
   thread costs 450–620 ms on the GB10, against about 10 ms on a persistent thread.

## Measured on the GB10 (2026-10-03)

- **Latency:** fp16 on `cuda:0`. Server time for a 768x432 background PNG: yolo11s 11.7 ms,
  worldv2 12.5 ms, both 15.9 ms. Round trip through the client: 25–30 ms.
- **Memory:** `nvidia-smi` shows about 360 MiB for the process, CUDA context included. The torch
  allocator reserves 108 MB.
