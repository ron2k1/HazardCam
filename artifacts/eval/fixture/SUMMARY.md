# Eval summary: fixture

Scored at 2026-10-02T16:42:37+00:00 on commit `b03632474d7ec8901f90f38c930c77737aa9e445`, rules in `eval/SCORING.md`. Rates are k/n = rate [Wilson 95%].

- Models: `replay: qwen3-vl:4b-instruct` + `replay: ministral-3:3b`
- Verdict: pipeline_ok = **True**, beats_constant_baselines = **False**

## Decision

| metric | value | best constant baseline |
|---|---|---|
| decision accuracy | 9/22 = 0.41 [0.23, 0.61] | 0.64 (always `unknown`) |
| balanced accuracy | 0.42 | 0.67 (always `unknown`) |
| positive | 2/8 = 0.25 [0.07, 0.59] | |
| negative | 5/7 = 0.71 [0.36, 0.92] | |
| ambiguous | 2/7 = 0.29 [0.08, 0.64] | |
| false alarms on negatives (failed runs count) | 2/7 = 0.29 [0.08, 0.64] | |
| abstention rate | 8/22 = 0.36 [0.20, 0.57] | |
| raw (pre-gate) accuracy | 9/22 = 0.41 [0.23, 0.61] | |

Outcomes: abstain_ok 1, correct_reject 5, false_alarm 2, hit 3, miss_abstain 2, miss_no_event 1, wrong_class 8

## Region

- Region acceptance (event claims with accepted zones): 0/11 = 0.00 [0.00, 0.26]
- Full hit (positives, class and region): 0/8 = 0.00 [0.00, 0.32]
- Fusion had an accepted zone among its candidates: 0/14 = 0.00 [0.00, 0.22]
- Median localization error: chosen candidate 23.4 m, best candidate 20.7 m

## Evidence and time

- 13 event claims; median cited evidence 7.0; unsupported 0; Brier 0.504
- Median best cluster IoU with the event window: 0.60

## System

- Completion 22/22 = 1.00 [0.85, 1.00]; schema-valid 22/22 = 1.00 [0.85, 1.00]
- GT leaks 0; failed adapter calls 0; fixture replay mismatches 0
- Scenario ms {'median': 1053.7, 'max': 2032.7}; perception call s {'median': 0.0, 'max': 0.0}; reasoning s {'median': 0.0, 'max': 0.0}

## Failures

| scenario | category | outcome | submitted | raw |
|---|---|---|---|---|
| eval_002 | positive | wrong_class | vehicle_turnaround | vehicle_turnaround |
| eval_003 | ambiguous | wrong_class | vehicle_stop | vehicle_stop |
| eval_004 | negative | false_alarm | vehicle_departure | vehicle_departure |
| eval_007 | positive | wrong_class | passenger_dropoff_pickup | passenger_dropoff_pickup |
| eval_012 | ambiguous | miss_no_event | no_event | no_event |
| eval_013 | negative | false_alarm | vehicle_stop | vehicle_stop |
| eval_015 | ambiguous | wrong_class | vehicle_turnaround | vehicle_turnaround |
| eval_016 | positive | miss_abstain | unknown | unknown |
| eval_018 | ambiguous | wrong_class | passenger_dropoff_pickup | passenger_dropoff_pickup |
| eval_019 | positive | wrong_class | vehicle_turnaround | vehicle_turnaround |
| eval_020 | positive | miss_abstain | unknown | unknown |
| eval_021 | ambiguous | wrong_class | vehicle_turn | vehicle_turn |
| scenario_001 | positive | wrong_class | vehicle_loading_unloading | vehicle_loading_unloading |
