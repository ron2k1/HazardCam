#!/usr/bin/env bash
# One command to run the app locally: the API on 127.0.0.1:$API_PORT and a production build
# of the web app on 127.0.0.1:$WEB_PORT, then open http://127.0.0.1:$WEB_PORT/ops.
#
#   scripts/start_app.sh                          # fixture profile: no model calls, no network
#   MODEL_PROFILE=lite-local scripts/start_app.sh # real local models (Ollama must be up)
#   scripts/start_app.sh --smoke                  # start, check both answer, stop, exit 0
#
# Runs in the foreground; Ctrl+C (or a TERM) stops both servers. Env: API_PORT (8080),
# WEB_PORT (3000), MODEL_PROFILE (fixture), READY_TIMEOUT_S (120), STOP_GRACE_S (10: how long
# a server gets to exit after TERM before KILL), SKIP_BUILD=1 to reuse apps/web/.next (only a
# build this script made for the same API_PORT, since NEXT_PUBLIC_API_BASE_URL is inlined at
# build time).
set -euo pipefail
# wait -n needs bash 4.3 and _proc.sh's "${started_jobs[@]}" on an empty array under set -u
# needs 4.4 (macOS ships 3.2 as /bin/bash)
if ((BASH_VERSINFO[0] * 100 + BASH_VERSINFO[1] < 404)); then
  echo "scripts/start_app.sh needs bash 4.4 or newer; this is $BASH_VERSION" >&2
  exit 1
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/_python.sh
. scripts/_python.sh
# shellcheck source=scripts/_proc.sh
. scripts/_proc.sh

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

# Silent: a refusal is often expected. bash does the redirect: curl is a native Windows binary
# in Git Bash, and -o /dev/null reaches it unconverted under MSYS_NO_PATHCONV=1.
answers() { curl -fs --max-time 2 "$1" >/dev/null; }

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
# The API URL the build in apps/web/.next inlined. `next build` empties .next first, so a
# build made any other way (the e2e suite's, a manual one) leaves no stamp.
BUILD_STAMP=apps/web/.next/api-base-url.txt
if [ "${SKIP_BUILD:-0}" = 1 ] && [ "$(cat "$BUILD_STAMP" 2>/dev/null)" != "$API_URL" ]; then
  echo "SKIP_BUILD=1, but apps/web/.next was not built by this script for $API_URL; run without SKIP_BUILD" >&2
  exit 1
fi

set -m # each background job gets its own process group, so a kill reaches its children
stop_jobs_on_exit

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
api_pid=$!
started_jobs+=("$api_pid")
wait_for api "$API_URL/healthz" "$api_pid"

if [ "${SKIP_BUILD:-0}" != 1 ]; then
  echo "web: building for $API_URL"
  (cd apps/web && NEXT_PUBLIC_API_BASE_URL="$API_URL" NEXT_TELEMETRY_DISABLED=1 "${NEXT[@]}" build)
  printf '%s\n' "$API_URL" >"$BUILD_STAMP"
fi
(cd apps/web && NEXT_TELEMETRY_DISABLED=1 exec "${NEXT[@]}" start -H 127.0.0.1 -p "$WEB_PORT") &
web_pid=$!
started_jobs+=("$web_pid")
wait_for web "$WEB_URL/ops" "$web_pid"

if ((smoke)); then
  # The build takes minutes; the API that answered before it must still be up.
  if ! kill -0 "$api_pid" 2>/dev/null || ! answers "$API_URL/healthz"; then
    echo "smoke: api no longer answers $API_URL/healthz" >&2
    exit 1
  fi
  echo "smoke: api and web answer; stopping"
  exit 0
fi
echo "open $WEB_URL/ops   (Ctrl+C stops both servers)"
wait -n || true # returns when either server exits; the EXIT trap stops the other
echo "a server exited; stopping" >&2
exit 1
