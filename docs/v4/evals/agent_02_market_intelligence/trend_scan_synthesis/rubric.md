# Judge rubric — `agent_02.trend_scan synthesis`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (3C) |
| Owner | Agent 02 |
| Used by | eval gate (27 §5); judge prompt `agent_02/trend_scan_judge.v1` (to be written with the first build ticket of the step) |
| Scope | Subjective quality only. Partition, references, screens, flags, numbers and phrases are checked deterministically (README §4) and are **not** judged. |

The judge receives the case input, the step output and this rubric, and returns integer scores 1–5 per criterion with a one-sentence justification each. Scores below the case's `judge_min` fail the case.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Cluster coherence** — items grouped by the audience need; translations merged; distinct concepts split | every cluster is one concept and nothing that belongs together is split | one borderline item misplaced, no concept mixed | one cluster mixes two minor sub-topics, or one concept split in two | two concepts merged, or most translations not merged | clusters are arbitrary or by shared word only |
| **J2 Interpretation grounding** — only what the fields show; neutral; no forecast or advice | every sentence is supported by the items and neutral | one sentence slightly generic but supported | one unsupported inference, still neutral | a speculative claim about the audience or market | invented facts, forecast or recommendation |
| **J3 Label quality** — short neutral noun phrase, informative, `label_local` correct when given | clear, specific, correct local label or null | clear but slightly broad | vague or one local-label error | misleading or copies a title | wrong subject |
| **J4 Screen-note quality** — the note names why the rule applies or why it is clear | specific to the topic and the rule | specific but terse | generic but correct | vague or points to the wrong rule | missing or wrong |

Calibration: before the judge is used in CI, two humans label a fixed calibration subset (at least 10 cases from `cases.jsonl`, including AK-02 and EDGE-27); the judge must agree within ±1 point on ≥ 90 % of criterion scores (design default, recalibrated after the pilot). The calibration result is stored with the judge prompt version.
