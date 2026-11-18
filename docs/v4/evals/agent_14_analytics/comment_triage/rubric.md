# Judge rubric — `svc_s13.comment_triage`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 14 |
| Used by | eval gate (27 §5); judge prompt `agent_14/comment_triage_judge.v1` (written with the build ticket) |
| Scope | Subjective quality only. Class, flags, confidence, order and schema are checked deterministically (README §4) and are **not** judged. |

The judge receives the case input, the step output and this rubric, and returns integer scores 1–5 per criterion with one sentence each. A score below the case's `judge_min` fails the case.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Rationale accuracy** — the rationale names the real deciding feature, adds nothing | exact, specific, nothing invented | accurate, slightly generic | correct but vague | partly wrong or mentions a feature that is not in the comment | wrong, invented, or repeats personal details |
| **J2 Signal fit** — `signals` match the comment and the other applicable classes are visible | every applicable signal present, none extra | one minor signal missing or one extra | a needed secondary signal missing (for example a question inside an abusive comment) | signals contradict the class | signals empty or unrelated |

Calibration: two humans label at least 10 cases; the judge must agree within ±1 point on at least 90 % of scores (design default, recalibrated after the 3C pilot). The result is stored with the judge prompt version.
