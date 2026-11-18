# Judge rubric — `agent_04.research_pack` step `plan`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 04 |
| Used by | eval gate (27 §5); judge prompt `agent_04/research_pack_plan_judge.v1` (written with the first build ticket for the gate) |
| Scope | Subjective quality only. Schema, refusal, time references, gap closure, languages and limits are deterministic (README §4) and are **not** judged. |

The judge receives the case input, the step output and this rubric, and returns integer scores 1–5 per criterion with a one-sentence justification each. Scores below the case's `judge_min` fail the case.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Coverage** — the concepts are what a viewer needs to understand the topic | nothing essential missing, dependency order clear | one minor concept missing | one important sub-concept or common mistake missing | the core concept or a needed example kind is missing | plan does not address the topic |
| **J2 Economy** — no padding, no overlap | every concept distinct and needed | one concept could be merged | two overlapping or padded concepts | many overlapping concepts | list fills the maximum with filler |
| **J3 Query quality** — queries would find passages that state the concept | specific, varied, right languages, glossary wording used | one weak query | queries mostly generic or one language missing | several queries would return the wrong material | queries unrelated to the concepts |
| **J4 Rationale and evidence needs** — `rationale` and `evidence_needs` fit the concept | specific and consistent | minor vagueness | generic but correct | partly wrong (for example no example kind for an applied concept) | missing or wrong |

Calibration: before use in CI, two humans label a fixed subset (at least 10 cases); the judge must agree within ±1 point on ≥ 90 % of criterion scores (design default, recalibrated after the pilot). The calibration result is stored with the judge prompt version.
