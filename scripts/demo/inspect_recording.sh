#!/usr/bin/env bash
# Look at a demo recording without playing it: stream facts, frozen and black stretches, a
# contact sheet of evenly spaced frames and the frames where the screen changes. Read-only on
# the recording; the timestamps are drawn on the inspection sheet, never on the video.
#
#   scripts/demo/inspect_recording.sh VIDEO [OUT_DIR]
#
# OUT_DIR defaults to artifacts/event_day/d04/inspect_<video name>. Writes probe.txt,
# freeze.txt (still for 6 s or more: a stuck step, or just a result being read),
# black.txt, sheet.jpg (4x4 frames) and scene_*.jpg (screen changes, at most 40).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VIDEO="${1:?usage: scripts/demo/inspect_recording.sh VIDEO [OUT_DIR]}"
name="$(basename "${VIDEO%.*}")"
OUT="${2:-$ROOT/artifacts/event_day/d04/inspect_$name}"
mkdir -p "$OUT"
rm -f "$OUT"/scene_*.jpg

ffprobe -v error -show_entries format=duration,size,bit_rate:stream=codec_name,width,height,r_frame_rate,pix_fmt,nb_frames \
  -of default=noprint_wrappers=1 "$VIDEO" | tee "$OUT/probe.txt"
duration="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VIDEO")"

ffmpeg -hide_banner -nostats -i "$VIDEO" -vf "freezedetect=n=0.002:d=6" -map 0:v -f null - 2>&1 \
  | grep -oE 'freeze_(start|duration|end): [0-9.]+' >"$OUT/freeze.txt" || true
ffmpeg -hide_banner -nostats -i "$VIDEO" -vf "blackdetect=d=1:pix_th=0.05" -map 0:v -f null - 2>&1 \
  | grep -oE 'black_start:[0-9.]+ black_end:[0-9.]+ black_duration:[0-9.]+' >"$OUT/black.txt" || true

step="$(python3 -c "print(max(float('$duration') / 16, 0.1))")"
ffmpeg -v error -y -i "$VIDEO" -vf \
  "fps=1/$step,scale=480:-2,drawtext=text='%{pts\:hms}':x=6:y=6:fontsize=18:fontcolor=yellow:box=1:boxcolor=black@0.7,tile=4x4:padding=4" \
  -frames:v 1 "$OUT/sheet.jpg"
ffmpeg -v error -y -i "$VIDEO" -vf "select='gt(scene,0.06)',scale=960:-2" -fps_mode vfr -frames:v 40 \
  -frame_pts 1 "$OUT/scene_%06d.jpg"

echo "duration ${duration}s; freezes: $(grep -c freeze_start "$OUT/freeze.txt" || true); black: $(wc -l <"$OUT/black.txt"); scenes: $(ls "$OUT"/scene_*.jpg 2>/dev/null | wc -l)"
echo "wrote $OUT"
