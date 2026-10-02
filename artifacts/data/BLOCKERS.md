# P05 data blockers

## Hard blockers: none

The chosen source (MEVA KF1) needs no registration, login, form or gated terms. Video comes from a public S3
bucket, and annotations and calibration come from a public GitLab repo. All 22 prepared scenarios were built
without credentials.

## Optional asks (not needed for the demo, recorded per the P05 rules)

I did not fill in any of these. Each is tied to the user's identity and only adds a backup option.

1. **StreetAware video (NYU), via a Globus login.**
   - URL: https://doi.org/10.58153/q1byv-qc065. The record links the Globus file manager:
     `https://app.globus.org/file-manager?origin_id=c43d41ac-d286-4ac4-9318-3d65f3d9b855&origin_path=%2Fq1byv-qc065-streetaware%2F`
   - What to do: sign in to Globus with an institutional or Google identity, then transfer one session folder (one
     intersection) to a Globus Connect Personal endpoint. All 11 sessions together hold about 236 GB of audio and
     video; the size of one session is UNVERIFIED.
   - Why it would beat the current fallback: these are real NYC street intersections, 8 radio-synced views at
     2592x1944, licensed CC BY-SA 4.0.
   - Why it does not beat MEVA: no event annotations and no camera calibration. Every label would be
     inspection-labeled, and ShareAlike would apply to the derived clips.
2. **AI City CityFlowV2.** No ask. The access form is gone, but the license (non-commercial, academic, no
   redistribution, no unredacted faces or plates) rules out showing clips in a public demo. Do not use it.

## Soft issues (not blockers)

- The MEVA clip-table README states the offset sign opposite to what the data says. The code uses the sign the data
  supports, and the evidence is in `artifacts/data/research.md`.
- PETS2009 servers are unreachable today (DNS failure, FTP timeout). It is not needed.
