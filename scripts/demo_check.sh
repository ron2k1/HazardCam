#!/usr/bin/env bash
set -euo pipefail
fail=0
check_url(){
  local name="$1" url="$2"
  if curl -fsS --max-time 5 "$url" >/dev/null; then echo "OK  $name $url"; else echo "BAD $name $url"; fail=1; fi
}

check_url "API" "${API_BASE_URL:-http://127.0.0.1:8080}/healthz"
check_url "WEB" "${WEB_BASE_URL:-http://127.0.0.1:3000}/ops"

if [ "${MODEL_MODE:-local}" = "local" ]; then
  check_url "QWEN" "${QWEN_BASE_URL:-http://127.0.0.1:8000/v1}/models"
  check_url "MISTRAL" "${MISTRAL_BASE_URL:-http://127.0.0.1:8001/v1}/models"
fi

for f in data/prepared/scenario_001/cam_a.mp4 data/prepared/scenario_001/cam_b.mp4 data/prepared/scenario_001/cam_c.mp4 data/prepared/scenario_001/hidden_ground_truth.mp4; do
  [ -f "$f" ] && echo "OK  $f" || { echo "BAD missing $f"; fail=1; }
done

if command -v nemoclaw >/dev/null 2>&1; then
  nemoclaw "${NEMOCLAW_SANDBOX:-ambient-mirror}" status || fail=1
else
  echo "BAD nemoclaw not found"; fail=1
fi

exit "$fail"
