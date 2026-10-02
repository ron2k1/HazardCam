#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p artifacts/event_day
{
  echo "event_day_start_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "git_head=$(git rev-parse HEAD 2>/dev/null || echo no-git)"
  echo "git_status_begin"
  git status --short 2>/dev/null || true
  echo "git_status_end"
} | tee artifacts/event_day/START.txt

echo "Event-day baseline captured. Build the actual OpenClaw agent now; do not copy in a prebuilt finished agent."
