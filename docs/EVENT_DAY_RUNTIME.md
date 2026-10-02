# Event-day runtime: NemoClaw + OpenClaw + OpenShell on the GB10

Prepared 2026-10-02 by the runtime-readiness worker. It is a runbook for D02 and D03, and every version and model ID below was checked live on that date.

This document does not contain an agent definition, a tool registration, a system prompt, a decision policy or a network policy file for our agent. Under `docs/PREBUILD_BOUNDARY.md`, those get written on the day (D00, D01, D02). The commands below use only stock components, the default `main` agent and a trivial prompt.

Companion evidence:

- `artifacts/runtime/runtime_smoke.md`: laptop rehearsal of the OpenClaw runtime against local Ollama (commands, timings, findings)
- `artifacts/runtime/runtime_smoke.log`: raw ASCII log of that rehearsal
- `artifacts/runtime/BLOCKERS.md`: steps that need a person (GB10 access, sudo, license acceptance, NGC login)

## 0. Verdict

| Layer | State on 2026-10-02 |
|---|---|
| OpenClaw runtime + local model routing | **Proven** on the dev laptop (Windows 11, native) with OpenClaw 2026.9.2 and 2026.7.1 against Ollama `ministral-3:8b`, through both the embedded path (`agent --local`) and a loopback gateway. No cloud calls once the config was hardened. |
| NemoClaw + OpenShell | **Not rehearsed.** They are Linux/macOS only and need Docker. The laptop has no usable WSL (the service is disabled) and no Docker. The steps below come from the official docs, not from a run. |
| GB10 readiness | **Conditional.** We need shell + sudo on the box before the clock starts, Docker 28+, and model weights plus the vLLM image either reachable on the venue network or pre-staged on disk (see BLOCKERS B2). |

## 1. What the three components are

| Component | What it is | Who / license | Version checked | Platforms | Source |
|---|---|---|---|---|---|
| **OpenClaw** | An agent runtime: a gateway, an embedded agent loop, tools, skills, channels, MCP client (`mcp.servers`) and plugins. It is the thing that "is the agent". | OpenClaw Foundation, MIT | npm `openclaw` latest 2026.9.7, extended-stable 2026.8.35 | Node 24.15+ on Linux, macOS, Windows (native or WSL2) | https://docs.openclaw.ai/install , https://github.com/openclaw/openclaw |
| **OpenShell** | A sandbox runtime for agents: container sandboxes, Landlock + seccomp, a gateway that does policy-enforced egress, plus an `inference.local` endpoint that routes model calls to a configured provider | NVIDIA, Apache-2.0, alpha | v0.1.2 (2026-09-28) | Linux x86_64/aarch64, macOS arm64 supported; Windows only via WSL2 (experimental). Docker 28+, Linux 6.2+ for Landlock ABI 3 | https://github.com/NVIDIA/OpenShell , https://docs.nvidia.com/openshell/latest/about/support-matrix.md |
| **NemoClaw** | NVIDIA's reference stack that installs OpenShell, builds a sandbox image with an agent inside (OpenClaw by default; also Hermes and LangChain Deep Agents), wires inference (cloud, Ollama, vLLM, NIM, llama.cpp) and applies network-policy presets | NVIDIA, Apache-2.0, alpha | installer tag `lkg` = v0.0.124 (sandbox pins openclaw 2026.7.1); `main` pins openclaw 2026.9.2; newest tag v0.0.130 | DGX Spark and Linux tested; macOS and WSL2 tested with limitations; no native Windows | https://github.com/NVIDIA/NemoClaw , https://docs.nvidia.com/nemoclaw/latest/get-started/prerequisites.html , https://build.nvidia.com/spark/nemoclaw/instructions |

How they fit together on the day: we install NemoClaw on the GB10. Its installer brings in the OpenShell CLI and gateway, then builds an OpenShell sandbox with OpenClaw inside it. The agent inside the sandbox never calls a model server directly. It sends Chat Completions to `https://inference.local`, and OpenShell forwards that to the host model server via `host.openshell.internal:<port>` over the private `openshell-docker` bridge. Any other egress from the sandbox has to be allowed by a network-policy preset. The required stack in `CLAUDE.md` is the whole chain, so running OpenClaw alone is useful only as a diagnostic.

Look-alikes to ignore: the npm package `nemoclaw` 0.1.0 (ISC) is not NVIDIA's. NVIDIA's CLI comes from `https://www.nvidia.com/nemoclaw.sh`.

## 2. What the laptop rehearsal proved

Details are in `artifacts/runtime/runtime_smoke.md`. In short:

