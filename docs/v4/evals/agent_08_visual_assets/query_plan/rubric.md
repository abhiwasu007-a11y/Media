# Judge rubric — `agent_08.asset_sourcing` step `query_plan`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 08 |
| Used by | eval gate (27 §5); judge prompt `agent_08/query_plan_judge.v1` (pending Agent 08 build ticket) |
| Scope | Subjective quality only. Status, reason codes, counts, leakage, avoid subjects and schema are checked deterministically (README §4) and are **not** judged. |

The judge receives the case input, the step output and this rubric, and returns integer scores 1–5 per criterion with a one-sentence justification each. Scores below the case's `judge_min` fail the case.

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Coverage and literalness** — the queries capture the described subject, setting, action and shot type | every key element of the description is searchable through at least one query; shot type kept | one minor element missing (e.g. lighting) | main subject captured, setting or action missing | queries capture only part of the main subject | queries unrelated to the description |
| **J2 Query craftsmanship** — useful to a stock or file search | clear literal-to-broad progression, concise, no padding, sensible avoid terms, owner queries in the owner's words | minor redundancy | queries usable but repetitive or too broad | many near-duplicates or too long | unusable as search strings |
| **J3 Restraint** — adds nothing the description does not say | no invented subject, place or claim; notes factual and short | one harmless embellishment | one invented detail that does not change the picture | an invented detail that changes the picture | invents facts, claims or advice |

Calibration: before the judge is used in CI, two humans label a fixed calibration subset (at least 10 cases from `cases.jsonl`); the judge must agree within ±1 point on ≥ 90 % of criterion scores (design default, recalibrated after the pilot). The calibration result is stored with the judge prompt version.
