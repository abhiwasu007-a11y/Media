# Judge rubric — `agent_06.claim_extraction`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 06 |
| Used by | eval gate (27 §5); judge prompt `agent_06/claim_extraction_judge.v1` (to be written with the agent_06 blueprint) |
| Scope | Subjective quality only. Verdicts, flags, offsets and schema are checked deterministically (README §4) and are **not** judged. |

The judge receives the case input, the step output and this rubric, and returns integer scores 1–5 per criterion with a one-sentence justification each. Scores below the case's `judge_min` fail the case.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Completeness** — every checkable statement extracted | none missed | one minor statement missed (no rule relevance) | one statement missed that is checkable but not rule-relevant, or two minor | a rule-relevant statement missed | most statements missed |
| **J2 Atomicity** — one checkable statement per claim, split/merge correct | all claims atomic, no over-splitting | one claim merges two minor statements | several merges or over-splits, meaning kept | splits/merges change the meaning | claims are whole paragraphs |
| **J3 Normalisation faithfulness** — `normalized_claim` adds nothing, keeps numbers/instruments | exact meaning, numbers and names kept | minor wording loss | one detail lost or softened | a fact added or a number changed | meaning changed |
| **J4 Rationale quality** — explains type, time reference and flag decision briefly | clear and specific for every claim | specific for most | generic but correct | vague or partly wrong | missing or wrong |

Calibration: before the judge is used in CI, two humans label a fixed calibration subset (at least 10 cases from `cases.jsonl`); the judge must agree within ±1 point on ≥ 90 % of criterion scores (design default, recalibrated after the pilot). The calibration result is stored with the judge prompt version.
