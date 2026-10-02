# Eval summary: full-local

Scored at 2026-10-02T15:53:21+00:00 on commit `b51f3d7f87556d028c51281b9e9a287762a61fbc`, rules in `eval/SCORING.md`. Rates are k/n = rate [Wilson 95%].

- Models: `qwen3.5:9b` + `ministral-3:8b`
- Verdict: pipeline_ok = **True**, beats_constant_baselines = **False**

## Decision

| metric | value | best constant baseline |
|---|---|---|
| decision accuracy | 10/22 = 0.45 [0.27, 0.65] | 0.64 (always `unknown`) |
| balanced accuracy | 0.46 | 0.67 (always `unknown`) |
| positive | 3/8 = 0.38 [0.14, 0.69] | |
| negative | 5/7 = 0.71 [0.36, 0.92] | |
| ambiguous | 2/7 = 0.29 [0.08, 0.64] | |
| false alarms on negatives | 2/7 = 0.29 [0.08, 0.64] | |
| abstention rate | 6/22 = 0.27 [0.13, 0.48] | |
| raw (pre-gate) accuracy | 10/22 = 0.45 [0.27, 0.65] | |

Outcomes: abstain_ok 1, correct_reject 5, false_alarm 2, hit 4, miss_abstain 1, miss_no_event 3, wrong_class 6

## Region

- Region acceptance (event claims with accepted zones): 0/9 = 0.00 [0.00, 0.30]
- Full hit (positives, class and region): 0/8 = 0.00 [0.00, 0.32]
- Fusion had an accepted zone among its candidates: 0/14 = 0.00 [0.00, 0.22]
- Median localization error: chosen candidate 26.4 m, best candidate 26.4 m

## Evidence and time

- 12 event claims; median cited evidence 6.0; unsupported 0; Brier 0.341
- Median best cluster IoU with the event window: 0.53

## System

- Completion 22/22 = 1.00 [0.85, 1.00]; schema-valid 22/22 = 1.00 [0.85, 1.00]
- GT leaks 0; failed adapter calls 0; fixture replay mismatches None
- Scenario ms {'median': 77214.0, 'max': 177426.4}; perception call s {'median': 13.198, 'max': 90.453}; reasoning s {'median': 17.394, 'max': 32.808}

## Failures

| scenario | category | outcome | submitted | raw |
|---|---|---|---|---|
| eval_002 | positive | wrong_class | vehicle_turnaround | vehicle_turnaround |
| eval_003 | ambiguous | wrong_class | passenger_dropoff_pickup | passenger_dropoff_pickup |
| eval_004 | negative | false_alarm | passenger_dropoff_pickup | passenger_dropoff_pickup |
| eval_007 | positive | wrong_class | passenger_dropoff_pickup | passenger_dropoff_pickup |
| eval_008 | positive | miss_abstain | unknown | unknown |
| eval_010 | negative | false_alarm | vehicle_stop | vehicle_stop |
| eval_012 | ambiguous | wrong_class | passenger_dropoff_pickup | passenger_dropoff_pickup |
| eval_015 | ambiguous | miss_no_event | no_event | no_event |
| eval_018 | ambiguous | wrong_class | passenger_dropoff_pickup | passenger_dropoff_pickup |
| eval_019 | positive | miss_no_event | no_event | no_event |
| eval_020 | positive | wrong_class | passenger_dropoff_pickup | passenger_dropoff_pickup |
| eval_021 | ambiguous | miss_no_event | no_event | no_event |
