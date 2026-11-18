# Judge rubric — `agent_17.concept_variants`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 17 |
| Used by | eval gate (27 §5); judge prompt `agent_17/concept_variants_judge.v1` (written at build time) |
| Scope | Subjective quality only. Schema, counts, references, flags, names and wording limits are checked deterministically (README §4) and are **not** judged. |

The judge receives the case input, the step output and this rubric, and returns integer scores 1-5 per criterion with a one-sentence justification each. Scores below the case's `judge_min` fail the case.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Distinctness** — variants are different ideas (angle, hook, structure), not rewordings | variants are clearly different ideas | one pair is similar in idea | two pairs similar or one is a rewording | most variants are rewordings | all variants the same idea |
| **J2 Brief fit** — objective, audience, tone and offer of the brief are served; nothing contradicts the brief | objective, audience, tone and offer all served | one element weakly served | one element ignored | an element contradicted | brief ignored |
| **J3 Producibility** — each variant can be produced with the formats, the client's media and the visual hierarchy | every variant producible with given formats, media and hierarchy | one needs a small adjustment | one needs media or effects not available | several not producible | none producible |
| **J4 Rationale quality** — rationale is brief, ties the variant to the objective and the audience, and adds no fact | rationale specific and fact-free for every variant | specific for most | generic but correct | vague or adds a fact | missing or wrong |

Calibration: before the judge is used in CI, two humans label a fixed calibration subset (at least 10 cases from `cases.jsonl`); the judge must agree within ±1 point on >= 90 % of criterion scores (design default, recalibrated after the first client ad pilot). The calibration result is stored with the judge prompt version.
