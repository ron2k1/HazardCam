#!/usr/bin/env bash
# Start the local YOLO detector for the Safety hazard scan. Idempotent:
#   1. builds the image cameravision/detector:local if it is missing, from the already-loaded
#      nvcr.io/nvidia/pytorch:26.04-py3 plus ultralytics installed OFFLINE from the bundle
#      wheelhouse (build container has --network none; torch/torchvision/numpy pinned; the
#      image's PIP_CONSTRAINT is kept), then `docker commit` (no registry pull or push).
#      opencv-python (GUI) from the wheelhouse needs X11/GL libraries the CUDA image does not
#      ship (libGL, libX11, libxcb, ...), so it is swapped for opencv-python-headless at the
#      same version: the wheel pinned in uv.lock that the app's .venv already installed,
#      repacked from .venv with every file checked against its RECORD sha256;
#   2. starts the container "detector" if it is not running (GPU, 127.0.0.1:8003 only,
#      models + hazards/detector mounted read-only, Ultralytics offline env);
#   3. waits for GET /health to report ok and checks the container log for download attempts.
#
# usage: scripts/hazards/detector_up.sh [--rebuild] [--recreate] [--timeout SECONDS]
#        scripts/hazards/detector_up.sh --load-base [PYTORCH_TAR]
#   --rebuild   rebuild the image even if it exists (implies --recreate)
#   --recreate  remove and start the container again (picks up new env/mounts)
#   --load-base load the bundle's pytorch tar so the containerd image store can run it, then
#               exit. Plain `docker load` of that tar gives "mismatched image rootfs and manifest
#               layers": its manifest.json lists 62 deduplicated layers while the config has 78
#               diff_ids (the empty layer repeats). This streams the same blobs and config with
#               a manifest that lists all 78, after checking every layer's diff_id.
# env: HAZARDS_MODELS_DIR (default ~/bundle/models), HAZARDS_WHEELS_DIR
#      (default ~/bundle/stack/wheels/py312-aarch64), DETECTOR_PORT (default 8003),
#      DETECTOR_BASE_IMAGE (default nvcr.io/nvidia/pytorch:26.04-py3),
#      HAZARDS_EXTRA_WHEELS_DIR (default ~/.cache/cameravision/wheels, repacked headless wheel)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

BASE_IMAGE="${DETECTOR_BASE_IMAGE:-nvcr.io/nvidia/pytorch:26.04-py3}"
IMAGE="cameravision/detector:local"
NAME="detector"
PORT="${DETECTOR_PORT:-8003}"
MODELS_DIR="${HAZARDS_MODELS_DIR:-$HOME/bundle/models}"
WHEELS_DIR="${HAZARDS_WHEELS_DIR:-$HOME/bundle/stack/wheels/py312-aarch64}"
APP_DIR="$ROOT/hazards/detector"
EXTRA_WHEELS_DIR="${HAZARDS_EXTRA_WHEELS_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/cameravision/wheels}"
VENV_SITE="$ROOT/.venv/lib/python3.12/site-packages"
TIMEOUT_S=180
REBUILD=0
RECREATE=0
LOAD_BASE=""
# Container paths of the models the server loads (name=path, comma separated).
DETECTOR_MODELS="yolo11s=/models/ultralytics__yolo11/yolo11s.pt,yolov8s-worldv2=/models/ultralytics__yolov8-world/yolov8s-worldv2.pt"

while (($#)); do
  case "$1" in
    --rebuild) REBUILD=1; RECREATE=1 ;;
    --load-base)
      LOAD_BASE="$HOME/bundle/containers/pytorch-26.04-py3-arm64.tar"
      if [[ ${2:-} == *.tar ]]; then LOAD_BASE="$2"; shift; fi
      ;;
    --recreate) RECREATE=1 ;;
    --timeout) TIMEOUT_S="${2:?--timeout needs seconds}"; shift ;;
    -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done
