# Threshold calibration — kb1_retail, microsoft/harrier-oss-v1-0.6b@f9b9dc8d

preliminary (KB #1 only); full calibration in Phase 6. 100 answerable, 30 unanswerable questions; 186 s.

| Value | Calibrated | Placeholder |
|---|---|---|
| SCORE_THRESHOLD | **0.553** | 0.45 |
| CONF_MID | **0.553** | 0.55 |
| CONF_HIGH | **0.599** | 0.70 |

| Metric | Value | Target |
|---|---|---|
| False fallback on answerable | 0.050 | ≤ 0.05 |
| Correct fallback on unanswerable | 0.567 | ≥ 0.90 |
| Precision at/above CONF_MID | 0.8611111111111112 | ≥ 0.85 |
| Precision at/above CONF_HIGH | 0.9523809523809523 | ≥ 0.95 |
| Answerable questions bucketed high | 0.800 | — |

Top-score distribution (dense cosine of the best of 4 chunks):

| Set | min | p10 | median | p90 | max |
|---|---|---|---|---|---|
| answerable | 0.521 | 0.584 | 0.636 | 0.687 | 0.776 |
| unanswerable | 0.387 | 0.460 | 0.549 | 0.613 | 0.631 |
