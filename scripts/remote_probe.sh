#!/usr/bin/env bash
set -euo pipefail
CFG="config/remote.env"
if [ ! -f "$CFG" ]; then
  echo "No $CFG. Copy config/remote.env.example and set REMOTE_ALIAS." >&2
  exit 2
fi
# shellcheck disable=SC1090
source "$CFG"
mkdir -p artifacts/remote
OUT="artifacts/remote/probe.txt"

ssh -o BatchMode=yes -o ConnectTimeout=8 "$REMOTE_ALIAS" 'bash -s' <<'EOS' | tee "$OUT"
set +e
printf 'timestamp='; date -Is 2>/dev/null || date
printf 'host='; hostname
uname -a
printf '\n== CPU ==\n'; (lscpu || sysctl -a 2>/dev/null | head -100)
printf '\n== RAM ==\n'; (free -h || vm_stat 2>/dev/null)
printf '\n== DISK ==\n'; df -h .
printf '\n== GPU ==\n'; (nvidia-smi || true)
printf '\n== TOOLS ==\n'
for x in git python3 node npm ffmpeg docker claude codex ultracode; do
  printf '%-12s ' "$x"; command -v "$x" || true
done
EOS

echo "Remote probe saved to $OUT"