[[ $TIMEOUT_S =~ ^[1-9][0-9]{0,4}$ ]] || { echo "--timeout must be whole seconds" >&2; exit 2; }
[[ $PORT =~ ^[1-9][0-9]{1,4}$ ]] || { echo "DETECTOR_PORT must be a port number" >&2; exit 2; }

say() { printf '[detector_up] %s\n' "$*" >&2; }

# Shells started before the user joined the docker group need `sg docker`.
if docker info >/dev/null 2>&1; then
  dk() { docker "$@"; }
else
  dk() { sg docker -c "$(printf '%q ' docker "$@")"; }
fi

# Load the bundle pytorch docker-archive with a manifest that lists every layer (see --load-base).
load_base_image() {
  local tar="$1"
  [[ -f $tar ]] || { say "not found: $tar"; exit 1; }
  say "loading $tar with a corrected manifest (verifying every layer first)"
  python3 - "$tar" <<'PY' | dk load
import hashlib, io, json, sys, tarfile, zlib
from concurrent.futures import ThreadPoolExecutor

src = sys.argv[1]
with tarfile.open(src, "r:") as t:
    members = {m.name: m for m in t.getmembers()}
    manifest = json.load(t.extractfile(members["manifest.json"]))
    if len(manifest) != 1:
        sys.exit("expected one image in manifest.json")
    entry = manifest[0]
    config = json.load(t.extractfile(members[entry["Config"]]))
diff_ids = config["rootfs"]["diff_ids"]

def layer_digests(name):
    m = members[name]
    d = zlib.decompressobj(16 + zlib.MAX_WBITS) if name.endswith(".gz") else None
    raw, packed, left = hashlib.sha256(), hashlib.sha256(), m.size
    with open(src, "rb") as f:
        f.seek(m.offset_data)
        while left:
            buf = f.read(min(8 << 20, left))
            if not buf:
                sys.exit(f"short read in {name}")
            left -= len(buf)
            packed.update(buf)
            raw.update(d.decompress(buf) if d else buf)
        if d:
            raw.update(d.flush())
    return name, "sha256:" + packed.hexdigest(), "sha256:" + raw.hexdigest()

with ThreadPoolExecutor(max_workers=8) as ex:
    found = list(ex.map(layer_digests, entry["Layers"]))
by_diff = {}
for name, packed, raw in found:
    stem = name.rsplit("/", 1)[-1].split(".")[0]
    if packed.split(":")[1] != stem:
        sys.exit(f"{name}: content digest {packed} does not match its file name")
    by_diff[raw] = name
missing = [d for d in diff_ids if d not in by_diff]
if missing:
    sys.exit(f"{len(missing)} diff_ids have no layer in the tar: {missing[:3]}")
fixed = [{"Config": entry["Config"], "RepoTags": entry.get("RepoTags") or [],
          "Layers": [by_diff[d] for d in diff_ids]}]
print(f"manifest: {len(entry['Layers'])} layers listed -> {len(diff_ids)} (one per diff_id); "
      f"all {len(found)} layer digests verified", file=sys.stderr)
data = json.dumps(fixed).encode()
out = tarfile.open(fileobj=sys.stdout.buffer, mode="w|", format=tarfile.PAX_FORMAT)
info = tarfile.TarInfo("manifest.json")
info.size, info.mode = len(data), 0o644
out.addfile(info, io.BytesIO(data))
with tarfile.open(src, mode="r|") as t:
    for m in t:
        if m.name != "manifest.json":
            out.addfile(m, t.extractfile(m) if m.isfile() else None)
out.close()
PY
}

if [[ -n $LOAD_BASE ]]; then
  load_base_image "$LOAD_BASE"
  exit 0
fi