- Portable Node 24.21.0 plus OpenClaw 2026.9.2 and 2026.7.1, all under `%LOCALAPPDATA%\ambient-mirror-runtime`. State is isolated with `OPENCLAW_HOME` / `OPENCLAW_STATE_DIR` / `OPENCLAW_CONFIG_PATH`.
- Stock onboarding: `--auth-choice ollama --custom-base-url http://127.0.0.1:11434`. Tools, skills, channels, memory search, catalog refresh, telemetry and update checks were turned off.
- `ministral-3:8b` answered `ready` on every run. A warm `--local` turn took about 1.0 s of agent time (8 to 10 s wall, mostly Node start). A warm gateway turn took 0.57 to 1.1 s of agent time (2.3 to 4.7 s wall).
- `ministral-3:3b` returned `NO_REPLY` (empty payload, exit 0) on every run. Do not use a 3B model as the agent's brain.
- Two runtime traps turned up and both are now in the pitfalls list (section 7): the memory subsystem called OpenAI embeddings using a credential it found on the machine, and OpenClaw wrote into the real `~/.openclaw` once even though the isolation variables were set.

## 3. GB10 install and run (NemoClaw + OpenShell + OpenClaw)

Run the steps in order. Commands are bash on the GB10. `sudo` is needed only where marked.

### 3.0 Pre-checks (5 min)

```bash
uname -m                                  # expect aarch64
uname -r                                  # expect >= 6.2 (Landlock ABI 3)
cat /sys/kernel/security/lsm              # expect landlock in the list
nvidia-smi                                # GB10 visible, driver loaded
docker --version                          # expect >= 28.0
docker info >/dev/null && echo docker-ok  # daemon reachable without sudo (else: user in docker group)
node --version 2>/dev/null || echo no-node  # NemoClaw needs Node >= 22.19 and npm >= 10; the installer can provide it
df -h ~ /var/lib/docker                   # need 20-40 GB for NemoClaw plus the weights and images in section 4
free -g                                   # 128 GB unified; note what is already used
ss -ltnp | grep -E ':(8000|8001|8080|11434|18789|18790)\b'   # ports we plan to use must be free
```

If `docker info` fails with a permission error, that is a sudo task (`sudo usermod -aG docker $USER`, then log in again). See BLOCKERS B2.

### 3.1 Start the model servers before onboarding

NemoClaw looks for an existing vLLM at `localhost:${NEMOCLAW_VLLM_PORT}/v1/models`, validates structured tool calls against it, and stops onboarding if the model fails. So the server the agent will use as its brain has to be up and healthy first. Use section 4 to start the perception and reasoning servers. Then run:

```bash
curl -s http://127.0.0.1:8000/v1/models   # perception server answers with the expected model id
curl -s http://127.0.0.1:8001/v1/models   # reasoning server answers with the expected model id
```

### 3.2 Install NemoClaw (brings in OpenShell and the OpenClaw sandbox)

Do not install OpenShell separately first. NemoClaw's installer pins the OpenShell it was tested with.

```bash
# A team member must read and accept the third-party notice (BLOCKERS B3).
# These variables skip Express (Express would start its own managed vLLM on :8000 with
# Qwen3.6-35B-A3B-NVFP4 at gpu-memory-utilization 0.4, which collides with our perception server)
# and point onboarding at the server we already started.
export NEMOCLAW_NO_EXPRESS=1
export NEMOCLAW_AGENT=openclaw
export NEMOCLAW_PROVIDER=vllm
export NEMOCLAW_VLLM_PORT=<port of the server chosen as the agent's brain>   # D02 decides; see section 5
export NEMOCLAW_SANDBOX_NAME=ambient-mirror   # 19 characters max; scripts/demo_check.sh expects this name
# Optional pin. Default is the lkg tag (v0.0.124, sandbox openclaw 2026.7.1). Record whichever you use.
# export NEMOCLAW_INSTALL_TAG=lkg

# The installer installs the CLI and then runs onboarding straight away with the variables above.
# Interactive form, where a team member answers the prompts:
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
# Non-interactive form, only after a human has read and accepted the notice:
#   export NEMOCLAW_NON_INTERACTIVE=1 NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1
#   curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
source ~/.bashrc            # if the shell did not pick up the new PATH
```

The docs estimate 30 to 60 minutes for a first pass: the sandbox image build, the OpenShell gateway, and validation. If it gets interrupted, `nemoclaw onboard --resume` picks up where it stopped. If onboarding fails, run `nemoclaw host probe` (it changes nothing, exits 0/2/3 for supported/incompatible/inconclusive) and `nemoclaw ambient-mirror doctor`, fix what they report, then `--resume`.

