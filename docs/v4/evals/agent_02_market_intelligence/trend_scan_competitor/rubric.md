# Judge rubric — `agent_02.trend_scan competitor`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (3C) |
| Owner | Agent 02 |
| Used by | eval gate (27 §5); judge prompt `agent_02/trend_scan_judge.v1` (to be written with the first build ticket of the step) |
| Scope | Subjective quality only. Partition, references, screens, flags, numbers and phrases are checked deterministically (README §4) and are **not** judged. |

The judge receives the case input, the step output and this rubric, and returns integer scores 1–5 per criterion with a one-sentence justification each. Scores below the case's `judge_min` fail the case.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Pattern accuracy** — label fits the anomaly and the history (new topic vs known topic) | every label exact | one label defensible but not best | one wrong label that does not change relevance | wrong label that changes relevance | labels unrelated to anomalies |
| **J2 Description grounding and neutrality** — only supplied fields; descriptive; no advice | every description supported and neutral | slightly generic | one unsupported inference | speculation or hidden recommendation | invented facts or advice to copy |
| **J3 Relevance reasoning** — HIGH/MEDIUM/LOW follows seed match and field fit | all ratings correct | one rating one step off | two ratings one step off | a HIGH without a seed, or LOW for a clear seed match | ratings arbitrary |
| **J4 Screen-note quality** — names the rule and why | specific | specific but terse | generic but correct | vague or wrong rule | missing or wrong |

Calibration as in the synthesis dataset (at least 10 cases including AK-02, HN-15 and EDGE-22).
