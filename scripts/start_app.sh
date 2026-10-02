#!/usr/bin/env bash
# One command to run the app locally: the API on 127.0.0.1:$API_PORT and a production build
# of the web app on 127.0.0.1:$WEB_PORT, then open http://127.0.0.1:$WEB_PORT/ops.
#
#   scripts/start_app.sh                          # fixture profile: no model calls, no network
#   MODEL_PROFILE=lite-local scripts/start_app.sh # real local models (Ollama must be up)
#   scripts/start_app.sh --smoke                  # start, check both answer, stop, exit 0
#
# Runs in the foreground; Ctrl+C stops both servers. Env: API_PORT (8080), WEB_PORT (3000),
# MODEL_PROFILE (fixture), SKIP_BUILD=1 to reuse apps/web/.next (it must have been built
# for the same API_PORT, since NEXT_PUBLIC_API_BASE_URL is inlined at build time),
# READY_TIMEOUT_S (120).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/_python.sh
. scripts/_python.sh

smoke=0
case "${1:-}" in
  --smoke) smoke=1 ;;
  "") ;;
  *)
    echo "usage: scripts/start_app.sh [--smoke]" >&2
    exit 2
    ;;
esac

API_PORT="${API_PORT:-8080}"
WEB_PORT="${WEB_PORT:-3000}"
API_URL="http://127.0.0.1:$API_PORT"
WEB_URL="http://127.0.0.1:$WEB_PORT"
READY_TIMEOUT_S="${READY_TIMEOUT_S:-120}"
export MODEL_PROFILE="${MODEL_PROFILE:-fixture}"
NEXT=(node node_modules/next/dist/bin/next)

answers() { curl -fsS --max-time 2 -o /dev/null "$1"; }

# A server already on the port would pass the readiness check without being ours.
for url in "$API_URL/healthz" "$WEB_URL/ops"; do
  if answers "$url"; then
    echo "something already answers $url; stop it or set API_PORT / WEB_PORT" >&2
    exit 1
  fi
done
[ -d apps/web/node_modules ] || {
  echo "apps/web/node_modules missing; run: pnpm --dir apps/web install" >&2
  exit 1
}

set -m # each background job gets its own process group, so a kill reaches its children
pids=()
stop() {
  trap - EXIT INT TERM
  local pid
  for pid in "${pids[@]}"; do
    if [ -r "/proc/$pid/winpid" ]; then # Git Bash: end the Windows process tree by PID
      taskkill //F //T //PID "$(cat "/proc/$pid/winpid")" >/dev/null 2>&1 || true
    else
      kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}
trap stop EXIT
trap 'exit 130' INT TERM

wait_for() { # name url pid
  local deadline=$((SECONDS + READY_TIMEOUT_S))
  until answers "$2"; do
    if ! kill -0 "$3" 2>/dev/null; then
      echo "$1 exited before answering $2" >&2
      return 1
    fi
    if ((SECONDS >= deadline)); then
      echo "$1 did not answer $2 within ${READY_TIMEOUT_S}s" >&2
      return 1
    fi
    sleep 1
  done
  echo "ok  $1 $2"
}

echo "api: profile $MODEL_PROFILE on $API_URL"
AUM_CORS_ORIGINS="$WEB_URL,http://localhost:$WEB_PORT" PYTHONUTF8=1 \
  py -m uvicorn apps.api.main:app --host 127.0.0.1 --port "$API_PORT" --log-level warning &
pids+=("$!")
wait_for api "$API_URL/healthz" "${pids[0]}"

if [ "${SKIP_BUILD:-0}" != 1 ]; then
  echo "web: building for $API_URL"
  (cd apps/web && NEXT_PUBLIC_API_BASE_URL="$API_URL" NEXT_TELEMETRY_DISABLED=1 "${NEXT[@]}" build)
fi
(cd apps/web && NEXT_TELEMETRY_DISABLED=1 exec "${NEXT[@]}" start -H 127.0.0.1 -p "$WEB_PORT") &
pids+=("$!")
wait_for web "$WEB_URL/ops" "${pids[1]}"

if ((smoke)); then
  echo "smoke: api and web answer; stopping"
  exit 0
fi
echo "open $WEB_URL/ops   (Ctrl+C stops both servers)"
wait -n || true # returns when either server exits; the EXIT trap stops the other
echo "a server exited; stopping" >&2
exit 1
