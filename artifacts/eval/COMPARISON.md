# Eval comparison

Best constant baselines: decision accuracy 0.64 (always `unknown`), balanced accuracy 0.67 (always `unknown`).

| profile | models | decision acc | balanced | positive | negative | ambiguous | full hit | median s | pipeline_ok | beats baselines |
|---|---|---|---|---|---|---|---|---|---|---|
| fixture | replay: qwen3-vl:4b-instruct + replay: ministral-3:3b | 9/22 = 0.41 [0.23, 0.61] | 0.42 | 2/8 = 0.25 [0.07, 0.59] | 5/7 = 0.71 [0.36, 0.92] | 2/7 = 0.29 [0.08, 0.64] | 0/8 = 0.00 [0.00, 0.32] | 1.1 | True | False |
