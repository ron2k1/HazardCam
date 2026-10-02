# Runtime readiness: manual blockers

Recorded 2026-10-02 by the runtime-readiness worker. None of these were done automatically. Each one needs a person: admin rights, an account, or a license acceptance.

## B1. NemoClaw + OpenShell cannot be rehearsed on the dev laptop (optional)

- **State:** `wsl -l -v` fails with `Wsl/0x80070422`. The Windows features `Microsoft-Windows-Subsystem-Linux` and `VirtualMachinePlatform` are both enabled, but the `WSLService` service has StartType **Disabled**. It may have been disabled on purpose, for example during game-performance tuning, so re-enable it only if you want WSL back. Docker is not installed. OpenShell ships no Windows binary (v0.1.2 assets are Linux x86_64/aarch64, macOS arm64, deb/rpm/snap). NemoClaw's Windows support goes through WSL2 with Docker Desktop (WSL backend) or rootless Podman. OpenShell lists Windows WSL2 as "Experimental".
- **Ask (admin):** only if you want a local rehearsal before getting on the GB10. In an elevated PowerShell:
  1. `Set-Service -Name WSLService -StartupType Manual`
  2. `wsl --install -d Ubuntu-24.04`. Reboot if asked; the features are already enabled, so it may not ask.
  3. Install Docker Desktop with the WSL2 backend. Its license is free for personal and education use; check that your use qualifies.
  4. Inside Ubuntu: `curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash`, then follow `docs/EVENT_DAY_RUNTIME.md` section 3 with Ollama as the provider.
- **Skip it if** you can get onto the GB10, or any Ubuntu 24.04 box with Docker 28+ and kernel 6.2+, before the event. That is the higher-value rehearsal.

## B2. Access to the actual GB10 (needed)

- **Ask:** confirm (a) whether we get shell access with sudo on the GB10 before the clock starts, (b) whether it runs DGX OS with Docker preinstalled, and (c) whether the venue network allows Hugging Face, NGC and npm downloads, or whether model weights must arrive pre-staged.
- **Why it matters:** the DGX Spark playbook needs sudo for its setup steps. The first NemoClaw pass is estimated at 30 to 60 min. The pinned NGC vLLM image alone is 9.6 GB to download and 27.7 GB unpacked. The 35B-class Qwen checkpoints are about 22 to 36 GB. If the venue network is slow, pre-stage the HF cache (`~/.cache/huggingface`) and the container image (`docker save` / `docker load`) on a USB SSD.

## B3. License and terms acceptances (needed on the day, by a human)

- The NemoClaw installer asks you to accept a third-party software notice. The non-interactive form is `NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1`. A team member has to read and accept it. An agent must not set this on someone's behalf.
- OpenClaw's onboarding needs `--accept-risk` ("agents are powerful and full system access is risky"). Same rule.
- Model licenses: every candidate checkpoint checked (Qwen3.6/3.5-35B-A3B, Qwen3-VL-30B-A3B, Ministral-3 3B/8B/14B, Mistral-Small-3.2-24B, Magistral-Small-2509, nvidia/Qwen3.6-35B-A3B-NVFP4) is Apache-2.0 and not gated on Hugging Face as of 2026-10-02. No click-through is needed.

## B4. NGC account (only if a pull is refused)

- **Ask:** if `docker pull nvcr.io/nvidia/vllm@sha256:9204569b17ee4c0eff75194b8e6e458479c8aee18953b5ab9cf359fcdac659e2` (the image NemoClaw's Spark recipe pins) or any NIM image is refused anonymously, someone needs to log in with `docker login nvcr.io` (username `$oauthtoken`, password = a personal NGC API key). Never paste the key into the repo, the logs, or chat.
- An NVIDIA API key (`NVIDIA_INFERENCE_API_KEY`) is **not** needed for local providers per the NemoClaw docs. Some March 2026 blog posts say otherwise; they are out of date.

## B5. System Node on the laptop is below OpenClaw's floor (optional)

- **State:** `C:\Program Files\nodejs` is v24.14.0, and OpenClaw needs `>=24.15.0 <25` (2026.9.2 and 2026.7.1) or `>=24.16.0 <25` (2026.9.7). I used a portable Node 24.21.0 in `%LOCALAPPDATA%` instead, with no admin.
- **Ask (admin):** upgrade the system Node to 24.21.0 LTS with the MSI, only if you want `openclaw` on the normal PATH. Not needed for anything else.

## Not blockers, but you should know

- **OpenClaw used a local OpenAI credential.** Its memory subsystem made embedding calls to OpenAI with no OpenAI key in the environment, most likely reusing the Codex CLI login (`~\.codex\auth.json`). The calls failed with `insufficient_quota` and stopped once memory search was disabled. No action is needed. Keep it in mind for any OpenClaw install on this laptop.
- **The PC's OpenClaw gateway** (`ron.tail7d447c.ts.net`) was not touched, per instructions.
