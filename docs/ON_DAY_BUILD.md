# Event-Day Build Sheet

The application is already tested through a non-agent harness. Build only the actual OpenClaw agent and runtime integration now.

## Step 1 — inspect tool interfaces

Confirm these tested functions/interfaces exist:
- inspect camera
- fetch supporting frames
- correlate observations
- triangulate region
- reason hypothesis
- submit hypothesis

Do not change their schemas unless GB10/runtime integration forces a minimal compatibility fix.

## Step 2 — create OpenClaw agent

Create the agent definition from scratch on event day.

The agent should:
1. inspect only allowed cameras
2. request more frames only when evidence is insufficient
3. call deterministic correlation/triangulation
4. invoke the reasoning adapter on the fused evidence
5. consider alternatives
6. abstain when support is weak
7. submit the structured final hypothesis

## Step 3 — register tools

Register only the allowed tool surface. Ground-truth media/path must not be reachable through tool args, environment variables, scenario payloads, or generic filesystem access granted to the agent.

## Step 4 — NemoClaw/OpenShell

Run the agent through the required stack, configure local model routes, and record runtime status.

## Step 5 — GB10 calibration

Tune only deployment parameters first:
- frame count/fps
- concurrent camera requests
- quantization/serving profile
- context limits
- timeouts

Avoid architecture rewrites.

## Step 6 — final checks

Run fixture path first, then judged real-model scenario. Verify evidence seeking and ground-truth isolation. Record one backup video after the first clean run.