Do not use the installer's `--local-model-runtime=vllm` flag. It installs NemoClaw's own fixed vLLM recipe, rejects `NEMOCLAW_PROVIDER` and `NEMOCLAW_MODEL`, and would compete with our servers for memory.

When the wizard asks for an agent, keep the stock default. Our own agent gets written afterwards as part of D00/D01.

An NVIDIA API key is **not** needed for local providers. Some blog posts from March 2026 say it is; those posts are out of date.

### 3.3 Verify the stack

```bash
nemoclaw list                               # ambient-mirror listed
nemoclaw ambient-mirror status              # sandbox Running; Inference row healthy (provider vllm, expected model)
nemoclaw inference get                      # provider + model actually recorded for the sandbox
nemoclaw ambient-mirror doctor              # deeper probe of the recorded inference route
nemoclaw ambient-mirror policy list         # presets applied to the sandbox
nemoclaw ambient-mirror policy explain      # redacted summary of what egress is allowed and blocked
openshell --version                         # record for D02 "required stack status captured"
nemoclaw --version                          # record
nemoclaw ambient-mirror logs --follow       # leave open in a spare terminal
```

`nemoclaw ambient-mirror dashboard-url --quiet` prints a URL with a token in it. Open it in a browser, but never paste it into a log, an artifact or chat.

### 3.4 Stock one-shot inside the sandbox (proves the runtime before our agent exists)

```bash
nemoclaw ambient-mirror connect             # shell inside the OpenShell sandbox
openclaw --version                          # expect 2026.7.1 on lkg, 2026.9.2 on main
openclaw agent --agent main --message "Reply with the single word: ready" --json
openclaw tui                                # optional interactive check; exit with Ctrl+C
exit
```

Pass means the JSON payload text is `ready`, the run reports the provider/model of our local server, and the logs show no outbound call other than `inference.local`. An empty payload with exit 0 is a **failure**, not a pass (see pitfall P5).

### 3.5 Reset and teardown

```bash
nemoclaw onboard --fresh --name ambient-mirror --recreate-sandbox   # rebuild the sandbox from scratch
nemoclaw inference set --provider vllm --model <id> --sandbox ambient-mirror   # switch the route without rebuilding
nemoclaw uninstall --yes                    # removes sandboxes, the OpenShell gateway, containers, CLI, state
# nemoclaw uninstall --yes --delete-models  # also deletes downloaded models; do not run on the day
```

### 3.6 Diagnostic only: bare OpenClaw on the host

If the NemoClaw/OpenShell layer is failing and you need to tell whether the problem is the model or the sandbox, run the laptop recipe from `artifacts/runtime/runtime_smoke.md` on the GB10 host. Point it at the reasoning server through the OpenAI-compatible provider, or at Ollama. This does **not** satisfy the required stack. Use it only to bisect a failure.

## 4. Local model serving on the GB10

### 4.1 Budget

The GB10 has 128 GB of unified memory, shared by the CPU, GPU, Docker, the OpenShell sandbox and our FastAPI/ffmpeg. vLLM's `--gpu-memory-utilization` is a fraction of the whole pool, and each server claims it separately. NemoClaw's docs warn that an operator-managed vLLM that is too large on DGX Spark can cause `NV_ERR_NO_MEMORY`, lost SSH, or a host freeze. Keep the **sum** across servers at about 0.6 or less, keep `--max-model-len` and `--max-num-seqs` small, and start the larger server first.

| Role | Weights (approx.) | Suggested start values to calibrate in D03 |
|---|---|---|
| Perception, Qwen 35B-A3B FP8 | ~36 GB | `--gpu-memory-utilization 0.40 --max-model-len 32768 --max-num-seqs 4` |
| Perception, Qwen3.8-27B FP8 | ~28 GB | `--gpu-memory-utilization 0.35 --max-model-len 32768 --max-num-seqs 4` |
| Reasoning, Ministral-3-14B (FP8 as published) | ~14 GB | `--gpu-memory-utilization 0.20 --max-model-len 32768 --max-num-seqs 4` |

These values are a starting point, not a measured result. Record the final values in `config/models/gb10.yaml` (D03).

### 4.2 vLLM (primary: matches `config/models/gb10.yaml`)

`gb10.yaml` already assumes an OpenAI-compatible server with `response_format` json_schema and thinking toggled through `chat_template_kwargs`. Of the options here, only vLLM gives all of that as-is.

Container image, pick one and record the digest:

