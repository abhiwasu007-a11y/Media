# Judge rubric — `agent_17.brief_intake`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 17 |
| Used by | eval gate (27 §5); judge prompt `agent_17/brief_intake_judge.v1` (written at build time) |
| Scope | Subjective quality only. Schema, counts, references, flags, names and wording limits are checked deterministically (README §4) and are **not** judged. |

The judge receives the case input, the step output and this rubric, and returns integer scores 1-5 per criterion with a one-sentence justification each. Scores below the case's `judge_min` fail the case.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Completeness** — every material claim, person, brand and AI-content request in the brief is captured | nothing material missed | one minor item missed, no rule relevance | one checkable item missed, not rule-relevant | a rule-relevant item missed (person, brand, claim, AI request) | most items missed |
| **J2 Question quality** — questions are specific, answerable in one reply, non-duplicate, and `blocking` is used only where concepts cannot be written or a rule would be broken | every question needed, specific, one-reply, blocking set exactly right | one question vague or one blocking flag off | several vague or duplicate questions | questions leading, compound or irrelevant | questions unusable or missing where needed |
| **J3 Faithfulness** — the summary restates the client's meaning and adds nothing; wording of risk notes is neutral | restates meaning, adds nothing | minor wording drift | one detail softened or lost | a fact added or a number changed | meaning changed |
| **J4 Rationale quality** — `reason` and risk-note text explain briefly and correctly why the question or flag exists | reasons clear and specific for every question and flag | specific for most | generic but correct | vague or partly wrong | missing or wrong |

Calibration: before the judge is used in CI, two humans label a fixed calibration subset (at least 10 cases from `cases.jsonl`); the judge must agree within ±1 point on >= 90 % of criterion scores (design default, recalibrated after the first client ad pilot). The calibration result is stored with the judge prompt version.
