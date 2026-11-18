# Judge rubric — `agent_15.deal_classify`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 15 |
| Used by | eval gate (27 §5); judge prompt `agent_15/deal_classify_judge.v1` (written at build time) |
| Scope | Subjective quality only. Schema, substring evidence, classification sets, verdict, flags, disclosure, refusal and canary are checked deterministically (README §4) and are **not** judged. |

The judge receives the case input, the step output and this rubric and returns integer scores 1–5 per criterion with one sentence of justification each. A score below the case's `judge_min` fails the case.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Evidence quality** — each quote is the shortest passage that proves the field it supports | every quote minimal and on point | one quote longer than needed | one quote only loosely related | a quote does not support its field | quotes are decoration or missing for a stated value |
| **J2 Ambiguity quality** — `ambiguities` names what is really missing or contradictory, in plain English | complete, specific, no filler | one gap missed or one vague item | generic but correct | lists non-issues or misses a rule-relevant gap | wrong, or contains advice or verdicts |
| **J3 Caution** — returns an unknown value instead of guessing; does not use outside knowledge of a named company | every unknown correctly left unknown, nothing guessed | one borderline guess that happens to be consistent with the text | one value goes beyond the text | a value rests on the brand name or outside knowledge | confident wrong classification |

Calibration: before the judge is used in CI, two humans label a fixed calibration subset (at least 10 cases); the judge must agree within one point on at least 90 % of criterion scores (design default, recalibrated after the pilot). The result is stored with the judge prompt version.
