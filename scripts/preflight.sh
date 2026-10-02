#!/usr/bin/env bash
set -u
mkdir -p artifacts
OUT="artifacts/PREFLIGHT_RAW.txt"
: > "$OUT"
log(){ printf '%s\n' "$*" | tee -a "$OUT"; }
cmd(){ log "\n$ $*"; ("$@" 2>&1 || true) | tee -a "$OUT"; }

log "Ambient Mirror preflight — $(date -Is 2>/dev/null || date)"
cmd uname -a
cmd git --version
cmd python3 --version
cmd node --version
cmd npm --version
cmd ffmpeg -version
cmd claude --version
cmd nvidia-smi
cmd free -h
cmd df -h .
cmd bash -lc 'command -v nemoclaw || true; nemoclaw --version 2>/dev/null || true'
cmd bash -lc 'command -v openshell || true; openshell --version 2>/dev/null || true'
cmd bash -lc 'command -v openclaw || true; openclaw --version 2>/dev/null || true'

log "\nImportant files:"
for p in reference/theme-reference.jpeg TASK_GRAPH.json contracts/scenario.schema.json; do
  if [ -e "$p" ]; then log "OK $p"; else log "MISSING $p"; fi
done

log "\nNext: run the orchestrator and have it turn this raw output into artifacts/PREFLIGHT_REPORT.md"
