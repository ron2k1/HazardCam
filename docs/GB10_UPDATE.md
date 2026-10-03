# GB10 update (event day, 2026-10-03)

News from the laptop session since `docs/GB10_HANDOFF.md`. Read this, then carry on with the handoff's order of work.

## Where things stand

- Step 1 is done: Docker runs without sudo and GPU access from Docker is verified. Continue with step 2 (copy the
  USB bundle to `~/bundle` per its README section 1, then `verify_bundle.py` must print `ALL OK`).

## Scenario videos (needed before anything in this repo can run end to end)

`data/prepared/**/*.mp4` is gitignored, so this clone has the manifests but none of the 88 videos. They are a
release asset on this private repo. From the repo root:

```bash
gh release download data-prepared-v1 -D /tmp/aum-v1
tar -xf /tmp/aum-v1/aum-prepared-v1.tar
sha256sum -c /tmp/aum-v1/SHA256SUMS-prepared-v1.txt
```

All 88 lines must say `OK`. This needs no GPU, so run it alongside the bundle copy.

## Multi-angle blindspot work is happening on the laptop

The laptop session is building it on branch `feat/blindspots`:

- scenarios go from 3 visible MEVA angles to 6 (adding G505 and G509 at the bus station and G301 at the hospital;
  G341 stays the withheld ground-truth camera)
- `contracts/scenario.schema.json`, `scripts/data/prepare_scenario.py`, `scripts/data/scenario_specs.json` and the
  `/ops` blind-zone plan change to match
- a deterministic coverage tool maps which ground cells 0, 1 or 2+ cameras see, from the MEVA calibrations

To avoid merge conflicts, do not edit those files, `apps/web/src/components/ops/blind-zone-plan.tsx` or
`contracts/tools.schema.json` in this session. D00-D04 registers the tools that `contracts/tools.schema.json`
defines when it runs. When the branch and a `data-prepared-v2` video release are ready, the user will tell you to
merge them.

## Git

The laptop may push to `feat/prebuild` too. Run `git pull --rebase` before every push.
