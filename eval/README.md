# Evaluation Harness

Implement `scripts/eval/run_eval.py` (or equivalent) to execute a directory of scenario manifests under a selected model profile and produce machine-readable results plus a concise summary.

Recommended command:

```bash
MODEL_PROFILE=fixture python scripts/eval/run_eval.py --manifest data/eval/manifest.json --out artifacts/eval
```

See `docs/EVALUATION_PLAN.md`.
