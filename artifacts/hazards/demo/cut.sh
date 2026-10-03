#!/usr/bin/env bash
# Cut list (raw-video seconds). Segments: wall -> reasoning tab -> /hazards -> wall (re-run, idle checking trimmed) -> blind spot -> reasoning tab -> wall
set -euo pipefail
D=/home/dell/ambient-urban-mirror/artifacts/hazards/demo
SEGS="0:1.0:33.0 1:0.734:16.27 0:50.04:81.6 0:82.3:85.2 0:94.6:121.79 2:0.852:8.63 0:130.32:134.5"
F=""; C=""; n=0
for s in $SEGS; do IFS=: read i a b <<<"$s"; F+="[$i:v]trim=start=$a:end=$b,setpts=PTS-STARTPTS,fps=25,scale=1920:1080,setsar=1[s$n];"; C+="[s$n]"; n=$((n+1)); done
ffmpeg -v error -y -i $D/raw/main_raw.webm -i $D/raw/tab1_raw.webm -i $D/raw/tab2_raw.webm \
  -filter_complex "${F}${C}concat=n=$n:v=1:a=0[v]" -map "[v]" -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -movflags +faststart $D/hazards_demo.mp4
