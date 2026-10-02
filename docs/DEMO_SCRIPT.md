# 3-Minute Demo Story

## 0:00–0:25 — problem
“Cameras fail exactly where their field of view ends. But an unseen event still leaves effects in the environment.”

## 0:25–0:45 — proof setup
Show 3 input cameras and the withheld ground-truth camera. State clearly:
“Ground truth is visible to you, but the model cannot access this feed.”

## 0:45–1:40 — live run
Press ANALYZE. Narrate only as evidence appears:
- Qwen extracts observable cues
- deterministic code aligns timestamps/geometry
- OpenClaw reasons over the evidence locally

## 1:40–2:20 — result
Show hypothesis, confidence, alternatives, limitations. Click each evidence item so the corresponding camera seeks to the supporting timestamp.

## 2:20–2:45 — local-first proof
Show local stack status: Qwen, Mistral/Ministral, NemoClaw, OpenClaw, OpenShell; explain the judged run does not need cloud inference.

## 2:45–3:00 — business/value close
“Existing cameras are already deployed. We turn them into distributed physical sensors that can reason about events outside any single field of view.”
