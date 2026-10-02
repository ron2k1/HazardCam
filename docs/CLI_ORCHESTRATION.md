# Claude Ultracode + External Coding CLI Orchestration

Current Claude Code supports non-interactive execution with `claude -p` and current versions expose Ultracode/dynamic workflow orchestration. The safe pattern here is:

## Main orchestrator

```bash
claude --effort ultracode "$(cat MASTER_ORCHESTRATOR_PROMPT.md)"
```

If the installed version uses a different Ultracode toggle flow, start `claude`, inspect `/effort`, enable Ultracode, then paste the master prompt. Always verify the installed version/status rather than assuming exact version semantics.

## External worker fallback

Use external headless workers only for isolated tasks:

```bash
./scripts/spawn_code_worker.sh T02 claude local
./scripts/spawn_code_worker.sh T03 codex local
```

The wrapper creates an isolated git worktree and writes worker output under `artifacts/workers/`.

### Why worktrees

Parallel agents editing the same checkout create lost changes and unreviewable merges. One task = one branch/worktree = one worker.

### Integration discipline

Workers never merge themselves. The main orchestrator:
1. reviews worker report
2. inspects diff
3. runs integration tests
4. cherry-picks/merges only after verification

## Permissions

Do not default to bypass-permission modes. The helper scripts intentionally avoid `--dangerously-skip-permissions`. If the human chooses a more autonomous permission mode, that is an explicit local decision.
