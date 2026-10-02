# Scoring rules (pre-registered)

These rules were committed before any eval run was scored. The lite-local fixture
recording batch was running at the time, and its progress log had printed the raw
event type for eval_001 to eval_005; no hypothesis had been compared to an
`expected.json`. The class rule below was drafted before that batch started. Any later
change to a rule must land as its own commit that says why, and every summary records
the commit it was scored at.

## Inputs

For each scenario the scorer reads, after the harness has returned:

- the submitted hypothesis (after the submit gate), which is what the system claims;
- the raw hypothesis (before the gate), as a diagnostic only;
- the evidence bundle and the observation batches;
- run telemetry: duration, adapter calls, tool latencies, completion;
- `data/prepared/<id>/expected.json`, which is judge-only. The harness never sees it.

Natural-language fields (`reason`, `limitations`, alternative reasons) are never
scored. Every rule compares categorical fields, ids or numbers.

## Event class

Let `H` be the submitted `event_type`, `A` the scenario's `accepted_event_types`, and
`abst` its `abstention_acceptable` flag.

    class_ok = H in A  or  (H == "unknown" and abst)

Read per category, with the labels as prepared:

- negative (`A` = unknown, none, no_event): correct iff the system abstains or says
  `no_event`. Any event claim is a false alarm.
- positive (`abst` false): correct iff `H` is in `A`. Abstaining is a miss, and so is
  `no_event`.
- ambiguous (`abst` true): correct iff `H` is in `A` or the system abstains. `no_event`
  is wrong: the GT camera does show an event, so "nothing happened" is a false claim,
  not an abstention.

Each scenario also gets one outcome label for failure capture: `hit`, `wrong_class`,
`abstain_ok`, `miss_abstain`, `miss_no_event`, `correct_reject` or `false_alarm`.

A run that fails (a tool error, or no hypothesis) counts as incorrect in every rate.
It is never dropped from a denominator.

## Region

The region is scored only when the scenario has accepted zones and the hypothesis
names an event (`H` is neither `unknown` nor `no_event`).

- `region_ok`: the hypothesis `region` is in `accepted_zone_ids`.
- `localization_error_m`: the distance from the center of the bundle candidate the
  hypothesis names to `event_point_local_m`, when both exist. Reported, not thresholded.
- `full_hit` (positives only): `class_ok` and `region_ok`.

Fusion is scored apart from the reasoner, so a wrong pick can be told from a missing
candidate:

- `fusion_region_hit`: some bundle candidate's id is in `accepted_zone_ids`.
- `best_candidate_error_m`: the smallest candidate-center distance to the event point.

## Time

Diagnostic only, never a pass criterion: `best_cluster_iou` is the largest temporal
IoU between any bundle cluster and the expected `time_window`.

## Evidence and confidence

- `evidence_count`: cited evidence ids after the gate, plus the distinct cameras they
  come from.
- `unsupported_claim`: an event claim citing no evidence.
- Brier score over event claims, treating `confidence` as P(class_ok).

## Validity and safety

- Schema validity: each observation batch, the bundle and both hypotheses validate
  against `contracts/`.
- GT safety: every event the harness emits is checked with the scenario's `GtGuard`.
  Any leak marks the run invalid.
- Fixture replay: in fixture mode, the submitted hypothesis must match the
  recording's `provenance.json`. The gate and fusion are deterministic, so a mismatch
  is a bug.

## Headline numbers

Over all scenarios in the manifest:

- decision accuracy (mean `class_ok`) with a Wilson 95% interval;
- per category: positive hit rate, negative correct-reject rate and ambiguous
  acceptable rate, each with a Wilson interval, and their mean (balanced accuracy);
- false-alarm rate on negatives, and the abstention rate;
- region acceptance rate, `full_hit` rate and median localization error;
- completion rate, schema-valid rate, GT leaks, failed adapter calls, latency
  (median and max per scenario, per camera and per tool).

## Baselines

Every summary carries constant baselines computed from the same `expected.json` files:
always abstain, and always answer `X` for each event type in the vocabulary.

On this set (8 positive, 7 negative, 7 ambiguous), always abstaining scores 14/22
decision accuracy and 2/3 balanced accuracy without looking at any video.

## Verdict flags

- `pipeline_ok`: completion rate 1.0, schema-valid rate 1.0 and zero GT leaks.
- `beats_constant_baselines`: decision accuracy and balanced accuracy are both
  strictly above the best constant baseline for that metric.

There is no other verdict. With 22 scenarios a Wilson interval is roughly plus or
minus 0.2, so a gap smaller than that is reported as a gap, not a finding.

## Clarifications (2026-10-02, after the fixture and full-local runs)

A code review of the scorer found places where the text above could be read two ways.
Each reading below is the stricter one, so none can raise a score. Neither recorded run
(fixture, full-local) had a failed run or a GT leak, so no recorded number changes.

1. A run with any GT leak is invalid. It counts as incorrect in every rate, exactly like
   a failed run, and it also fails `pipeline_ok`. Before this, a leaking run's answer
   still counted toward accuracy.
2. "Incorrect in every rate" includes the false-alarm rate: a failed or invalid run on a
   negative counts as a false alarm, so a failure can never lower that rate.
3. Region acceptance stays conditional on an event claim, as defined under Region; a
   failed run makes no claim. Failures stay visible in `full_hit` and
   `fusion_region_hit`, which keep them in their denominators.
4. Two outcome labels join the seven listed under Event class: `run_failed` (a tool
   error, or no hypothesis) and `gt_leak` (an invalid run).
