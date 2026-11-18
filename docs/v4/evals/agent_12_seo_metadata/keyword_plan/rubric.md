# Judge rubric — `agent_12.keyword_plan`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 12 |
| Used by | eval gate (27 §5); judge prompt `agent_12/keyword_plan_judge.v1` (written with the Agent 12 build ticket) |
| Scope | Subjective quality only. Schema, candidate identity, exclusions of forbidden phrases, caps, grounding and numbers are checked deterministically (README §4) and are **not** judged. |

The judge receives the case input, the step output and this rubric, and returns integer scores 1 to 5 per criterion with a one-sentence justification each. A score below the case's `judge_min` fails the case. The judge never changes a verdict that a deterministic assertion made.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Primary fit** — the primary names the promise topic and is a phrase a viewer in that language would search | exact topic, natural search phrase | right topic, slightly generic or slightly awkward | right topic but a weak search phrase | related topic, not the promise | wrong topic |
| **J2 Promise coverage and script support** — every promise term covered or honestly missing; every kept keyword is taught by a section | all covered, all kept keywords supported, missing terms explained | one weakly supported keyword | one promise term silently dropped | several unsupported keywords | keywords promise content the script lacks |
| **J3 Compliance restraint without over-blocking** — risky phrases excluded; educational phrases kept | all risky phrases out, all educational ones kept | one borderline educational phrase excluded | one educational phrase excluded without need, or one borderline phrase kept | an educational phrase wrongly labelled as risk several times | risky phrase kept (this also fails KA5) |
| **J4 Rationale quality** — short, specific, no invented data | each rationale cites the promise or a section; no numbers | most are specific | generic but true | vague or partly wrong | missing, wrong or invents demand figures |

Calibration: before the judge is used in CI, two humans label a fixed calibration subset (at least 10 cases from `cases.jsonl`); the judge must agree within ±1 point on at least 90 % of criterion scores (design default, recalibrated after the pilot). The calibration result is stored with the judge prompt version.
