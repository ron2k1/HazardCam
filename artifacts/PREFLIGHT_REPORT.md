# Preflight report (P00)

Generated: 2026-10-02 (integrator). The raw probe output is in `artifacts/PREFLIGHT_RAW.txt` and comes from `scripts/preflight.sh`.

## Development machine (actual)

| Item | Value |
|---|---|
| Machine | Dell G15 5530 laptop |
| OS | Windows 11 Home 10.0.26200 (Git Bash + PowerShell 7) |
| CPU | Intel Core i7-13650HX |
| RAM | 15.7 GB |
| GPU | NVIDIA GeForce RTX 4060 Laptop, 8188 MiB VRAM, driver 616.92, CUDA UMD 13.4 |
| Disk free | 178 GB on C: |
| Python | `.venv` CPython 3.12 via uv. System has 3.14, and bash `python3` resolves to 3.11.9 |
| Node / pnpm | v24.14.0 / 10.33.0 |
| ffmpeg / ffprobe | 8.1 full build (gyan.dev, winget) |
| Model runtime | Ollama 0.22.1 tray server on `127.0.0.1:11434`, OpenAI-compatible `/v1` |
| `make` | NOT installed. Use `scripts/run.sh` (P16) or call the scripts directly |
| NemoClaw / OpenShell / OpenClaw | not installed. These are event-day items (D02) and intentionally absent |

## Local models pulled (Ollama)

| Role | Lite profile | Closest-practical full on 8 GB |
|---|---|---|
| Perception (Qwen, multimodal) | `qwen3-vl:4b-instruct` (3.3 GB) | `qwen3.5:9b` (6.6 GB, natively multimodal, hybrid thinking) |
| Reasoning (Mistral) | `ministral-3:3b` (3.0 GB) | `ministral-3:8b` (6.0 GB) |

The intended full stack is a Qwen 35B-class model (`qwen3.5:35b-a3b`) plus a larger Mistral. It does not fit in 8 GB VRAM and 16 GB RAM at a usable speed, so P15 benchmarks the closest-practical pair and documents the gap. The GB10 profile, with 128 GB unified memory, is where the intended checkpoints run on event day.

## Remote 16 GB worker

`config/remote.env` is not configured. The PC (Omen Obelisk, RTX 2060) is normally reachable over Tailscale, but the laptop's Tailscale reported "starting" during preflight, and the PC's Ollama endpoint did not answer within 3 s. Per CLAUDE.md the remote is optional, so it is treated as unavailable and nothing depends on it.

## Hardware and software plan (frozen)

- **fixture**: no model runtime. Used for UI, API and E2E development and for the P13 gate.
- **lite-local**: Ollama with `qwen3-vl:4b-instruct` and `ministral-3:3b`. This is the P14 gate.
- **full-local**: Ollama with `qwen3.5:9b` and `ministral-3:8b`. The models run one at a time because together they exceed 8 GB VRAM. This is the P15 benchmark.
- **remote16gb**: profile kept, endpoint unconfigured.
- **gb10**: same adapters, with intended checkpoints and endpoints filled in on event day (D02/D03).

## Fallbacks

1. If the perception model is slow or OOMs, drop `max_frames_per_camera` from 8 to 4 and `max_width` from 768 to 512, or move to a smaller Qwen tag.
2. If a model fails mid-demo, the fixture profile replays recorded real-model outputs. See FAILURE_LADDER.md.
3. If real multi-camera data access is blocked, MEVA (public S3, CC-BY-4.0, no registration) is the default no-registration source.

## Secrets

No secrets are present in the repo. `.env*` and `config/remote.env` are gitignored. Profiles name environment variables and never contain values.
