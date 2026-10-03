#!/usr/bin/env bash
# Cut the ~30 s /ops beat from scripts/demo/record_ops_beat.mjs's raw recording: one jump cut
# over the middle of the run, nothing drawn on top. The cut points come from the timing marks
# in ops_beat.json, so the clip always matches the run that was filmed.
#
#   scripts/demo/cut_ops_beat.sh [DIR]   # DIR defaults to artifacts/event_day/d04/ops_beat
#
# Part 1: 1 s before the page was ready, the Run click, and the first 10 s of the run.
# Part 2: 1 s before the run ended, the final message, and the technical console to the end.
# Writes DIR/ops_beat.mp4 (H.264, yuv420p, 25 fps) and DIR/ops_beat_cut.json.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIR="${1:-$ROOT/artifacts/event_day/d04/ops_beat}"
RAW="$DIR/ops_beat_raw.webm"
[ -f "$RAW" ] && [ -f "$DIR/ops_beat.json" ] || { echo "need $RAW and $DIR/ops_beat.json" >&2; exit 1; }

read -r a0 a1 b0 b1 < <(DIR="$DIR" python3 - <<'PY'
import json, os
m = json.load(open(os.path.join(os.environ["DIR"], "ops_beat.json")))["marks_video_s"]
a0 = max(0.0, m["page_ready"] - 1.0)
a1 = min(m["run_clicked"] + 10.0, m["run_ended"] - 1.0)
print(f"{a0:.2f} {a1:.2f} {m['run_ended'] - 1.0:.2f} {m['end']:.2f}")
PY
)

ffmpeg -v error -y -i "$RAW" -filter_complex \
  "[0:v]trim=start=$a0:end=$a1,setpts=PTS-STARTPTS[a];[0:v]trim=start=$b0:end=$b1,setpts=PTS-STARTPTS[b];[a][b]concat=n=2:v=1[v]" \
  -map "[v]" -r 25 -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -movflags +faststart "$DIR/ops_beat.mp4"

duration="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$DIR/ops_beat.mp4")"
printf '{"source": "ops_beat_raw.webm", "part1_s": [%s, %s], "part2_s": [%s, %s], "duration_s": %s, "overlay": "none"}\n' \
  "$a0" "$a1" "$b0" "$b1" "$duration" >"$DIR/ops_beat_cut.json"
echo "wrote $DIR/ops_beat.mp4 (${duration} s): raw ${a0}-${a1} s + ${b0}-${b1} s"
