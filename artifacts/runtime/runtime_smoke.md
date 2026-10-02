# Runtime smoke: stock OpenClaw against local Ollama (dev laptop)

Date: 2026-10-02, 09:55 to 10:12 ET. Raw log: `artifacts/runtime/runtime_smoke.log`.

## Verdict

| Component | Result on this laptop | Evidence |
|---|---|---|
| OpenClaw 2026.9.2 (NemoClaw `main` pin), embedded `--local` turn | PASS with `ministral-3:8b` (reply `ready`) | smoke-4/5/6 |
| OpenClaw 2026.9.2 through its own gateway (loopback) | PASS with `ministral-3:8b` (reply `ready`) | smoke-gw-7/8 |
| OpenClaw 2026.7.1 (NemoClaw `lkg` v0.0.124 pin), embedded `--local` turn | PASS with `ministral-3:8b` (reply `ready`) | smoke71-1/2 |
| `ministral-3:3b` under the stock prompt | Routing PASS, answer FAIL: the model replied `NO_REPLY` (OpenClaw's silent-reply token), so the payload was empty | smoke-1/2/3 |
| OpenShell | NOT RUN. It ships no Windows binary, and the WSL2 path needs WSL + Docker, neither of which is available here | `wsl -l -v` -> `Wsl/0x80070422`; `docker` not installed |
| NemoClaw | NOT RUN. Windows is supported only through WSL2 + Docker Desktop or Podman | same |

Every turn ran on the local Ollama at `http://127.0.0.1:11434`, using the `ollama` provider and the native `/api/chat` API. The receipts show `effective.provider=ollama`, `rerouted=false` and `cost 0`. All tools were removed (`tools=0`) and skills were disabled (`skills=0`). Channels, daemon, hooks, search and bootstrap files were skipped at onboarding. No agent definition, tool registration or prompt of ours was created. The only agent is the stock default `main`.

## What got installed (user scope, no admin, nothing in the repo)

| Item | Version | Path |
|---|---|---|
| Portable Node.js | v24.21.0 (npm 11.19.0), SHA256 verified against nodejs.org `SHASUMS256.txt` | `%LOCALAPPDATA%\ambient-mirror-runtime\node-v24.21.0-win-x64` |
| OpenClaw | 2026.9.2 (3928bad), MIT | `%LOCALAPPDATA%\ambient-mirror-runtime\openclaw-2026.9.2` |
| OpenClaw | 2026.7.1 (2d2ddc4), MIT | `%LOCALAPPDATA%\ambient-mirror-runtime\openclaw-2026.7.1` |
| Isolated OpenClaw state (2026.9.2) | config + sqlite + workspace | `%LOCALAPPDATA%\ambient-mirror-runtime\home\.openclaw` |
| Isolated OpenClaw state (2026.7.1) | same | `%LOCALAPPDATA%\ambient-mirror-runtime\home-2026.7.1\.openclaw` |

Total is about 860 MB. The system Node is `C:\Program Files\nodejs` v24.14.0, which is below OpenClaw's engine floor (`>=24.15.0 <25`). Upgrading that MSI install needs admin, so I used the portable Node instead and left the system Node alone. The pre-existing dormant `~\.openclaw` from April 2026 was not modified. One stray file did land there and was removed, see Finding 4. Removing everything is a single folder delete: `%LOCALAPPDATA%\ambient-mirror-runtime`.

## Exact commands

Session environment (PowerShell). It isolates state from `~\.openclaw` and turns off update pings and telemetry:

```powershell
$root = "$env:LOCALAPPDATA\ambient-mirror-runtime"
$nd   = "$root\node-v24.21.0-win-x64"
$env:PATH = "$nd;$env:PATH"
$env:OPENCLAW_HOME        = "$root\home"
$env:OPENCLAW_STATE_DIR   = "$root\home\.openclaw"
$env:OPENCLAW_CONFIG_PATH = "$root\home\.openclaw\openclaw.json"
$env:OPENCLAW_NO_AUTO_UPDATE = '1'
$env:DO_NOT_TRACK = '1'
$oc = "$root\openclaw-2026.9.2\node_modules\openclaw\openclaw.mjs"   # run as: & "$nd\node.exe" $oc <args>
```

Install:

```powershell
& "$nd\npm.cmd" install -g --prefix "$root\openclaw-2026.9.2" openclaw@2026.9.2 --allow-scripts=openclaw --no-fund --no-audit
& "$nd\node.exe" $oc --version          # OpenClaw 2026.9.2 (3928bad)
```

Onboarding. It is non-interactive and local-only. It installs no daemon and sets up no channels, skills, hooks, search, UI or bootstrap files:

```powershell
& "$nd\node.exe" $oc onboard --non-interactive --accept-risk --mode local --flow manual `
  --auth-choice ollama --custom-base-url 'http://127.0.0.1:11434' --custom-model-id 'ministral-3:3b' `
  --skip-channels --skip-daemon --skip-health --skip-hooks --skip-search --skip-skills --skip-ui `
  --skip-bootstrap --suppress-gateway-token-output --gateway-bind loopback --tailscale off --json
```

Next, I hardened the stock config. I edited it with a Node JSON round-trip, not PowerShell `ConvertTo-Json`, because that cmdlet silently truncates nested JSON. Then I ran `openclaw config validate`, which returned `Config valid`.

| Key (2026.9.2) | Value | Why |
|---|---|---|
| `models.mode` | `replace` | only configured providers, no built-in catalog |
| `models.providers.ollama.models` | `ministral-3:3b`, `ministral-3:8b` only | onboarding auto-discovered `qwen3.5:cloud` from the local Ollama tag list |
| `models.catalogRefresh.enabled` | `false` | the gateway fetched a remote model catalog on start |
| `tools` | `{ "profile": "minimal", "deny": ["*"] }` | no tools for the smoke |
| `agents.defaults.skills` | `[]` | per the schema, an empty array gives inheriting agents no skills |
| `agents.defaults.silentReply` | `{ "group": "disallow", "internal": "disallow" }` | tried for the 3b `NO_REPLY` issue, did not change it |
| `memory.search.enabled` | `false` | stopped the OpenAI embeddings calls (Finding 2) |
| `update.checkOnStart` | `false` | no update pings |
| `telemetry.enabled` | `false` | no statistics pings |

For 2026.7.1 the same intent maps to different keys. Memory search lives at `agents.defaults.memorySearch.enabled=false`, and 2026.7.1 has neither `models.catalogRefresh` nor a `telemetry` block.

The one-shot turn (embedded agent, no gateway):

```powershell
& "$nd\node.exe" $oc agent --local --agent main --session-id smoke-4 --model 'ollama/ministral-3:8b' `
  --message 'Reply with the single word: ready' --thinking off --json --timeout 300
```

The same turn through a gateway. I started the gateway hidden on loopback port 18799, then stopped it by PID:

```powershell
$p = Start-Process -FilePath "$nd\node.exe" -ArgumentList @("`"$oc`"",'gateway','run','--bind','loopback','--port','18799','--tailscale','off','--compact') `
     -RedirectStandardOutput gw.out.txt -RedirectStandardError gw.err.txt -WindowStyle Hidden -PassThru
& "$nd\node.exe" $oc agent --agent main --session-id smoke-gw-7 --model 'ollama/ministral-3:8b' `
  --message 'Reply with the single word: ready' --thinking off --json --timeout 300
Stop-Process -Id $p.Id -Force    # after checking that its CommandLine contains "gateway run" and the runtime dir
```

## Results

Wall time includes the Node CLI cold start and plugin preload. That costs 7 to 10 s per invocation on Windows and disappears when calls go through a running gateway. `agent_ms` is OpenClaw's own `meta.durationMs`.

| Run | OpenClaw | Path | Model | Wall ms | agent_ms | Tokens in/out | Reply | Verdict |
|---|---|---|---|---|---|---|---|---|
| smoke-1 | 2026.9.2 | `--local`, cold | ministral-3:3b | 23804 | 6179 | 1669/5 | `NO_REPLY` (empty payload) | routing ok, answer fail |
| smoke-2 | 2026.9.2 | `--local` | ministral-3:3b | 10976 | 984 | 1669/5 | `NO_REPLY` | routing ok, answer fail |
| smoke-3 | 2026.9.2 | `--local`, memory off | ministral-3:3b | 8702 | 908 | 1669/5 | `NO_REPLY` | routing ok, answer fail |
| smoke-4 | 2026.9.2 | `--local`, cold load | ministral-3:8b | 14301 | 7069 | 1669/2 | `ready` | PASS |
| smoke-5 | 2026.9.2 | `--local`, warm | ministral-3:8b | 10361 | 1086 | 1669/2 | `ready` | PASS |
| smoke-6 | 2026.9.2 | `--local`, warm | ministral-3:8b | 7997 | 993 | 1669/2 | `ready` | PASS |
| smoke-gw-7 | 2026.9.2 | gateway :18799 | ministral-3:8b | 4739 | 1085 | n/a | `ready` | PASS |
| smoke-gw-8 | 2026.9.2 | gateway :18799 | ministral-3:8b | 2266 | 568 | n/a | `ready` | PASS |
| smoke71-1 | 2026.7.1 | `--local`, cold load | ministral-3:8b | 16571 | 10055 | 2512/2 | `ready` | PASS |
| smoke71-2 | 2026.7.1 | `--local`, warm | ministral-3:8b | 11877 | 4037 | 2512/2 | `ready` | PASS |

The gateway was listening 9 s after spawn. Its log shows `[gateway] ready` 5.1 s after `loading configuration`, and it loaded 13 plugins. 2026.7.1 logged the tool removal explicitly: `tool policy removed 25 tool(s) via tools.profile (minimal)` and `removed 1 tool(s) via tools.deny: session_status; matched *`.

## Findings that matter for event day

1. **Small models can fail at the agent layer even when routing works.** `ministral-3:3b` answered OpenClaw's silent-reply token `NO_REPLY` on all three tries. Setting `silentReply: disallow` did not change that. `ministral-3:8b` answered correctly every time. On GB10, the model behind the OpenClaw agent should be the large reasoning model, and a smoke turn has to check the payload, not just the exit code (exit was 0 with an empty payload).
2. **A cloud call happened through a side channel.** Even with only the Ollama provider configured, OpenClaw's memory subsystem sent embedding requests to OpenAI and got `429 insufficient_quota`. The process environment had no `OPENAI_API_KEY`. The credential was most likely picked up from a local CLI login (`~\.codex\auth.json` exists; I did not open it). The calls stopped once memory search was disabled. On GB10, disable memory search, or point it at a local embedding model, before anything else. The sandbox network policy should block this anyway. It still has to be off, because D02 requires "No cloud model route".
3. **The gateway fetches a remote model catalog on start.** Its log said `remote model catalog updated`. For an offline venue, set `models.catalogRefresh.enabled=false` (2026.9.x) and `update.checkOnStart=false`.
4. **State isolation is not airtight in 2026.7.1.** During its first onboarding/config pass, a new `~\.openclaw\state\openclaw.sqlite` appeared in the real home even though `OPENCLAW_HOME` and `OPENCLAW_STATE_DIR` were set. A later fresh-home onboard and agent runs did not reproduce it. I deleted the stray file and its directory, and no pre-existing file was touched. Inside a NemoClaw sandbox this does not matter. On a shared host it does.
5. **The onboarding catalog pulls in every local Ollama tag, `:cloud` tags included.** Trim the catalog, or use `models.mode=replace`, so a `:cloud` model can never be selected.
6. **Version skew.** The NemoClaw installer defaults to the `lkg` tag (v0.0.124), which pins OpenClaw 2026.7.1. NemoClaw `main` pins 2026.9.2, and npm `latest` is 2026.9.7. The config schemas differ (Finding 2's key moved). Run `openclaw --version` and `openclaw config schema` inside the sandbox on the day before writing any config.
7. **Windows noise is harmless.** Every command prints a WSL2 recommendation banner. One run's stderr carried errors from the user's PowerShell profile (Terminal-Icons module), triggered by a shell-environment probe. npm skipped 4 install scripts (`koffi`, `tree-sitter-bash`, `protobufjs`, `@google/genai`) under the new `allowScripts` policy, and the smoke did not need them.

## Shared-resource side effects and cleanup

- Ollama was not restarted or reconfigured, and no models were pulled. Loading `ministral-3:3b` evicted another worker's resident `qwen3.5:9b`, and p06-inference was told. Resident models show `expires_at` in the year 2319, which means keep_alive is -1, so nothing unloads by itself. I unloaded each model I loaded with `POST /api/generate {"model":"<m>","keep_alive":0}`. `/api/ps` was empty at the end.
- The gateway (PID 22280) and its conhost child (PID 25648) were stopped by PID after checking their command lines. Ports 18789 and 18799 were not listening at the end, and no `node.exe` with the runtime folder in its command line was left.
- No scheduled task, service or daemon was installed (`--skip-daemon`, `installDaemon=false`).
- The gateway token was generated into the isolated config and never printed. The log redacts it.

## What this does not prove

- That OpenClaw works inside an OpenShell sandbox, or the `inference.local` route. Both need Linux plus Docker (GB10, or WSL2 here).
- ARM64 behaviour, vLLM serving, and tool calling with the large Qwen/Mistral checkpoints.
- Anything about our agent. Per `docs/COMPLIANCE.md`, that is built on event day (D00 to D02).

See `docs/EVENT_DAY_RUNTIME.md` for the GB10 procedure and `artifacts/runtime/BLOCKERS.md` for the manual asks.
