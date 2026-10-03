#!/usr/bin/env bash
# Event day (2026-10-03, D02): capture NemoClaw/OpenShell status and local model health.
#
#   scripts/runtime/capture_status.sh [out_dir]      # default artifacts/event_day/runtime
#
# Writes runtime_status_<UTC>.txt: nemoclaw sandbox status, OpenShell sandbox list, the
# OpenClaw agents/MCP config as the gateway sees it, the vLLM /v1/models of both local
# servers, inference.local from inside the sandbox, and the cloud-route check (every
# configured base URL must be loopback). No tokens: config is summarised by key, not dumped.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"
export PATH="$HOME/.local/bin:$PATH"
SANDBOX="${AUM_SANDBOX:-ambient-mirror}"
OUT_DIR="${1:-artifacts/event_day/runtime}"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/runtime_status_$(date -u +%Y%m%dT%H%M%SZ).txt"
strip() { sed -E 's/\x1b\[[0-9;]*m//g'; }
section() { printf '\n===== %s =====\n' "$1"; }
sbx() { timeout 60 openshell sandbox exec -n "$SANDBOX" -- sh -c "$1" </dev/null 2>&1; }

{
  echo "captured_utc: $(date -u +%FT%TZ)"
  echo "host: $(hostname) $(uname -m)  git: $(git rev-parse --short HEAD)"
  echo "nemoclaw: $(nemoclaw --version 2>&1 | strip | tail -1)  openshell: $(openshell --version 2>&1 | tail -1)"

  section "nemoclaw $SANDBOX status"
  timeout 90 nemoclaw "$SANDBOX" status 2>&1 | strip | sed -n '1,/^Policy:/p'
  echo "(network policy names) $(timeout 90 nemoclaw "$SANDBOX" status 2>&1 | strip \
    | grep -E '^    [a-z0-9_-]+:$' | tr -d ' :' | tr '\n' ' ')"

  section "openshell sandbox list"
  timeout 30 openshell sandbox list 2>&1 | strip

  section "openclaw agents (gateway view)"
  sbx 'openclaw agents list 2>/dev/null' | grep -v -E 'UNDICI|trace-warnings'

  section "openclaw.json (keys only, no secrets)"
  sbx 'node -e "
const c=require(\"/sandbox/.openclaw/openclaw.json\");
const m=(c.mcp||{}).servers||{};
for (const [k,v] of Object.entries(m)) console.log(\"mcp.servers.\"+k+\": url=\"+v.url+\" transport=\"+v.transport+\" tools=\"+JSON.stringify((v.toolFilter||{}).include)+\" auth_header=\"+(v.headers&&v.headers.Authorization?\"set\":\"none\"));
for (const a of (c.agents||{}).list||[]) console.log(\"agent \"+a.id+\": model=\"+JSON.stringify(a.model)+\" alsoAllow=\"+JSON.stringify((a.tools||{}).alsoAllow||[])+\" deny=\"+JSON.stringify((a.tools||{}).deny||[]));
const p=(c.models||{}).providers||{};
for (const [k,v] of Object.entries(p)) console.log(\"models.providers.\"+k+\": baseUrl=\"+v.baseUrl+\" models=\"+JSON.stringify((v.models||[]).map(x=>x.id)));
"'

  section "local model health (host)"
  for port in 8000 8001; do
    printf 'http://127.0.0.1:%s/v1/models -> ' "$port"
    curl -s -m 5 "http://127.0.0.1:$port/v1/models" \
      | python3 -c 'import json,sys; print(", ".join(f"{m["id"]} (max_model_len {m.get("max_model_len")})" for m in json.load(sys.stdin)["data"]))' \
      2>/dev/null || echo "UNREACHABLE"
    printf 'http://127.0.0.1:%s/health -> HTTP %s\n' "$port" \
      "$(curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:$port/health")"
  done
  docker ps --format '{{.Names}}  {{.Image}}  {{.Status}}  {{.Ports}}' 2>/dev/null \
    | grep -E '^(qwen|cosmos) ' || echo "(docker ps unavailable in this shell; try sg docker)"

  section "inference.local from inside the sandbox"
  sbx 'curl -s -m 10 https://inference.local/v1/models' \
    | python3 -c 'import json,sys; print("models:", [m["id"] for m in json.load(sys.stdin)["data"]])' \
    2>/dev/null || echo "UNREACHABLE"

  section "cloud-route check (gb10 profile + sandbox inference route)"
  .venv/bin/python - <<'EOF'
from urllib.parse import urlparse
from inference.profiles import load_profile
p = load_profile("gb10")
bad = []
for slot in ("perception", "reasoning"):
    s = getattr(p, slot)
    host = urlparse(s.base_url).hostname
    ok = host in {"127.0.0.1", "localhost", "::1"}
    bad += [] if ok else [slot]
    print(f"gb10.{slot}: {s.model} @ {s.base_url} local={ok}")
print("RESULT:", "OK no cloud route" if not bad else f"CLOUD ROUTE in {bad}")
EOF
  timeout 60 nemoclaw inference get 2>&1 | strip | grep -v 'Active gateway'
} > "$OUT" 2>&1

echo "$OUT"