- NemoClaw's pinned Spark image: `nvcr.io/nvidia/vllm@sha256:9204569b17ee4c0eff75194b8e6e458479c8aee18953b5ab9cf359fcdac659e2` (arm64; 9.6 GB to download, 27.7 GB unpacked).
- The DGX Spark vLLM playbook image: `vllm/vllm-openai:qwen38` (https://build.nvidia.com/spark/vllm/instructions). The playbook health check is `curl -i http://localhost:8000/health`.

Check that the image's vLLM version is at least 0.19.0 for Qwen3.6 and at least 0.12.0 for Ministral-3: `docker run --rm --entrypoint python3 <image> -c "import vllm; print(vllm.__version__)"`. Overriding the entrypoint avoids the image's default `vllm serve` wrapper swallowing the flag.

**Perception (Qwen, :8000).** The model card's flags are below. Thinking is turned off per request with `chat_template_kwargs: {"enable_thinking": false}`, which is how `gb10.yaml` already sends it.

```bash
vllm serve Qwen/Qwen3.6-35B-A3B-FP8 --host <see section 5> --port 8000 \
  --reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_coder \
  --gpu-memory-utilization 0.40 --max-model-len 32768 --max-num-seqs 4 \
  --limit-mm-per-prompt '{"image": 12}'
```

**Reasoning (Mistral, :8001).** These are the model card's flags, plus the card's own advice to keep temperature below 0.1. `gb10.yaml` already uses 0.0.

```bash
vllm serve mistralai/Ministral-3-14B-Instruct-2512 --host <see section 5> --port 8001 \
  --tokenizer_mode mistral --config_format mistral --load_format mistral \
  --enable-auto-tool-choice --tool-call-parser mistral \
  --gpu-memory-utilization 0.20 --max-model-len 32768 --max-num-seqs 4
```

Both servers need `--enable-auto-tool-choice` and a tool-call parser if either one is the agent's brain. NemoClaw validates tool calls during onboarding. It also forces `/v1/chat/completions`, because vLLM's `/v1/responses` does not run the tool parser.

### 4.3 Model IDs to verify on the day

All of these were checked on Hugging Face on 2026-10-02. All are Apache-2.0 and none are gated.

| Role | Hugging Face ID | Params | HF task | Notes |
|---|---|---|---|---|
| Perception (first choice, the "35B-class") | `Qwen/Qwen3.6-35B-A3B-FP8` | 36.0B (MoE, ~3B active) | image-text-to-text | vLLM >= 0.19.0; `--language-model-only` exists but would drop vision, so do not use it for perception |
| Perception (BF16 original) | `Qwen/Qwen3.6-35B-A3B` | 36.0B | image-text-to-text | ~72 GB in BF16; too large next to a second server |
| Perception (newer, dense) | `Qwen/Qwen3.8-27B-FP8` | 27.8B | image-text-to-text | released 2026-08-05; native image + video; recipe at https://recipes.vllm.ai/Qwen/Qwen3.8-27B |
| Perception (NVFP4, vision unconfirmed) | `nvidia/Qwen3.6-35B-A3B-NVFP4`, `nvidia/Qwen3.8-27B-NVFP4` | | text-generation | NemoClaw's Spark recipe and the Spark playbook serve these. They are tagged text-only on HF; the 3.8 card passes `--mm-encoder-tp-mode data`, which hints the vision tower is kept. **Send one image and check the description before using either one for perception.** |
| Perception (older fallback, in `gb10.yaml` comment) | `Qwen/Qwen3.5-35B-A3B-FP8`, `Qwen/Qwen3-VL-30B-A3B-Instruct-FP8` | | image-text-to-text | |
| Reasoning (first choice) | `mistralai/Ministral-3-14B-Instruct-2512` | 13.9B | (vision + text) | FP8 as published; 256k context; vLLM >= 0.12.0 |
| Reasoning (larger) | `mistralai/Mistral-Small-3.2-24B-Instruct-2506` | 24.0B | (vision + text) | BF16 ~48 GB; only if perception is the 27B or the NVFP4 build |
| Reasoning (smaller, dev parity) | `mistralai/Ministral-3-8B-Instruct-2512` | | | matches the 8b used in the laptop rehearsal |
| Do not use on GB10 | `Qwen/Qwen3.8-Flash-Next(-FP8)` (180B), `nvidia/Qwen3.8-Flash-Next-NVFP4` (~120B) | | | does not fit next to a second model |

On the day, record the exact revision hash of each model, which is the folder name in `ls ~/.cache/huggingface/hub/models--<org>--<name>/snapshots/`. Put it in `gb10.yaml` (`quantization` label + model id) and in `artifacts/event_day/`.

### 4.4 Ollama ARM64 (fallback)

Use this if vLLM images or HF weights are not available on the box but Ollama tags are.

```bash
curl -fsSL https://ollama.com/install.sh | sh     # needs sudo (installs a systemd service)
ollama pull qwen3.6:35b-a3b                       # 22.6 GB, includes the vision projector
ollama pull ministral-3:14b                       # 9.1 GB
# alternatives: qwen3.8:27b (17.7 GB, has projector), qwen3-vl:30b-a3b-instruct (19.6 GB),
#               mistral-small3.2:24b (15.2 GB), qwen3.5:35b-a3b (23.9 GB)
```

Ollama tags that do not exist (checked): `qwen3.8:35b`. Never pull or select a tag that ends in `:cloud`.

What changes when the backend is Ollama:

- The base URL becomes `http://127.0.0.1:11434/v1` for both roles. Copy the request shape from `config/models/lite-local.yaml`, which sends `think_param: reasoning_effort`, not `chat_template_kwargs`.
- For the agent's brain, NemoClaw reaches Ollama through its own proxy on 11435. OpenClaw's own docs warn that the `/v1` path can break tool calls and prefer the native `http://<host>:11434` API (`api: "ollama"`).
- Do not set `keep_alive -1` while another process shares the server. On the laptop, loading a second model pushed a pinned model out of memory.
- Check the server's context length. On the laptop's Ollama it is 4096, and a prompt that is too long gets truncated without any error (reported by the inference worker). OpenClaw's prompt is about 1.7k to 2.5k tokens even with no tools enabled, and it grows with every tool registered. Set `OLLAMA_CONTEXT_LENGTH` on the server (or `num_ctx` per request), then confirm the value in the server log.
- On the `/v1` API, thinking models need `reasoning_effort: "none"` to answer at all. `think: false` is silently ignored there. `qwen3.5:9b` returned empty content without it. Ministral-3 does not think internally, so it is not affected.

### 4.5 NVIDIA NIM (experimental)

NemoClaw lists `nim-local`, but only behind `NEMOCLAW_EXPERIMENTAL=1`. It needs `docker login nvcr.io` (BLOCKERS B4). Treat it as a third option. Nothing in this repo has been tested against a NIM.

## 5. Interface note: how the event-day agent reaches our service and tools

This section describes boundaries. It is not an implementation. The agent, its tool registration, and its policy get written on the day.

- **Two separate inference paths.** Our tool code (`tools/*.py`, behind the FastAPI app) calls the perception and reasoning servers directly from the host, using `config/models/gb10.yaml` (`:8000` and `:8001`). The agent's own LLM traffic goes out of the sandbox only as `https://inference.local`, and OpenShell routes it to whichever host server NemoClaw recorded. Do not mix the two: the agent must not get raw model endpoints as tools.
- **Brain choice is D00/D02's decision.** Whichever server is the brain has to pass NemoClaw's tool-call validation, so it needs `--enable-auto-tool-choice` plus the right parser. Pointing NemoClaw at an existing server (`NEMOCLAW_VLLM_PORT=8001` or `=8000`) costs no extra memory. A third server for the brain does. NemoClaw's default port is 8000, the same as our perception port, so always set `NEMOCLAW_VLLM_PORT` explicitly.
- **Binding.** The sandbox is a container, so `127.0.0.1` inside it is not the host. Any host service the sandbox has to reach must listen on the host loopback **and** on the `openshell-docker` bridge gateway address. That covers the brain model server and whatever endpoint exposes our tools. Find the bridge with `docker network ls` and `docker network inspect openshell-docker`. NemoClaw's vLLM guide says to allow the port only from that subnet, keep loopback, and deny it on every other interface. vLLM's and uvicorn's `--host` accept only one address. In practice that means one of two setups:

  - `--host 0.0.0.0` plus a host firewall rule (sudo) for that port.
  - A container that publishes the port twice: `-p 127.0.0.1:<port>:<port> -p <bridge-gateway-ip>:<port>:<port>`. This is what NemoClaw's managed profile does. The bridge address exists only once OpenShell's gateway is up, so this setup means restarting the server after onboarding.

  Today `apps/api/main.py` documents `--host 127.0.0.1 --port 8080`, which the sandbox cannot reach.
- **Egress policy.** By default the sandbox can reach only what its presets allow. The stock `local-inference` preset opens `host.openshell.internal` ports 8081, 11434, 11435 and 8000 for a fixed set of binaries, and nothing on 8080 or 8001. D02 has to add a custom preset (`nemoclaw ambient-mirror policy add --from-file <file> --dry-run`, then without `--dry-run`). That preset should allow only the agent-facing FastAPI or tool paths on the chosen port, with method and path rules (`protocol: rest`, `enforcement: enforce`), and give no rule at all for `/api/judge/**`. The command reference says custom presets may not carry their own `allowed_ips`. A private destination such as the bridge address has to be admitted with `--trusted-private-host <exact-host>`, which generates the address pins. Keep `--dry-run` output in `artifacts/event_day/` as part of the ground-truth exclusion proof (D03).
- **Managed MCP surface (if D01 picks MCP).** `nemoclaw <sandbox> mcp add <server> --url <streamable-http-url> --env <KEY>` registers a Streamable HTTP MCP server in one step. It writes OpenClaw's `mcp.servers`, generates a binary-scoped egress rule, and attaches a bearer credential. It requires a bearer token (the `--env KEY`), so the host-side server has to check one. `--deny-tool <name-or-glob>` blocks tool calls by name at the OpenShell proxy. `mcp status <server>` runs the supported reachability check; a failed `curl` from the sandbox shell is not evidence, because the rule only admits the agent's own binaries. The command is documented in both the `lkg` and `main` references.
- **Ground truth.** By default the sandbox has no mount of the repo or the data directory, so the agent cannot read ground truth from disk. NemoClaw has an `onboard --host-mount <host-dir:/sandbox/dir>` option, which is read-only. Do not use it for the repo or the data directory. Over HTTP, the only judge-only surface today is the `/api/judge` router. `/media/scenarios/{id}/cameras/{camera_id}` already refuses the ground-truth camera ("the ground-truth camera is judge-only"). The D03 proof is a request from inside the sandbox to `/api/judge/...` that the policy denies, plus a log line showing the denial.
- **Tool contract.** Tool names and schemas are in `contracts/tools.schema.json`. The run-scoped bindings are `tools/session.py` (`ToolSession`): `call_tool(name, arguments)` validates a call, runs it, emits the same `tool.*` and domain events the UI already renders, and returns the result's JSON form. The NON-AGENT dev harness drives the same session today. Both OpenClaw versions in play (2026.7.1 in NemoClaw lkg, 2026.9.2 on main) have an `mcp.servers` client section and a `plugins` section in their config schema. Choosing how the tools are exposed (an MCP server on the host, a plugin, or HTTP endpoints on FastAPI) is D01's job. Whatever D01 chooses has to keep the names and JSON schemas exactly as in the contract.
- **Status for D02.** `nemoclaw ambient-mirror status`, `nemoclaw inference get`, `openshell --version`, `openclaw --version` (inside the sandbox) and `curl /api/models/health` give the "required stack status captured" evidence. The existing `/healthz` and `/api/models/health` endpoints are where a failure gets "surfaced to UI".

## 6. Morning pre-flight checklist

Tick these off in order, and copy the outputs into `artifacts/event_day/` as you go.

1. [ ] Shell on the GB10 works, `sudo -v` succeeds, and `docker info` runs without sudo (3.0).
2. [ ] `uname -m` = aarch64, kernel >= 6.2, `landlock` appears in `/sys/kernel/security/lsm`, Docker >= 28.
3. [ ] Free disk for the images and weights in section 4 (at least 120 GB is comfortable). `free -g` looks idle.
4. [ ] Network test: `curl -sI https://huggingface.co`, `curl -sI https://www.nvidia.com/nemoclaw.sh`, `curl -sI https://registry.npmjs.org/openclaw`. If any fail, switch to the pre-staged USB copies (BLOCKERS B2).
5. [ ] vLLM image present (`docker images`) and its version noted (`vllm --version` inside the image).
6. [ ] Model snapshots present under `~/.cache/huggingface/hub`, with revision hashes noted.
7. [ ] Perception server up on :8000. `/v1/models` lists the expected id. One image request returns a description, which proves vision is on.
8. [ ] Reasoning server up on :8001. `/v1/models` lists the expected id. One request with `response_format` json_schema returns valid JSON.
9. [ ] `free -g` and `nvidia-smi` after both servers are loaded leave at least 30 GB of headroom.
10. [ ] The servers are reachable on the bridge address and **not** from the LAN. From another machine, `curl http://<gb10-lan-ip>:8000/v1/models` must fail.
11. [ ] NemoClaw installed, and the notice accepted by a team member (B3). `nemoclaw --version`, `openshell --version` recorded.
12. [ ] `nemoclaw ambient-mirror status` shows Running and a healthy Inference row naming the local model. `nemoclaw inference get` does not name any cloud provider.
13. [ ] Stock one-shot (3.4) returns `ready` and the payload is not empty.
14. [ ] FastAPI up. `curl http://127.0.0.1:8080/healthz` and `curl http://127.0.0.1:8080/api/models/health` both report healthy with the gb10 profile.
15. [ ] `python -m pytest` (or the repo's standard gate) passes on the box. A fixture-mode run completes in `/ops`.
16. [ ] Prebuild commit hash recorded with the provided scripts before any event-day code is written (`docs/PREBUILD_BOUNDARY.md`).

## 7. Known pitfalls

- **P1. Version skew.** NemoClaw `lkg` puts OpenClaw 2026.7.1 in the sandbox. `main` puts in 2026.9.2. npm `latest` is 2026.9.7, which needs Node 24.16+. Config keys differ between versions: memory search is `agents.defaults.memorySearch.enabled` in 2026.7.1 and `memory.search.enabled` in 2026.9.2, and 2026.7.1 has no `models.catalogRefresh` or `telemetry` keys. Write the agent against the version that is actually inside the sandbox (`openclaw --version` after `connect`).
- **P2. Cloud leak through memory.** On the laptop, OpenClaw's memory search sent embedding requests to OpenAI with no `OPENAI_API_KEY` set. It most likely reused a credential it found on disk, and it failed with `insufficient_quota`. Turn memory search off (key from P1), and confirm in the logs that no host other than the local server or `inference.local` is contacted. The sandbox's egress policy should block this on the GB10, but check anyway: a "No cloud model route" acceptance criterion depends on it.
- **P3. Background network calls.** Catalog refresh, update checks and telemetry are all separate settings, and each makes outbound calls. Turn them off where the version has the key, and set `OPENCLAW_NO_AUTO_UPDATE=1` and `DO_NOT_TRACK=1`.
- **P4. `:cloud` models.** Ollama's catalog includes `:cloud` tags, and OpenClaw's model catalog can list them too. Use `models.mode=replace` with an explicit local list so a cloud model cannot be selected by accident.
- **P5. Silent empty reply.** A model that is too small (ministral-3:3b) produced `NO_REPLY`, with an empty payload and exit code 0. Any health check has to assert that the payload text is not empty, not just that the exit code is 0.
- **P6. Tool calls arriving as text.** This happens if the server has no `--enable-auto-tool-choice` / tool-call parser, if the parser does not match the model (`qwen3_coder` for Qwen3.6/3.8, `mistral` for Ministral), or if the client goes through `/v1/responses`. NemoClaw forces chat completions for vLLM, so leave that alone.
- **P7. Spark memory freeze.** A vLLM server with high `--gpu-memory-utilization` or a long `--max-model-len` can freeze a DGX Spark or drop SSH. Start conservatively (4.1), raise the values one at a time, and keep a second SSH session open.
- **P8. Port collision.** NemoClaw's default vLLM port (8000) is the same as our perception port. Express mode would start its own managed vLLM on 8000. Set `NEMOCLAW_NO_EXPRESS=1` and `NEMOCLAW_VLLM_PORT` explicitly. The stock `local-inference` preset does not cover 8001 or 8080.
- **P9. Wrong host name.** Inside the sandbox, use `host.openshell.internal`, never `localhost`, `127.0.0.1` or `host.docker.internal`. On the host, services must listen on the bridge address as well as loopback (section 5).
- **P10. Stale blog commands.** OpenShell removed `openshell inference set`. Inference now uses provider profiles attached to a sandbox, and the workload has to send the real model id. Use `nemoclaw inference get/set` instead. Blog posts from March 2026 also claim an NVIDIA API key is required for local use; that is no longer true.
- **P11. Sandbox name length.** `NEMOCLAW_SANDBOX_NAME` is limited to 19 characters. `ambient-mirror` is 14.
- **P12. State isolation.** The laptop already had an older `~/.openclaw` from another project. During one run, OpenClaw wrote `~/.openclaw/state/openclaw.sqlite` even though the isolation variables were set. On the GB10 the agent lives inside the sandbox, so this mostly matters for the diagnostic path in 3.6: there, set all three `OPENCLAW_*` path variables and check `~/.openclaw` afterwards.
- **P13. Shared Ollama.** If Ollama is the fallback, it is shared by the tools and possibly the brain. Loading a model can push out another model that was pinned with `keep_alive -1`. Pull and warm the exact tags first, and check `/api/ps`.
- **P14. Wrong package.** `npm install nemoclaw` installs an unrelated ISC package. Use NVIDIA's installer URL.
- **P15. Token-bearing output.** `dashboard-url --quiet` and gateway startup print tokens. Keep them out of `artifacts/` and out of screenshots. (On the laptop, onboarding used `--suppress-gateway-token-output`.)
- **P16. NVFP4 and vision.** The `nvidia/*-NVFP4` builds that the Spark recipes default to are tagged text-generation. Check that vision works before using one for perception (4.3).
- **P17. Private-host egress.** A custom preset that names `host.openshell.internal` or a bridge IP will not take effect unless `--trusted-private-host` is passed, because hand-written `allowed_ips` are rejected. Run `--dry-run` and confirm the generated pins appear.
- **P18. Docs track `main`, installer defaults to `lkg`.** The published docs describe `main`. I compared the v0.0.124 (`lkg`) command reference with `main` for every NemoClaw command this document uses (`host probe`, `doctor`, `policy add/list/explain`, `--trusted-private-host`, `--host-mount`, `mcp add`, `inference get/set`, `dashboard-url`, `--recreate-sandbox`, `--version`). All of them appear in both. Still run `nemoclaw --help` on the installed version, since flag details can differ.

## 8. How this maps to D02 and D03

| Task | Acceptance item | Where this doc helps |
|---|---|---|
| D02 | Required stack status captured | 3.3 commands; checklist items 11 to 13 |
| D02 | No cloud model route | 3.2 provider env vars; P2, P3, P4; `nemoclaw inference get` |
| D02 | Failure surfaced to UI | section 5 status bullet (`/healthz`, `/api/models/health`) |
| D02 | Runtime command documented | sections 3 and 4 hold the commands; D02 records the exact ones it ran in `artifacts/event_day/workers/` |
| D03 | Real Qwen + Mistral + OpenClaw path completes | 4.2 servers + 3.4 stock proof, then our agent |
| D03 | Latency recorded | laptop baseline in `runtime_smoke.md` (warm agent turn ~1 s on ministral-3:8b) to compare against |
| D03 | Ground-truth exclusion proof | section 5 ground-truth and egress-policy bullets (denied `/api/judge` request from inside the sandbox) |
| D03 | Playwright screenshot | unchanged; not a runtime item |

D02's allowed paths are `runtime/**`, `scripts/runtime/**`, `config/models/gb10.yaml`, `artifacts/event_day/**` and `tests/integration/runtime/**`. The custom policy preset and any start scripts belong there, written on the day.

## 9. Sources (checked 2026-10-02)

- OpenClaw install: https://docs.openclaw.ai/install
- OpenClaw on Windows: https://docs.openclaw.ai/windows
- OpenClaw `agent` CLI: https://docs.openclaw.ai/cli/agent
- OpenClaw `onboard` CLI: https://docs.openclaw.ai/cli/onboard
- OpenClaw environment variables: https://docs.openclaw.ai/help/environment
- OpenClaw Ollama provider: https://docs.openclaw.ai/providers/ollama/setup.md
- OpenClaw license: https://raw.githubusercontent.com/openclaw/openclaw/main/LICENSE
- OpenClaw npm package: https://registry.npmjs.org/openclaw
- NemoClaw repo and README: https://github.com/NVIDIA/NemoClaw
- NemoClaw command reference (`main`): https://github.com/NVIDIA/NemoClaw/blob/main/docs/reference/commands.mdx
- NemoClaw managed-inference presets: https://raw.githubusercontent.com/NVIDIA/NemoClaw/main/managed-inference/presets
- NemoClaw prerequisites: https://docs.nvidia.com/nemoclaw/latest/get-started/prerequisites.html
- NemoClaw quickstart: https://docs.nvidia.com/nemoclaw/latest/get-started/quickstart.html
- NemoClaw choosing an inference provider: https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/inference/learn-and-choose/choose-inference-provider
- NemoClaw local inference: https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/inference/use-local-inference
- NemoClaw network policy: https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/network-policy/customize-network-policy
- DGX Spark NemoClaw playbook: https://build.nvidia.com/spark/nemoclaw/instructions
- DGX Spark vLLM playbook: https://build.nvidia.com/spark/vllm/instructions
- OpenShell repo: https://github.com/NVIDIA/OpenShell
- OpenShell installer: https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh
- OpenShell support matrix: https://docs.nvidia.com/openshell/latest/about/support-matrix.md
- OpenShell inference: https://docs.nvidia.com/openshell/latest/how-it-works/inference.md
- OpenShell policy schema: https://docs.nvidia.com/openshell/latest/reference/policy-schema.html
- Model cards:
  - https://huggingface.co/Qwen/Qwen3.6-35B-A3B-FP8
  - https://huggingface.co/Qwen/Qwen3.8-27B-FP8
  - https://huggingface.co/nvidia/Qwen3.6-35B-A3B-NVFP4
  - https://huggingface.co/nvidia/Qwen3.8-27B-NVFP4
  - https://huggingface.co/mistralai/Ministral-3-14B-Instruct-2512
  - https://huggingface.co/mistralai/Mistral-Small-3.2-24B-Instruct-2506
- Ollama: https://ollama.com/install.sh , https://ollama.com/library/qwen3.6 , https://ollama.com/library/ministral-3 (tag sizes read from `registry.ollama.ai/v2/library/<name>/manifests/<tag>`)