[[ -f "$APP_DIR/server.py" ]] || { say "missing $APP_DIR/server.py"; exit 1; }
[[ -d "$MODELS_DIR" ]] || { say "models dir not found: $MODELS_DIR"; exit 1; }
for f in ultralytics__yolo11/yolo11s.pt ultralytics__yolov8-world/yolov8s-worldv2.pt; do
  [[ -f "$MODELS_DIR/$f" ]] || { say "model not found: $MODELS_DIR/$f"; exit 1; }
done

# Repack the opencv-python-headless wheel the app's .venv installed (uv sync --frozen, pinned in
# uv.lock) into a .whl: exactly the files its RECORD lists, each verified against the RECORD
# sha256, so the container gets the same OpenCV build the scan uses. Prints the wheel path.
repack_headless_wheel() {
  mkdir -p "$EXTRA_WHEELS_DIR"
  python3 - "$VENV_SITE" "$EXTRA_WHEELS_DIR" <<'PY'
import base64, csv, hashlib, io, os, sys, zipfile
from pathlib import Path

site, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
dists = sorted(site.glob("opencv_python_headless-*.dist-info"))
if len(dists) != 1:
    sys.exit(f"expected one opencv_python_headless dist-info in {site} (run uv sync --frozen)")
dist = dists[0]
version = dist.name[len("opencv_python_headless-") : -len(".dist-info")]
tags = [l.split(":", 1)[1].strip() for l in (dist / "WHEEL").read_text().splitlines()
        if l.startswith("Tag:")]
if len(tags) != 1:
    sys.exit(f"unexpected WHEEL tags {tags}")
record_name = f"{dist.name}/RECORD"
record_text = (dist / "RECORD").read_text()
rows = list(csv.reader(io.StringIO(record_text)))
out = out_dir / f"opencv_python_headless-{version}-{tags[0]}.whl"
tmp = out.with_name(out.name + ".partial")
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
    for row in rows:
        path, digest = row[0], row[1]
        if path == record_name:
            continue
        if not digest or path.startswith(("/", "..")):
            sys.exit(f"RECORD row without a hash or outside site-packages: {path}")
        algo, _, want = digest.partition("=")
        f = site / path
        data = f.read_bytes()
        got = base64.urlsafe_b64encode(hashlib.new(algo, data).digest()).rstrip(b"=").decode()
        if got != want:
            sys.exit(f"{path}: sha256 does not match RECORD; refusing to repack")
        info = zipfile.ZipInfo(path, date_time=(2020, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (os.stat(f).st_mode & 0o777 | 0o100000) << 16
        z.writestr(info, data)
    info = zipfile.ZipInfo(record_name, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    z.writestr(info, record_text)
tmp.replace(out)
print(out)
print(f"repacked {len(rows) - 1} files, all RECORD hashes verified", file=sys.stderr)
PY
}

build_image() {
  if ! dk image inspect "$BASE_IMAGE" >/dev/null 2>&1; then
    say "base image $BASE_IMAGE is not loaded; load it from the bundle first:"
    say "  docker load -i ~/bundle/containers/pytorch-26.04-py3-arm64.tar"
    exit 1
  fi
  [[ -d "$WHEELS_DIR" ]] || { say "wheelhouse not found: $WHEELS_DIR"; exit 1; }
  local probe
  if ! probe="$(dk run --rm --network none --entrypoint true "$BASE_IMAGE" 2>&1)"; then
    say "base image $BASE_IMAGE does not start: $probe"
    if [[ $probe == *"mismatched image rootfs"* ]]; then
      say "it was loaded with plain docker load; reload it with:"
      say "  scripts/hazards/detector_up.sh --load-base"
    fi
    exit 1
  fi
  local headless tmp="detector-build-$$"
  headless="$(repack_headless_wheel)" || { say "could not repack opencv-python-headless"; exit 1; }
  say "headless OpenCV wheel: $headless"
  say "building $IMAGE from $BASE_IMAGE (offline wheelhouse, no network)"
  # The build script arrives on stdin; the container has no network, so pip can only use the
  # mounted wheel folders, and the torch stack is pinned to what the image ships.
  if ! dk run -i --name "$tmp" --gpus all --network none \
      -v "$WHEELS_DIR:/wheels:ro" \
      -v "$headless:/extra-wheels/$(basename "$headless"):ro" \
      -e YOLO_OFFLINE=1 -e YOLO_AUTOINSTALL=false -e HF_HUB_OFFLINE=1 \
      -e YOLO_CONFIG_DIR=/opt/cameravision/ultralytics \
      --entrypoint bash "$BASE_IMAGE" -s <<'BUILD'
set -euo pipefail
shopt -s nullglob
echo "PIP_CONSTRAINT=${PIP_CONSTRAINT:-<unset>}"
mkdir -p "$YOLO_CONFIG_DIR"
python - <<'PY' > /tmp/pins.txt
from importlib.metadata import version
for p in ("torch", "torchvision", "numpy"):
    print(f"{p}=={version(p)}")
PY
cat /tmp/pins.txt
before="$(python -c 'import torch; print(torch.__version__, torch.__file__)')"
# Keep the image's own constraint file and add the pins (pip splits this env var on spaces).
export PIP_CONSTRAINT="${PIP_CONSTRAINT:-} /tmp/pins.txt"
pip install --no-index --find-links /wheels --no-cache-dir --disable-pip-version-check \
  ultralytics
# Same OpenCV version, headless build: the GUI build needs X11/GL libraries this image lacks.
pip uninstall -y --disable-pip-version-check opencv-python
headless=(/extra-wheels/opencv_python_headless-*.whl)
((${#headless[@]} == 1)) || { echo "expected one headless wheel in /extra-wheels" >&2; exit 1; }
pip install --no-index --no-deps --no-cache-dir --disable-pip-version-check "${headless[0]}"
after="$(python -c 'import torch; print(torch.__version__, torch.__file__)')"
echo "torch before: $before"
echo "torch after:  $after"
[[ "$before" == "$after" ]] || { echo "torch changed during install" >&2; exit 1; }
pip list --disable-pip-version-check 2>/dev/null \
  | grep -i -E '^(torch|torchvision|numpy|opencv-python-headless|opencv-python|ultralytics)[ -]'
python - <<'PY'
import os
import torch
assert torch.cuda.is_available(), "CUDA not available in the build container"
print("cuda:", torch.cuda.get_device_name(0), "torch", torch.__version__)
import cv2
import ultralytics
from ultralytics.utils import ONLINE, SETTINGS
SETTINGS.update({"sync": False})
assert ONLINE is False, "YOLO_OFFLINE did not take effect"
print("ultralytics", ultralytics.__version__, "cv2", cv2.__version__, "ONLINE", ONLINE,
      "sync", SETTINGS["sync"], "settings", os.environ["YOLO_CONFIG_DIR"])
PY
BUILD
  then
    dk rm -f "$tmp" >/dev/null 2>&1 || true
    say "image build failed"
    exit 1
  fi
  # `docker run --entrypoint bash` above is part of the container config, so restore the base
  # image's entrypoint (it runs NVIDIA's driver/compat checks, then execs CMD).
  local entrypoint
  entrypoint="$(dk image inspect -f '{{json .Config.Entrypoint}}' "$BASE_IMAGE")"
  [[ $entrypoint == \[* ]] || entrypoint='["/opt/nvidia/nvidia_entrypoint.sh"]'
  dk commit \
    --change "ENTRYPOINT $entrypoint" \
    --change 'ENV YOLO_OFFLINE=1' \
    --change 'ENV YOLO_AUTOINSTALL=false' \
    --change 'ENV HF_HUB_OFFLINE=1' \
    --change 'ENV YOLO_CONFIG_DIR=/opt/cameravision/ultralytics' \
    --change 'ENV DETECTOR_PORT=8003' \
    --change 'EXPOSE 8003' \
    --change 'WORKDIR /app' \
    --change 'CMD ["python", "/app/server.py"]' \
    --change 'LABEL org.opencontainers.image.title=cameravision-detector' \
    --change "LABEL cameravision.base_image=$BASE_IMAGE" \
    --message "ultralytics installed offline from the bundle wheelhouse; headless OpenCV" \
    "$tmp" "$IMAGE" >/dev/null
  dk rm -f "$tmp" >/dev/null
  say "built $IMAGE"
}

if ((REBUILD)) || ! dk image inspect "$IMAGE" >/dev/null 2>&1; then
  build_image
fi

state="$(dk inspect -f '{{.State.Status}}' "$NAME" 2>/dev/null || true)"
if ((RECREATE)) && [[ -n $state ]]; then
  say "removing existing container $NAME ($state)"
  dk rm -f "$NAME" >/dev/null
  state=""
fi
case "$state" in
  running) say "container $NAME already running" ;;
  "")
    say "starting container $NAME on 127.0.0.1:$PORT"
    # HTTP(S)_PROXY points at a closed local port: if anything ever tried to fetch over HTTP it
    # would fail fast and show up in the log instead of downloading.
    dk run -d --name "$NAME" --gpus all \
      -p "127.0.0.1:$PORT:8003" \
      -v "$MODELS_DIR:/models:ro" \
      -v "$APP_DIR:/app:ro" \
      -e YOLO_OFFLINE=1 -e YOLO_AUTOINSTALL=false -e HF_HUB_OFFLINE=1 \
      -e HTTP_PROXY=http://127.0.0.1:9 -e HTTPS_PROXY=http://127.0.0.1:9 \
      -e http_proxy=http://127.0.0.1:9 -e https_proxy=http://127.0.0.1:9 \
      -e NO_PROXY=127.0.0.1,localhost -e no_proxy=127.0.0.1,localhost \
      -e DETECTOR_MODELS="$DETECTOR_MODELS" -e DETECTOR_DEFAULT_MODELS=yolo11s \
      -e DETECTOR_HALF=1 \
      --log-opt max-size=10m --log-opt max-file=3 \
      "$IMAGE" >/dev/null
    ;;
  *)
    say "starting stopped container $NAME ($state)"
    dk start "$NAME" >/dev/null
    ;;
esac

say "waiting for http://127.0.0.1:$PORT/health (up to ${TIMEOUT_S}s)"
deadline=$((SECONDS + TIMEOUT_S))
health=""
while ((SECONDS < deadline)); do
  if health="$(curl -fsS --noproxy '*' --max-time 3 "http://127.0.0.1:$PORT/health" 2>/dev/null)" \
      && [[ "$(jq -r '.ok' <<<"$health" 2>/dev/null)" == "true" ]]; then
    break
  fi
  health=""
  if [[ "$(dk inspect -f '{{.State.Status}}' "$NAME" 2>/dev/null || true)" != "running" ]]; then
    say "container $NAME stopped; last log lines:"
    dk logs --tail 40 "$NAME" >&2 || true
    exit 1
  fi
  sleep 2
done
if [[ -z $health ]]; then
  say "detector not healthy after ${TIMEOUT_S}s; last log lines:"
  dk logs --tail 40 "$NAME" >&2 || true
  curl -sS --noproxy '*' --max-time 3 "http://127.0.0.1:$PORT/health" >&2 || true
  exit 1
fi

# No download may ever happen in this container: flag any server-era log line that looks like
# one (from the last "[detector] starting" marker on; the NVIDIA banner before it has URLs).
if dk logs "$NAME" 2>&1 \
    | awk '/\[detector\] starting/{n=NR} {line[NR]=$0} END{for(i=(n ? n : 1); i<=NR; i++) print line[i]}' \
    | grep -i -E 'download|https?://|proxy|urlopen|connection(error| refused)' >&2; then
  say "WARNING: the lines above look like download attempts"
else
  say "log check: no download attempts in the container log"
fi
jq -c '{ok, device, half, models, gpu_memory}' <<<"$health"
