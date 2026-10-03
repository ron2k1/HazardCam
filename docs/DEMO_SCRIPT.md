# CameraVision: 2-minute demo script

Event day, 2026-10-03. The demo is a staged screen recording, not a live show. CameraVision is a
safety monitor for factories and warehouses. There is no bus-station beat.

The backup video is `artifacts/hazards/demo/hazards_demo.mp4` (2:01, 1920×1080), recorded by
the hazard workflow at 14:34 CDT. The time codes below are that video's, so lay the narration
over it. For a new take driven by hand, keep the same order and lines. Since the 14:41 fixes,
going back to the wall keeps the finished checks (6 of 6 done, nothing re-runs), so the
1:20–1:34 beat shows the finished wall and the close can end on all six done.

**What is real.** The recording replays real checks that ran on this GB10 today, at demo speed.
Each camera's check is compressed to about 12 s and the six are staggered, so they all land in
about 25 s. Every word, number, picture and video on screen comes from those stored runs through
the app's API, and nothing is typed into the page or mocked. The reasoning tab shows the real
times measured when each check ran: the safety agent's log and the model run panel. Its Steps
list shows the demo-speed replay, so do not point at it for timing. The two featured runs are
press line camera `hz_00` (run `f12f98a9f3b78349`, agent turn 74.5 s) and warehouse aisle camera
`bs_03` (run `4d233e56fc45a9bc`, agent turn 97.6 s). Both ran on local Qwen 3.6 through the
OpenClaw agent.

Speak to someone who has never seen a model or a terminal. The lines in quotes are the
narration. The rest is what is on screen. At a calm 140 words a minute the narration takes
about 1:30 of the 2:01, which leaves room to pause.

## 0:00–0:32 The camera wall

Screen: `/` is a CCTV wall of six feeds. CAM 1–3 watch the factory floor for safety hazards.
CAM 4–6 watch warehouse blind spots. The checks start by themselves. From about 0:14 the
detections pop out with a big alert, a pulsing border on the tile, a warning label and a
notification on the right.

> "This is CameraVision, a safety monitor for factories and warehouses. Three cameras watch the
> factory floor and three watch the warehouse. A safety agent checks each one and posts a
> warning when it finds something."

> "This recording replays real checks run on this box today, at demo speed."

At the first alerts:

> "Each warning says what kind of hazard, which camera and which zone."

## 0:32–0:48 How it decided

Screen: "Open reasoning ↗" opens `/hazards/process` for the press line camera. At the top are
the stack status (NemoClaw sandbox, OpenClaw agent, OpenShell gateway, Qwen, network local
only) and the line "Replay of the GB10 run". Below are the safety agent's timed log and the
instructions the AI was given.

> "One click opens the reasoning. The OpenClaw agent runs in NVIDIA's NemoClaw sandbox with a
> local Qwen model. Its log shows the real times: the AI review took about 55 seconds."

The log line reads `hazard_review_clip ok in 54.6 s`.

## 0:48–1:20 One factory hazard

Screen: back on the wall, click the CAM 1 notification. `/hazards` opens on the press line
camera: "2 safety hazards found". The first is Machine guard, high priority, Zone 3 and Zone 5,
with the action "Verify the machine's energy state immediately". The AI-marked video has the
warning labels pinned where the hazards are, then come the pictures the warning cites and the
gallery of every picture the AI looked at.

> "Click a warning and you see why. The label sits right where the problem is, with how serious
> it is and what to do. These are the pictures the AI points to, and here is every picture it
> looked at."

> "It cannot tell from the pictures whether the press is running, so it does not guess. It asks
> a person to check the machine's power first."

## 1:20–1:34 Back on the wall

Screen (backup video): the wall replays its checks and the alerts land again. These are the
same stored runs replayed, not new detections. In a new take the wall shows the six finished
checks instead.

> "The agent keeps every camera under watch."

## 1:34–1:50 One warehouse blind spot

Screen: click the CAM 6 notification. `/hazards` opens on aisle camera 3: "3 blind spots found".
The first is Blind corner, high priority, Zone 6, "Install a convex mirror at the corner to…",
with the pinned labels on the video and the gallery.

> "In the warehouse it looks for blind spots, where people and vehicles meet out of sight. Here
> it found a blind corner and suggests a convex mirror."

## 1:50–2:01 Close

Screen: the blind spot's reasoning tab, then back to the wall.

> "Most sites already have the cameras. CameraVision turns them into a safety partner that
> explains itself and runs entirely on site."

## Words to avoid on camera

- "Mistral". On the GB10 both model slots run Qwen 3.6 (`nvidia/Qwen3.6-35B-A3B-NVFP4`) on the
  local vLLM server, and the Mistral weights are not on the box.
- "Live" or "real time" for the wall: it replays real runs at demo speed. Only the reasoning
  tab's agent log and model run panel carry the measured times.
- "New hazards" for the second pass over the wall (1:20–1:34): it replays the same runs.
- "Always right" or "accurate". These are a handful of single runs, not an accuracy
  measurement. On the factory clips the findings only partly match the dataset labels
  (`artifacts/hazards/GB10_REVIEW_RUNS.md`).
- Bus station, `/ops`, or anything about several cameras piecing together one event. That
  part is out of this demo.

## If it has to be recorded again

1. `API_BASE_URL=http://127.0.0.1:8088 MISTRAL_BASE_URL=http://127.0.0.1:8000/v1 make demo-check`
   passes.
2. No other model jobs on the GPU.
3. Browser at 1920×1080, zoom 100 %, no `?mock=1`.
4. Check the result with `scripts/demo/inspect_recording.sh <video>` (frozen stretches, black
   frames, a contact sheet and the scene changes) before using it.
