#!/usr/bin/env bash
# Pre-recording check: the services, media and local stack the demo needs all answer.
#
#   scripts/demo_check.sh
#   API_BASE_URL=http://127.0.0.1:8088 MISTRAL_BASE_URL=http://127.0.0.1:8000/v1 scripts/demo_check.sh
#
# Env: API_BASE_URL (8080), WEB_BASE_URL (3000), QWEN_BASE_URL (8000/v1), MISTRAL_BASE_URL
# (8001/v1), MODEL_MODE (local; anything else skips the model probes), DETECTOR_BASE_URL
# (8003; reported, never required, since the hazard replay makes no detector call),
# NEMOCLAW_SANDBOX (ambient-mirror), NEMOCLAW_TIMEOUT_S (60). Exit 1 if a required check fails.
set -euo pipefail
fail=0
API="${API_BASE_URL:-http://127.0.0.1:8080}"
WEB="${WEB_BASE_URL:-http://127.0.0.1:3000}"
check_url(){
  local name="$1" url="$2"
  if curl -fsS --max-time "${3:-5}" "$url" >/dev/null; then echo "OK  $name $url"; else echo "BAD $name $url"; fail=1; fi
}

check_url "API" "$API/healthz"
# next dev compiles a page on its first request, so the web pages get longer than the API.
# / is the camera wall; /ops stays (unlinked) for the D03 judged-path proof.
for page in / /hazards /hazards/process /ops; do
  check_url "WEB" "$WEB$page" 60
done

if [ "${MODEL_MODE:-local}" = "local" ]; then
  check_url "QWEN" "${QWEN_BASE_URL:-http://127.0.0.1:8000/v1}/models"
  check_url "MISTRAL" "${MISTRAL_BASE_URL:-http://127.0.0.1:8001/v1}/models"
fi

DETECTOR="${DETECTOR_BASE_URL:-http://127.0.0.1:8003}"
if curl -fsS --max-time 5 "$DETECTOR/health" >/dev/null; then
  echo "OK  DETECTOR $DETECTOR/health"
else
  echo "--  DETECTOR $DETECTOR/health not answering (only a fresh hazard scan needs it)"
fi

for f in data/prepared/scenario_001/cam_a.mp4 data/prepared/scenario_001/cam_b.mp4 data/prepared/scenario_001/cam_c.mp4 data/prepared/scenario_001/hidden_ground_truth.mp4; do
  [ -f "$f" ] && echo "OK  $f" || { echo "BAD missing $f"; fail=1; }
done

# Safety hazards: the runtime status rows (NemoClaw, OpenClaw, OpenShell, tool server, Qwen,
# detector, network) are all ok and local only; at least one reviewed clip; every reviewed
# clip serves its source video, AI-marked video and evidence pictures; and the worker text
# carries no ids, scores or schema words (the worker view is what the recording shows).
if ! API="$API" python3 - <<'PY'; then fail=1; fi
import json, os, re, sys, urllib.request

api = os.environ["API"]
LEAK = re.compile(
    r"\b(?:Z\d{2}|E\d{3}|H\d{2}|(?:hz|bs)_\d+|cam_[a-z]\.o\d+)\b"  # zone/evidence/finding/clip/obs ids
    r"|\b(?:json|schema|zone_id|evidence_id|run_id|confidence)\b"
    r"|\b0\.\d{2,}\b",  # raw scores
    re.IGNORECASE,
)


def get(path, timeout=10):
    req = urllib.request.Request(api + path, headers={"Range": "bytes=0-1023"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def strings(node, key=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from strings(v, k)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v, key)
    elif isinstance(node, str) and key != "id" and not key.endswith("url"):
        yield key, node


bad = 0
try:
    status = json.loads(get("/api/runtime/status")[1])
    rows = status.get("rows") or []
    off = [f"{r.get('label')}={r.get('status')}" for r in rows if r.get("status") != "ok"]
    if off or not rows or status.get("local_only") is not True:
        print(f"BAD RUNTIME {', '.join(off) or 'no rows'}; local_only={status.get('local_only')}")
        bad += 1
    else:
        print(f"OK  RUNTIME {len(rows)} rows ok ({', '.join(r.get('label', '?') for r in rows)}), local only")
except Exception as exc:
    print(f"BAD RUNTIME {api}/api/runtime/status {type(exc).__name__}: {exc}")
    bad += 1
try:
    clips = json.loads(get("/api/hazards/clips")[1])["clips"]
except Exception as exc:
    print(f"BAD HAZARDS {api}/api/hazards/clips {type(exc).__name__}: {exc}")
    sys.exit(1)
reviewed = [c["clip_id"] for c in clips if c.get("status") == "reviewed"]
checking = sum(c.get("status") == "reviewing" for c in clips)
print(f"{'OK ' if reviewed else 'BAD'} HAZARDS {len(reviewed)}/{len(clips)} clips reviewed, {checking} being checked now")
bad += not reviewed
for clip_id in reviewed:
    try:
        view = json.loads(get(f"/api/hazards/clips/{clip_id}")[1])
        vision, worker = view.get("vision") or {}, view.get("worker") or {}
        urls = [vision.get("source_video_url"), vision.get("processed_video_url")]
        urls += [e["image_url"] for h in worker.get("hazards", []) for e in h.get("evidence", [])]
        missing = [u for u in urls if not u]
        if missing:
            raise ValueError(f"{len(missing)} media url(s) missing")
        for url in urls:
            get(url)
        leaks = sorted({m.group(0) for _, s in strings(worker) for m in LEAK.finditer(s)})
    except Exception as exc:
        print(f"BAD HAZARDS {clip_id} {type(exc).__name__}: {exc}")
        bad += 1
        continue
    if leaks:
        print(f"BAD HAZARDS {clip_id} worker text shows {', '.join(leaks)}")
        bad += 1
    else:
        print(f"OK  HAZARDS {clip_id} {len(urls)} media files served, worker text clean")
sys.exit(1 if bad else 0)
PY

if command -v nemoclaw >/dev/null 2>&1; then
  timeout "${NEMOCLAW_TIMEOUT_S:-60}" nemoclaw "${NEMOCLAW_SANDBOX:-ambient-mirror}" status </dev/null || {
    echo "BAD nemoclaw status (exit $?)"
    fail=1
  }
else
  echo "BAD nemoclaw not found"; fail=1
fi

exit "$fail"
