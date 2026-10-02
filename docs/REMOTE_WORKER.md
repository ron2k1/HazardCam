# Optional 16 GB SSH Worker

## Principle

The remote desktop expands throughput; it is not part of the critical path. A 16 GB system-RAM host is useful for CPU/data/build tasks. Do not assume it can host Qwen 35B.

## Configure

Create an SSH alias on the orchestrator machine, e.g. in `~/.ssh/config`:

```sshconfig
Host mirror-worker
  HostName 192.0.2.10
  User your-user
  IdentityFile ~/.ssh/id_ed25519
  IdentitiesOnly yes
  ServerAliveInterval 30
```

Copy:
```bash
cp config/remote.env.example config/remote.env
```

Set only the alias/root. Do not put private keys or passwords in the repo.

## Probe

```bash
./scripts/remote_probe.sh
```

The probe checks CPU/RAM/disk/GPU and common tools. Route work based on actual output.

## Recommended jobs

- dataset retrieval
- ffmpeg transcode/frame extraction
- optical flow / frame-difference candidate ranking
- npm build/lint
- pytest fixture suite
- Playwright if browser deps exist
- compressed artifact generation

## Small model use

Only consider a small quantized model if `nvidia-smi` or equivalent proves sufficient GPU memory. System RAM alone is not a reason to offload 35B VLM inference.

## Remote coding CLI

The remote host must be authenticated to its own coding CLI. Never rsync authentication directories from the main machine.
